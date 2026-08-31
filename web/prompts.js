/* หน้าโชว์คำสั่งจริงที่ส่งเข้า AI — เปิดจากปุ่ม ⚙ ข้างแท็บสตอรีบอร์ด
 *
 * เจ้าของสั่งไว้ 31 ส.ค. 2569 (สายคลิปส่งสเปคมาให้หลังเจ้าของคอนเฟิร์ม):
 * "ตรงหน้า storyboard เวลากดมาให้มีโชว์ ตรงนี้เป็นปุ่มตั้งค่า ถ้ากดไปให้ลิ้ง
 *  ไปอีกหน้านึง โชว์ 1.prompt ที่ส่งเข้า gemini เพื่อเลือกรูป
 *  2.prompt ที่ส่งเข้า chatgpt เพื่อ gen story board"
 *
 * **ดูอย่างเดียว แก้ไม่ได้** ทั้งหน้าไม่มีปุ่มที่เปลี่ยนข้อมูลเลย
 *
 * ข้อมูลมาจาก GET {CLIP_API}/api/prompts (พอร์ต 8877 — เซิร์ฟเวอร์สายคลิป)
 *
 * ## ทำไมหน้านี้ถึงคุ้มค่าที่จะมี
 *
 * ส่วนที่ติดธง `outside` คือพร้อมประจำตัวของ custom GPT ซึ่ง **อยู่ฝั่ง OpenAI
 * ระบบเราอ่านไม่ได้** วันที่ 31 ส.ค. เจ้าของเอาพร้อมตัวนั้นมาวางเทียบเองแล้ว
 * พบว่า **ขัดกับกติกาที่เราส่งไปทับถึง 3 จุด**
 *
 *     จำนวนจุดเด่น     พร้อมบอก 3 ข้อ  · เราส่งไปทับว่า 4 ข้อ
 *     ตัวหนังสือในคลิป  พร้อมบอก "no text" · เราส่งไปทับว่าให้มีตัวหนังสือ
 *                      → 8 สัปดาห์แรกได้ตัวหนังสือครบทุกฉากแค่ 3% ของคลิป
 *     ชั้นวางของ       พร้อมสั่งให้เน้นชั้นวางมินิมอล ค้างมาจากสินค้าเก่า
 *                      → 13 ใบ (7%) พูดถึงชั้นวางทั้งที่เป็นเก้าอี้/จอคอม
 *
 * **กว่าจะเจอต้องรอให้เจ้าของเอาพร้อมมาวางเทียบด้วยมือ** หน้านี้จึงวางของ
 * สองฝั่งให้เห็นคู่กัน โดยเรียงพร้อมของ custom GPT ไว้ **บนสุด** ก่อนกติกา
 * ที่เราส่งไปทับ จะได้เห็นตั้งแต่แรกว่าอะไรทับอะไร
 */

import { CLIP_API } from "./core.js";

const $ = (sel) => document.querySelector(sel);

function partBox(part) {
  const box = document.createElement("section");
  box.className = "pp-part";
  if (part.outside) box.classList.add("pp-outside");
  if (part.vary) box.classList.add("pp-vary");

  const head = document.createElement("header");
  head.className = "pp-part-head";
  const label = document.createElement("h4");
  label.textContent = part.label || "(ไม่มีหัวข้อ)";
  head.append(label);

  // ธงต้องอ่านแล้วรู้ **ผลกระทบ** ไม่ใช่รู้แค่ชื่อธง
  if (part.outside) {
    const flag = document.createElement("span");
    flag.className = "pp-flag pp-flag-out";
    flag.textContent = "อยู่ฝั่ง OpenAI — เราแก้ไม่ได้";
    head.append(flag);
  }
  if (part.vary) {
    const flag = document.createElement("span");
    flag.className = "pp-flag pp-flag-vary";
    flag.textContent = "เปลี่ยนตามสินค้าแต่ละใบ";
    head.append(flag);
  }

  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "ghost pp-copy";
  copy.textContent = "📋 คัดลอก";
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(part.text || "");
      copy.textContent = "คัดลอกแล้ว ✓";
    } catch {
      // คัดลอกไม่ได้ (เบราว์เซอร์ไม่อนุญาต) — บอกตรงๆ ไม่ใช่ทำเหมือนสำเร็จ
      copy.textContent = "คัดลอกไม่ได้ — เลือกข้อความเอง";
    }
    setTimeout(() => (copy.textContent = "📋 คัดลอก"), 2500);
  });
  head.append(copy);

  const body = document.createElement("pre");
  body.className = "pp-text";
  body.textContent = part.text || "";

  const from = document.createElement("p");
  from.className = "pp-source";
  from.textContent = part.source || "";

  box.append(head, body, from);
  return box;
}

