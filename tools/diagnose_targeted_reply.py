"""One explicitly selected reply; default is inspect only. Save UI evidence."""
import argparse
import json
from pathlib import Path
import sys
import traceback
from datetime import datetime
from unittest.mock import patch
from urllib.request import urlopen
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fb_engage
import fb_engagement as store
import facebook_group_post as fb


def main():
    args = argparse.ArgumentParser()
    args.add_argument('--send', action='store_true')
    args.add_argument('--manual', action='store_true', help='Explicit owner override of hourly/gap only')
    args.add_argument('--record-block', type=Path, help='Persist a captured restriction, without touching phone')
    args.add_argument('--account', default='Preaw Buchakorn')
    args.add_argument('--author', default='จุ๊บ แจง')
    args.add_argument('--url', default='https://www.facebook.com/share/p/1BZdem2mYw/')
    opt = args.parse_args()
    account, author, url = opt.account, opt.author, opt.url
    post = next(p for p in store.threads(500, False, account) if p['post_url'] == url)
    matches = [c for c in post['comments_list'] if c['author'] == store.split_comment_author(author)[0] and c.get('reply_draft')]
    if len(matches) != 1:
        raise RuntimeError('Target must be unique')
    item = {**post, **matches[0]}
    if opt.record_block:
        import fb_auto_post
        xml = opt.record_block.read_text(encoding='utf-8')
        reason = fb.fb_comment_guard.detect_block(xml)
        if not reason:
            raise RuntimeError('No Facebook restriction in evidence')
        with fb_auto_post.use_account(account):
            fb.fb_comment_guard.note_failure(xml)
            print(fb.fb_comment_guard.hold_reason())
        print(store.mark_reply_result(item['comment_key'], False,
              reason + ' — พบแจ้งเตือนจริงหลังส่ง เปิดตรวจซ้ำแล้วยังยืนยันคำตอบไม่ได้'))
        return
    if item.get('reply_sent_at'):
        print('Already recorded successful; no action')
        return
    with urlopen('http://127.0.0.1:8866/api/fb/engage/status?account=' + quote(account), timeout=15) as response:
        status = json.load(response)
    if status.get('work_priority', {}).get('blocked'):
        raise RuntimeError('Post priority currently blocks this account')
    if opt.send and store.reply_daily_status(account)['waiting']:
        raise RuntimeError('Daily quota exhausted')
    if opt.manual:
        allowed = {'Bunriam Phiwwandee', 'จรีรัตน์ พึ่งดาบศ', 'จินดา วิลัยพล',
                   'สมบูรณ์ วรรณใส', 'Namtip Janpunya'}
        if account != 'Khao Fang Nichapa' or item['author'] not in allowed:
            raise RuntimeError('Manual override is authorized only for the five selected replies')
        fb.allow_manual(10)
    out = Path('diagnostics') / ('target-reply-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True, exist_ok=True)
    print('Evidence:', out, flush=True)
    log_file = out / 'trace.log'
    def log(line):
        print(line, flush=True)
        with log_file.open('a', encoding='utf-8') as handle:
            handle.write(str(line) + '\n')
    original = fb.Phone
    import fb_account_guard
    original_guard_dump = fb_account_guard._dump
    guard_count = 0
    def guard_dump(*args, **kwargs):
        nonlocal guard_count
        xml = original_guard_dump(*args, **kwargs)
        guard_count += 1
        (out / f'guard-{guard_count:03d}.xml').write_text(xml, encoding='utf-8')
        return xml
    class EvidencePhone(original):
        count = 0
        def dump(self):
            xml = super().dump()
            self.count += 1
            (out / f'{self.count:03d}.xml').write_text(xml, encoding='utf-8')
            return xml
    try:
        with patch.object(fb, 'Phone', EvidencePhone), patch.object(fb_account_guard, '_dump', guard_dump):
            result = fb_engage.run_queued_reply(item, send=opt.send, log=log)
    except Exception as error:
        log(traceback.format_exc())
        result = {'sent': False, 'error': f'{type(error).__name__}: {error}'}
    if opt.send and not result.get('waiting'):
        result['receipt'] = store.mark_reply_result(item['comment_key'], bool(result.get('sent')), result.get('error', ''))
        if result.get('sent'):
            store.schedule_next_reply(item['comment_key'], account)
    (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    log(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
