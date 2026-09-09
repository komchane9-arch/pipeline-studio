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

function jobCard(job, runningOn) {
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
  const total = (job.group_names || job.groups || []).length;
  prog.textContent =
    `โพสต์แล้ว ${job.posted_count ?? 0}/${total} กลุ่ม` +
    (job.pending_groups?.length ? ` · เหลือ ${job.pending_groups.length} กลุ่ม` : "") +
    ` · ใบงาน ${job.id}`;
  box.append(prog);

  // **บรรทัดที่เจ้าของขอ — กำลังทำขั้นตอนไหน**
  const step = document.createElement("p");
  step.className = "fc-step";
  step.textContent = job.latest_step
    ? `▸ ${job.latest_step}`
    : "▸ ยังไม่มีบันทึกขั้นตอน";
  box.append(step);

  const where = runningOn?.[job.id];
  if (where) {
    const dev = document.createElement("p");
    dev.className = "fc-dev";
    dev.textContent = `📱 ใช้เครื่อง ${where}`;
    box.append(dev);
  }

  const c = job.controls || {};
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
    data = await api("/api/fb/jobs");
  } catch (error) {
    // **แยก "อ่านไม่ได้" ออกจาก "ไม่มีงาน"** สองอย่างนี้ต่างกันสิ้นเชิง
    if (note) note.textContent = `อ่านสถานะบอทไม่ได้ — ${error.message}`;
    return;
  }

  const jobs = data.jobs || [];
  const live = jobs.filter((j) => !["done", "cancelled"].includes(j.status));
  const show = live.length ? live : jobs.slice(0, 2);

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
    return;
  }
  show.forEach((job) => wrap.append(jobCard(job, data.running_on)));
}

/** ดูสดตอนบอทเดินอยู่เท่านั้น — ว่างแล้วหยุดถาม ไม่ยิงทิ้งทั้งวัน
 *  (หน้านี้เปิดค้างได้ทั้งวัน ถ้าถามทุก 5 วินาทีตลอดคือยิงฟรีหมื่นกว่าครั้ง) */
export function watchFbControl() {
  if (timer) clearInterval(timer);
  timer = setInterval(async () => {
    const wrap = $("#fcList");
    if (!wrap || !wrap.isConnected) return;
    // แท็บถูกซ่อนอยู่ = ไม่มีใครดู ไม่ต้องถาม
    if (wrap.closest(".tab-area")?.hidden) return;
    await loadFbControl();
  }, 5000);
}
