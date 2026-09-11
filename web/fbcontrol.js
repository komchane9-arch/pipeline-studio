/* แผงคุมบอทสายโพสต์ — ตอนนี้ทำอะไรอยู่ ขั้นตอนไหน + ปุ่มหยุด/ทำต่อ/ยกเลิก
 *
 * เจ้าของสั่งไว้ 9 ก.ย. 2569: "หน้านี้ให้เขียนเพิ่มว่า บอทสายโพสต์กำลังทำอะไร
 * อยู่ขั้นตอนไหน แล้วมีปุ่มให้หยุด resume หรือ ยกเลิกการทำงานด้วย"
 *
 * ## ไม่ได้ทำที่อยู่ใหม่เลย — ของเดิมมีครบอยู่แล้ว
 *
 *   GET  /api/fb/jobs                  ← running · running_on · ทุกใบงาน
 *        แต่ละใบมี status · latest_step · posted_count · pending_groups
 *        และ **controls** ที่เซิร์ฟเวอร์คิดมาให้แล้วว่าปุ่มไหนกดได้
 *   POST /api/fb/jobs/<id>/stop        หยุดที่จุดปลอดภัย เก็บผลไว้ทำต่อได้
 *   POST /api/fb/jobs/<id>/resume      ทำต่อเฉพาะกลุ่มที่ยังไม่สำเร็จ
 *   POST /api/fb/jobs/<id>/cancel      ยกเลิกทิ้ง
 *
 * **ปุ่มไหนโผล่ ให้เซิร์ฟเวอร์ตัดสิน ไม่ใช่หน้าเว็บเดาเอง** (`controls`)
 * เพราะเงื่อนไขจริงซับซ้อน — ขั้นที่แตะโพสต์ไปแล้วห้ามทำซ้ำเด็ดขาด
 * ถ้าหน้าเว็บเดาเองวันหนึ่งจะโชว์ปุ่มที่กดแล้วโพสต์ซ้ำ ซึ่งถอนไม่ได้
 *
 * ## "หยุด" ไม่ได้แปลว่าหยุดทันที
 *
 * วัดจริง 9 ก.ย.: กด Stop เวลา 12:56:02 → บอทเขียนว่า "รอจบกลุ่มปัจจุบัน"
 * → ปล่อยจอจริงตอน 12:57:05 (**ใช้เวลา 63 วินาที**) เพราะมันตัดกลางกลุ่มไม่ได้
 * หน้าจึงต้องบอกให้ชัดว่า "กำลังหยุด" ต่างจาก "หยุดแล้ว" ไม่งั้นเจ้าของจะกดซ้ำ
 * เพราะนึกว่าปุ่มไม่ทำงาน
 */

import { api } from "./core.js";

const $ = (sel) => document.querySelector(sel);

const STATUS_LOOK = {
  running: { icon: "🟢", label: "กำลังทำงาน" },
  ready: { icon: "🟡", label: "รอเริ่ม" },
  stopped: { icon: "⏸️", label: "หยุดไว้" },
  done: { icon: "✅", label: "เสร็จแล้ว" },
  failed: { icon: "🔴", label: "ล้มเหลว" },
  cancelled: { icon: "⚪", label: "ยกเลิกแล้ว" },
};

let timer = null;

function statusOf(job) {
  return STATUS_LOOK[job.status] || { icon: "•", label: job.status || "ไม่ทราบ" };
}

/** ผ่านมากี่วินาทีแล้วจากเวลาที่อยู่หน้าบรรทัด ("16:39:02 เปิดกลุ่ม…")
 *
 *  คืน null เมื่ออ่านเวลาไม่ออก — **ห้ามเดาเป็น 0** เพราะ 0 แปลว่า
 *  "เพิ่งขยับเมื่อกี้" ซึ่งตรงข้ามกับ "ไม่รู้" (กติกาข้อ 2.3.1 ข้อ 4)
 *
 *  ข้ามเที่ยงคืนได้ — เวลาในบันทึกไม่มีวันที่ ถ้าคำนวณตรงๆ จะติดลบเป็นหมื่น
 *  วินาทีตอนข้ามวัน แล้วขึ้นว่า "ค้างมา -86000 วินาที"
 */
function secondsSinceStamp(text) {
  const found = /(\d{1,2}):(\d{2}):(\d{2})/.exec(String(text || ""));
  if (!found) return null;
  const now = new Date();
  const then = Number(found[1]) * 3600 + Number(found[2]) * 60 + Number(found[3]);
  const clock = now.getHours() * 3600 + now.getMinutes() * 60 + now.getSeconds();
  let gap = clock - then;
  if (gap < -60) gap += 86400;          // บันทึกเมื่อวาน เพิ่งข้ามเที่ยงคืน
  return gap < 0 ? 0 : gap;
}

