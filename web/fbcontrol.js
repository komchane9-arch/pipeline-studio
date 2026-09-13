/* แผงบอทสายโพสต์ — ใบโพสต์แบบสด: คิวกลุ่ม · เวลา · ปุ่มสั่งงาน
 *
 * เจ้าของสั่งไว้ 9 ก.ย. 2569: "หน้านี้ให้เขียนเพิ่มว่า บอทสายโพสต์กำลังทำอะไร
 * อยู่ขั้นตอนไหน แล้วมีปุ่มให้หยุด resume หรือ ยกเลิกการทำงานด้วย"
 * เพิ่ม 11 ก.ย. 2569: "ทำแบบ real time update" · "ปรับให้อัปเดตไวขึ้น" ·
 * "ทำให้โชว์คิวและรายละเอียด เหมือนใบโพสต์ มีเวลาที่รอโพสต์อะไรต่างๆด้วย"
 *
 * ## ที่อยู่ที่ใช้ — ของเดิมทั้งหมด ไม่มีเส้นสั่งงานใหม่เลย
 *
 *   GET  /api/fb/jobs/live[?history=1]   ใบที่ยังไม่จบ + คิวกลุ่ม + เวลา
 *   POST /api/fb/jobs/<id>/run           เริ่มโพสต์ใบที่พร้อมแล้ว
 *   POST /api/fb/jobs/<id>/stop          หยุดที่จุดปลอดภัย เก็บผลไว้ทำต่อได้
 *   POST /api/fb/jobs/<id>/resume        ทำต่อเฉพาะกลุ่มที่ยังไม่สำเร็จ
 *   POST /api/fb/jobs/<id>/reset         ล้างเฉพาะกล่องสถานะ ไม่แตะมือถือ
 *   POST /api/fb/jobs/<id>/cancel        ยกเลิกทิ้ง
 *
 * **ปุ่มไหนกดได้ ให้เซิร์ฟเวอร์ตัดสิน ไม่ใช่หน้าเว็บเดาเอง** เพราะเงื่อนไขจริง
 * ซับซ้อน — กลุ่มที่โพสต์ไปแล้วห้ามส่งซ้ำเด็ดขาด ถ้าหน้าเว็บเดาเอง วันหนึ่ง
 * จะโชว์ปุ่มที่กดแล้วโพสต์ซ้ำ ซึ่งถอนไม่ได้ ต้องเข้าไปลบเองในแอป
 *
 * ## "หยุด" ไม่ได้แปลว่าหยุดทันที
 *
 * วัดจริง 9 ก.ย.: กด Stop เวลา 12:56:02 → บอทเขียนว่า "รอจบกลุ่มปัจจุบัน"
 * → ปล่อยจอจริงตอน 12:57:05 (**ใช้เวลา 63 วินาที**) เพราะมันตัดกลางกลุ่มไม่ได้
 * จอจึงต้องแยก "กำลังหยุด" ออกจาก "หยุดแล้ว" ไม่งั้นเจ้าของจะกดซ้ำเพราะนึกว่า
 * ปุ่มไม่ทำงาน — เซิร์ฟเวอร์ส่ง `stopping` มาบอกช่วงนี้โดยเฉพาะ
 *
 * ## ทำไมต้องแก้ที่เดิม ไม่ใช่วาดใหม่ทั้งแผงทุกวินาที
 *
 * ของเดิมล้างแล้ววาดใหม่ทั้งก้อนทุกรอบ ตอนถามทุก 15 วินาทียังพอทน แต่พอเจ้าของ
 * สั่งให้ถามทุก 1 วินาที มันกลายเป็นแผงที่ **ลากคลุมข้อความไปคัดลอกไม่ได้เลย**
 * (ตัวหนังสือหายไปใต้มือทุกวินาที) กล่องที่กางดูอยู่หุบเอง และแถบบันทึกเด้งกลับ
 * ทุกครั้งที่เลื่อนขึ้นไปอ่านย้อน
 *
 * ตอนนี้จึงสร้างการ์ดครั้งเดียวแล้วเขียนทับเฉพาะค่าที่เปลี่ยน — เพิ่ม/ลบการ์ด
 * เฉพาะตอนใบงานเข้าออกจากคิวจริงๆ
 */

