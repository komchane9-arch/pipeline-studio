"""Read-only mobile evidence for one job's linked post; never send comments."""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import facebook_group_post as fb
import studio_shared as shared


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--job', required=True)
    parser.add_argument('--account', required=True)
    parser.add_argument('--group', required=True)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    devices = json.loads(Path('data/devices.json').read_text(encoding='utf-8'))['devices']
    matching = [d for d in devices.values() if d.get('account') == args.account and d.get('enabled')]
    if len(matching) != 1:
        raise RuntimeError('Device mapping is not unique')
    serial = matching[0]['serial']
    jobs = json.loads((shared.account_dir(args.account) / 'fb_jobs.json').read_text(encoding='utf-8'))
    if isinstance(jobs, dict):
        jobs = jobs['jobs']
    job = next(j for j in jobs if j['id'] == args.job)
    row = next(r for r in job['results'] if r['group_id'] == args.group)
    out = Path('diagnostics') / ('job-comments-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True)
    with shared.phone_lock(serial, timeout=30, label='ตรวจคอมเมนต์จากลิงก์แบบอ่านอย่างเดียว'):
        phone = fb.Phone('adb', serial)
        opened = fb.open_post_link(phone, row['link'], job['caption'], group_id=args.group)
        if not opened:
            raise RuntimeError('Linked post could not be confirmed')
        if args.verify:
            original_dump = phone.dump
            counter = [0]
            def dump():
                xml = original_dump()
                (out / f'{counter[0]:02d}.xml').write_text(xml, encoding='utf-8')
                counter[0] += 1
                return xml
            phone.dump = dump
            result = fb.verify_existing_comments(phone, lambda: job['comments'], args.account)
            (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(result, ensure_ascii=False), flush=True)
            print('EVIDENCE=' + str(out.resolve()), flush=True)
            return
        samples = []
        for index in range(9):
            xml = phone.dump()
            (out / f'{index:02d}.xml').write_text(xml, encoding='utf-8')
            visible = fb.visible_comments(xml)
            samples.append({'step':index,'comments':visible,
                            'probes':[fb.screen_has(xml, fb.comment_probe(t)) for t in job['comments']]})
            print(json.dumps(samples[-1], ensure_ascii=False), flush=True)
            if index < 8:
                phone.vswipe('1700','1200','500')
                time.sleep(1.5)
        (out / 'evidence.json').write_text(json.dumps({'account':args.account,'serial':serial,
            'job':args.job,'link':row['link'],'wanted':job['comments'],'samples':samples},
            ensure_ascii=False, indent=2), encoding='utf-8')
    print('EVIDENCE=' + str(out.resolve()), flush=True)


if __name__ == '__main__':
    main()
