"""Fail-closed composer and delivery verification for queued mobile replies."""
import re
import time
import xml.etree.ElementTree as ET

import facebook_group_post as fb

UNKNOWN = "ส่งแล้วแต่ยังยืนยันไม่ได้ — ตรวจผลก่อน ห้ามส่งซ้ำ"


class FacebookRestricted(RuntimeError):
    """A real Facebook restriction is not an ordinary delivery timeout."""


def require_unrestricted(xml):
    reason = fb.fb_comment_guard.detect_block(xml)
    if reason:
        fb.fb_comment_guard.note_failure(xml)
        raise FacebookRestricted(reason + ' — พักการส่งของบัญชีนี้ เก็บคิวไว้และไม่ส่งซ้ำ')


def norm(text):
    return " ".join(re.sub(r"[\u200b-\u200f\ufeff]", "", str(text or "")).split())


def is_editor(node):
    return (node.get('class', '').rsplit('.', 1)[-1] in {
        'EditText', 'AutoCompleteTextView', 'MultiAutoCompleteTextView'}
        or node.get('editable') == 'true')


def editor(xml):
    fields = [n for n in ET.fromstring(xml).iter('node')
              if is_editor(n) and n.get('focused') == 'true']
    if len(fields) != 1:
        raise ValueError("ไม่พบช่องตอบกลับที่โฟกัสเพียงช่องเดียว — ไม่ส่ง")
    text = fields[0].get('text', '')
    # Facebook's accessibility text wraps the mention; these words are not typed.
    mention = re.match(r'^กล่าวถึง, (.+?), นอกเหนือการกล่าวถึง', text)
    if mention:
        suffix = text[mention.end():]
        # Accessibility joins the end-of-mention token and typed text with ', '.
        # Remove that single separator, keeping the actual typed leading space.
        if suffix.startswith(', '):
            suffix = suffix[2:]
        text = mention.group(1) + suffix
    return text


def composer_plan(existing, author, answer):
    value = norm(existing)
    if not value:
        return answer, norm(answer)
    if value == norm(author):
        return ' ' + answer, norm(author + ' ' + answer)
    if value in {norm(answer), norm(author + ' ' + answer)}:
        return '', value
    raise ValueError("ช่องตอบมีข้อความเดิมที่ไม่ตรงกับชื่อหรือคำตอบ — ไม่ล้างและไม่ส่ง")


