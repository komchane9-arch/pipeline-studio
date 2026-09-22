/* โพสต์ลง "เพจ" Facebook — อยู่ในหมวด Group Facebook (เจ้าของสั่ง 22 ก.ย. 2569)
 *
 * งานจริงอยู่ฝั่งเซิร์ฟเวอร์ (facebook_page_post.py) ไฟล์นี้แค่รับค่าแล้วส่งไป
 * กับคอยถามสถานะมาแสดง — **ห้ามตัดสินใจอะไรเองในนี้** เพราะหน้าเว็บมองไม่เห็น
 * หน้าจอมือถือ ถ้าเดาแทนจะได้ป้ายสถานะที่ไม่ตรงกับความจริง (กติกาข้อ 2.3.1)
 *
 * แยกเป็นไฟล์ของตัวเองเพราะ post.js เป็นของสายโพสต์และยาว 1,200 บรรทัดแล้ว
 */
import { api } from "./core.js";

const $ = (id) => document.getElementById(id);
const POLL_MS = 3000;
let timer = 0;

function note(message, bad = false) {
  const box = $("pgNote");
  if (!box) return;
  box.textContent = message;
  box.classList.toggle("bad", Boolean(bad));
}

// ---------------------------------------------------------- ช่องคอมเมนต์
//
// เจ้าของขอให้ "คอมเมนต์ได้มากกว่า 1" จึงทำเป็นรายการที่เพิ่ม/ลบได้เอง
// ไม่ใช่ช่องตายตัวสองช่องแบบของกลุ่ม
function addComment(value = "") {
  const list = $("pgComments");
  if (!list) return;
  const row = document.createElement("div");
  row.className = "inline-row";
  const box = document.createElement("textarea");
  box.rows = 2;
  box.placeholder = `คอมเมนต์ที่ ${list.children.length + 1}`;
  box.value = value;
  const drop = document.createElement("button");
  drop.type = "button";
  drop.className = "ghost";
  drop.textContent = "✕";
  drop.title = "เอาคอมเมนต์ช่องนี้ออก";
  drop.addEventListener("click", () => { row.remove(); renumber(); });
  row.append(box, drop);
  list.append(row);
}

function renumber() {
  [...($("pgComments")?.children || [])].forEach((row, index) => {
    const box = row.querySelector("textarea");
    if (box) box.placeholder = `คอมเมนต์ที่ ${index + 1}`;
  });
}

function comments() {
  return [...($("pgComments")?.querySelectorAll("textarea") || [])]
    .map((box) => box.value.trim()).filter(Boolean);
}

// ------------------------------------------------------------- โหลดรายการ
export async function loadPages() {
  const picker = $("pgPage");
  const devices = $("pgDevice");
  if (!picker || !devices) return;
  try {
    const data = await api("/api/fb/pages");
    picker.innerHTML = "";
    for (const page of data.pages || []) {
      const option = document.createElement("option");
      option.value = page.name;
      option.textContent = page.name;
      picker.append(option);
    }
    devices.innerHTML = "";
    for (const device of data.devices || []) {
      const option = document.createElement("option");
      option.value = device.serial;
      option.textContent = device.account
        ? `${device.label} — ${device.account}`
        : `${device.label} — ยังไม่ได้ผูกบัญชี`;
      devices.append(option);
    }
    if (!(data.pages || []).length) {
      note("ยังไม่มีเพจในรายการ — เพิ่มชื่อกับรหัสเพจในไฟล์ data/fb_pages.json ก่อน", true);
    } else if (!(data.devices || []).length) {
      note("ยังไม่มีมือถือที่เปิดใช้อยู่ — เสียบเครื่องแล้วเปิดใช้ในหน้าตั้งค่ามือถือก่อน", true);
    } else {
      note("");
    }
    if (data.busy) watch();
  } catch (error) {
    note(`โหลดรายการเพจไม่ได้ — ${error.message}`, true);
  }
}

// ------------------------------------------------------------------ สั่งงาน
async function send() {
  const caption = $("pgCaption")?.value.trim() || "";
  if (!caption) { note("ต้องใส่แคปชันก่อน", true); return; }
  const page = $("pgPage")?.value || "";
  if (!page) { note("ยังไม่ได้เลือกเพจ", true); return; }

  const form = new FormData();
  form.append("serial", $("pgDevice")?.value || "");
  form.append("page", page);
  form.append("caption", caption);
  form.append("comments", JSON.stringify(comments()));
  for (const file of $("pgImages")?.files || []) form.append("post_images", file);

  $("pgSend").disabled = true;
  try {
    const got = await api("/api/fb/page-post", { method: "POST", body: form });
    note(got.message || "เริ่มโพสต์แล้ว");
    watch();
  } catch (error) {
    note(error.message, true);
    $("pgSend").disabled = false;
  }
}

// ------------------------------------------------------------- ตามดูสถานะ
//
// ถามซ้ำทุก 3 วินาทีเฉพาะตอนมีงานเดินอยู่ — งานจบแล้วหยุดถาม ไม่ยิงทิ้งไว้ทั้งวัน
function watch() {
  clearInterval(timer);
  timer = setInterval(poll, POLL_MS);
  poll();
}

async function poll() {
  try {
    const state = await api("/api/fb/page-post/status");
    const head = $("pgStatus");
    if (head) head.textContent = state.headline || "";
    const log = $("pgLog");
    if (log) {
      log.textContent = (state.lines || []).join("\n");
      log.scrollTop = log.scrollHeight;
    }
    $("pgSend").disabled = Boolean(state.running);
    if (!state.running) clearInterval(timer);
  } catch (error) {
    clearInterval(timer);
    note(`ถามสถานะไม่ได้ — ${error.message}`, true);
  }
}

// ---------------------------------------------------------------- ต่อสายปุ่ม
$("pgSend")?.addEventListener("click", send);
$("pgAddComment")?.addEventListener("click", () => addComment());
$("pgReload")?.addEventListener("click", loadPages);
addComment();
