/* สมุดโน้ตในหน้า Studio — ปุ่ม 📝 บนแถบบนสุด กดแล้วเด้งหน้าต่างขึ้นมา
 *
 * เจ้าของสั่ง 21 ก.ย. 2569 — "เขียนเพิ่มตรงหน้านี้ให้หน่อยว่าเป็น note
 * พอคลิ้กแล้วให้โชว์เป็น pop-up ในหน้าเว็ป"
 *
 * หน้าตาทั้งหมดอยู่ใน notes-ui.js เพราะใช้ร่วมกับหน้าเดี่ยวบนมือถือ (/notes)
 * ไฟล์นี้ทำแค่ 3 อย่าง: ปุ่มบนแถบบนสุด · กล่องหน้าต่างเด้ง · ปุ่มเปิดบนมือถือ
 *
 * **ปุ่มกับหน้าต่างสร้างจากที่นี่ ไม่ได้เขียนไว้ใน index.html โดยตั้งใจ** —
 * ตอนนี้มีหลายแชทแก้ index.html พร้อมกัน ยิ่งแตะน้อยยิ่งชนกันน้อย
 */
import { api } from "./core.js";
import { ensureNotesCss, mountNotes } from "./notes-ui.js";

ensureNotesCss();

const dialog = document.createElement("dialog");
dialog.id = "notesDialog";
dialog.className = "notes-dialog";
document.body.append(dialog);

const ui = mountNotes(dialog, api, { onClose: () => dialog.close() });

// ปุ่มเปิด — เสียบไว้ในแถบบนสุด ข้างปุ่มสลับธีม
// (เคยลองย้ายไปลอยมุมขวาล่าง 21 ก.ย. 2569 แต่เจ้าของขอให้กลับมาที่เดิม)
const opener = document.createElement("button");
opener.id = "openNotes";
opener.type = "button";
opener.className = "gear-button";
opener.title = "โน้ต — ที่แปะข้อความและลิงก์ Shopee / Lazada";
opener.setAttribute("aria-label", "โน้ต");
opener.textContent = "📝";
document.querySelector(".topbar")?.insertBefore(
  opener, document.querySelector("#themeToggle"));

/* ---------------------------------------------------- เปิดบนมือถือ
 *
 * เจ้าของสั่ง 21 ก.ย. 2569 — "ถ้าวางข้อมูลบนเว็ปให้สามารถเปิดดูในมือถือได้ด้วย
 * สร้างไอคอนไว้ในหน้าที่ผมเปิดอยู่"
 *
 * **ใช้ QR ไม่ให้พิมพ์ที่อยู่เอง** ที่อยู่จริงคือ
 * https://laptop-ipb0ansq.tailcb70ec.ts.net/notes ซึ่งพิมพ์บนมือถือแล้วผิดง่าย
 * เครื่องที่จะเปิดได้ต้องอยู่ใน Tailscale วงเดียวกัน (มือถือของเจ้าของอยู่แล้ว)
 */
const phone = document.createElement("button");
phone.type = "button";
phone.className = "ghost notes-phone";
phone.textContent = "📲 เปิดบนมือถือ";
ui.sideTop?.append(phone);

const sheet = document.createElement("div");
sheet.className = "notes-phone-sheet";
sheet.hidden = true;
ui.side?.append(sheet);

let phoneUrl = "";

async function showPhoneCard() {
  sheet.hidden = false;
  sheet.replaceChildren();
  const wait = document.createElement("p");
  wait.className = "note";
  wait.textContent = "กำลังหาที่อยู่สำหรับมือถือ…";
  sheet.append(wait);

  try {
    if (!phoneUrl) {
      // ที่อยู่ Tailscale อยู่ที่ /api/access/status ไม่ใช่ /api/system
      // (เคยถามผิดที่แล้วขึ้นว่า "ยังไม่ได้ต่อ Tailscale" ทั้งที่ต่ออยู่ —
      //  ข้อความที่บอกสาเหตุผิดแบบนั้นพาไปแก้ผิดจุด กติกาข้อ 2.3.1)
      const info = await api("/api/access/status");
      const base = String(info.tailscale_url || "").replace(/\/+$/, "");
      if (!base) {
        // ถอยไปใช้ที่อยู่ของหน้านี้เอง ดีกว่าไม่ให้อะไรเลย
        // แต่ต้องบอกด้วยว่าถ้าไม่ใช่ https จะติดตั้งเป็นแอปไม่ได้
        phoneUrl = `${window.location.origin}/notes`;
      } else {
        phoneUrl = `${base}/notes`;
      }
    }
  } catch (error) {
    wait.textContent = `หาที่อยู่ไม่สำเร็จ: ${error.message}`;
    wait.classList.add("is-bad");
    return;
  }

  sheet.replaceChildren();

  const how = document.createElement("p");
  how.className = "note";
  how.textContent = "สแกนด้วยกล้องมือถือ → เปิดใน Chrome → เมนู ⋮ → "
    + "\"เพิ่มลงในหน้าจอหลัก\" จะได้ไอคอนโน้ตบนมือถือ ใช้กองเดียวกับที่นี่";

  const img = document.createElement("img");
  img.className = "notes-qr";
  img.alt = `QR ของ ${phoneUrl}`;
  img.src = `/api/qr.png?text=${encodeURIComponent(phoneUrl)}`;

  const link = document.createElement("a");
  link.className = "notes-phone-url";
  link.href = phoneUrl;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.textContent = phoneUrl;

  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "ghost";
  copy.textContent = "คัดลอกที่อยู่";
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(phoneUrl);
      copy.textContent = "✅ คัดลอกแล้ว";
    } catch {
      copy.textContent = "คัดลอกไม่ได้ — เลือกเอง";
    }
    window.setTimeout(() => { copy.textContent = "คัดลอกที่อยู่"; }, 2000);
  });

  sheet.append(how, img, link, copy);

  if (!phoneUrl.startsWith("https://")) {
    const warn = document.createElement("p");
    warn.className = "note is-bad";
    warn.textContent = "ที่อยู่นี้ไม่ใช่ https — เปิดดูได้ แต่ติดตั้งเป็นแอป"
      + "บนจอโฮมไม่ได้ ต้องเปิดผ่าน Tailscale";
    sheet.append(warn);
  }
}

phone.addEventListener("click", () => {
  if (!sheet.hidden) { sheet.hidden = true; return; }
  showPhoneCard();
});

/* ---------------------------------------------------- เปิด/ปิดหน้าต่าง */

// ปิดหน้าต่างด้วย Esc หรือกดพื้นหลัง — **ต้องบันทึกให้จบก่อนเสมอ**
dialog.addEventListener("close", () => { ui.flush(); });
dialog.addEventListener("click", (event) => {
  if (event.target === dialog) dialog.close();
});

opener.addEventListener("click", async () => {
  dialog.showModal();
  try {
    await ui.load();
    if (!ui.count) {
      ui.tellState("ยังไม่มีโน้ต กด ＋ เพื่อเริ่มใบแรก");
    } else {
      await ui.openFirst();
      ui.showList();   // จอกว้างเปิดมาเห็นทั้งสองฝั่ง
    }
  } catch (error) {
    ui.tellState(`โหลดโน้ตไม่ได้: ${error.message}`, true);
  }
});

export { ui as notesUI };
