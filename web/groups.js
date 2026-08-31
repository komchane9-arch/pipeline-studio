/* แท็บ Group Facebook — กลุ่มไหนยังมีชีวิต กลุ่มไหนตายแล้ว
 *
 * เจ้าของสั่งไว้ 31 ส.ค. 2569: "เอากลุ่มที่ให้เสิชหาว่ากลุ่มไหนมี engagement
 * ดีไม่ดี ตายแล้วหรือยัง มาใส่บนเว็บ ... ในนั้นให้ทำเป็น block แยก status
 * ต่างๆของแต่ละกลุ่ม"
 *
 * ข้อมูลมาจาก /api/fb/group-health (ดู fb_group_health.py ว่าคิดยังไง)
 *
 * **หัวใจของหน้านี้คือแยก "กลุ่มตาย" ออกจาก "โพสต์เราไม่ติด"** สองอย่างนี้
 * แก้คนละทางกันสิ้นเชิง — กลุ่มตายให้เลิกโพสต์ ส่วนของเราไม่ติดต้องแก้เนื้อหา
 * ถ้าโชว์รวมเป็นตัวเลขเดียว คนอ่านจะแยกไม่ออกว่าควรทำอะไรต่อ
 */

import { api } from "./core.js";

const $ = (sel) => document.querySelector(sel);

// สี + คำอธิบายของแต่ละสถานะ — คำอธิบายบอก **สิ่งที่ควรทำ** ไม่ใช่แค่บอกสถานะ
// เพราะเจ้าของเปิดหน้านี้เพื่อตัดสินใจ ไม่ได้เปิดมาดูเฉยๆ
const LOOKS = {
  good: { chip: "gh-good", icon: "🟢", act: "โพสต์ต่อได้เลย" },
  mismatch: { chip: "gh-warn", icon: "🟡", act: "กลุ่มไม่ผิด — ลองเปลี่ยนแนวเนื้อหา" },
  slow: { chip: "gh-slow", icon: "🟠", act: "ได้ผลน้อย เก็บไว้ท้ายๆ คิว" },
  dead: { chip: "gh-dead", icon: "🔴", act: "เลิกโพสต์ ไปหากลุ่มใหม่ดีกว่า" },
  unknown: { chip: "gh-none", icon: "⚪", act: "ให้บอทไปเก็บโพสต์กลุ่มนี้ก่อน" },
};

function num(value) {
  return value === null || value === undefined ? "—" : String(value);
}

/** ยอดสมาชิกอ่านง่าย — 1200000 กลายเป็น "1.2 ล้าน" */
function members(count) {
  if (!count) return "";
  if (count >= 1e6) return `${(count / 1e6).toFixed(1)} ล้านคน`;
  if (count >= 1000) return `${Math.round(count / 1000)} พันคน`;
  return `${count} คน`;
}

