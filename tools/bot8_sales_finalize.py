"""Recheck a completed Bot8 sales report and retain rejected rows as an audit trail."""
import argparse
import json
from pathlib import Path
import shutil
import sys

from bot8_today_report import ROOT, sale_reason, save_report, score


def recheck(state, folder):
    if state.get('mode') != 'sales' or len(state.get('groups', [])) != 12:
        raise ValueError('ต้องเป็นรายงานโพสต์ขายที่ตรวจครบ 12 กลุ่ม')
    if not str(state.get('status', '')).startswith('จบรอบค้นเพิ่ม'):
        raise ValueError('รอบค้นเพิ่มยังไม่จบ — ห้ามปรับรายงานระหว่างทำงาน')
    rejected = []
    for group in state['groups']:
        kept = []
        for post in group.get('selected', []):
            reason = sale_reason(post)
            if not reason:
                rejected.append({'group': group['name'], 'id': post.get('id'),
                                 'url': post.get('url'), 'why': 'ไม่มีหลักฐานชวนซื้อชัดเจน',
                                 'caption': post.get('caption', ''), 'image': post.get('image', '')})
                continue
            if score(post) <= 100 or not post.get('url') or not (folder / post.get('image', '')).is_file():
                raise ValueError('โพสต์ที่เลือกขาดยอดรวม ลิงก์ หรือภาพ: ' + str(post.get('id')))
            post['sales_reason'] = reason
            kept.append(post)
        if len(kept) > 5:
            raise ValueError('คัดเกิน 5 โพสต์ในกลุ่ม ' + group['name'])
        group['selected'] = kept
        group['verified_count'] = len(kept)
    state['audit_rejected'] = rejected
    state['audit_note'] = 'คัดซ้ำจากข้อความและภาพตัวอย่าง; รายการที่ไม่ชวนซื้อชัดเจนเก็บไว้ใน audit_rejected โดยไม่ลบหลักฐาน'
    state['status'] = 'ตรวจคัดซ้ำแล้ว — ' + str(sum(len(g['selected']) for g in state['groups'])) + ' โพสต์ขายเข้าเกณฑ์'
    return rejected


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--apply', action='store_true', help='Write audited JSON and HTML after dry run')
    args = parser.parse_args()
    folder = args.report.resolve()
    if not folder.is_relative_to(ROOT / 'data' / 'reports'):
        raise ValueError('report ต้องอยู่ใน data/reports ของโปรเจกต์นี้')
    state = json.loads((folder / 'report.json').read_text(encoding='utf-8'))
    rejected = recheck(state, folder)
    print('คัดออก', len(rejected), 'โพสต์:', [(row['group'], row['id']) for row in rejected])
    print('คงไว้', sum(len(group['selected']) for group in state['groups']), 'โพสต์')
    if args.apply:
        for name in ('report.json', 'report.html'):
            original = folder / name
            backup = folder / name.replace('report.', 'report-before-audit.')
            if not backup.exists():
                shutil.copy2(original, backup)
        save_report(folder, state)


if __name__ == '__main__':
    main()
