"""Extend one Bot8 sales report using read-only searches inside missing groups."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sys
import time
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.bot8_today_report import sale_reason, save_report, score

TZ = timezone(timedelta(hours=7))


def new_sales(posts, group_id, known):
    """Take only qualifying posts in this group, excluding already saved IDs/URLs."""
    result = []
    seen = set(known)
    for post in posts:
        url = post.get('url') or ''
        pid = str(post.get('id') or '')
        if not url or not pid or f'/groups/{group_id}/' not in url or score(post) <= 100:
            continue
        reason = sale_reason(post)
        if not reason or url in seen or (pid and pid in seen):
            continue
        post['total_engagement'] = score(post)
        post['sales_reason'] = reason
        result.append(post)
        seen.update((url, pid))
    return sorted(result, key=lambda post: -post['total_engagement'])


def main():
    args = argparse.ArgumentParser()
    args.add_argument('--report', type=Path, required=True)
    args.add_argument('--scrolls', type=int, default=25)
    args.add_argument('--queries', default='พิกัด,สั่งซื้อ')
    options = args.parse_args()
    if options.scrolls < 1 or options.scrolls > 100:
        raise ValueError('--scrolls ต้องอยู่ระหว่าง 1 ถึง 100')
    folder = options.report.resolve()
    if not folder.is_relative_to(ROOT / 'data' / 'reports'):
        raise ValueError('report ต้องอยู่ใน data/reports ของโปรเจกต์นี้')
    state = json.loads((folder / 'report.json').read_text(encoding='utf-8'))
    if state.get('mode') != 'sales' or len(state.get('groups', [])) != 12:
        raise ValueError('ต้องใช้รายงานโหมด sales ที่ตรวจครบ 12 กลุ่ม')
    queries = [query.strip() for query in options.queries.split(',') if query.strip()]
    if not queries:
        raise ValueError('ไม่มีคำค้น')

    import evidence
    import fb_mass_finder as finder
    import studio_shared as shared
    from bot_profiles import ProfileFarm
    from playwright.sync_api import sync_playwright

    def log(message):
        line = datetime.now(TZ).isoformat() + ' ' + message
        print(line, flush=True)
        with (folder / 'progress.log').open('a', encoding='utf-8') as out:
            out.write(line + '\n')

    missing = [group for group in state['groups'] if len(group.get('selected', [])) < 5]
    if not missing:
        log('ครบ 5 โพสต์ทุกกลุ่มอยู่แล้ว')
        return
    farm = ProfileFarm(shared.DATA_DIR)
    entry = finder.find_bot(farm, 'Bot8')
    log(f'เริ่มค้นเพิ่ม {len(missing)} กลุ่ม; ไม่สแกนฟีดเดิมซ้ำ')
    state['status'] = 'กำลังค้นเพิ่มในกลุ่มที่ยังไม่ครบ'
    save_report(folder, state)
    try:
        with sync_playwright() as pw:
            context = finder.launch_bot_browser(pw, farm, entry)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                finder.ensure_logged_in(page, context)
                for index, group in enumerate(missing):
                    if index:
                        state['status'] = 'พักระหว่างกลุ่ม 60 วินาที'
                        save_report(folder, state)
                        time.sleep(60)
                    state['status'] = 'กำลังค้นเพิ่ม ' + group['name']
                    save_report(folder, state)
                    log(state['status'])
                    known = set()
                    for post in group.get('selected', []):
                        known.update((str(post.get('id') or ''), post.get('url') or ''))
                    candidates = {}
                    group.setdefault('search_notes', [])
                    for query in queries:
                        if len(group['selected']) + len(candidates) >= 5:
                            break
                        url = f"https://www.facebook.com/groups/{group['id']}/search/?q={quote(query)}"
                        try:
                            result = finder.scan_group(page, url, options.scrolls, log)
                            posts = result['posts']
                            for post in new_sales(posts, group['id'], known | set(candidates)):
                                candidates[str(post['id'])] = post
                            note = {'query': query, 'scanned': len(posts),
                                    'new_eligible': len(candidates), 'error': result.get('error', '')}
                            group['search_notes'].append(note)
                            log(f"  คำค้น {query}: อ่าน {len(posts)} โพสต์ · ผ่านเพิ่ม {len(candidates)}")
                        except Exception as exc:
                            why = type(exc).__name__ + ': ' + str(exc)
                            evidence.capture('Bot8-ค้นโพสต์ขายไม่สำเร็จ-' + group['id'],
                                             tag='bot8', page=page, note=query + ': ' + why)
                            group['search_notes'].append({'query': query, 'error': why})
                            log(f'  คำค้น {query} ล้ม: {why}')
                        save_report(folder, state)
                    ranked = sorted(candidates.values(), key=lambda post: -score(post))
                    group['search_eligible_count'] = len(ranked)
                    group['eligible_count'] = int(group.get('eligible_count') or 0) + len(ranked)
                    for post in ranked:
                        if len(group['selected']) >= 5:
                            break
                        rank = len(group['selected']) + 1
                        try:
                            page.goto(post['url'], wait_until='domcontentloaded', timeout=60000)
                            page.wait_for_timeout(4000)
                            if 'login' in page.url or 'checkpoint' in page.url:
                                raise RuntimeError('Facebook กลับไปหน้า login/checkpoint')
                            shot = evidence.capture('โพสต์ขายค้นเพิ่ม-' + group['id'] + '-' + str(rank),
                                                    tag='bot8', page=page,
                                                    note=json.dumps(post, ensure_ascii=False))
                            if not shot or not shot.with_suffix('.png').exists():
                                raise RuntimeError('ไม่พบภาพหลักฐานของโพสต์')
                            name = group['id'] + '-' + str(rank) + '.png'
                            shutil.copy2(shot.with_suffix('.png'), folder / name)
                            post['image'] = name
                            post['capture_note'] = 'พบโพสต์จากผลค้นหาและเก็บภาพแล้ว; ตรวจภาพประกอบ'
                            group['selected'].append(post)
                            known.update((str(post.get('id') or ''), post['url']))
                            save_report(folder, state)
                        except Exception as exc:
                            why = type(exc).__name__ + ': ' + str(exc)
                            evidence.capture('Bot8-แคปโพสต์ค้นเพิ่มไม่สำเร็จ-' + group['id'],
                                             tag='bot8', page=page, note=why + ' ' + post['url'])
                            log('  ข้ามโพสต์ที่แคปไม่ได้: ' + why)
                    group['selected'].sort(key=lambda post: -score(post))
                    log(f"ค้นเพิ่มเสร็จ {index + 1}/{len(missing)}: รวม {len(group['selected'])}/5 โพสต์")
                    save_report(folder, state)
            finally:
                context.close()
        state['status'] = 'จบรอบค้นเพิ่ม — ดูจำนวนที่ผ่านเกณฑ์จริงแต่ละกลุ่ม'
    except Exception as exc:
        state['status'] = 'หยุดค้นเพิ่ม: ' + type(exc).__name__ + ': ' + str(exc)
        log(state['status'])
        raise
    finally:
        save_report(folder, state)


if __name__ == '__main__':
    main()
