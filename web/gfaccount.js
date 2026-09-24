/* โปรไฟล์ที่หน้า Group Facebook กำลังดูอยู่ — ใช้ร่วมกันสองส่วน
 *
 * **เจ้าของสั่ง 16 ก.ย. 2569** — *"ตรงหน้านี้ด้านล่าง group facebook ให้ทำแยก
 * profile คนละอันเลย ให้คลิ้กเลือก · ในแต่ละโปรไฟล์จะแยกทั้งบอทสายโพสต์
 * และตอบคอมเมนต์ คนละอันเลย"*
 *
 * เก็บค่าไว้ที่เดียวแล้วให้ทั้งสองส่วนอ่านจากตรงนี้ — ถ้าต่างคนต่างจำ
 * จะหลุดกันเองเมื่อไหร่ก็ได้ แล้วหน้าจะโชว์บอทของโปรไฟล์หนึ่ง
 * คู่กับคอมเมนต์ของอีกโปรไฟล์ ซึ่งอ่านแล้วเข้าใจผิดทันที
 */
import { $, api } from "./core.js";

let current = "";
const listeners = [];
let linkedGroups = [];
let accountList = [];
let selectionSave = Promise.resolve();

/** โปรไฟล์ที่เลือกอยู่ — ว่าง = ยังไม่เลือก/มีโปรไฟล์เดียว */
export function gfAccount() {
  return current;
}

/** ต่อท้ายชื่อโปรไฟล์ให้ที่อยู่ */
export function gfQuery(path) {
  if (!current) return path;
  return path + (path.includes("?") ? "&" : "?")
    + "account=" + encodeURIComponent(current);
}

/** ขอให้เรียกกลับเมื่อผู้ใช้สลับโปรไฟล์ */
export function onGfAccountChange(fn) {
  listeners.push(fn);
}

function renderLinkedGroups() {
  const wrap = $("#gfLinkedGroups");
  const count = $("#gfLinkedCount");
  if (!wrap) return;
  if (count) count.textContent = `${linkedGroups.length.toLocaleString("th-TH")} กลุ่ม`;

  if (!linkedGroups.length) {
    const empty = document.createElement("p");
    empty.className = "gf-linked-empty";
    empty.textContent = current
      ? "บัญชีนี้ยังไม่มีกลุ่มที่ผูกไว้"
      : "เลือกโปรไฟล์ก่อนเพื่อดูรายชื่อกลุ่ม";
    wrap.replaceChildren(empty);
    return;
  }

  wrap.replaceChildren(...linkedGroups.map((group) => {
    const row = document.createElement("article");
    row.className = "gf-linked-group" + (group.enabled === false ? " is-off" : "");

    const open = document.createElement("a");
    open.className = "gf-linked-name";
    open.href = `https://www.facebook.com/groups/${encodeURIComponent(group.group_id)}`;
    open.target = "_blank";
    open.rel = "noreferrer";
    open.textContent = group.name || group.group_id;
    open.title = "เปิดกลุ่มใน Facebook";

    const id = document.createElement("span");
    id.className = "gf-linked-id";
    id.textContent = group.group_id;

    const state = document.createElement("span");
    state.className = "gf-linked-state";
    state.textContent = group.enabled === false ? "ปิดใช้" : "ใช้งานอยู่";

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "ghost danger";
    remove.textContent = "ลบ";
    remove.title = `ลบออกจากบัญชี ${current}`;
    remove.addEventListener("click", async () => {
      const account = current;
      const label = group.name || group.group_id;
      if (!confirm(`ลบ “${label}” ออกจากบัญชี ${current}?\n\nโพสต์เดิมใน Facebook จะไม่ถูกลบ`)) return;
      remove.disabled = true;
      const note = $("#gfLinkedNote");
      try {
        const payload = await api(gfQuery(`/api/fb/groups/${group.group_id}`), {
          method: "DELETE",
        });
        if (account !== current) return;
        linkedGroups = payload.groups || [];
        renderLinkedGroups();
        if (note) note.textContent = `ลบ “${label}” ออกจาก ${current} แล้ว`;
        await refreshAccountHeader();
      } catch (error) {
        if (account !== current) return;
        remove.disabled = false;
        if (note) note.textContent = `ลบไม่ได้ — ${error.message}`;
      }
    });

    row.append(open, id, state, remove);
    return row;
  }));
}

/** โหลดทะเบียนของโปรไฟล์ที่เลือกเท่านั้น — ห้ามถอยไปอ่านรวมทุกบัญชี */
export async function loadGfLinkedGroups() {
  const account = current;
  const note = $("#gfLinkedNote");
  if (!current) {
    linkedGroups = [];
    renderLinkedGroups();
    return;
  }
  if (note) note.textContent = `กำลังโหลดกลุ่มของ ${current}…`;
  try {
    const payload = await api(gfQuery("/api/fb/groups"));
    if (account !== current) return;
    linkedGroups = payload.groups || [];
    renderLinkedGroups();
    if (note) note.textContent = linkedGroups.length
      ? `แสดงเฉพาะกลุ่มของ ${payload.account || current}`
      : `ยังไม่มีกลุ่มในบัญชี ${payload.account || current}`;
  } catch (error) {
    if (account !== current) return;
    linkedGroups = [];
    renderLinkedGroups();
    if (note) note.textContent = `อ่านรายชื่อกลุ่มไม่ได้ — ${error.message}`;
  }
}

