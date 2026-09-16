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
  // โปรไฟล์เดียวไม่ต้องโชว์แท็บให้รก
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
    where.textContent = a.device;
    tab.append(dot, name, where);
    tab.addEventListener("click", () => pick(a.account));
    return tab;
  }));

  if (note && !note.hidden) {
    const picked = list.find((a) => a.account === current);
    note.textContent = picked
      ? `กำลังดูของ ${picked.account} — มือถือ ${picked.device} · บอท ${picked.bot || "(ยังไม่มี)"}`
      : "";
  }
}

async function pick(account) {
  if (account === current) return;
  current = account;
  try {
    await api("/api/fb/post-accounts", {
      method: "POST",
      body: JSON.stringify({ account }),
    });
  } catch { /* จำไม่ได้ก็ยังใช้ค่าในหน้านี้ต่อได้ */ }
  await loadGfAccounts();
  for (const fn of listeners) {
    try {
      await fn(account);
    } catch { /* ส่วนหนึ่งพังต้องไม่ลามไปหยุดอีกส่วน */ }
  }
}
