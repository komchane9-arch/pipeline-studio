/* กระดานกลุ่มที่บอทสำรวจมา — ช่วงสมาชิก × ดี/ก้ำกึ่ง/ไม่ดี + ปุ่มตัดสิน
 *
 * เจ้าของสั่งไว้ 1 ก.ย. 2569: "แยกตามเกณฑ์ 100,000 / 50-100 / 10-50 แล้ว
 * แต่ละอันแยก ดี ก้ำกึ่ง ไม่ดี พร้อมลิงก์เฟส อันไหนก้ำกึ่งมีปุ่มให้ผม approve
 * หรือ reject ด้วย"
 *
 * **วาดรายชื่อตอนกดเปิดเท่านั้น** มี 1,588 กลุ่ม ถ้าวาดหมดตั้งแต่แรกจะได้
 * ก้อน DOM เป็นหมื่นชิ้นที่ไม่มีใครดู หน้าจะหน่วงตั้งแต่เปิด
 *
 * กอง "ไม่ดี" (1,173 ใบ = สองในสามของทั้งหมด) ไม่ได้ส่งมากับรอบแรกด้วยซ้ำ
 * ต้องขอเป็นรายกองตอนกด — เจ้าของเปิดผ่าน Tailscale ไม่ใช่ในเครื่อง
 */

import { api } from "./core.js";

const $ = (sel) => document.querySelector(sel);

const LOOK = {
  good: { icon: "🟢", label: "ดี" },
  edge: { icon: "⚖️", label: "ก้ำกึ่ง" },
  bad: { icon: "🔴", label: "ไม่ดี" },
};

let boardCache = null;

function human(count) {
  if (!count) return "ไม่รู้จำนวน";
  if (count >= 1e6) return `${(count / 1e6).toFixed(1)} ล้านคน`;
  if (count >= 1000) return `${Math.round(count / 1000).toLocaleString("th-TH")} พันคน`;
  return `${count.toLocaleString("th-TH")} คน`;
}

/** ป้ายเกณฑ์รายข้อ — ✅ ผ่าน · ❌ ตก · — ยังไม่ได้วัด
 *  เจ้าของสั่งว่า "แยกให้ด้วยอันไหนจากเกณฑ์ไหนบ้าง" จึงต้องเห็นทีละข้อ
 *  ไม่ใช่เห็นแค่ผลรวม — ก้ำกึ่งสองใบอาจก้ำกึ่งคนละเหตุผลกันสิ้นเชิง */
function mark(pass) {
  if (pass === null || pass === undefined) return "—";
  return pass ? "✅" : "❌";
}

function rowOf(g, onDecide) {
  const det = document.createElement("details");
  det.className = `bd-row bd-${g.status}`;

  // summary = ชื่อ + ลิงก์ — กดแล้วค่อยขยาย
  const sum = document.createElement("summary");
  sum.className = "bd-row-summary";
  const name = document.createElement("span");
  name.className = "bd-name";
  name.textContent = g.name;
  sum.append(name);
  if (g.url) {
    const link = document.createElement("a");
    link.className = "bd-open";
    link.href = g.url;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = "เปิด ↗";
    link.addEventListener("click", (e) => e.stopPropagation()); // ไม่ toggle
    sum.append(link);
  }
  det.append(sum);

  // body — แสดงเมื่อ open
  const body = document.createElement("div");
  body.className = "bd-row-body";

  const facts = document.createElement("p");
  facts.className = "bd-facts";
  facts.textContent = `${human(g.members)}${g.keyword ? ` · เจอจากคำค้น "${g.keyword}"` : ""}`;
  body.append(facts);

  const tests = document.createElement("p");
  tests.className = "bd-tests";
  const avg = g.avg === null || g.avg === undefined ? "ยังไม่ได้วัด" : g.avg.toFixed(1);
  const over = g.over === null || g.over === undefined ? "ยังไม่ได้วัด" : `${g.over} ใบ`;
  tests.textContent =
    `${mark(g.pass_members)} สมาชิก≥100k    ` +
    `${mark(g.pass_avg)} ไลก์เฉลี่ย ${avg} (เกณฑ์ 8)    ` +
    `${mark(g.pass_over)} โพสต์ดัง ${over} (เกณฑ์ 5)`;
  body.append(tests);

  if (g.decision) {
    const said = document.createElement("p");
    said.className = "bd-said";
    said.textContent =
      `คุณกด${g.decision === "approve" ? "รับ" : "ตัด"}เอง` +
      `${g.decided_at ? ` เมื่อ ${g.decided_at.slice(5, 16).replace("T", " ")}` : ""}` +
      ` — บอทเดิมว่า "${LOOK[g.auto_status]?.label || "?"}"`;
    body.append(said);
  }

  // ปุ่มขึ้นทั้งกองก้ำกึ่ง และกองที่เราเคยตัดสินเอง (จะได้เปลี่ยนใจได้)
  if (g.auto_status === "edge" || g.decision) {
    const bar = document.createElement("div");
    bar.className = "bd-buttons";
    const add = (text, decision, cls) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `bd-btn ${cls}`;
      button.textContent = text;
      button.addEventListener("click", () => onDecide(g, decision, button));
      bar.append(button);
    };
    if (g.decision !== "approve") add("✅ รับไว้", "approve", "bd-yes");
    if (g.decision !== "reject") add("❌ ตัดทิ้ง", "reject", "bd-no");
    if (g.decision) add("↩ ยกเลิกที่กดไป", "clear", "bd-undo");
    body.append(bar);
  }

  det.append(body);
  return det;
}