function groupBox(group) {
  const box = document.createElement("article");
  box.className = "pp-group";

  const head = document.createElement("header");
  head.className = "pp-group-head";
  const step = document.createElement("span");
  step.className = "pp-step";
  step.textContent = `ขั้น ${group.step ?? "?"}`;
  const who = document.createElement("span");
  who.className = "pp-who";
  who.textContent = group.service || "";
  const title = document.createElement("h3");
  title.textContent = group.title || "";
  head.append(step, who, title);

  box.append(head);
  if (group.note) {
    const note = document.createElement("p");
    note.className = "pp-note";
    note.textContent = group.note;
    box.append(note);
  }
  // `models` กับ `gpt_url` มีบ้างไม่มีบ้าง — ต้องเช็คก่อนวาด (สเปคระบุไว้)
  if (Array.isArray(group.models) && group.models.length) {
    const models = document.createElement("p");
    models.className = "pp-models";
    models.textContent = `ไล่ลองโมเดล: ${group.models.join(" → ")}`;
    box.append(models);
  }
  if (group.gpt_url) {
    const link = document.createElement("a");
    link.className = "pp-gpt";
    link.href = group.gpt_url;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = "เปิด custom GPT ตัวนี้ ↗";
    box.append(link);
  }
  (group.parts || []).forEach((part) => box.append(partBox(part)));
  return box;
}

export async function loadPrompts() {
  const wrap = $("#ppList");
  const note = $("#ppNote");
  if (!wrap) return;
  wrap.textContent = "";
  if (note) note.textContent = "กำลังอ่าน…";

  let data;
  try {
    const answer = await fetch(`${CLIP_API}/api/prompts`);
    data = await answer.json();
    if (!answer.ok) {
      // เซิร์ฟเวอร์สายคลิปเขียนข้อความให้อ่านรู้เรื่องมาแล้ว แสดงตรงๆ
      throw new Error(data?.detail || `HTTP ${answer.status}`);
    }
  } catch (error) {
    // **แยก "ต่อไม่ได้" ออกจาก "ต่อได้แต่พัง"** สองอย่างนี้แก้คนละทาง
    const dead = error instanceof TypeError;
    if (note) {
      note.textContent = dead
        ? "ต่อสายคลิปไม่ได้ — เปิดเซิร์ฟเวอร์สายคลิปก่อน (พอร์ต 8877)"
        : `อ่านคำสั่งไม่สำเร็จ — ${error.message}`;
    }
    return;
  }

  const groups = data.groups || [];
  if (!groups.length) {
    if (note) note.textContent = "ยังไม่มีคำสั่งให้แสดง — แจ้งสายคลิป";
    return;
  }
  const parts = groups.reduce((sum, g) => sum + (g.parts || []).length, 0);
  if (note) note.textContent = `${groups.length} ก้อน · ${parts} ส่วน — ${data.note || ""}`;
  groups.forEach((group) => wrap.append(groupBox(group)));
}

/** เปิดหน้านี้ — ซ่อนแท็บอื่นทั้งหมด แล้วโหลดข้อมูลถ้ายังไม่เคยโหลด */
export function openPrompts() {
  document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
  document.querySelectorAll(".tab-area").forEach((area) => {
    area.hidden = area.id !== "tab-prompts";
  });
  const wrap = $("#ppList");
  if (wrap && !wrap.childElementCount) loadPrompts();
}