import { api } from "./core.js";

const $ = (sel) => document.querySelector(sel);

const STATUS_LOOK = {
  running: { icon: "🟢", label: "กำลังทำงาน" },
  ready: { icon: "🟡", label: "รอโพสต์" },
  stopped: { icon: "⏸️", label: "หยุดไว้" },
  done: { icon: "✅", label: "เสร็จแล้ว" },
  failed: { icon: "🔴", label: "ล้มเหลว" },
  cancelled: { icon: "⚪", label: "ยกเลิกแล้ว" },
  waiting_caption: { icon: "✏️", label: "รอแคปชัน" },
  waiting_image: { icon: "🖼", label: "รอรูป" },
};

const SOURCE_LOOK = { telegram: "📨 จาก Telegram", web: "💻 จากหน้าเว็บ" };

const QUEUE_LOOK = {
  ok: { icon: "✅", label: "โพสต์แล้ว" },
  fail: { icon: "❌", label: "ไม่สำเร็จ" },
  now: { icon: "🔄", label: "กำลังโพสต์" },
  wait: { icon: "⏳", label: "รอคิว" },
};

let timer = null;
const cards = new Map();          // รหัสใบงาน -> การ์ดที่สร้างไว้แล้ว

// ---------------------------------------------------------------- เวลาเป็นคำ

function when(text) {
  const value = new Date(String(text || ""));
  return Number.isNaN(value.getTime()) ? null : value;
}

/** "14:41" ถ้าวันนี้ · "11/09 14:41" ถ้าคนละวัน · "" ถ้าอ่านไม่ออก */
function clockText(text) {
  const at = when(text);
  if (!at) return "";
  const pad = (n) => String(n).padStart(2, "0");
  const hhmm = `${pad(at.getHours())}:${pad(at.getMinutes())}`;
  const today = new Date();
  const sameDay = at.getFullYear() === today.getFullYear()
    && at.getMonth() === today.getMonth() && at.getDate() === today.getDate();
  return sameDay ? hhmm : `${pad(at.getDate())}/${pad(at.getMonth() + 1)} ${hhmm}`;
}