def _reply_frame(xml, item, context=None):
    """Read one viewport and carry the target thread boundary across viewports.

    Facebook can place a long child reply below the viewport that still contains
    its parent.  ``context`` remembers the parent's left edge after that parent
    scrolls away.  A row at or left of that edge closes the thread, so a matching
    sentence under the next top-level comment can never verify this delivery.
    """
    context = dict(context or {})
    root = ET.fromstring(xml)
    for node in root.iter('node'):
        if is_editor(node):
            for child in node.iter():
                child.set('text', '')
                child.set('content-desc', '')
    xml = ET.tostring(root, encoding='unicode')
    rows = fb.visible_comments(xml)
    avatars = {}
    widgets = list(fb.iter_widgets(xml))
    for labels, box, _ in widgets:
        for label in labels:
            if label.startswith(fb.AVATAR_PREFIX):
                avatars[box[1]] = box[0]
    parents = [i for i, row in enumerate(rows)
               if norm(row['author']) == norm(item['author'])
               and norm(fb.comment_text_only(row['text'], row['author'])) ==
               norm(fb.comment_text_only(item['body'], item['author']))]
    if len(parents) > 1:
        return {"verified": False, "reason": "parent_ambiguous",
                "message": "พบคอมเมนต์ต้นทางชื่อและข้อความซ้ำมากกว่าหนึ่งแถว",
                "context": context}
    start = 0
    if len(parents) == 1:
        parent = rows[parents[0]]
        left = avatars.get(parent['top'])
        if left is None:
            return {"verified": False, "reason": "parent_avatar_unreadable",
                    "message": "พบข้อความต้นทางแต่หารูปโปรไฟล์ที่ใช้แบ่งเธรดไม่เจอ",
                    "context": context}
        context.update(parent_seen=True, parent_left=left, thread_open=True)
        start = parents[0] + 1
    elif not context.get("parent_seen"):
        return {"verified": False, "reason": "parent_not_visible",
                "message": "ยังไม่เห็นคอมเมนต์ต้นทางในหน้าจอที่ตรวจ",
                "context": context}
    left = context.get("parent_left")
    if left is None or not context.get("thread_open", True):
        return {"verified": False, "reason": "thread_closed",
                "message": "เลื่อนผ่านเธรดเป้าหมายแล้วโดยยังไม่พบคำตอบ",
                "context": context}
    # ``visible_comments`` deliberately omits URL nodes so link-preview cards
    # are not mistaken for extra comments.  Apply the same transformation to
    # the queued draft before exact comparison; otherwise every valid reply
    # containing a URL is impossible to verify even while it is visible.
    expected = norm(fb.comment_text_only(item['reply_draft']))
    accepted = {expected, norm(item['author'] + ' ' + expected)}
    saw_account = False
    saw_body = False
    for index, row in enumerate(rows[start:], start):
        child_left = avatars.get(row['top'])
        if child_left is None:
            continue
        if child_left <= left:
            context["thread_open"] = False
            break
        body = norm(fb.comment_text_only(row['text'], row['author']))
        owner_ok = norm(row['author']) == norm(item['account'])
        body_ok = body in accepted
        # Prose-only parsing omits URL nodes. Require the draft's URLs inside
        # this same reply row too; a matching sentence alone is insufficient.
        expected_urls = set(re.findall(r'https?://[^\s<>"\u200b]+', item['reply_draft']))
        row_end = rows[index + 1]['top'] if index + 1 < len(rows) else 10**6
        visible_urls = set()
        for labels, box, _ in widgets:
            if row['top'] < box[1] < row_end:
                for label in labels:
                    visible_urls.update(re.findall(r'https?://[^\s<>"\u200b]+', label))
        body_ok = body_ok and expected_urls.issubset(visible_urls)
        saw_account = saw_account or owner_ok
        saw_body = saw_body or body_ok
        # The child's Reply control is often below the viewport or omitted from
        # accessibility.  Parent boundary + indentation + exact owner/body are
        # sufficient delivery evidence; requiring that control caused false
        # negatives for long replies.
        if owner_ok and body_ok:
            return {"verified": True, "reason": "confirmed",
                    "message": "พบคำตอบใต้คอมเมนต์เป้าหมาย ชื่อบัญชีและข้อความตรง",
                    "context": context}
    if not context.get("thread_open", True):
        reason, message = "reply_not_in_thread", "ส่วนเธรดที่แสดงยังไม่พบคำตอบที่ตรง (ไม่ใช่หลักฐานว่ายังไม่ได้ส่ง)"
    elif saw_account:
        reason, message = "reply_body_mismatch", "พบคำตอบของบัญชีนี้ แต่ข้อความไม่ตรงกับที่สั่ง"
    elif saw_body:
        reason, message = "reply_owner_mismatch", "พบข้อความตรง แต่ชื่อผู้ตอบไม่ใช่บัญชีที่สั่ง"
    else:
        reason, message = "reply_not_visible_yet", "ยังไม่เห็นคำตอบที่ตรงในส่วนเธรดที่อ่านแล้ว"
    return {"verified": False, "reason": reason, "message": message,
            "context": context}


def verified_reply(xml, item, context=None, return_detail=False):
    result = _reply_frame(xml, item, context)
    return result if return_detail else bool(result["verified"])


