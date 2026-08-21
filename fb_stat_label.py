"""ติดป้ายคอมเมนต์ด้วยกฎ — ล้างชื่อที่แท็กออก + แยกคนขาย/ลูกค้า/สแปม

ทำไมต้องมี (วัดจริงจาก 321 คอมเมนต์ในกลุ่ม 530350214974266):
  74.8% ของคอมเมนต์มีการแท็กชื่อเพื่อน · 41.7% เป็นชื่อล้วนไม่มีเนื้อความเลย
  และคอมเมนต์ที่ไลก์สูงสุดในฐาน (♥10) คือชื่อคน 8 คนต่อกันไม่มีตัวคั่น
  ถ้าไม่ล้างก่อน "คอมเมนต์ยอดนิยม" ที่ส่งให้ Claude อ่านจะเป็นขยะทั้งแถว

กติกา: กฎเป็นคนตัดสินก่อนเสมอ และต้องบันทึกว่าใช้กฎข้อไหน (rule_hit) เพื่อตรวจย้อนได้
Claude แก้ทับได้เฉพาะแถวที่กฎยอมรับว่าไม่มั่นใจ (rule_role='chat'/'unknown')
ผ่านคอลัมน์ llm_role — ของเดิมไม่ถูกลบ เทียบกันได้ว่ากฎพลาดตรงไหนบ่อย
"""
from __future__ import annotations

import re
import time

import fb_stat_store as st

# ── คำสแปม — ขยายจาก is_spam() เดิมที่วัด recall ได้แค่ 40% (จับเงินกู้ได้ แต่พลาดพนัน/ใบขับขี่)
SPAM_PAT = re.compile(
    r"ปล่อยกู้|เงินกู้|สร้างเครดิต|ยอดว่าง|ดอกเบี้ยต่ำ|อนุมัติไว"
    r"|wy88|ufa|สล็อต|บาคาร่า|เว็บตรง|แทงบอล|ฝากถอนออโต้|พนัน|เครดิตฟรี"
    r"|ใบขับขี่|รับทำใบ|กยศ|ปิดหนี้")
# ── คนขาย: ประโยคที่มีแต่ฝั่งคนเสนอของเท่านั้นที่พูด
SELLER_PAT = re.compile(
    r"แชทมา|ทักแชท|ทักมา|inbox|อินบ๊อก|ฝากร้าน|ฝากหน่อย|ขออนุญาต(โพสต์|ฝาก)"
    r"|รวมส่ง|มีขาย|ขายอยู่|เหลือ\s*\d|รับหิ้ว|สนใจทัก|เผื่อสนใจ|ราคาส่ง|พร้อมส่ง")
# ── ลูกค้า: ประโยคถามซื้อ/ถามราคา
CUSTOMER_PAT = re.compile(
    r"เท่า(ไหร่|ไร)|ราคา(เท่า|ไหม|มั้ย)?$|ยังอยู่|ขายไหม|ขายมั้ย|ซื้อ(ยัง|ไง|ที่ไหน)"
    r"|สั่ง(ยัง|ไง|ที่ไหน)|จอง|เอาคะ|เอาครับ|ปล่อยทักมา|ไปยัง|อยู่ที่ไหน|กี่บาท")
# ── ขานรับ/คุยเล่นสั้นๆ ที่ไม่มีข้อมูลอะไรเลย (วัดแล้วมี 45 แถวในโพสต์เดียว)
ACK_PAT = re.compile(r"^(เห็น|อยู่|มา|ครับ|ค่ะ|คะ|จ้า|โอเค|ok|\+|5|ๆ|\W|\d)+$", re.I)

# คำหน้าที่/คำพูดทั่วไปในภาษาไทย — ถ้าข้อความยาวแต่ไม่มีคำพวกนี้เลย แปลว่าไม่ใช่ประโยค
# (ใช้เป็นกฎชั้นที่ 4 จับชื่อไทยที่ไม่มีเครื่องหมายประดับ ซึ่งสามชั้นแรกจับไม่ได้)
THAI_FUNC = re.compile(
    r"ครับ|ค่ะ|คะ|นะ|จ้า|ที่|ไม่|มี|เป็น|ไป|มา|ได้|จะ|แล้ว|ยัง|กับ|ให้|อยาก|ขอ|ทำ|เอา"
    r"|ดี|เห็น|กัน|เลย|มาก|ราคา|บาท|555|อยู่|ๆ")
HAS_DIGIT = re.compile(r"\d")

# ชื่อฝรั่งที่ FB แท็กมาติดกัน: อย่างน้อยสองคำขึ้นต้นด้วยตัวใหญ่
LATIN_NAME = re.compile(r"\b[A-Z][A-Za-z]{1,}(?:\s+[A-Z][A-Za-z]{1,})+\b")
# ชื่อเล่นไทยแบบ FB มักมีเครื่องหมายประดับติดมา (ฯ ' ’ จุดกลางคำ)
THAI_DECOR = re.compile(r"[^\s]*[ฯ'’·][^\s]*")

RULE_VER = st.RULE_VER