/** ช่วงเวลาเป็นคำที่คนอ่านออก — "2 ชม. 51 นาที" ไม่ใช่ "10260 วินาที" */
function spanText(seconds) {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total} วินาที`;
  const mins = Math.floor(total / 60);
  if (mins < 60) return `${mins} นาที`;
  const hours = Math.floor(mins / 60);
  const rest = mins % 60;
  if (hours < 24) return rest ? `${hours} ชม. ${rest} นาที` : `${hours} ชม.`;
  return `${Math.floor(hours / 24)} วัน ${hours % 24} ชม.`;
}

function gapFrom(text) {
  const at = when(text);
  return at ? (Date.now() - at.getTime()) / 1000 : null;
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

// ------------------------------------------------------------------ สั่งงานบอท

async function send(jobId, what, button, bar) {
  const siblings = [...bar.children];
  siblings.forEach((b) => { b.disabled = true; });
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
    siblings.forEach((b) => { b.disabled = false; });
    return;
  }
  button.textContent = original;
  siblings.forEach((b) => { b.disabled = false; });
  await loadFbControl();
}

// --------------------------------------------------------- สร้างการ์ดครั้งเดียว

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** เขียนข้อความใหม่เฉพาะตอนค่าเปลี่ยน — เขียนทับทุกรอบจะลากคลุมคัดลอกไม่ได้ */
function setText(node, text) {
  const value = String(text ?? "");
  if (node.textContent !== value) node.textContent = value;
}

function show(node, on) {
  if (node.hidden === Boolean(on)) node.hidden = !on;
}

function buildCard(jobId) {
  const root = el("article", "fc-job");
  const head = el("div", "fc-head");
  const badge = el("span", "fc-badge");
  const title = el("span", "fc-title");
  const source = el("span", "fc-src");
  head.append(badge, title, source);

  const caption = el("p", "fc-caption");
  const meta = el("p", "fc-meta");
  const times = el("p", "fc-when");
  const alert = el("p", "fc-alert");
  alert.hidden = true;

  const track = el("div", "fc-bar");
  const fill = el("span");
  track.append(fill);
  const prog = el("p", "fc-prog");
  const step = el("p", "fc-step");
  const idle = el("p", "fc-idle");
  idle.hidden = true;

  const feed = el("div", "fc-feed");
  feed.hidden = true;

  const queueBox = el("details", "fc-queue-box");
  queueBox.open = true;
  const queueHead = el("summary", "fc-queue-sum", "คิวกลุ่ม");
  const queue = el("ol", "fc-queue");
  queueBox.append(queueHead, queue);

  // เนื้อหาที่จะโพสต์ — ปิดไว้ก่อน รูปค่อยโหลดตอนกางจริง ไม่งั้นแผงสถานะ
  // จะลากรูปทุกใบของทุกงานมาโหลดทิ้งตั้งแต่เปิดหน้า
  const content = el("details", "fc-content");
  content.append(el("summary", "", "ดูเนื้อหาที่จะโพสต์"));
  const contentBody = el("div", "fc-content-body");
  content.append(contentBody);

  const bar = el("div", "fc-buttons");
  const buttons = {};
  [["run", "🚀 โพสต์เลย", "fc-run"], ["stop", "⏸️ หยุด", "fc-stop"],
    ["resume", "▶️ ทำต่อ", "fc-resume"], ["reset", "↺ รีเซ็ต", "fc-reset"],
    ["cancel", "✖️ ยกเลิก", "fc-cancel"]].forEach(([what, text, cls]) => {
    const button = el("button", `fc-btn ${cls}`, text);
    button.type = "button";
    button.hidden = true;
    button.addEventListener("click", () => send(jobId, what, button, bar));
    buttons[what] = button;
    bar.append(button);
  });

  const why = el("p", "fc-why");
  why.hidden = true;
  const help = el("p", "fc-help",
    "ทำต่อ = โพสต์เฉพาะกลุ่มที่ยังไม่สำเร็จ · รีเซ็ต = ล้างกล่องสถานะเฉยๆ "
    + "ไม่ลบงาน · หยุด = หยุดที่จุดปลอดภัยแล้วกลับมาทำต่อได้");

  root.append(head, caption, meta, times, alert, track, prog, step, idle,
    feed, queueBox, content, bar, why, help);

  const entry = {
    root, badge, title, source, caption, meta, times, alert,
    fill, prog, step, idle, feed, queueHead, queue, content,
    contentBody, buttons, bar, why, job: null,
    feedKey: "", queueKey: "", contentKey: "",
  };

  content.addEventListener("toggle", () => {
    if (content.open) paintContent(entry);
  });
  return entry;
}

// -------------------------------------------------------------- วาดของในการ์ด

function paintContent(entry) {
  const job = entry.job;
  if (!job) return;
  const key = `${job.images}|${job.comment_images}|${(job.comment_texts || []).join("|")}`;
  if (entry.contentKey === key) return;
  entry.contentKey = key;

  const parts = [];
  if (job.images) {
    const strip = el("div", "fc-shots");
    for (let i = 0; i < job.images; i += 1) {
      const img = document.createElement("img");
      img.loading = "lazy";
      img.alt = `รูปโพสต์ใบที่ ${i + 1}`;
      img.src = `/api/fb/jobs/${encodeURIComponent(job.id)}/media/post/${i}`;
      strip.append(img);
    }
    parts.push(strip);
  }
  (job.comment_texts || []).forEach((text, index) => {
    const block = el("div", "fc-comment");
    block.append(el("strong", "", `คอมเมนต์ช่อง ${index + 1}`));
    block.append(el("span", "", text));
    if (index < job.comment_images) {
      const img = document.createElement("img");
      img.loading = "lazy";
      img.alt = `รูปคอมเมนต์ช่อง ${index + 1}`;
      img.src = `/api/fb/jobs/${encodeURIComponent(job.id)}/media/comment/${index}`;
      block.append(img);
    }
    parts.push(block);
  });
  if (!parts.length) parts.push(el("p", "fc-help", "ใบนี้ยังไม่มีรูปและคอมเมนต์"));
  entry.contentBody.replaceChildren(...parts);
}

function paintFeed(entry, lines) {
  const key = lines.join("\n");
  if (entry.feedKey === key) return;
  entry.feedKey = key;
  show(entry.feed, lines.length > 0);
  if (!lines.length) { entry.feed.replaceChildren(); return; }
  // เลื่อนตามเฉพาะตอนที่อ่านอยู่ท้ายสุด — ถ้าเลื่อนขึ้นไปอ่านย้อนอยู่
  // แล้วโดนดึงกลับลงมาทุกวินาที คืออ่านย้อนไม่ได้เลย
  const stick = entry.feed.scrollHeight - entry.feed.scrollTop
    - entry.feed.clientHeight < 24;
  entry.feed.replaceChildren(...lines.map((line, index) => {
    const row = el("div", "fc-line", line);
    // บรรทัดล่าสุดเน้นไว้ — ตาจะได้วิ่งไปหาก่อนโดยไม่ต้องอ่านทั้งก้อน
    if (index === lines.length - 1) row.classList.add("fc-line-now");
    return row;
  }));
  if (stick) entry.feed.scrollTop = entry.feed.scrollHeight;
}

function paintQueue(entry, job) {
  const rows = job.queue || [];
  const key = rows.map((r) => `${r.state}:${r.name}:${r.link || ""}:${r.error || ""}`)
    .join("|");
  if (entry.queueKey === key) return;
  entry.queueKey = key;

  const done = rows.filter((r) => r.state === "ok").length;
  setText(entry.queueHead, `คิวกลุ่ม — ${rows.length} กลุ่ม · โพสต์แล้ว ${done}`);
  entry.queue.replaceChildren(...rows.map((row) => {
    const look = QUEUE_LOOK[row.state] || QUEUE_LOOK.wait;
    const line = el("li", `fc-q fc-q-${row.state}`);
    line.append(el("span", "fc-q-icon", look.icon));
    line.append(el("span", "fc-q-name", row.name || "(ไม่ทราบชื่อกลุ่ม)"));
    const tail = [look.label];
    // ❤️/💬 ติดได้เฉพาะกลุ่มที่โพสต์ขึ้นจริง — กลุ่มที่ล้มแล้วขึ้นหัวใจ
    // อ่านแล้วขัดกันเอง เหมือนบอกว่าล้มแต่ก็กดใจให้โพสต์ที่ไม่มีอยู่
    if (row.state === "ok" && row.liked) tail.push("❤️");
    if (row.state === "ok" && row.commented) tail.push("💬");
    line.append(el("span", "fc-q-state", tail.join(" ")));
    if (row.error) line.append(el("span", "fc-q-err", `— ${row.error}`));
    if (row.link) {
      const open = document.createElement("a");
      open.className = "fc-q-link";
      open.href = row.link;
      open.target = "_blank";
      open.rel = "noreferrer";
      open.textContent = "🔗 ดูโพสต์";
      line.append(open);
    }
    return line;
  }));
}

function paintCard(entry, job) {
  entry.job = job;
  const look = STATUS_LOOK[job.status] || { icon: "•", label: job.status || "ไม่ทราบ" };
  entry.root.className = `fc-job fc-${job.status}`;
  setText(entry.badge, `${look.icon} ${look.label}`);
  setText(entry.title, `ใบงาน ${job.id}`);
  setText(entry.source, SOURCE_LOOK[job.source] || "");
  setText(entry.caption, (job.caption || "(ยังไม่มีแคปชัน)").trim());

  const bits = [`🖼 ${job.images} ใบ`];
  bits.push(job.comments ? `💬 ${job.comments} คอมเมนต์` : "💬 ไม่มีคอมเมนต์");
  bits.push(`📦 ${job.total} กลุ่ม`);
  if (job.device) bits.push(`📱 ${job.device}`);
  setText(entry.meta, bits.join(" · "));

  // ---- เวลา: ตั้งไว้เมื่อไร รอมานานแค่ไหน เหลืออีกเท่าไร ทำไปแล้วกี่นาที
  const lines = [];
  if (job.created_at) lines.push(`สร้าง ${clockText(job.created_at)}`);
  if (job.run_at) {
    const left = -(gapFrom(job.run_at) ?? 0);
    lines.push(left > 0
      ? `⏰ นัดโพสต์ ${clockText(job.run_at)} · อีก ${spanText(left)}`
      : `⏰ นัดไว้ ${clockText(job.run_at)} · ถึงเวลาแล้ว`);
  } else if (job.status === "ready") {
    lines.push("⏰ ไม่ได้ตั้งเวลา — กด \"โพสต์เลย\" ถึงจะเริ่ม");
  }
  if (job.started_at) {
    const ended = when(job.finished_at);
    const begun = when(job.started_at);
    const ran = ended && begun ? (ended - begun) / 1000 : gapFrom(job.started_at);
    lines.push(job.finished_at
      ? `เริ่ม ${clockText(job.started_at)} · จบ ${clockText(job.finished_at)}`
        + (ran !== null ? ` · ใช้เวลา ${spanText(ran)}` : "")
      : `เริ่ม ${clockText(job.started_at)} · ทำมาแล้ว ${spanText(ran ?? 0)}`);
  } else if (job.created_at && ["ready", "stopped"].includes(job.status)) {
    const waited = gapFrom(job.created_at);
    if (waited !== null) lines.push(`รอคิวมาแล้ว ${spanText(waited)}`);
  }
  setText(entry.times, lines.join(" · "));

  // ---- สถานะที่ขัดกันเอง ต้องดังขึ้นมา ไม่ใช่ปล่อยให้ดูปกติ
  let alert = "";
  // ใบที่ถูกเรียกไปโพสต์เป็นใบอื่นแล้ว — ต้องบอกให้ชัด ไม่งั้นเห็น "0/6 กลุ่ม"
  // แล้วนึกว่ายังไม่ได้ลง แล้วสั่งลงซ้ำ ซึ่งถอนคืนไม่ได้
  if (job.posted_via) {
    alert = `✅ ใบนี้ถูกเรียกไปโพสต์เป็นใบ ${job.posted_via} แล้ว — ไม่ต้องโพสต์ซ้ำ`;
  } else if (job.stopping) {
    alert = "⏸️ สั่งหยุดแล้ว — มือถือกำลังทำกลุ่มปัจจุบันให้จบก่อน "
      + "(วัดจริงใช้เวลาราว 1 นาที) ไม่ต้องกดซ้ำ";
  } else if (job.orphan) {
    alert = "⚠️ ใบงานเขียนว่ากำลังทำ แต่ไม่มีตัวรันถืออยู่ — ตัวรันน่าจะหลุดไป "
      + "กด \"ทำต่อ\" เพื่อเริ่มเฉพาะกลุ่มที่เหลือ";
  } else if (job.deferred) {
    alert = "⏳ ถึงเวลาที่ตั้งไว้แล้ว แต่จอมือถือไม่ว่าง — ระบบจะลองใหม่เองทุก 20 วินาที";
  }
  setText(entry.alert, alert);
  show(entry.alert, Boolean(alert));

  const pct = job.total ? Math.min(100, (job.posted_count / job.total) * 100) : 0;
  entry.fill.style.width = `${pct}%`;
  entry.fill.className = job.failed ? "fc-bar-some" : "";
  setText(entry.prog,
    `โพสต์แล้ว ${job.posted_count}/${job.total} กลุ่ม`
    + (job.failed ? ` · ไม่สำเร็จ ${job.failed}` : "")
    + (job.pending ? ` · เหลือ ${job.pending}` : ""));

  setText(entry.step, job.latest_step ? `▸ ${job.latest_step}` : "▸ ยังไม่มีบันทึกขั้นตอน");

  // **ค้างมานานแค่ไหน** — บอทค้างกับบอทกำลังทำงานหน้าตาเหมือนกันทุกอย่าง
  // ถ้าไม่บอกเวลา จะแยกไม่ออกว่าควรรอต่อหรือควรเข้าไปดู (กติกาข้อ 2.4)
  const since = job.status === "running" ? secondsSinceStamp(job.latest_step) : null;
  if (since === null) {
    show(entry.idle, false);
  } else {
    entry.idle.className = since >= 90 ? "fc-idle fc-idle-long" : "fc-idle";
    setText(entry.idle, since >= 90
      ? `⏳ ขั้นนี้ค้างมา ${Math.round(since)} วินาทีแล้ว — ปกติไม่เกิน 90 วินาที`
      : `กำลังทำขั้นนี้มา ${Math.round(since)} วินาที`);
    show(entry.idle, true);
  }

  paintFeed(entry, Array.isArray(job.tail) ? job.tail.slice(-14) : []);
  paintQueue(entry, job);
  if (entry.content.open) paintContent(entry);

  show(entry.buttons.run, Boolean(job.can_run));
  show(entry.buttons.stop, Boolean(job.can_stop) && !job.stopping);
  // ใบที่ยังไม่เคยเริ่ม "ทำต่อ" กับ "โพสต์เลย" คือสิ่งเดียวกัน — โชว์สองปุ่ม
  // ที่ทำงานเหมือนกันแต่ชื่อต่างกัน มีแต่ทำให้ลังเลว่ากดอันไหนถึงจะถูก
  show(entry.buttons.resume, Boolean(job.can_resume) && !job.can_run);
  show(entry.buttons.reset, Boolean(job.can_reset));
  show(entry.buttons.cancel, !["done", "cancelled"].includes(job.status));

  setText(entry.why, job.why || "");
  show(entry.why, Boolean(job.why));
}

// -------------------------------------------------------------------- ประวัติ

let historyOpen = false;

function paintHistory(rows) {
  const box = $("#fcHistory");
  if (!box) return;
  if (!rows.length) {
    box.replaceChildren(el("p", "fc-help", "ยังไม่มีงานที่ทำจบไปในระบบ"));
    return;
  }
  box.replaceChildren(...rows.map((job) => {
    const look = STATUS_LOOK[job.status] || { icon: "•", label: job.status };
    const line = el("div", "fc-past");
    line.append(el("span", "fc-past-when", clockText(job.finished_at) || "—"));
    line.append(el("span", "fc-past-badge", `${look.icon} ${look.label}`));
    // ต้นฉบับที่ถูกเรียกไปใช้ ไม่ได้โพสต์เองจริงๆ — เขียน "0/6 กลุ่ม" จะอ่าน
    // เหมือนล้มเหลว ทั้งที่เนื้อหาขึ้นครบแล้วผ่านใบอื่น
    line.append(el("span", "fc-past-text",
      (job.posted_via ? `เรียกไปโพสต์เป็นใบ ${job.posted_via}` : `${job.posted_count}/${job.total} กลุ่ม`)
      + ` · ${(job.caption || "").replace(/\s+/g, " ")}`));
    (job.links || []).forEach((link, index) => {
      const open = document.createElement("a");
      open.className = "fc-q-link";
      open.href = link;
      open.target = "_blank";
      open.rel = "noreferrer";
      open.textContent = `🔗${index + 1}`;
      line.append(open);
    });
    return line;
  }));
}

// ------------------------------------------------------------------- ดึงข้อมูล

export async function loadFbControl() {
  const wrap = $("#fcList");
  const note = $("#fcNote");
  if (!wrap) return false;
  let data;
  try {
    // เส้นเบา — ส่งเฉพาะที่แผงนี้โชว์ ราว 10 KB แทน 134 KB ของเส้นเต็ม
    // จึงถามได้ทุกวินาทีโดยไม่ทำให้หน้าหน่วง (ดู app.py /api/fb/jobs/live)
    data = await api(`/api/fb/jobs/live${historyOpen ? "?history=1" : ""}`);
  } catch (error) {
    // **แยก "อ่านไม่ได้" ออกจาก "ไม่มีงาน"** สองอย่างนี้ต่างกันสิ้นเชิง
    if (note) setText(note, `อ่านสถานะบอทไม่ได้ — ${error.message}`);
    return false;
  }

  const rows = data.jobs || [];
  const live = data.live_count ?? rows.length;
  if (note) {
    setText(note, data.running
      ? `🟢 บอทสายโพสต์กำลังทำงานอยู่ · ค้างในคิว ${live} ใบ`
      : live
        ? `⏸️ บอทไม่ได้เดินอยู่ · มีงานในคิว ${live} ใบ`
        : "⚪ บอทว่าง ไม่มีงานค้าง");
  }
  const stamp = $("#fcStamp");
  if (stamp) setText(stamp, `อัปเดต ${data.at || ""}`);

  if (!rows.length) {
    cards.clear();
    wrap.replaceChildren(el("p", "gh-sub", "ยังไม่เคยมีงานโพสต์ในระบบ"));
    if (historyOpen) paintHistory(data.history || []);
    return false;
  }

  // เพิ่ม/ลบการ์ดเฉพาะตอนคิวเปลี่ยนจริง แล้วค่อยเรียงให้ตรงลำดับคิว
  const keep = new Set(rows.map((job) => job.id));
  [...cards.keys()].forEach((id) => {
    if (!keep.has(id)) {
      cards.get(id).root.remove();
      cards.delete(id);
    }
  });
  rows.forEach((job, index) => {
    let entry = cards.get(job.id);
    if (!entry) {
      entry = buildCard(job.id);
      cards.set(job.id, entry);
    }
    paintCard(entry, job);
    const at = wrap.children[index];
    if (at !== entry.root) wrap.insertBefore(entry.root, at || null);
  });
  if (historyOpen) paintHistory(data.history || []);
  return Boolean(data.running);
}

// ------------------------------------------------------------------ จังหวะถาม

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
const HIDDEN_MS = 30000;   // ไม่มีใครเปิดดูแท็บนี้ — ถามห่างๆ พอให้ข้อมูลไม่เก่า
const PEEK_MS = 1200;      // แวะดูว่ามีคนเปิดมาดูหรือยัง (ไม่ยิงขออะไรเลย)

export function watchFbControl() {
  if (timer) clearTimeout(timer);

  const reload = $("#fcReload");
  if (reload && !reload.dataset.wired) {
    reload.dataset.wired = "1";
    reload.addEventListener("click", () => loadFbControl());
  }
  const history = $("#fcHistoryBox");
  if (history && !history.dataset.wired) {
    history.dataset.wired = "1";
    history.addEventListener("toggle", () => {
      historyOpen = history.open;
      if (historyOpen) loadFbControl();
    });
  }

  /* ตอนแท็บถูกซ่อน **แยกสองจังหวะออกจากกัน**
   *
   * เจอจริง 11 ก.ย. 2569: เปิดหน้าเว็บแล้วกดเข้าแท็บนี้ — แผงว่างเปล่านาน
   * **30 วินาที** ทั้งที่ข้อมูลพร้อมอยู่แล้ว เพราะรอบแรกยิงตอนแท็บยังซ่อนอยู่
   * แล้วสั่งนอนยาว 30 วินาทีทันที กว่าจะตื่นมาก็สายไปแล้ว
   *
   * จังหวะ "ขอข้อมูล" กับจังหวะ "ดูว่ามีคนเปิดมาดูหรือยัง" เป็นคนละเรื่อง
   * อย่างแรกมีต้นทุนจริงจึงต้องห่าง อย่างหลังแค่อ่านค่าบนหน้า ไม่มีต้นทุนเลย
   */
  let lastAsk = 0;

  const tick = async () => {
    const wrap = $("#fcList");
    if (!wrap || !wrap.isConnected) return;        // หน้าถูกวาดใหม่ — เลิกวน

    let wait;
    const hidden = wrap.closest(".tab-area")?.hidden || document.hidden;
    if (hidden) {
      // ไม่มีใครดู — ขอข้อมูลห่างๆ พอให้ไม่เก่า แต่ยังแวะดูบ่อยๆ ว่าเปิดมาหรือยัง
      if (Date.now() - lastAsk >= HIDDEN_MS) {
        lastAsk = Date.now();
        await loadFbControl();
      }
      wait = PEEK_MS;
    } else {
      lastAsk = Date.now();
      const running = await loadFbControl();
      wait = running ? FAST_MS : SLOW_MS;
    }
    timer = setTimeout(tick, wait);
  };

  timer = setTimeout(tick, FAST_MS);
}