def target_reply_expander(xml, item):
    rows = fb.visible_comments(xml)
    parents = [i for i, row in enumerate(rows)
               if norm(row['author']) == norm(item['author'])
               and norm(fb.comment_text_only(row['text'], row['author'])) ==
               norm(fb.comment_text_only(item['body'], item['author']))]
    if len(parents) != 1:
        return None
    index = parents[0]
    top = rows[index]['top']
    bottom = rows[index + 1]['top'] if index + 1 < len(rows) else 10**6
    pattern = r'^ดูการตอบกลับ\s+\d+\s+รายการที่\s+' + re.escape(norm(item['author'])) + r'\s+ได้รับ'
    points = set()
    for labels, (x1, y1, x2, y2), clickable in fb.iter_widgets(xml):
        if clickable and top < y1 < bottom and any(re.match(pattern, norm(label)) for label in labels):
            points.add(((x1 + x2) // 2, (y1 + y2) // 2))
    return next(iter(points)) if len(points) == 1 else None


def verify_on_phone_result(phone, item):
    """Reacquire the parent, expand it, then verify children across viewports."""
    expanded = False
    context = {}
    backward = 0
    forward = 0
    last_reason = {"reason": "parent_not_visible",
                   "message": "ยังไม่เห็นคอมเมนต์ต้นทางในหน้าจอที่ตรวจ"}
    for attempt in range(14):
        xml = phone.dump()
        require_unrestricted(xml)
        result = verified_reply(xml, item, context=context, return_detail=True)
        # Keep compatibility with tests/integrations which monkeypatch the old
        # boolean verifier while this function adds structured diagnostics.
        if isinstance(result, bool):
            if result:
                return {"verified": True, "reason": "confirmed",
                        "message": "พบคำตอบที่ตรง"}
        else:
            context = result["context"]
            last_reason = result
            if result["verified"]:
                return result
            if result["reason"] == "parent_ambiguous":
                break
        expand = target_reply_expander(xml, item) if not expanded else None
        if expand is not None:
            phone.tap(expand)
            expanded = True
            # The next visible parent can close a collapsed thread. Expand
            # before treating that boundary as final, then establish it anew.
            context = {}
        elif isinstance(result, dict) and result["reason"] in {
                "thread_closed", "reply_not_in_thread"}:
            break
        elif context.get("parent_seen"):
            if forward >= 7:
                break
            phone.vswipe('1500', '1150', '500')
            forward += 1
        elif backward < 3:
            # After posting, Facebook may leave the child visible while its
            # parent sits just above the viewport.  Move toward older content
            # first so the verifier can establish the exact parent boundary.
            phone.vswipe('850', '1250', '500')
            backward += 1
        else:
            # Cross the original position and search forward if the parent was
            # initially below us.  All matching still requires full parent ID.
            if forward >= 7:
                break
            phone.vswipe('1500', '1150', '500')
            forward += 1
        # A UI dump can remain byte-identical briefly after expanding or a
        # short swipe.  The loop is already bounded, so do not treat one stale
        # frame as proof that the thread has ended.
        time.sleep(1.5)
    return {"verified": False,
            "reason": last_reason.get("reason", "verification_timeout"),
            "message": last_reason.get("message", "ตรวจครบจำนวนรอบแล้วยังยืนยันไม่ได้")}


def verify_on_phone(phone, item):
    return bool(verify_on_phone_result(phone, item)["verified"])


def verification_error(result):
    if result.get("verified"):
        return ""
    return (f"{UNKNOWN} · {result.get('reason', 'verification_timeout')}: "
            f"{result.get('message', 'ตรวจครบจำนวนรอบแล้วยังยืนยันไม่ได้')}")


def send_reply(phone, item, before_submit, *, return_detail=False):
    snapshot = phone.dump()
    require_unrestricted(snapshot)
    field = phone.find(snapshot, fb.COMMENT_FIELD_HINTS)
    if field is None:
        raise ValueError("ไม่พบช่องตอบกลับ — ยังไม่ส่ง")
    phone.tap(field)
    time.sleep(1)
    existing = editor(phone.dump())
    addition, expected = composer_plan(existing, item['author'], item['reply_draft'])
    if addition:
        phone.shell('input keyevent 123')  # MOVE_END; preserve the recipient mention
        phone.type_text(addition)
    typed = phone.dump()
    require_unrestricted(typed)
    if norm(editor(typed)) != expected:
        raise ValueError("ข้อความเต็มในช่องตอบไม่ตรง — อาจแทรกกลางชื่อ จึงไม่กดส่ง")
    from fb_engage import _new_reply_target
    if not _new_reply_target('<hierarchy/>', typed, item['author']):
        raise ValueError("ก่อนส่งไม่เห็นชื่อผู้รับเต็มตรงกับคิว — หยุดไว้")
    send = phone.find(typed, fb.COMMENT_SEND_HINTS)
    if send is None:
        raise ValueError("ไม่พบปุ่มส่ง — ยังไม่ส่ง")
    before_submit()  # durable intent BEFORE the irreversible tap
    try:
        phone.tap(send)
        time.sleep(2)
        result = verify_on_phone_result(phone, item)
        return result if return_detail else bool(result["verified"])
    except FacebookRestricted:
        raise
    except Exception as error:
        phone.log(f"{UNKNOWN}: {type(error).__name__}: {error}")
        result = {"verified": False, "reason": "phone_command_error",
                  "message": f"{type(error).__name__}: {error}"}
        return result if return_detail else False
