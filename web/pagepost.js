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

// ------------------------------------------- สั่งจากสรุปผล (ปุ่มในหน้า artifact)
//
// เจ้าของสั่ง 22 ก.ย. 2569 — *"เพิ่มให้มีปุ่ม post facebook … โดยปุ่มโพสต์ facebook
// จะไปทำการโพสต์ตาม step ที่โพสต์สำเร็จเมื่อกี้"*
//
// **หน้าสรุปผลสั่งโพสต์ตรงๆ ไม่ได้ และไม่ควรได้** มันอยู่คนละที่กับเซิร์ฟเวอร์นี้
// ถ้าเปิดให้ยิงคำสั่งข้ามที่มาได้ ใครก็สั่งโพสต์ลงเพจของเราได้โดยเราไม่เห็น
// ปุ่มตรงนั้นจึงแค่ **เปิดหน้านี้พร้อมรหัสใบงาน** แล้วมากดยืนยันที่นี่
// จะได้เห็นชัดว่ากำลังจะลงอะไร ก่อนแตะมือถือจริง
function jobFromHash() {
  const m = /page-post=([A-Za-z0-9_-]+)/.exec(location.hash || "");
  return m ? m[1] : "";
}

function line(label, value) {
  return `<div class="row"><b>${label}</b><span>${value}</span></div>`;
}

async function showJob(id) {
  const box = $("pgJob");
  if (!box) return;
  box.innerHTML = `<p class="note">กำลังอ่านใบงาน ${id} …</p>`;
  $("pgBox")?.setAttribute("open", "open");
  document.querySelector('.tab[data-tab="groups"]')?.click();
  $("pgBox")?.scrollIntoView({ behavior: "smooth", block: "center" });
  let plan;
  try {
    plan = await api(`/api/fb/page-post/plan/${encodeURIComponent(id)}`);
  } catch (error) {
    box.innerHTML = `<p class="note bad">อ่านใบงานไม่ได้ — ${error.message}</p>`;
    return;
  }
  if (!plan.found) {
    box.innerHTML = `<p class="note bad">${plan.blocked || "ไม่พบใบงานนี้"}</p>`;
    return;
  }

  // **เติมของจริงลงช่องให้เห็นกับตา ไม่ใช่โชว์ตัวอย่างอ่านอย่างเดียว**
  //
  // เจ้าของทักเอง 22 ก.ย. 2569: "คอมเมนต์ไม่โชว์ รูปก็ไม่โชว์" — ของเดิมโชว์
  // แค่กล่องตัวอย่างข้างล่าง ส่วนช่องแคปชันกับช่องคอมเมนต์ยังว่างเปล่า
  // ซึ่งอ่านแล้วเหมือนระบบไม่มีข้อมูล ทั้งที่มีครบ
  // เติมลงช่องแล้วยัง **แก้ได้ก่อนกด** ด้วย และสิ่งที่เห็นบนจอคือสิ่งที่จะลงจริง
  if ($("pgCaption")) $("pgCaption").value = plan.full_caption || "";
  const list = $("pgComments");
  if (list) {
    list.innerHTML = "";
    (plan.comments || []).forEach((text) => addComment(text));
    if (!(plan.comments || []).length) addComment();
  }

  const head = `<h4>ใบงาน ${id}${plan.account ? " · " + plan.account : ""}</h4>`;
  const thumbs = (plan.images || []).map((_, i) =>
    `<img src="/api/fb/jobs/${encodeURIComponent(id)}/media/post/${i}" ` +
    `alt="รูปของใบงาน ${id}" ` +
    `style="max-width:150px;max-height:150px;border-radius:8px;` +
    `border:1px solid var(--line);object-fit:cover" />`).join(" ");

  let photoNote;
  if (plan.images.length) {
    photoNote = `<p class="note">ใช้รูปของใบงานนี้ ${plan.images.length} ใบ ` +
      `— ไม่ต้องเลือกไฟล์เอง (ถ้าเลือกไฟล์ในช่องด้านบน จะใช้ไฟล์ที่เลือกแทน)</p>` +
      `<div class="row">${thumbs}</div>`;
  } else if (plan.images_missing) {
    photoNote = `<p class="note bad">รูปเดิมของใบงานนี้ถูกลบไปแล้ว ` +
      `${plan.images_missing} ใบ (ระบบเก็บรูปไว้ 300 ใบล่าสุด) ` +
      `— <b>ถ้าจะลง ต้องเลือกไฟล์รูปในช่อง “รูป” ด้านบนก่อน</b></p>`;
  } else {
    photoNote = `<p class="note">ใบงานนี้ไม่มีรูป</p>`;
  }

  if (plan.posted) {
    box.innerHTML = head + photoNote + `<p class="note">✅ ใบนี้ลงเพจ ` +
      `${plan.posted.page} ไปแล้วเมื่อ ${plan.posted.at} · ` +
      `ไลก์${plan.posted.liked ? "ติด" : "ไม่ติด"} · ` +
      `คอมเมนต์ ${plan.posted.comment_count} ข้อความ<br>` +
      `ถ้าจะลงซ้ำ ต้องลบบันทึกก่อนด้วยคำสั่ง ` +
      `<code>python fb_page_jobs.py clear ${id}</code></p>`;
    return;
  }
  box.innerHTML = head + photoNote +
    `<p class="note">ช่องแคปชันกับช่องคอมเมนต์ด้านบนถูกเติมจากใบงานนี้แล้ว ` +
    `<b>แก้ได้ก่อนกด</b> — ที่เห็นบนจอคือที่จะลงจริง</p>` +
    `<div class="row"><button id="pgJobGo" class="primary" type="button">` +
    `🚀 โพสต์ใบงาน ${id} ลงเพจ</button></div>`;
  $("pgJobGo")?.addEventListener("click", () => runJob(id));
}

async function runJob(id) {
  const button = $("pgJobGo");
  if (button) button.disabled = true;
  const form = new FormData();
  form.append("serial", $("pgDevice")?.value || "");
  form.append("page", $("pgPage")?.value || "");
  // ส่งของที่อยู่บนจอไป ไม่ใช่ให้เซิร์ฟเวอร์ไปอ่านใบงานเอง
  // ไม่งั้นแก้แคปชันแล้วโพสต์ออกมาเป็นของเดิมโดยไม่มีอะไรบอก
  form.append("caption", $("pgCaption")?.value || "");
  form.append("comments", JSON.stringify(comments()));
  for (const file of $("pgImages")?.files || []) form.append("post_images", file);
  try {
    const got = await api(`/api/fb/page-post/job/${encodeURIComponent(id)}`,
                          { method: "POST", body: form });
    note(got.message || "เริ่มโพสต์แล้ว");
    watch();
  } catch (error) {
    note(error.message, true);
    if (button) button.disabled = false;
  }
}

window.addEventListener("hashchange", () => {
  const id = jobFromHash();
  if (id) showJob(id);
});
if (jobFromHash()) setTimeout(() => showJob(jobFromHash()), 400);