function blockOf(row) {
  const look = LOOKS[row.status] || LOOKS.unknown;
  const g = row.group_side || {};
  const o = row.our_side || {};
  const box = document.createElement("article");
  box.className = `gh-card ${look.chip}`;

  const head = document.createElement("header");
  head.className = "gh-head";
  const chip = document.createElement("span");
  chip.className = "gh-chip";
  chip.textContent = `${look.icon} ${row.status_label}`;
  const title = document.createElement("h3");
  title.className = "gh-name";
  title.textContent = row.name;
  head.append(chip, title);
  if (!row.enabled) {
    const off = document.createElement("span");
    off.className = "gh-off";
    off.textContent = "ปิดใช้อยู่";
    head.append(off);
  }

  const why = document.createElement("p");
  why.className = "gh-why";
  why.textContent = row.why;

  const act = document.createElement("p");
  act.className = "gh-act";
  act.textContent = `→ ${look.act}`;

  // สองคอลัมน์ **ห้ามรวมกัน** — ดูแยกกันถึงจะรู้ว่าปัญหาอยู่ฝั่งไหน
  const grid = document.createElement("div");
  grid.className = "gh-grid";

  const left = document.createElement("div");
  left.className = "gh-col";
  left.innerHTML = "<h4>คนอื่นในกลุ่ม</h4>";
  if (g.known) {
    const size = members(g.members);
    left.insertAdjacentHTML(
      "beforeend",
      `<p>ไลก์เฉลี่ย <b>${num(g.avg_reactions)}</b> ต่อโพสต์</p>` +
        `<p>โพสต์ดังเกิน 100 ไลก์ <b>${num(g.hot_posts)}</b> ใบ</p>` +
        `<p>7 วันล่าสุดมีโพสต์ใหม่ <b>${num(g.fresh_posts)}</b> ใบ</p>` +
        `<p class="gh-sub">เก็บมาแล้ว ${Number(g.posts).toLocaleString("th-TH")} โพสต์` +
        (size ? ` · สมาชิก ${size}` : "") +
        `</p>`,
    );
  } else {
    left.insertAdjacentHTML("beforeend", `<p class="gh-sub">ยังไม่มีข้อมูล — บอทยังไม่เคยไปเก็บ</p>`);
  }

  const right = document.createElement("div");
  right.className = "gh-col";
  right.innerHTML = "<h4>โพสต์ของเรา</h4>";
  if (o.known) {
    right.insertAdjacentHTML(
      "beforeend",
      `<p>ไลก์เฉลี่ย <b>${num(o.avg_reactions)}</b> ต่อโพสต์</p>` +
        `<p>คอมเมนต์เฉลี่ย <b>${num(o.avg_comments)}</b> อัน</p>` +
        (o.owed ? `<p class="gh-owed">ค้างตอบ ${o.owed} คอมเมนต์</p>` : "") +
        `<p class="gh-sub">ลงไปแล้ว ${num(o.posts)} โพสต์</p>`,
    );
  } else {
    right.insertAdjacentHTML("beforeend", `<p class="gh-sub">ยังไม่มีข้อมูล — ยังไม่เคยโพสต์ หรือยังตามยอดไม่ได้</p>`);
  }
  grid.append(left, right);

  box.append(head, why, act, grid);
  if (row.url) {
    const link = document.createElement("a");
    link.className = "gh-link";
    link.href = row.url;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = "เปิดกลุ่มใน Facebook ↗";
    box.append(link);
  }
  return box;
}

export async function loadGroupHealth() {
  const wrap = $("#ghList");
  const note = $("#ghNote");
  if (!wrap) return;
  wrap.textContent = "";
  if (note) note.textContent = "กำลังอ่าน…";
  let data;
  try {
    data = await api("/api/fb/group-health");
  } catch (error) {
    // **บอกว่าอ่านไม่ได้ ห้ามขึ้นว่า "ไม่มีกลุ่ม"** — สองอย่างนี้ต่างกัน
    // ถ้าขึ้นว่าไม่มีกลุ่ม เจ้าของจะนึกว่าทะเบียนหาย แล้วไปไล่ผิดทาง
    if (note) note.textContent = `อ่านสถานะกลุ่มไม่ได้ — ${error.message}`;
    return;
  }
  const rows = data.groups || [];
  if (!rows.length) {
    if (note) note.textContent = "ยังไม่มีกลุ่มในทะเบียน — เพิ่มกลุ่มที่แท็บ Publish ก่อน";
    return;
  }
  const t = data.tally || {};
  const parts = [];
  if (t.good) parts.push(`🟢 ดี ${t.good}`);
  if (t.mismatch) parts.push(`🟡 ของเราไม่ติด ${t.mismatch}`);
  if (t.slow) parts.push(`🟠 ซบเซา ${t.slow}`);
  if (t.dead) parts.push(`🔴 ตายแล้ว ${t.dead}`);
  if (t.unknown) parts.push(`⚪ ยังไม่รู้ ${t.unknown}`);
  if (note) {
    note.textContent = `${rows.length} กลุ่ม — ${parts.join(" · ")} · อ่านเมื่อ ${
      (data.checked_at || "").slice(11, 16)
    }`;
  }
  rows.forEach((row) => wrap.append(blockOf(row)));
}
