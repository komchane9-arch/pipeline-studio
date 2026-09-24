"""Read-only, bounded Bot8 collection for daily or popular-sale reports."""
import argparse
from datetime import datetime, timedelta, timezone
import html
import json
from pathlib import Path
import re
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TZ = timezone(timedelta(hours=7))

COMMERCE_LINK = re.compile(
    r'(?:s\.shopee\.co\.th|shopee\.(?:co\.th|com)|s\.lazada\.co\.th|'
    r'lazada\.co\.th|shop\.tiktok\.com|vt\.tiktok\.com/[^\s]+)', re.I)
SALE_CTA = re.compile(
    r'(?:พิกัด\s*(?:สั่ง|ในคอม|ใต้(?:รูป|ภาพ)|อยู่(?:ที่|ใน)|[:👉📍])|'
    r'กดสั่ง|สั่งซื้อ|สั่งได้|รับออเดอร์|พร้อมส่ง|สนใจทัก|'
    r'ทัก(?:แชท|เพจ|มาสั่ง)|แปะลิงก์|ลิงก์สั่ง|กดตะกร้า|ในตะกร้า|'
    r'โค้ด(?:ลด|ส่วนลด)|โปร(?:วันนี้|พิเศษ|ลดราคา)|ซื้อได้ที่|'
    r'เปิดรับพรีออเดอร์|รับหิ้ว|ราคาพิเศษ|ขายต่อ|ปล่อยต่อ)', re.I)
REQUEST_ONLY = re.compile(r'(?:ขอพิกัด|พิกัดอยู่ไหน|สั่งซื้อที่ไหน|ซื้อที่ไหน)', re.I)
NOT_OFFER = re.compile(
    r'(?:เดี๋ยวแชร์.{0,60}พิกัด|ใช้ตัวไหนดี|ใครมีลิ[ง๊]ก์ฝาก|เผลอกดสั่ง)', re.I)


def score(post):
    return sum(int(post.get(key) or 0) for key in ('likes', 'comments', 'shares'))


def sale_reason(post):
    """Return positive purchase evidence, not a guess from a product name alone."""
    caption = post.get('caption') or ''
    if not caption.strip():
        return ''
    if COMMERCE_LINK.search(caption):
        return 'มีลิงก์ร้านค้าในข้อความโพสต์'
    if SALE_CTA.search(caption) and not REQUEST_ONLY.search(caption) and not NOT_OFFER.search(caption):
        return 'มีข้อความชวนสั่งซื้อ/เสนอขาย'
    return ''


def popular_sale_posts(posts):
    eligible = []
    for post in posts:
        if score(post) <= 100:
            continue
        reason = sale_reason(post)
        if reason:
            post['sales_reason'] = reason
            post['total_engagement'] = score(post)
            eligible.append(post)
    return sorted(eligible, key=lambda p: -p['total_engagement'])[:5]


def today_posts(posts, date):
    selected = []
    for post in posts:
        try:
            day = datetime.fromtimestamp(float(post.get('posted_at')), TZ).date().isoformat()
        except (ValueError, TypeError, OverflowError, OSError):
            continue
        if day == date:
            selected.append(post)
    return sorted(selected, key=lambda p: -score(p))[:5]


def save_report(folder, state):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'report.json').write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    sales = state.get('mode') == 'sales'
    popular = state.get('mode') == 'popular'
    title = ('โพสต์แมสจากกลุ่มที่ผูกไว้' if popular else
             'โพสต์ขายของยอดสนใจสูง' if sales else 'โพสต์วันนี้ — ' + state['date'])
    rule = ('ไม่จำกัดวัน · ยอดไลก์+คอมเมนต์+แชร์รวมเกิน 100 · มีลิงก์ร้านค้าหรือข้อความชวนซื้อชัดเจน'
            if sales else 'ไม่จำกัดวัน · ยอดไลก์+คอมเมนต์+แชร์รวมเกิน 100 · ไม่บังคับว่าเป็นโพสต์ขาย'
            if popular else 'เฉพาะโพสต์วันนี้')
    parts = ['<!doctype html><meta charset="utf-8"><title>Bot8 posts</title>',
             '<style>body{font:17px sans-serif;max-width:1100px;margin:30px auto}img{max-width:100%;max-height:700px}article{border:1px solid #ddd;padding:16px;margin:12px 0}pre{white-space:pre-wrap}</style>',
             '<h1>' + html.escape(title) + '</h1>',
             '<p>' + html.escape(rule) + ' · คัดสูงสุด 5 โพสต์ต่อกลุ่มจากที่ Bot8 อ่านพบ เรียงยอดรวม ไม่ใช่อันดับรับรองทั้งกลุ่ม</p>',
             '<p>สถานะ: ' + html.escape(state['status']) + '</p>']
    for group in state['groups']:
        parts.append('<h2>' + html.escape(group['name']) + '</h2><p>' + html.escape(', '.join(group['accounts'])) + '</p>')
        count_text = (f"พบยอดรวมเกิน 100 จำนวน {group.get('eligible_count', 0)} โพสต์" if popular
                      else f"คัดยืนยันแล้ว {group['verified_count']} โพสต์" if sales and 'verified_count' in group
                      else f"พบเข้าเกณฑ์ {group.get('eligible_count', 0)} โพสต์" if sales
                      else f"พบวันนี้ {group.get('today_count', 0)} โพสต์")
        parts.append('<p>' + html.escape(group.get('error', '')) +
                     f" {count_text} จากที่อ่าน {group.get('scanned', 0)} โพสต์</p>")
        for p in group.get('selected', []):
            metrics = (f"ยอดรวม {score(p)} = ถูกใจ {int(p.get('likes') or 0)} + "
                       f"คอมเมนต์ {int(p.get('comments') or 0)} + แชร์ {int(p.get('shares') or 0)}")
            parts.append('<article><a target="_blank" href="' + html.escape(p['url'], quote=True) +
                         '">เปิดโพสต์</a><p>' + metrics + '</p><p>' +
                         html.escape(p.get('sales_reason', '')) + '</p><pre>' +
                         html.escape(p.get('caption') or '') + '</pre>')
            if p.get('image'):
                parts.append('<img src="' + html.escape(p['image'], quote=True) + '">')
            parts.append('<p>' + html.escape(p.get('capture_note', '')) + '</p></article>')
    (folder / 'report.html').write_text('\n'.join(parts), encoding='utf-8')


