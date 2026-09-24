import { api, CLIP_API } from './library-api.js';

const node = (tag, props = {}, ...children) => {
  const n = Object.assign(document.createElement(tag), props);
  n.append(...children);
  return n;
};
let panel, data = { shops: [], items: [] }, selected = '', lastLoad = 0, loading = null;
let detailSequence = 0, selectedSignature = '';
const expanded = new Set();
const pullingShops = new Set();
let onChange = () => {};
const endpoint = `${CLIP_API}/api/link-library`;
const safeURL = value => { try { const u = new URL(value); return ['http:', 'https:'].includes(u.protocol) ? u.href : ''; } catch { return ''; } };
const fileURL = (id, file) => `${CLIP_API}/api/clips/${encodeURIComponent(id)}/file/${file.split('/').map(encodeURIComponent).join('/')}`;

function note(message, bad = false) {
  const n = panel.querySelector('.ll-note'); n.textContent = message; n.classList.toggle('ll-error', bad);
}
async function copyShopLinks(shop) {
  // Copy the whole group, including rows hidden by the current search.
  const urls = [...new Set(data.items.filter(row => row.shop === shop).map(row => row.url).filter(Boolean))];
  if (!urls.length) return;
  const text = urls.join('\n');
  let copied = false;
  try { await navigator.clipboard.writeText(text); copied = true; } catch {}
  if (!copied) {
    const previous = document.activeElement;
    const field = node('textarea', { value: text, readOnly: true });
    field.style.cssText = 'position:fixed;top:0;left:0;opacity:0;width:1px;height:1px';
    document.body.append(field); field.focus(); field.select(); field.setSelectionRange(0, text.length);
    try { copied = document.execCommand('copy'); } catch {}
    field.remove(); previous?.focus({ preventScroll: true });
  }
  panel.querySelector('.ll-copy-manual')?.remove();
  if (copied) note(`คัดลอก ${urls.length} ลิงก์จาก ${shop || 'ยังไม่จัดร้าน'} แล้ว`);
  else {
    const field = node('textarea', { className: 'll-copy-manual', value: text, readOnly: true, rows: 5, ariaLabel: 'ลิงก์ทั้งหมดสำหรับคัดลอก' });
    panel.querySelector('.ll-note').after(field); field.focus(); field.select();
    note('อุปกรณ์ไม่อนุญาตให้คัดลอกอัตโนมัติ กดค้างในช่องลิงก์แล้วเลือกคัดลอก', true);
  }
}
function fillShops() {
  const select = panel.querySelector('#llShop'), previous = select.value;
  select.replaceChildren(node('option', { value: '', textContent: 'เลือกร้านค้า' }),
    ...data.shops.map(s => node('option', { value: s, textContent: s })));
  select.value = previous;
}
async function refresh(force = false) {
  if (loading) { await loading; if (force) return refresh(true); return; }
  if (!force && Date.now() - lastLoad < 5000) return;
  loading = (async () => { try {
    data = await api(endpoint); lastLoad = Date.now(); fillShops(); paint();
    const row = data.items.find(i => i.url === selected);
    const signature = row ? JSON.stringify([row.item_id, row.stage, row.name, row.shop]) : '';
    if (row && signature !== selectedSignature) await showDetail(row);
  } catch (e) { note(`โหลดคลังไม่สำเร็จ: ${e.message}`, true); }
  })();
  try { await loading; } finally { loading = null; }
}
function paint() {
  const q = panel.querySelector('#llSearch').value.toLocaleLowerCase().trim();
  const groups = new Map(data.shops.map(s => [s, []]));
  for (const row of data.items) {
    if (q && !`${row.shop} ${row.name} ${row.url}`.toLocaleLowerCase().includes(q)) continue;
    if (!groups.has(row.shop)) groups.set(row.shop, []);
    groups.get(row.shop).push(row);
  }
  const list = panel.querySelector('.ll-list');
  list.replaceChildren();
  let count = 0;
  for (const [shop, rows] of groups) {
    if (q && !rows.length) continue;
    count += rows.length;
    const details = node('details', { className: 'll-group', open: expanded.has(shop) || !!q });
    const copy = node('button', { type: 'button', className: 'll-copy-group',
      textContent: 'คัดลอกลิงก์ทั้งหมด', ariaLabel: `คัดลอกลิงก์ทั้งหมดใน ${shop || 'ยังไม่จัดร้าน'}`,
      disabled: !data.items.some(row => row.shop === shop && row.url) });
    copy.addEventListener('click', async event => {
      event.preventDefault(); event.stopPropagation(); copy.disabled = true;
      try { await copyShopLinks(shop); } finally { copy.disabled = false; }
    });
    const pullAll = node('button', { type: 'button', className: 'll-pull-group',
      textContent: pullingShops.has(shop) ? 'กำลังเข้าคิว…' : 'ดึงลิงก์ทั้งร้าน',
      ariaLabel: `ดึงลิงก์ทั้งร้าน ${shop || 'ยังไม่จัดร้าน'}`,
      disabled: pullingShops.has(shop) || !data.items.some(row => row.shop === shop && row.url) });
    pullAll.addEventListener('click', async event => {
      event.preventDefault(); event.stopPropagation();
      if (pullingShops.has(shop)) return;
      const urls = [...new Set(data.items.filter(row => row.shop === shop).map(row => row.url).filter(Boolean))];
      if (!urls.length) return;
      pullingShops.add(shop); pullAll.disabled = true; pullAll.textContent = 'กำลังเข้าคิว…';
      note(`กำลังส่งลิงก์ของ ${shop || 'ยังไม่จัดร้าน'} เข้าคิว…`);
      try {
        const result = await api(`${CLIP_API}/api/jobs`, { method: 'POST',
          body: JSON.stringify({ links: urls.join('\n'), ...(shop ? { shop } : {}) }) });
        const unsupported = Math.max(0, urls.length - result.count - (result.skipped || 0));
        note(`ส่งเข้าคิว ${result.count} ลิงก์จาก ${shop || 'ยังไม่จัดร้าน'}${result.skipped ? ` · มีใบงานแล้ว ${result.skipped} ลิงก์` : ''}${unsupported ? ` · ไม่เข้าคิว ${unsupported} ลิงก์ (รองรับเฉพาะ Shopee / TikTok)` : ''} · ระบบจะดึงต่อกันตามคิว`);
        await refresh(true); onChange();
      } catch (e) { note(`ส่งเข้าคิวไม่สำเร็จ: ${e.message}`, true); }
      finally { pullingShops.delete(shop); paint(); }
    });
    details.append(node('summary', {}, node('span', { className: 'll-group-title' },
      node('strong', { textContent: shop || 'ยังไม่จัดร้าน' }),
      node('span', { className: 'll-count', textContent: `${rows.length} ลิงก์` })), copy, pullAll));
    details.addEventListener('toggle', () => { if (details.open) expanded.add(shop); else expanded.delete(shop); });
    for (const row of rows) {
      const status = !row.job_id && !row.item_id ? 'บันทึกไว้ · ยังไม่ดึง' : row.error ? 'ต้องตรวจสอบ' : row.stage_label || (row.item_id ? 'มีข้อมูลสินค้า' : 'รอดึง');
      const button = node('button', { type: 'button', className: `ll-row${selected === row.url ? ' is-selected' : ''}` },
        node('span', { className: 'll-row-copy' }, node('b', { textContent: row.name || row.url }),
          node('small', { textContent: row.url })),
        node('span', { className: 'll-status', textContent: status }));
      button.addEventListener('click', () => { selected = row.url; paint(); showDetail(row); });
      details.append(button);
    }
    if (!rows.length) details.append(node('p', { className: 'note', textContent: 'ยังไม่มีลิงก์ในร้านนี้' }));
    list.append(details);
  }
  if (!count) list.append(node('p', { className: 'note', textContent: q ? 'ไม่พบรายการที่ค้นหา' : 'เลือกร้านแล้ววางลิงก์เพื่อเริ่มดึงข้อมูล' }));
}
async function showDetail(row) {
  const sequence = ++detailSequence;
  selectedSignature = JSON.stringify([row.item_id, row.stage, row.name, row.shop]);
  const box = panel.querySelector('.ll-preview');
  box.replaceChildren(node('h3', { textContent: row.name || 'รายละเอียดลิงก์' }),
    node('p', { className: 'note', textContent: row.shop || 'ยังไม่จัดร้าน' }));
  const assign = node('select', { ariaLabel: 'ย้ายลิงก์ไปร้าน' },
    node('option', { value: '', textContent: 'ยังไม่จัดร้าน' }),
    ...data.shops.map(s => node('option', { value: s, textContent: s })));
  assign.value = row.shop;
  assign.addEventListener('change', async () => {
    assign.disabled = true;
    try { await api(`${endpoint}/assign`, { method: 'POST', body: JSON.stringify({ url: row.url, shop: assign.value }) }); await refresh(true); }
    catch (e) { assign.value = row.shop; note(e.message, true); }
    finally { assign.disabled = false; }
  });
  box.append(node('label', {}, 'จัดร้าน ', assign));
  const savedOnly = !row.job_id && !row.item_id;
  const media = node('div', { className: 'll-media', textContent: row.item_id ? 'กำลังโหลดรูป…' : savedOnly ? 'บันทึกลิงก์แล้ว ยังไม่ได้ดึงข้อมูลหรือรูป' : 'รอดึงข้อมูลและรูปจากลิงก์' });
  box.append(media);
  if (savedOnly) {
    const pull = node('button', { type: 'button', textContent: '🔗 ดึงข้อมูลลิงก์นี้' });
    pull.addEventListener('click', async () => {
      pull.disabled = true;
      try {
        await api(`${CLIP_API}/api/jobs`, { method: 'POST', body: JSON.stringify({ links: row.url, ...(row.shop ? { shop: row.shop } : {}) }) });
        note('ส่งลิงก์เข้าคิวดึงข้อมูลแล้ว'); await refresh(true); onChange();
      } catch (e) { note(e.message, true); }
      finally { pull.disabled = false; }
    });
    box.append(pull, node('p', { className: 'note', textContent: 'ดึงข้อมูลรองรับ Shopee และ TikTok' }));
  }
  if (row.error) box.append(node('p', { className: 'll-error', textContent: row.error }));
  const url = safeURL(row.url);
  if (url) box.append(node('a', { href: url, target: '_blank', rel: 'noopener noreferrer', className: 'll-original', textContent: '↗ เปิดลิงก์ต้นฉบับ' }));
  if (!row.item_id) return;
  try {
    const payload = await api(`${endpoint}/images?url=${encodeURIComponent(row.url)}`);
    if (sequence !== detailSequence) return;
    media.replaceChildren();
    if (!payload.images.length) { media.textContent = 'ยังไม่มีรูปที่เปิดดูได้'; return; }
    const main = node('img', { className: 'll-main-image', alt: row.name || 'รูปสินค้า' });
    const show = file => { main.hidden = false; main.src = fileURL(payload.item_id, file); };
    const failure = node('p', { className: 'note', hidden: true, textContent: 'ไฟล์รูปนี้เปิดไม่ได้ ลองเลือกรูปอื่น' });
    main.addEventListener('error', () => { main.hidden = true; failure.hidden = false; });
    main.addEventListener('load', () => { failure.hidden = true; });
    show(payload.images[0]);
    const thumbs = node('div', { className: 'll-thumbs' });
    payload.images.forEach((file, index) => {
      const b = node('button', { type: 'button', ariaLabel: `ดูรูป ${index + 1}` },
        node('img', { src: fileURL(payload.item_id, file), alt: `รูป ${index + 1}`, loading: 'lazy' }));
      b.addEventListener('click', () => show(file)); thumbs.append(b);
    });
    media.append(main, failure, thumbs);
  } catch (e) { if (sequence === detailSequence) media.textContent = `โหลดรูปไม่ได้: ${e.message}`; }
}
function create(anchor) {
  panel = node('section', { className: 'll-panel', id: 'linkLibrary', hidden: true });
  panel.innerHTML = `<h3>🔗 ดึง Link · จัดเก็บตามร้าน</h3>
    <form class="ll-form">
      <label for="llShop">ร้านค้า</label><div class="ll-shop-controls"><select id="llShop" required><option value="">เลือกร้านค้า</option></select><button type="button" id="llAddShop">＋ เพิ่มร้าน</button></div>
      <div class="ll-new-shop" hidden><input id="llShopName" maxlength="120" placeholder="ชื่อร้านใหม่" aria-label="ชื่อร้านใหม่"><button type="button" id="llSaveShop">บันทึกร้าน</button></div>
      <label for="llLinks">ลิงก์สินค้า / โพสต์</label><div class="ll-link-controls"><textarea id="llLinks" rows="3" required placeholder="วางลิงก์ได้หลายรายการ เพื่อบันทึกไว้หรือดึงข้อมูล"></textarea><button id="llSaveLinks" type="submit">💾 บันทึกลิงก์</button><button class="primary" id="llSubmit" type="submit">🔗 ดึงลิงก์</button></div>
      <small>บันทึกลิงก์: เก็บไว้ก่อน ยังไม่ดึงข้อมูล · ดึงลิงก์: เข้าคิว Shopee / TikTok ทันที</small>
      <p class="ll-note" role="status" aria-live="polite"></p>
    </form><h4>ลิงก์แยกตามร้าน</h4><div class="ll-columns"><div><input id="llSearch" placeholder="ค้นหาร้านหรือลิงก์" aria-label="ค้นหาร้านหรือลิงก์"><div class="ll-list"></div></div><aside class="ll-preview">เลือกรายการเพื่อดูรูปและรายละเอียด</aside></div>`;
  if (!document.querySelector('link[href="/static/link-library.css"]')) {
    document.head.append(node('link', { rel: 'stylesheet', href: '/static/link-library.css' }));
  }
  anchor.after(panel);
  panel.querySelector('#llSearch').addEventListener('input', paint);
  panel.querySelector('#llAddShop').addEventListener('click', () => {
    const field = panel.querySelector('.ll-new-shop'); field.hidden = !field.hidden;
    if (!field.hidden) panel.querySelector('#llShopName').focus();
  });
  panel.querySelector('#llSaveShop').addEventListener('click', async event => {
    const input = panel.querySelector('#llShopName'), name = input.value.trim();
    if (!name) { note('กรุณาใส่ชื่อร้าน', true); return; }
    event.target.disabled = true;
    try {
      await api(`${endpoint}/shops`, { method: 'POST', body: JSON.stringify({ name }) });
      await refresh(true); panel.querySelector('#llShop').value = name;
      input.value = ''; panel.querySelector('.ll-new-shop').hidden = true; note('เพิ่มร้านแล้ว');
    } catch (e) { note(e.message, true); }
    finally { event.target.disabled = false; }
  });
  panel.querySelector('form').addEventListener('submit', async event => {
    event.preventDefault();
    const shop = panel.querySelector('#llShop').value, input = panel.querySelector('#llLinks');
    const links = input.value.trim(), button = panel.querySelector('#llSubmit');
    const saveButton = panel.querySelector('#llSaveLinks');
    const saveOnly = event.submitter?.id !== 'llSubmit';
    if (!shop || !links) { note('เลือกร้านและวางลิงก์ก่อน', true); return; }
    button.disabled = saveButton.disabled = true;
    note(saveOnly ? 'กำลังบันทึกลิงก์…' : 'กำลังเพิ่มลิงก์เข้าคิวดึงข้อมูล…');
    try {
      const result = await api(saveOnly ? `${endpoint}/save` : `${CLIP_API}/api/jobs`, { method: 'POST', body: JSON.stringify({ links, shop }) });
      input.value = ''; expanded.add(shop);
      note(saveOnly ? `บันทึก ${result.count} ลิงก์${result.skipped ? ` · มีอยู่แล้ว ${result.skipped} ลิงก์` : ''} · ยังไม่ดึงข้อมูล`
        : `เพิ่มเข้าคิว ${result.count} ลิงก์${result.skipped ? ` · ใช้รายการเดิม ${result.skipped} ลิงก์` : ''}${result.load_text ? ` · ${result.load_text}` : ''}`);
      await refresh(true); onChange();
    } catch (e) { note(e.message, true); }
    finally { button.disabled = saveButton.disabled = false; }
  });
}
export function syncLinkLibrary(anchor, visible, changed) {
  if (!panel) create(anchor);
  onChange = changed;
  panel.hidden = !visible;
  if (visible) refresh();
}
