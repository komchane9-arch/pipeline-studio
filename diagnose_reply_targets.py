"""Read-only target/delivery audit through the production phone lock and guard.

Never submits a reply. Keeps UI XML and screenshots for every dump so parsing
and navigation decisions can be replayed without operating the phone again.
"""
import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import fb_engage
import fb_engagement
import facebook_group_post as fb


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('author')
    parser.add_argument('--followup', action='store_true',
                        help='Audit the saved second comment instead of the first reply')
    parser.add_argument('--verification-only', action='store_true',
                        help='Inspect an existing delivery only; never open the Reply composer')
    parser.add_argument('--record-confirmed', action='store_true',
                        help='Record only positively verified existing delivery; never send')
    args = parser.parse_args()
    with sqlite3.connect(f'file:{fb_engagement.DB_FILE}?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute('SELECT * FROM my_comment WHERE author=? AND account=?',
                            (args.author, 'Khao Fang Nichapa')).fetchall()
    if len(rows) != 1:
        raise RuntimeError('Target must resolve to exactly one saved comment')
    item = dict(rows[0])
    if args.followup:
        if not str(item.get('followup_draft') or '').strip():
            raise RuntimeError('Target has no saved second comment')
        item.update(
            comment_key=fb_engagement.followup_key(item['comment_key']),
            parent_comment_key=item['comment_key'],
            queue_kind='followup',
            reply_draft=item['followup_draft'],
            reply_queued_at=item['followup_queued_at'],
            reply_submitted_at=item['followup_submitted_at'],
            reply_attempted_at=item['followup_attempted_at'],
            reply_error=item['followup_error'],
        )
    if args.verification_only and not item.get('reply_submitted_at'):
        # In-memory routing marker only.  It is never written to the database;
        # it selects run_queued_reply's read-only delivery verifier.
        item['reply_submitted_at'] = 'diagnostic-verification-only'
    meta = fb_engagement._post_meta_by_link().get(item['post_url'], {})
    item.update({key: meta.get(key, '') for key in ('caption', 'group_id', 'group_name', 'job_id')})
    folder = Path('data/reply-audit') / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + args.author.split()[0])
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'item.json').write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding='utf-8')
    original = fb.Phone.dump
    counter = 0

    def audited_dump(phone):
        nonlocal counter
        xml = original(phone)
        counter += 1
        stem = folder / f'{counter:03d}'
        stem.with_suffix('.xml').write_text(xml, encoding='utf-8')
        parsed = fb.visible_comments(xml)
        stem.with_suffix('.json').write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding='utf-8')
        try:
            png = phone.run('exec-out', 'screencap', '-p', timeout=15).stdout
            if png.startswith(b'\x89PNG'):
                stem.with_suffix('.png').write_bytes(png)
        except Exception as error:
            print('screenshot unavailable:', type(error).__name__, flush=True)
        print('snapshot', stem, flush=True)
        return xml

    fb.Phone.dump = audited_dump
    try:
        result = fb_engage.run_queued_reply(item, send=False, log=lambda s: print(s, flush=True))
        (folder / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        if args.record_confirmed and result.get('sent') and result.get('ok'):
            fb_engagement.mark_reply_result(item['comment_key'], True)
            print('Recorded confirmed delivery (no submission)', flush=True)
    finally:
        fb.Phone.dump = original


if __name__ == '__main__':
    main()