async function sendDecision(g, decision, button) {
  const bar = button.parentElement;
  [...bar.children].forEach((b) => (b.disabled = true));
  button.textContent = "กำลังบันทึก…";
  try {
    await api("/api/fb/group-decide", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ gid: g.gid, decision }),
    });
  } catch (error) {
    // บันทึกไม่ได้ต้องบอก **ห้ามทำเหมือนสำเร็จ** ไม่งั้นเจ้าของจะนึกว่ากดแล้ว
    button.textContent = `บันทึกไม่ได้ — ${error.message}`;
    [...bar.children].forEach((b) => (b.disabled = false));
    return;
  }
  boardCache = null;                 // ให้โหลดใหม่ ตัวเลขหัวตารางจะได้ตรง
  await loadBoard();
}

function cellOf(band, status, rows, counts) {
  const wrap = document.createElement("details");
  wrap.className = "bd-cell";
  const head = document.createElement("summary");
  const look = LOOK[status];
  head.textContent = `${look.icon} ${look.label} ${counts[status]} กลุ่ม`;
  wrap.append(head);

  const body = document.createElement("div");
  body.className = "bd-rows";
  wrap.append(body);

  let filled = false;
  wrap.addEventListener("toggle", async () => {
    if (!wrap.open || filled) return;
    filled = true;
    let list = rows;
    if (!list.length && counts[status]) {
      // กองนี้ไม่ได้ส่งมารอบแรก (กองไม่ดี) — ขอเฉพาะกองนี้
      body.textContent = "กำลังโหลด…";
      try {
        const more = await api(
          `/api/fb/group-board?want=${encodeURIComponent(`${band.key}:${status}`)}`);
        list = (more.bands.find((b) => b.key === band.key) || {}).groups?.[status] || [];
      } catch (error) {
        body.textContent = `โหลดไม่ได้ — ${error.message}`;
        filled = false;             // ให้ลองใหม่ได้ ไม่ใช่ค้างว่างตลอดไป
        return;
      }
    }
    body.textContent = "";
    list.forEach((g) => body.append(rowOf(g, sendDecision)));
  });
  return wrap;
}

export async function loadBoard() {
  const wrap = $("#bdList");
  const note = $("#bdNote");
  if (!wrap) return;
  if (note) note.textContent = "กำลังอ่าน…";
  let data;
  try {
    data = boardCache || (await api("/api/fb/group-board"));
    boardCache = data;
  } catch (error) {
    if (note) note.textContent = `อ่านกระดานกลุ่มไม่ได้ — ${error.message}`;
    return;
  }
  if (note) {
    note.textContent =
      `${data.total.toLocaleString("th-TH")} กลุ่มที่บอทสำรวจมา` +
      (data.decided ? ` · คุณตัดสินเองแล้ว ${data.decided} ใบ` : "") +
      ` · อ่านเมื่อ ${(data.checked_at || "").slice(11, 16)}`;
  }
  const rule = $("#bdRule");
  if (rule && data.rule) rule.textContent = data.rule.text;

  wrap.textContent = "";
  data.bands.forEach((band) => {
    const box = document.createElement("details");
    box.className = "bd-band";
    const head = document.createElement("summary");
    const c = band.counts;
    let extra = "";
    if (band.key === "big") {
      extra = ` <a href="/static/groups-affiliate.html" target="_blank" class="bd-analysis-btn" onclick="event.stopPropagation();">📊 บทวิเคราะห์</a>`;
    }
    head.innerHTML =
      `<b>${band.label}</b> — 🟢 ${c.good} · ⚖️ ${c.edge} · 🔴 ${c.bad}${extra}`;
    box.append(head);
    ["good", "edge", "bad"].forEach((s) => {
      if (c[s]) box.append(cellOf(band, s, band.groups[s] || [], c));
    });
    wrap.append(box);
  });
}
