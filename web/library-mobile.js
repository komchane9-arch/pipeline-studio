import { api } from './library-api.js';
import { syncLinkLibrary } from './link-library.js';
const anchor = document.querySelector('#libraryAnchor');
let busy = false;
function receiveShare() {
  const params = new URLSearchParams(location.hash.slice(1));
  if (params.get('share')) sessionStorage.setItem('pipelineSharedLink', params.get('share').slice(0, 20000));
  const text = sessionStorage.getItem('pipelineSharedLink');
  const input = document.querySelector('#llLinks');
  if (text && input) {
    input.value = text.slice(0, 20000);
    sessionStorage.removeItem('pipelineSharedLink');
    history.replaceState(null, '', location.pathname);
    input.focus();
  }
}
async function update() {
  if (busy || document.hidden) return;
  busy = true;
  const state = document.querySelector('#connection'), gate = document.querySelector('#gate');
  try {
    const access = await api('/api/access/status');
    if (access.token) localStorage.setItem('pipelineStudioToken', access.token);
    if (access.status !== 'approved') {
      gate.hidden = false;
      document.querySelector('#gateText').textContent = 'อุปกรณ์นี้ยังไม่ได้รับอนุญาต กรุณาตรวจสิทธิ์ก่อนใช้งาน';
      state.textContent = 'รออนุญาตอุปกรณ์';
      const panel = document.querySelector('#linkLibrary'); if (panel) panel.hidden = true;
      return;
    }
    gate.hidden = true;
    state.textContent = 'เชื่อมต่อแล้ว · ข้อมูลเดียวกับเว็บ Pipeline Studio';
    syncLinkLibrary(anchor, true, () => {});
    receiveShare();
  } catch {
    state.textContent = 'ออฟไลน์ · ตรวจการเชื่อมต่อกับคอม หรือ Tailscale';
    gate.hidden = false;
    document.querySelector('#gateText').textContent = 'ติดต่อเว็บไม่ได้ ข้อความที่กำลังกรอกยังอยู่ กดลองใหม่เมื่อเชื่อมต่อแล้ว';
  } finally { busy = false; }
}
document.querySelector('#retry').addEventListener('click', update);
window.addEventListener('hashchange', receiveShare);
window.addEventListener('online', update);
document.addEventListener('visibilitychange', update);
setInterval(update, 6000);
receiveShare();
update();