async function send(jobId, what, button, panel) {
  const siblings = [...button.parentElement.children];
  siblings.forEach((b) => (b.disabled = true));
  const original = button.textContent;
  button.textContent = "กำลังสั่ง…";
  try {
    await api(`/api/fb/jobs/${encodeURIComponent(jobId)}/${what}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
  } catch (error) {
    // สั่งไม่สำเร็จต้องบอก **ห้ามทำเหมือนสำเร็จ** ไม่งั้นเจ้าของจะนึกว่าหยุดแล้ว
    // ทั้งที่บอทยังเดินอยู่ แล้วจะไปเจอตอนโพสต์ขึ้นไปแล้ว
    button.textContent = `สั่งไม่ได้ — ${error.message}`;
    siblings.forEach((b) => (b.disabled = false));
    return;
  }
  button.textContent = original;
  if (what === "stop" && panel) {
    // บอกทันทีว่าสั่งแล้วแต่ยังไม่จบ — ของจริงใช้เวลาถึงนาที
    panel.dataset.stopping = "1";
  }
  await loadFbControl();
}

function jobCard(job) {
  const look = statusOf(job);
  const box = document.createElement("article");
  box.className = `fc-job fc-${job.status}`;

  const head = document.createElement("div");
  head.className = "fc-head";
  const badge = document.createElement("span");
  badge.className = "fc-badge";
  badge.textContent = `${look.icon} ${look.label}`;
  const title = document.createElement("span");
  title.className = "fc-title";
  title.textContent = (job.caption || "(ไม่มีข้อความ)").replace(/\s+/g, " ").slice(0, 70);
  head.append(badge, title);
  box.append(head);

  const prog = document.createElement("p");
  prog.className = "fc-prog";
  const total = job.total ?? 0;
  prog.textContent =
    `โพสต์แล้ว ${job.posted_count ?? 0}/${total} กลุ่ม` +
    (job.pending ? ` · เหลือ ${job.pending} กลุ่ม` : "") +
    ` · ใบงาน ${job.id}`;
  box.append(prog);

  // **บรรทัดที่เจ้าของขอ — กำลังทำขั้นตอนไหน**
  const step = document.createElement("p");
  step.className = "fc-step";
  step.textContent = job.latest_step
    ? `▸ ${job.latest_step}`
    : "▸ ยังไม่มีบันทึกขั้นตอน";
  box.append(step);

  /* ---- สายสด: ไล่ให้เห็นว่าทำอะไรมาบ้าง ไม่ใช่เห็นแค่บรรทัดล่าสุด ---------
   *
   * เจ้าของสั่ง 11 ก.ย. 2569: "ทำแบบ real time update ให้หน่อยว่าตอนนี้
   * กำลังทำอะไรอยู่"
   *
   * ใบงานเก็บบันทึกทีละขั้นพร้อมเวลาไว้อยู่แล้ว (วัดจริง: ใบหนึ่ง 158 บรรทัด)
   * และมากับข้อมูลชุดเดียวกันที่ดึงอยู่แล้ว **ไม่ต้องยิงขอเพิ่มอีกเส้น**
   *
   * โชว์ท้าย 14 บรรทัด — มากกว่านี้กลายเป็นกำแพงตัวหนังสือที่ไม่มีใครอ่าน
   * น้อยกว่านี้ก็ไล่ไม่ทันว่าเพิ่งผ่านอะไรมา
   */
  const lines = Array.isArray(job.tail) ? job.tail : [];
  if (lines.length) {
    const feed = document.createElement("div");
    feed.className = "fc-feed";
    lines.slice(-14).forEach((line, index, shown) => {
      const row = document.createElement("div");
      row.className = "fc-line";
      // บรรทัดล่าสุดเน้นไว้ — ตาจะได้วิ่งไปหาก่อนโดยไม่ต้องอ่านทั้งก้อน
      if (index === shown.length - 1) row.classList.add("fc-line-now");
      row.textContent = line;
      feed.append(row);
    });
    box.append(feed);
    // เลื่อนไปบรรทัดล่าสุดเสมอ ไม่ต้องให้คนลากเอง
    requestAnimationFrame(() => { feed.scrollTop = feed.scrollHeight; });
  }

  // **ค้างมานานแค่ไหน** — บอทค้างกับบอทกำลังทำงานหน้าตาเหมือนกันทุกอย่าง
  // ถ้าไม่บอกเวลา จะแยกไม่ออกว่าควรรอต่อหรือควรเข้าไปดู (กติกาข้อ 2.4)
  if (job.status === "running") {
    const since = secondsSinceStamp(job.latest_step);
    if (since !== null) {
      const idle = document.createElement("p");
      idle.className = since >= 90 ? "fc-idle fc-idle-long" : "fc-idle";
      idle.textContent = since >= 90
        ? `⏳ ขั้นนี้ค้างมา ${Math.round(since)} วินาทีแล้ว — ปกติไม่เกิน 90 วินาที`
        : `กำลังทำขั้นนี้มา ${Math.round(since)} วินาที`;
      box.append(idle);
    }
  }

  const where = job.device || "";
  if (where) {
    const dev = document.createElement("p");
    dev.className = "fc-dev";
    dev.textContent = `📱 ใช้เครื่อง ${where}`;
    box.append(dev);
  }

  const c = { can_resume: job.can_resume, reason: "" };
  const bar = document.createElement("div");
  bar.className = "fc-buttons";
  const add = (text, what, cls) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `fc-btn ${cls}`;
    button.textContent = text;
    button.addEventListener("click", () => send(job.id, what, button, box));
    bar.append(button);
  };
  if (job.status === "running") add("⏸️ หยุด", "stop", "fc-stop");
  if (c.can_resume) add("▶️ ทำต่อ", "resume", "fc-resume");
  if (!["done", "cancelled"].includes(job.status)) add("✖️ ยกเลิก", "cancel", "fc-cancel");
  if (bar.children.length) box.append(bar);

  if (c.reason && !c.can_resume && job.status !== "running") {
    const why = document.createElement("p");
    why.className = "fc-why";
    why.textContent = c.reason;
    box.append(why);
  }
  return box;
}

export async function loadFbControl() {
  const wrap = $("#fcList");
  const note = $("#fcNote");
  if (!wrap) return;
  let data;
  try {
    // เส้นเบา — ส่งเฉพาะที่แผงนี้โชว์ ราว 3 KB แทน 134 KB ของเส้นเต็ม
    // จึงถามได้ทุกวินาทีโดยไม่ทำให้หน้าหน่วง (ดู app.py /api/fb/jobs/live)
    data = await api("/api/fb/jobs/live");
  } catch (error) {
    // **แยก "อ่านไม่ได้" ออกจาก "ไม่มีงาน"** สองอย่างนี้ต่างกันสิ้นเชิง
    if (note) note.textContent = `อ่านสถานะบอทไม่ได้ — ${error.message}`;
    return false;
  }

  const show = data.jobs || [];
  const live = { length: data.live_count ?? show.length };

  if (note) {
    note.textContent = data.running
      ? `🟢 บอทสายโพสต์กำลังทำงานอยู่ · ${live.length} ใบที่ยังไม่จบ`
      : live.length
        ? `⏸️ บอทหยุดอยู่ · ค้างไว้ ${live.length} ใบ กด "ทำต่อ" เพื่อไปต่อ`
        : "⚪ บอทว่าง ไม่มีงานค้าง";
  }

  wrap.textContent = "";
  if (!show.length) {
    const p = document.createElement("p");
    p.className = "gh-sub";
    p.textContent = "ยังไม่เคยมีงานโพสต์ในระบบ";
    wrap.append(p);
    return false;
  }
  show.forEach((job) => wrap.append(jobCard(job)));
  // คืนว่าบอทเดินอยู่ไหม — ตัวจับจังหวะเอาไปเลือกว่าจะถามถี่หรือห่าง
  return Boolean(data.running);
}

/** ดูสดตอนบอทเดินอยู่เท่านั้น — ว่างแล้วหยุดถาม ไม่ยิงทิ้งทั้งวัน
 *  (หน้านี้เปิดค้างได้ทั้งวัน ถ้าถามทุก 5 วินาทีตลอดคือยิงฟรีหมื่นกว่าครั้ง) */
/** ดูสด — **ถี่ตอนบอทเดิน ห่างตอนบอทว่าง**
 *
 *  บอททำงานอยู่ ขั้นตอนเปลี่ยนทุกไม่กี่วินาที ต้องถามถี่ถึงจะเรียกว่าสด
 *  บอทว่าง ตัวเลขไม่ขยับเลย ถามถี่เท่ากันคือยิงทิ้งฟรี — หน้านี้เปิดค้างได้
 *  ทั้งวัน ถามทุก 2 วินาทีตลอด 8 ชั่วโมง = 14,400 ครั้งที่ได้คำตอบเดิม
 *
 *  ใช้ setTimeout ต่อกันทีละรอบ ไม่ใช่ setInterval — เปลี่ยนจังหวะกลางทางได้
 *  และรอบที่ช้ากว่าปกติจะไม่ถูกยิงซ้อนทับ
 */
const FAST_MS = 1000;      // บอทกำลังทำงาน — เส้นเบาพอให้ถามทุกวินาที
const SLOW_MS = 15000;     // บอทว่าง
const HIDDEN_MS = 30000;   // ไม่มีใครเปิดดูแท็บนี้

export function watchFbControl() {
  if (timer) clearTimeout(timer);

  const tick = async () => {
    const wrap = $("#fcList");
    if (!wrap || !wrap.isConnected) return;        // หน้าถูกวาดใหม่ — เลิกวน

    let wait = SLOW_MS;
    const hidden = wrap.closest(".tab-area")?.hidden || document.hidden;
    if (hidden) {
      // แท็บถูกซ่อน/สลับไปหน้าต่างอื่น = ไม่มีใครดู แค่แวะเช็คห่างๆ พอ
      wait = HIDDEN_MS;
    } else {
      const running = await loadFbControl();
      wait = running ? FAST_MS : SLOW_MS;
    }
    timer = setTimeout(tick, wait);
  };

  timer = setTimeout(tick, FAST_MS);
}