def clean_body(body: str, lexicon: set[str]) -> tuple[str, list[str]]:
    """ตัดชื่อที่ถูกแท็กออกจากข้อความ — คืน (ข้อความที่เหลือ, รายชื่อที่ตัดออก)

    ใช้สามชั้น เรียงจากมั่นใจสุด:
      1. ชื่อที่ตรงกับ lexicon (ชื่อผู้โพสต์/ผู้คอมเมนต์จริงในฐาน) — แม่นที่สุด
      2. ชื่อฝรั่งตัวใหญ่ติดกัน 2 คำขึ้นไป
      3. โทเคนที่มีเครื่องหมายประดับแบบชื่อเล่น FB
    """
    names: list[str] = []
    out = body
    for nm in sorted(lexicon, key=len, reverse=True):
        if len(nm) >= 4 and nm in out:
            out = out.replace(nm, " ")
            names.append(nm)
    for m in LATIN_NAME.finditer(out):
        names.append(m.group(0))
    out = LATIN_NAME.sub(" ", out)
    for m in THAI_DECOR.finditer(out):
        if len(m.group(0)) >= 3:
            names.append(m.group(0))
    out = THAI_DECOR.sub(" ", out)
    return re.sub(r"\s+", " ", out).strip(), names


def role_of(clean: str, raw: str, is_spam_db: int) -> tuple[str, str]:
    """คืน (บทบาท, กฎที่ยิงโดน) — ลำดับกฎสำคัญ ห้ามสลับ"""
    if m := SPAM_PAT.search(raw):
        return "spam", f"spam:{m.group(0)}"
    if is_spam_db:
        return "spam", "spam:is_spam()"
    if m := SELLER_PAT.search(clean):
        return "seller", f"seller:{m.group(0)}"
    if m := CUSTOMER_PAT.search(clean):
        return "customer", f"customer:{m.group(0)}"
    if len(clean) < 4:
        return "tagger", "tagonly:สั้นกว่า 4 ตัวอักษรหลังตัดชื่อ"
    if ACK_PAT.match(clean):
        return "chat", "ack:ขานรับล้วน"
    return "chat", "chat:มีเนื้อหาแต่ไม่เข้ากฎไหน"


def label_group(conn, gid: str) -> dict:
    """ติดป้ายคอมเมนต์ทั้งกลุ่ม (เขียนทับของเดิมเสมอเมื่อ rule_ver เปลี่ยน)"""
    lex = {r[0].strip() for r in conn.execute(
        "SELECT DISTINCT author FROM src.fb_post WHERE gid=? AND author<>'' "
        "UNION SELECT DISTINCT c.author FROM src.fb_comment c JOIN src.fb_post p "
        "ON p.post_id=c.post_id WHERE p.gid=? AND c.author<>''", (gid, gid))}
    rows = conn.execute("""
        SELECT c.comment_id, c.post_id, c.body, c.is_spam, c.likes
        FROM src.fb_comment c JOIN src.fb_post p ON p.post_id=c.post_id
        WHERE p.gid=?""", (gid,)).fetchall()
    now = int(time.time())
    tally = {"tagonly": 0, "lowinfo": 0}
    roles: dict[str, int] = {}
    for r in rows:
        raw = r["body"] or ""
        clean, names = clean_body(raw, lex)
        role, hit = role_of(clean, raw, r["is_spam"])
        tagonly = int(bool(names) and len(clean) < 4)
        # กฎชั้น 4: ยาวพอสมควร แต่ไม่มีคำหน้าที่ไทยและไม่มีตัวเลขเลย = รายชื่อคน ไม่ใช่ประโยค
        # วัดกับที่นับมือไว้ (แท็กล้วน 134/321 ในกลุ่ม 530350214974266) กฎนี้จับได้ 141 = เกินจริง ~5%
        if not tagonly and clean and len(clean) >= 8 \
                and not THAI_FUNC.search(clean) and not HAS_DIGIT.search(clean):
            tagonly = 1
            if role == "chat":
                role, hit = "tagger", "tagonly:ไม่มีคำหน้าที่ไทยเลย น่าจะเป็นรายชื่อ"
        lowinfo = int(len(clean) < 5 or bool(ACK_PAT.match(clean)) if clean else 1)
        tally["tagonly"] += tagonly
        tally["lowinfo"] += lowinfo
        roles[role] = roles.get(role, 0) + 1
        conn.execute("""INSERT OR REPLACE INTO comment_label
            (comment_id,gid,post_id,body_clean,tag_names,n_tags,is_tagonly,is_lowinfo,
             rule_role,rule_hit,llm_role,llm_note,rule_ver,labeled_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,
                    COALESCE((SELECT llm_role FROM comment_label WHERE comment_id=?),''),
                    COALESCE((SELECT llm_note FROM comment_label WHERE comment_id=?),''),
                    ?,?)""",
                     (r["comment_id"], gid, r["post_id"], clean, "|".join(names[:12]),
                      len(names), tagonly, lowinfo, role, hit,
                      r["comment_id"], r["comment_id"], RULE_VER, now))
    conn.commit()
    return {"gid": gid, "n": len(rows), "roles": roles, **tally}


def main() -> int:
    import sys
    conn = st.connect(write=True)
    gids = sys.argv[1:] or [r[0] for r in conn.execute(
        "SELECT p.gid FROM src.fb_comment c JOIN src.fb_post p ON p.post_id=c.post_id "
        "GROUP BY p.gid")]
    for gid in gids:
        info = label_group(conn, gid)
        pct = lambda k: f"{info[k]/max(info['n'],1)*100:.1f}%"
        print(f"[{gid}] คอมเมนต์ {info['n']} · แท็กล้วน {info['tagonly']} ({pct('tagonly')}) "
              f"· ข้อมูลน้อย {info['lowinfo']} ({pct('lowinfo')}) · {info['roles']}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