def main():
    args = argparse.ArgumentParser()
    args.add_argument('--scrolls', type=int, default=40)
    args.add_argument('--sales', action='store_true', help='No date filter; explicit sales posts with engagement > 100')
    options = args.parse_args()
    import fb_auto_post as auto
    import fb_mass_finder as finder
    import studio_shared as shared
    from bot_profiles import ProfileFarm
    import evidence
    from playwright.sync_api import sync_playwright

    date = datetime.now(TZ).date().isoformat()
    folder = ROOT / 'data' / 'reports' / (('bot8-sales-' if options.sales else 'bot8-today-') + datetime.now(TZ).strftime('%Y%m%d-%H%M%S'))
    groups = {}
    for account in ('Khao Fang Nichapa', 'Preaw Buchakorn'):
        with auto.use_account(account):
            for g in auto.GroupStore(auto.state_file('fb_groups.json')).listing():
                gid = str(g['group_id'])
                groups.setdefault(gid, {'id': gid, 'name': g['name'], 'accounts': []})['accounts'].append(account)
    state = {'date': date, 'mode': 'sales' if options.sales else 'today',
             'status': 'starting', 'groups': [], 'scope': list(groups.values())}
    save_report(folder, state)
    print('REPORT ' + str(folder), flush=True)

    def log(message):
        line = datetime.now(TZ).isoformat() + ' ' + message
        print(line, flush=True)
        with (folder / 'progress.log').open('a', encoding='utf-8') as out:
            out.write(line + '\n')

    try:
        farm = ProfileFarm(shared.DATA_DIR)
        entry = finder.find_bot(farm, 'Bot8')
        with sync_playwright() as pw:
            context = finder.launch_bot_browser(pw, farm, entry)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                try:
                    finder.ensure_logged_in(page, context)
                except Exception:
                    ev = evidence.capture('Bot8-ตรวจล็อกอินไม่ผ่าน', tag='bot8', page=page)
                    log('หลักฐานล็อกอิน: ' + str(ev))
                    raise
                for index, group in enumerate(groups.values()):
                    if index:
                        state['status'] = 'พักระหว่างกลุ่ม 60 วินาที'
                        save_report(folder, state)
                        time.sleep(60)
                    state['status'] = 'กำลังอ่าน ' + group['name']
                    save_report(folder, state)
                    log(state['status'])
                    record = dict(group)
                    state['groups'].append(record)
                    try:
                        result = finder.scan_group(page, 'https://www.facebook.com/groups/' + group['id'] + '/', options.scrolls, log)
                        posts = result['posts']
                        selected = popular_sale_posts(posts) if options.sales else today_posts(posts, date)
                        record.update(scanned=len(posts), selected=selected, error=result.get('error', ''))
                        if options.sales:
                            record['eligible_count'] = sum(score(p) > 100 and bool(sale_reason(p)) for p in posts)
                            record['high_engagement_preview'] = [
                                {key: p.get(key) for key in ('id', 'url', 'caption', 'likes', 'comments', 'shares')}
                                for p in sorted((p for p in posts if score(p) > 100), key=lambda p: -score(p))[:20]
                            ]
                        else:
                            record['today_count'] = sum(bool(today_posts([p], date)) for p in posts)
                        for rank, post in enumerate(record['selected'], 1):
                            page.goto(post['url'], wait_until='domcontentloaded', timeout=60000)
                            page.wait_for_timeout(5000)
                            body = page.inner_text('body')
                            caption = (post.get('caption') or '').strip()
                            visible = bool(caption and ' '.join(caption[:60].split()) in ' '.join(body.split()))
                            ev = evidence.capture(('โพสต์ขายยอดสูง-' if options.sales else 'โพสต์วันนี้-') + group['id'] + '-' + str(rank), tag='bot8', page=page, note=json.dumps(post, ensure_ascii=False))
                            if ev and ev.with_suffix('.png').exists():
                                name = group['id'] + '-' + str(rank) + '.png'
                                shutil.copy2(ev.with_suffix('.png'), folder / name)
                                post['image'] = name
                            post['capture_note'] = 'พบข้อความโพสต์ในหน้าที่แคป' if visible else 'แคปแล้ว แต่ยังยืนยันข้อความโพสต์บนหน้าภาพไม่ได้ ต้องตรวจภาพ'
                            save_report(folder, state)
                        log(f"เสร็จ {index+1}/{len(groups)}: เลือก {len(record['selected'])} โพสต์")
                    except Exception as exc:
                        record['error'] = type(exc).__name__ + ': ' + str(exc)
                        evidence.capture('กลุ่มอ่านไม่สำเร็จ-' + group['id'], tag='bot8', page=page, note=record['error'])
                        log(record['error'])
                    save_report(folder, state)
            finally:
                context.close()
        state['status'] = 'จบรอบตรวจ — ดูจำนวนที่พบและข้อจำกัดแต่ละกลุ่ม'
    except Exception as exc:
        state['status'] = 'หยุด: ' + type(exc).__name__ + ': ' + str(exc)
        log(state['status'])
        raise
    finally:
        save_report(folder, state)


if __name__ == '__main__':
    main()