async function refreshAccountHeader() {
  // การเพิ่ม/ลบสำเร็จแล้วต้องไม่ถูกรายงานย้อนว่า "ทำไม่ได้" เพียงเพราะ
  // การรีเฟรชตัวเลขบนหัวแท็บล้มชั่วคราว.
  try {
    const data = await api("/api/fb/post-accounts");
    renderAccountTabs(data.accounts || []);
  } catch { /* รายการหลักวาดจากผลเพิ่ม/ลบแล้ว จึงปล่อยให้กดโหลดใหม่ภายหลัง */ }
}

function renderAccountTabs(list) {
  accountList = list;
  const strip = $("#gfAccountTabs");
  const note = $("#gfAccountNote");
  if (!strip) return;
  strip.hidden = list.length < 2;
  if (note) note.hidden = list.length < 2;

  strip.replaceChildren(...list.map((a) => {
    const tab = document.createElement("button");
    tab.type = "button";
    tab.className = "fb-acct-tab" + (a.account === current ? " is-on" : "")
      + (a.ready ? "" : " is-todo");
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-selected", a.account === current ? "true" : "false");
    const dot = document.createElement("span");
    dot.className = "fb-acct-dot";
    dot.textContent = a.ready ? "●" : "○";
    const name = document.createElement("b");
    name.textContent = a.account;
    const where = document.createElement("small");
    where.textContent = `${a.device} · ${a.groups.toLocaleString("th-TH")} กลุ่ม`;
    tab.append(dot, name, where);
    tab.addEventListener("click", () => pick(a.account));
    return tab;
  }));

  if (note && !note.hidden) {
    const picked = list.find((a) => a.account === current);
    note.textContent = picked
      ? `กำลังดูของ ${picked.account} — ${picked.groups} กลุ่ม · มือถือ ${picked.device} · บอท ${picked.bot || "(ยังไม่มี)"}`
      : "";
  }
}

export async function loadGfAccounts() {
  const strip = $("#gfAccountTabs");
  const note = $("#gfAccountNote");
  if (!strip) return;
  let data;
  try {
    data = await api("/api/fb/post-accounts");
  } catch {
    return;
  }
  const list = data.accounts || [];
  if (!current) current = data.current || (list.length ? list[0].account : "");
  renderAccountTabs(list);
  await loadGfLinkedGroups();
}

async function pick(account) {
  if (account === current) return;
  current = account;
  linkedGroups = [];
  renderLinkedGroups();
  renderAccountTabs(accountList);
  // Notify synchronously: old cards must disappear before any network wait.
  for (const fn of listeners) {
    try { Promise.resolve(fn(account)).catch(() => {}); } catch {}
  }
  void loadGfLinkedGroups();
  // Preserve selection order when tabs are switched rapidly.
  selectionSave = selectionSave.catch(() => {}).then(() => api("/api/fb/post-accounts", {
      method: "POST",
      body: JSON.stringify({ account }),
    })).catch(() => {});
}

async function addLinkedGroup() {
  const account = current;
  const url = $("#gfLinkedUrl");
  const name = $("#gfLinkedName");
  const button = $("#gfLinkedAdd");
  const note = $("#gfLinkedNote");
  const link = url?.value.trim() || "";
  if (!current) {
    if (note) note.textContent = "เลือกโปรไฟล์ก่อนเพิ่มกลุ่ม";
    return;
  }
  if (!link) {
    if (note) note.textContent = "วางลิงก์กลุ่ม Facebook ก่อน";
    url?.focus();
    return;
  }
  button.disabled = true;
  try {
    // Route เพิ่มกลุ่มอ่าน account จาก body โดยตรง ไม่พึ่งค่าที่หน้าอื่นเลือกค้างไว้.
    const payload = await api("/api/fb/groups", {
      method: "POST",
      body: JSON.stringify({ account: current, link, name: name?.value || "" }),
    });
    if (account !== current) return;
    linkedGroups = payload.groups || [];
    renderLinkedGroups();
    if (url) url.value = "";
    if (name) name.value = "";
    if (note) note.textContent = payload.group?.duplicated
      ? `กลุ่มนี้มีอยู่แล้วใน ${current} — อัปเดตชื่อให้แล้ว`
      : `เพิ่ม “${payload.group?.name || payload.group?.group_id}” ให้ ${current} แล้ว`;
    await refreshAccountHeader();
  } catch (error) {
    if (account !== current) return;
    if (note) note.textContent = `เพิ่มไม่ได้ — ${error.message}`;
  } finally {
    button.disabled = false;
  }
}

$("#gfLinkedReload")?.addEventListener("click", loadGfLinkedGroups);
$("#gfLinkedAdd")?.addEventListener("click", addLinkedGroup);
$("#gfLinkedUrl")?.addEventListener("keydown", (event) => {
  if (event.key === "Enter") addLinkedGroup();
});
