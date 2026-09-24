/* ตอบคอมเมนต์ — โพสต์อยู่บน คอมเมนต์อยู่ใต้โพสต์ แบบเดียวกับ Facebook
 *
 * **เจ้าของสั่ง 13 ก.ย. 2569** — *"ช่องพิมพ์อยู่บนหน้าเว็บ ทำคล้ายๆ กับ
 * โครงสร้างเฟสบุ๊ค โพสต์ - คอมเมนต์ใต้โพสต์"* และ *"ทำ Input ให้ผมพิมพ์
 * เพื่อตอบ comment"*
 *
 * ## ทำงานเป็นสองช่วง — หน้านี้คือช่วงแรกเท่านั้น
 *
 *   ① Bot8 (Chrome)  เปิดลิงก์โพสต์ทีละกลุ่ม อ่านคอมเมนต์ + ชื่อคนคอมเมนต์
 *   ② หน้านี้          โชว์โพสต์พร้อมคอมเมนต์ใต้โพสต์ · เจ้าของพิมพ์คำตอบเก็บไว้
 *   ③ มือถือ           เปิดลิงก์นั้นใน Facebook หาคนจากชื่อที่บันทึกไว้
 *                      แล้ว **พิมพ์ตอบจริงบนแอป** (กติกาข้อ 2.7)
 *
 * **หน้านี้ไม่ส่งอะไรขึ้น Facebook เลย** พิมพ์แล้วแค่เก็บไว้ รอขั้น ③ เอาไปพิมพ์
 * จึงต้องเขียนให้ชัดบนจอ ไม่งั้นเจ้าของจะพิมพ์แล้วนึกว่าตอบไปแล้ว
 *
 *   GET  /api/fb/engage/threads    โพสต์ + คอมเมนต์ใต้โพสต์
 *   POST /api/fb/engage/reply      {comment_key, text} · text ว่าง = ลบที่พิมพ์ไว้
 *
 * ## สองอย่างที่ห้ามยุบรวมกัน
 *
 * "พิมพ์คำตอบเก็บไว้แล้ว" กับ "ตอบขึ้น Facebook แล้ว" **คนละเรื่องกันสิ้นเชิง**
 * ฝั่งเซิร์ฟเวอร์แยกไว้เป็น `reply_draft` กับ `reply_sent_at` หน้านี้ต้องแยกตาม
 * ถ้าพิมพ์แล้วทำให้คอมเมนต์หายไปจากรายการค้าง เจ้าของจะนึกว่าตอบครบแล้ว
 * ทั้งที่ยังไม่มีอะไรขึ้นไปสักตัว (กติกาข้อ 2.3.1)
 */

import { api } from "./core.js";
import { gfQuery, gfAccount } from "./gfaccount.js";

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};

let data = null;
// หน้าใหม่เริ่มจากโครงใบงานครบ เพื่อให้เห็นทุกกลุ่ม/โพสต์ที่ Bot8 ยังตามเก็บ;
// ผู้ใช้ยังสลับเป็น "เฉพาะที่ค้าง" ได้จากปุ่มเดิม.
let onlyPending = false;
let replyDeadline = 0;
let dailyDeadline = 0;
let priorityDeadline = 0;
let replyTimer = null;
let completionTimer = null;
let completionBusy = false;
let collectorTimer = null;
let collectorBusy = false;
let startNowBusy = false;
let restrictionResumeBusy = false;
const resumedReplies = new Map();
const completedReplyLinks = new Map();
let replyAlertsSignature = "";

function replyNoticeHost() {
  let host = $("#egReplyAlerts");
  if (!host && $("#egTimer")) {
    host = el("div", "eg-reply-alerts");
    host.id = "egReplyAlerts";
    host.setAttribute("aria-live", "polite");
    $("#egTimer").after(host);
  }
  return host;
}

function replyPostLink(url) {
  const link = el("a", "eg-notice-link", "🔗 เปิดโพสต์");
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:" || !/(^|\.)facebook\.com$/.test(parsed.hostname)) return null;
    link.href = parsed.href;
  } catch { return null; }
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function completeResumedReply(key, state) {
  const info = resumedReplies.get(key);
  if (!info || !state.reply_sent_at) return;
  completedReplyLinks.set(key, info);
  resumedReplies.delete(key);
}

function paintReplyAlerts() {
  const host = replyNoticeHost();
  if (!host || !data) return;
  const account = data.account || "";
  const pending = [];
  for (const post of data.posts || []) for (const item of post.comments_list || []) {
    completeResumedReply(item.comment_key, item);
    if (!item.is_ours && !item.ignored && !item.reply_sent_at && !item.answered
        && (item.reply_error || item.reply_submitted_at || resumedReplies.has(item.comment_key))) {
      pending.push({ item, post });
    }
  }
  const done = [...completedReplyLinks].filter(([, info]) => info.account === account);
  const signature = JSON.stringify([account, data.reply_schedule?.reason, data.reply_schedule?.waiting,
    pending.map(({item}) => [item.comment_key, item.reply_error, item.reply_submitted_at,
      item.reply_attempted_at, resumedReplies.get(item.comment_key)]), done]);
  if (signature === replyAlertsSignature) return;
  replyAlertsSignature = signature;
  host.replaceChildren();
  for (const {item, post} of pending) {
    const saved = resumedReplies.get(item.comment_key);
    const queued = saved?.state === "queued" && !item.reply_error;
    const notice = el("div", "eg-reply-notice");
    notice.dataset.commentKey = item.comment_key;
    const message = el("span", "eg-notice-message", `${item.author} · ${item.reply_attempted_at || ""} · ${saved?.error || (queued ? (item.reply_submitted_at ? "รอตรวจผล ไม่ส่งซ้ำ" : "เข้าคิวทำต่อแล้ว") : item.reply_error || "ส่งแล้วแต่ยังยืนยันไม่ได้")}`);
    const action = el("button", "eg-notice-retry", saved?.state === "sending" ? "กำลังสั่ง…" : queued ? "เข้าคิวแล้ว" : item.reply_submitted_at ? "🔎 ตรวจผล" : "▶ ทำต่อ");
    action.type = "button";
    action.disabled = queued || saved?.state === "sending" || (!item.reply_submitted_at
      && data.reply_schedule?.reason === "safety_hold" && data.reply_schedule?.waiting);
    action.title = item.reply_submitted_at ? "ตรวจคำตอบเดิมเท่านั้น ไม่ส่งซ้ำ" : "ใช้คำตอบที่บันทึกไว้ เข้าคิวโดยยังเคารพเวลาพักและโควต้า";
    action.addEventListener("click", async () => {
      const info = {account, post_url: post.post_url, author: item.author, state: "sending"};
      resumedReplies.set(item.comment_key, info);
      paintReplyAlerts();
      try {
        const out = await api("/api/fb/engage/retry", {method: "POST",
          body: JSON.stringify({comment_key: item.comment_key, account})});
        Object.assign(item, {reply_error: "", reply_queued_at: out.reply_queued_at,
          reply_submitted_at: out.reply_submitted_at || "", reply_sent_at: out.reply_sent_at || ""});
        resumedReplies.set(item.comment_key, {...info, state: "queued"});
        completeResumedReply(item.comment_key, out);
      } catch (error) {
        resumedReplies.set(item.comment_key, {...info, state: "error", error: error.message});
      }
      paintReplyTimer();
    });
    const remove = el("button", "eg-notice-delete", "🗑 ลบรายการ");
    remove.type = "button";
    remove.title = "นำรายการนี้ออกจากคิวและซ่อนจากหน้านี้ โดยไม่ลบคอมเมนต์บน Facebook";
    remove.addEventListener("click", async () => {
      action.disabled = remove.disabled = true;
      const original = remove.textContent;
      remove.textContent = "กำลังลบ…";
      try {
        await api("/api/fb/engage/ignore", {method: "POST",
          body: JSON.stringify({comment_key: item.comment_key, on: true})});
        item.ignored = 1;
        resumedReplies.delete(item.comment_key);
        completedReplyLinks.delete(item.comment_key);
        [...document.querySelectorAll(".eg-comment")]
          .find((node) => node.dataset.commentKey === item.comment_key)?.remove();
        replyAlertsSignature = "";
        paintReplyAlerts();
        paintHead();
      } catch (error) {
        remove.textContent = `ลบไม่ได้ — ${error.message}`;
        action.disabled = false;
        remove.disabled = false;
        return;
      }
      remove.textContent = original;
    });
    notice.append(message, action, remove);
    const link = replyPostLink(post.post_url);
    if (link) notice.append(link);
    host.append(notice);
  }
  for (const [key, info] of done) {
    const notice = el("div", "eg-reply-notice is-done");
    notice.append(el("span", "eg-notice-message", `✅ ${info.author} ตอบสำเร็จ — นำออกจากแจ้งเตือนแล้ว`));
    const link = replyPostLink(info.post_url);
    if (link) notice.append(link);
    const dismiss = el("button", "eg-notice-dismiss", "ปิด");
    dismiss.type = "button";
    dismiss.onclick = () => { completedReplyLinks.delete(key); paintReplyAlerts(); };
    notice.append(dismiss);
    host.append(notice);
  }
}
/* กล่องไหนถูกกางไว้ — ต้องจำข้ามการวาดใหม่
 *
 * เคยเจอมาแล้วกับแผงงานโพสต์: วาดใหม่ทุกครั้งแล้วกล่องที่กางอยู่หุบเอง
 * เจ้าของกำลังดูรูปอยู่แล้วมันหุบใส่หน้า = ใช้งานไม่ได้จริง
 */
const openGroups = new Set();
const openJobs = new Set();
const openPosts = new Set();
const openTracked = new Set();

function postGroupKey(post) {
  return `${post.account || ""}\u0000${post.job_id || "(ไม่มีใบงาน)"}\u0000${post.group_id || post.group_name || ""}`;
}

function postJobKey(post) {
  return `${post.account || ""}\u0000${post.job_id || "(ไม่มีใบงาน)"}`;
}

function postHasActionableComments(post) {
  return (post.comments_list || []).some((item) =>
    !item.is_ours && !item.ignored && !item.answered && !item.reply_sent_at);
}

const JOB_STATUS_LOOK = {
  running: "🟢 กำลังทำงาน", finishing: "🔵 กำลังตามเก็บให้ครบ",
  ready: "🟡 รอโพสต์", stopped: "⏸️ หยุดไว้", done: "✅ เสร็จครบทุกขั้น",
  manual_done: "☑️ จบงานด้วยมือแล้ว", failed: "🔴 ล้มเหลว",
  cancelled: "⚪ ยกเลิกแล้ว", waiting_caption: "✏️ รอแคปชัน",
  waiting_image: "🖼 รอรูป",
};
const JOB_SOURCE_LOOK = {telegram: "📨 จาก Telegram", web: "💻 จากหน้าเว็บ"};

function jobDate(value) {
  const parsed = new Date(String(value || ""));
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function jobClock(value) {
  const parsed = jobDate(value);
  if (!parsed) return "";
  const pad = (part) => String(part).padStart(2, "0");
  const time = `${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`;
  const now = new Date();
  return parsed.toDateString() === now.toDateString()
    ? time : `${pad(parsed.getDate())}/${pad(parsed.getMonth() + 1)} ${time}`;
}

function jobSpan(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  if (total < 60) return `${total} วินาที`;
  const mins = Math.floor(total / 60);
  if (mins < 60) return `${mins} นาที`;
  const hours = Math.floor(mins / 60);
  const rest = mins % 60;
  return rest ? `${hours} ชม. ${rest} นาที` : `${hours} ชม.`;
}

/** รายละเอียดใบงานต้นทาง — ใช้เฉพาะ metadata ของบัญชีที่ API กรองมาแล้ว. */
function jobDetail(post, posts) {
  const panel = el("section", "eg-job-detail");
  const account = String(post.job_account || post.account || "").trim();
  const status = JOB_STATUS_LOOK[post.job_status]
    || (post.job_status ? `• ${post.job_status}` : "• ไม่พบสถานะใบงาน");
  const source = JOB_SOURCE_LOOK[post.job_source]
    || (post.job_source ? `· ${post.job_source}` : "");

  const identity = el("div", "eg-job-identity");
  identity.append(el("strong", "eg-job-profile", `👤 โปรไฟล์ ${account || "ไม่ทราบบัญชี"}`));
  identity.append(el("span", "eg-job-state", `${status}${source ? ` · ${source}` : ""}`));
  panel.append(identity);

  const caption = String(post.caption || "").trim();
  if (caption) panel.append(el("p", "eg-job-caption", caption));

  const images = Number(post.images) || 0;
  const commentCount = Number(post.job_comment_count) || 0;
  const commentImages = Number(post.comment_images) || 0;
  const sourceGroups = Number(post.job_group_count) || 0;
  const shownGroups = new Set(posts.map(postGroupKey)).size;
  const groupCount = sourceGroups || shownGroups;

  const content = document.createElement("details");
  content.className = "eg-job-content";
  const bits = [];
  if (images) bits.push(`รูป ${images}`);
  if (caption) bits.push("แคปชัน");
  if (commentCount) bits.push(`คอมเมนต์ ${commentCount}`);
  if (commentImages) bits.push(`รูปในคอมเมนต์ ${commentImages}`);
  content.append(el("summary", "", bits.length
    ? `ดูเนื้อหาเต็ม — ${bits.join(" · ")}` : "ใบนี้ยังไม่มีเนื้อหา"));
  const contentBody = el("div", "eg-job-content-body");
  content.append(contentBody);
  let painted = false;
  content.addEventListener("toggle", () => {
    if (!content.open || painted) return;
    painted = true;
    const parts = [];
    if (images && post.job_id) {
      parts.push(el("strong", "eg-part", `รูปโพสต์ ${images} ใบ`));
      const strip = el("div", "eg-shots");
      for (let index = 0; index < images; index += 1) {
        const img = document.createElement("img");
        img.alt = `รูปโพสต์ใบที่ ${index + 1}`;
        img.src = `/api/fb/jobs/${encodeURIComponent(post.job_id)}/media/post/${index}`;
        img.title = "กดเพื่อเปิดรูปเต็ม";
        img.addEventListener("click", () => window.open(img.src, "_blank", "noreferrer"));
        strip.append(img);
      }
      parts.push(strip);
    }
    if (caption) parts.push(el("strong", "eg-part", "แคปชัน"),
      el("p", "eg-caption", caption));
    (post.job_comment_texts || []).forEach((text, index) => {
      const block = el("div", "eg-job-comment");
      block.append(el("strong", "", `คอมเมนต์ช่อง ${index + 1}`),
        el("p", "", String(text || "")));
      parts.push(block);
    });
    if (!parts.length) parts.push(el("p", "eg-empty", "ไม่พบเนื้อหาใบงานต้นทาง"));
    contentBody.replaceChildren(...parts);
  });
  panel.append(content);

  const meta = [`🖼 ${images} ใบ`, `💬 ${commentCount} คอมเมนต์`, `📦 ${groupCount} กลุ่ม`];
  panel.append(el("p", "eg-job-meta", meta.join(" · ")));

  const times = [];
  if (post.job_created_at) times.push(`สร้าง ${jobClock(post.job_created_at)}`);
  if (post.job_run_at) {
    const runAt = jobDate(post.job_run_at);
    const gap = runAt ? (runAt.getTime() - Date.now()) / 1000 : 0;
    times.push(gap > 0
      ? `⏰ นัดโพสต์ ${jobClock(post.job_run_at)} · อีก ${jobSpan(gap)}`
      : `⏰ นัดไว้ ${jobClock(post.job_run_at)} · ถึงเวลาแล้ว`);
  }
  if (post.job_started_at) {
    const start = jobDate(post.job_started_at);
    const end = jobDate(post.job_finished_at);
    const elapsed = start ? ((end || new Date()).getTime() - start.getTime()) / 1000 : 0;
    times.push(end
      ? `เริ่ม ${jobClock(post.job_started_at)} · จบ ${jobClock(post.job_finished_at)} · ใช้เวลา ${jobSpan(elapsed)}`
      : `เริ่ม ${jobClock(post.job_started_at)} · ทำมาแล้ว ${jobSpan(elapsed)}`);
  } else if (post.job_created_at) {
    const created = jobDate(post.job_created_at);
    if (created) times.push(`รอคิวมาแล้ว ${jobSpan((Date.now() - created.getTime()) / 1000)}`);
  }
  if (times.length) panel.append(el("p", "eg-job-times", times.join(" · ")));
  return panel;
}

function isPostActive(post) {
  return post.active !== false && Number(post.active) !== 0;
}

function groupActiveCount(posts) {
  const fromServer = Number(posts?.[0]?.group_active_posts);
  return Number.isFinite(fromServer)
    ? fromServer : (posts || []).filter(isPostActive).length;
}

/** เอาโพสต์ที่กดเลิกเก็บออกจากจอ โดยเก็บ snapshot/ประวัติไว้ฝั่งเซิร์ฟเวอร์. */
function removeStoppedPost(post, panel) {
  const same = (item) => {
    if (post.watch_key && item.watch_key) return item.watch_key === post.watch_key;
    return item.post_url === post.post_url;
  };
  data.posts = (data?.posts || []).filter((item) => !same(item));
  openPosts.delete(post.post_url);

  const group = panel.closest(".eg-group");
  const job = panel.closest(".eg-job");
  group?.querySelectorAll(".eg-post, .eg-tracked-row").forEach((row) => {
    if (row.dataset.postUrl === post.post_url) row.remove();
  });
  if (group && Number(group.dataset.activeCount) === 0) {
    openGroups.delete(group.dataset.groupKey || "");
    group.remove();
  } else {
    refreshGroupSummary(group);
  }
  if (job && !job.querySelector(".eg-job-body .eg-group")) {
    openJobs.delete(job.dataset.jobKey || "");
    job.remove();
  }
  paintHead();
  const wrap = box();
  if (wrap && !wrap.querySelector(".eg-job")) {
    wrap.replaceChildren(el("p", "eg-empty",
      "ไม่มีโพสต์ที่กำลังตามเก็บ — โพสต์ที่กดเลิกเก็บถูกนำออกจากหน้านี้แล้ว"));
  }
}

function replyRows() {
  return (data?.posts || []).flatMap((p) => (p.comments_list || []))
    .filter((c) => !c.is_ours && !c.ignored
      && (!c.reply_sent_at
        || (c.followup_queued_at && !c.followup_sent_at)
        || (c.followup_submitted_at && !c.followup_sent_at)
        || (c.followup_error && !c.followup_sent_at)));
}

function clock(seconds) {
  const whole = Math.max(0, Math.ceil(Number(seconds) || 0));
  const minutes = Math.floor(whole / 60);
  return `${String(minutes).padStart(2, "0")}:${String(whole % 60).padStart(2, "0")}`;
}

function longClock(seconds) {
  const whole = Math.max(0, Math.ceil(Number(seconds) || 0));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(whole % 60).padStart(2, "0")}`;
}

function manualCollectBusy() {
  return ["queued", "running"].includes(data?.collector_manual?.status);
}

function syncManualButtons() {
  document.querySelectorAll(".eg-manual").forEach((button) => {
    button.disabled = manualCollectBusy() || button.dataset.sending === "1";
  });
}

function manualFeedback(message, bad = false) {
  const box = $("#egManualFeedback");
  if (!box) return;
  box.hidden = !message;
  box.textContent = message || "";
  box.classList.toggle("is-bad", bad);
}

function collectScheduleText(value) {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("th-TH", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

function paintCollectSchedule() {
  const form = $("#egCollectSchedule");
  const clock = $("#egScheduleTime");
  const clear = $("#egScheduleClear");
  const status = $("#egScheduleStatus");
  if (!form || !clock || !clear || !status || !data) return;
  const account = data.account || gfAccount();
  if (form.dataset.account !== account) {
    form.dataset.account = account;
    delete form.dataset.dirty;
  }
  const schedule = data.collector_schedule || {};
  if (form.dataset.dirty !== "1") {
    if (schedule.time) clock.value = schedule.time;
    const chosen = form.querySelector(
      `input[name="egScheduleMode"][value="${schedule.mode || "once"}"]`,
    );
    if (chosen) chosen.checked = true;
  }
  clear.hidden = !schedule.enabled;
  status.classList.remove("is-bad");
  status.textContent = schedule.enabled
    ? `ตั้งไว้: ${schedule.mode === "daily" ? "เก็บทุกวัน" : "เก็บ 1 ครั้ง"}`
      + ` เวลา ${schedule.time} · รอบถัดไป ${collectScheduleText(schedule.next_at)}`
    : (schedule.last_run_at
      ? `รอบครั้งเดียวทำแล้ว ${collectScheduleText(schedule.last_run_at)} · ตั้งเวลาใหม่ได้`
      : "ยังไม่ได้ตั้งเวลา · ตารางนี้เก็บทุกโพสต์ที่ยังติดตามของบัญชีที่เลือก");
}

async function saveCollectSchedule(event) {
  event.preventDefault();
  const form = $("#egCollectSchedule");
  const clock = $("#egScheduleTime");
  const save = $("#egScheduleSave");
  const clear = $("#egScheduleClear");
  const status = $("#egScheduleStatus");
  if (!form || !clock || !save || !status || !data) return;
  const mode = form.querySelector('input[name="egScheduleMode"]:checked')?.value || "once";
  if (!clock.value) {
    status.textContent = "เลือกเวลาก่อนตั้งตาราง";
    status.classList.add("is-bad");
    return;
  }
  save.disabled = true;
  if (clear) clear.disabled = true;
  try {
    const out = await api("/api/fb/engage/schedule", {
      method: "POST",
      body: JSON.stringify({
        account: data.account || gfAccount(), time: clock.value, mode, action: "save",
      }),
    });
    data.collector_schedule = out.schedule || {};
    delete form.dataset.dirty;
    paintCollectSchedule();
  } catch (error) {
    status.textContent = `ตั้งเวลาไม่สำเร็จ — ${error.message}`;
    status.classList.add("is-bad");
  } finally {
    save.disabled = false;
    if (clear) clear.disabled = false;
  }
}

async function clearCollectSchedule() {
  const form = $("#egCollectSchedule");
  const save = $("#egScheduleSave");
  const clear = $("#egScheduleClear");
  const status = $("#egScheduleStatus");
  if (!form || !clear || !status || !data) return;
  clear.disabled = true;
  if (save) save.disabled = true;
  try {
    const out = await api("/api/fb/engage/schedule", {
      method: "POST",
      body: JSON.stringify({account: data.account || gfAccount(), action: "clear"}),
    });
    data.collector_schedule = out.schedule || {};
    delete form.dataset.dirty;
    paintCollectSchedule();
  } catch (error) {
    status.textContent = `ยกเลิกเวลาไม่สำเร็จ — ${error.message}`;
    status.classList.add("is-bad");
  } finally {
    clear.disabled = false;
    if (save) save.disabled = false;
  }
}

function massFeedback(message, bad = false) {
  const box = $("#egMassFeedback");
  if (!box) return;
  box.hidden = !message;
  box.textContent = message || "";
  box.classList.toggle("is-bad", bad);
}

function paintMassStatus() {
  const box = $("#egMassStatus");
  const start = $("#egMassStart");
  const open = $("#egMassOpen");
  if (!box || !data) return;
  const job = data.mass_report || {};
  const status = job.status || "idle";
  const busy = ["queued", "running"].includes(status);
  box.classList.toggle("is-active", status === "running");
  box.classList.toggle("is-waiting", status === "queued");
  box.replaceChildren();
  if (status === "queued") {
    box.append(el("b", "", "🟡 หาโพสต์แมสเข้าคิวแล้ว"),
      el("span", "eg-collector-detail", job.current_action || "รอ Bot8 เก็บคอมเมนต์ให้จบ"));
  } else if (status === "running") {
    box.append(el("b", "", `🟢 กำลังหาโพสต์แมส · ตรวจแล้ว ${Number(job.completed) || 0}/${Number(job.total) || 0} กลุ่ม`),
      el("span", "eg-collector-detail", `พบ ${Number(job.found) || 0} โพสต์ · ${job.current_action || "กำลังอ่าน Facebook"}`));
    if (job.current_group) box.append(el("span", "eg-collector-detail", `กลุ่ม: ${job.current_group}`));
  } else if (status === "complete") {
    box.append(el("b", "", `✅ หาโพสต์แมสเสร็จ · ${Number(job.found) || 0} โพสต์จาก ${Number(job.total) || 0} กลุ่ม`),
      el("span", "eg-collector-detail", "กลุ่มที่พบไม่ถึง 5 โพสต์จะแสดงจำนวนจริงในรายงาน"));
  } else if (status === "error") {
    box.append(el("b", "", "🔴 หาโพสต์แมสไม่สำเร็จ"),
      el("span", "eg-collector-detail", job.error || job.current_action || "ตรวจสาเหตุแล้วกดเริ่มใหม่ได้"));
  } else {
    box.append(el("b", "", "⚪ ยังไม่ได้สั่งหาโพสต์แมส"),
      el("span", "eg-collector-detail", "กดเริ่มตอนนี้หรือตั้งเวลา · งานจะรอคิวถ้า Bot8 เก็บคอมเมนต์อยู่"));
  }
  if (start) start.disabled = busy || start.dataset.sending === "1";
  if (open) {
    const report = data.mass_latest_report_url || job.report_url || "";
    open.hidden = !report.startsWith("/api/fb/mass-report/report/");
    if (!open.hidden) open.href = report;
    else open.removeAttribute("href");
  }
}

function paintMassSchedule() {
  const form = $("#egMassSchedule");
  const clock = $("#egMassTime");
  const clear = $("#egMassScheduleClear");
  const status = $("#egMassScheduleStatus");
  if (!form || !clock || !clear || !status || !data) return;
  const schedule = data.mass_schedule || {};
  if (form.dataset.dirty !== "1") {
    if (schedule.time) clock.value = schedule.time;
    const chosen = form.querySelector(`input[name="egMassMode"][value="${schedule.mode || "once"}"]`);
    if (chosen) chosen.checked = true;
  }
  clear.hidden = !schedule.enabled;
  status.classList.remove("is-bad");
  status.textContent = schedule.enabled
    ? `ตั้งไว้: ${schedule.mode === "daily" ? "ทุกวัน" : "1 ครั้ง"} เวลา ${schedule.time} · รอบถัดไป ${collectScheduleText(schedule.next_at)}`
    : (schedule.last_run_at
      ? `รอบครั้งเดียวเข้าคิวแล้ว ${collectScheduleText(schedule.last_run_at)} · ตั้งเวลาใหม่ได้`
      : "ยังไม่ได้ตั้งเวลา · ใช้คิว Bot8 เดียวกับงานเก็บคอมเมนต์");
}

async function startMassReport() {
  const button = $("#egMassStart");
  if (!button || !data || button.disabled) return;
  button.dataset.sending = "1";
  paintMassStatus();
  massFeedback("กำลังสั่ง Bot8 หาโพสต์แมส…");
  try {
    const out = await api("/api/fb/mass-report/start", {method: "POST"});
    data.mass_report = out.job || {};
    massFeedback(out.accepted
      ? `เข้าคิวแล้ว · จะตรวจ ${out.groups} กลุ่ม และรอ Bot8 เก็บคอมเมนต์ให้จบก่อน`
      : "มีงานหาโพสต์แมสรออยู่แล้ว ไม่สั่งซ้ำ");
  } catch (error) {
    massFeedback(`สั่งหาโพสต์แมสไม่สำเร็จ — ${error.message}`, true);
  } finally {
    delete button.dataset.sending;
    paintMassStatus();
  }
}

async function saveMassSchedule(event) {
  event.preventDefault();
  const form = $("#egMassSchedule");
  const clock = $("#egMassTime");
  const save = $("#egMassScheduleSave");
  const status = $("#egMassScheduleStatus");
  if (!form || !clock || !save || !status || !data) return;
  const mode = form.querySelector('input[name="egMassMode"]:checked')?.value || "once";
  if (!clock.value) {
    status.textContent = "เลือกเวลาก่อนตั้งตาราง";
    status.classList.add("is-bad");
    return;
  }
  save.disabled = true;
  try {
    const out = await api("/api/fb/mass-report/schedule", {
      method: "POST", body: JSON.stringify({time: clock.value, mode, action: "save"}),
    });
    data.mass_schedule = out.schedule || {};
    delete form.dataset.dirty;
    paintMassSchedule();
  } catch (error) {
    status.textContent = `ตั้งเวลาไม่สำเร็จ — ${error.message}`;
    status.classList.add("is-bad");
  } finally {
    save.disabled = false;
  }
}

async function clearMassSchedule() {
  const form = $("#egMassSchedule");
  const clear = $("#egMassScheduleClear");
  const status = $("#egMassScheduleStatus");
  if (!form || !clear || !status || !data) return;
  clear.disabled = true;
  try {
    const out = await api("/api/fb/mass-report/schedule", {
      method: "POST", body: JSON.stringify({action: "clear"}),
    });
    data.mass_schedule = out.schedule || {};
    delete form.dataset.dirty;
    paintMassSchedule();
  } catch (error) {
    status.textContent = `ยกเลิกเวลาไม่สำเร็จ — ${error.message}`;
    status.classList.add("is-bad");
  } finally {
    clear.disabled = false;
  }
}

async function collectManual(scope, values, button) {
  if (manualCollectBusy()) {
    manualFeedback("Bot8 มีรอบ Manual อยู่แล้ว — รอให้รอบนี้จบก่อน", true);
    return;
  }
  button.dataset.sending = "1";
  syncManualButtons();
  manualFeedback("กำลังส่งคำสั่งให้ Bot8…");
  try {
    const out = await api("/api/fb/engage/collect", {
      method: "POST",
      body: JSON.stringify({ scope, ...values }),
    });
    data.collector_manual = out.manual || {};
    manualFeedback("เข้าคิว Manual แล้ว — ดูกล่องสถานะ Bot8 ด้านบนได้ทันที");
    paintCollectorStatus();
  } catch (error) {
    manualFeedback(`สั่ง Bot8 ไม่สำเร็จ — ${error.message}`, true);
  } finally {
    delete button.dataset.sending;
    syncManualButtons();
  }
}

function paintCollectorStatus() {
  const box = $("#egCollector");
  if (!box || !data) return;
  const owner = data.collector_manual?.current_account || data.collector_cycle?.current_account;
  if (owner && owner !== data.account) {
    box.replaceChildren(el("span", "", "Bot8 กำลังใช้ร่วมกับบัญชีอื่น · บัญชีนี้รอคิวเก็บข้อมูล"));
    syncManualButtons();
    return;
  }
  const gate = data.collector_gate || {};
  if (gate.needs_login || gate.wait_seconds > 0) {
    box.replaceChildren(el("b", "", gate.needs_login
      ? "⛔ Bot8 ต้องล็อกอินใหม่ — หยุดเก็บไว้ ไม่วนลองอัตโนมัติ"
      : `⏳ Bot8 กำลังพัก · เหลือ ${longClock(gate.wait_seconds)} ก่อนใบงานถัดไป`));
    box.append(el("span", "eg-collector-detail", gate.needs_login
      ? "ล็อกอิน Bot8 ใน Pipeline Studio แล้วปิดหน้าต่าง จากนั้นกดเก็บใหม่เพื่อยืนยัน"
      : `${gate.note || "สุ่มพัก 1–5 นาทีหลังจบแต่ละใบงาน"} · คิวเดิมยังอยู่`));
    syncManualButtons();
    return;
  }
  const manual = data.collector_manual || {};
  if (["queued", "running"].includes(manual.status)) {
    const running = manual.status === "running";
    box.classList.toggle("is-active", running);
    box.classList.toggle("is-waiting", !running);
    box.replaceChildren();
    const progress = `ทำแล้ว ${Number(manual.completed) || 0}/${Number(manual.total) || 0}`
      + ` · เหลือ ${Number(manual.remaining) || 0}`;
    box.append(el("span", "eg-collector-top",
      `${running ? "🟢 Bot8 กำลังทำ Manual" : "🟡 Bot8 รอเริ่ม Manual"} · ${progress}`));
    box.append(el("span", "eg-collector-detail",
      `ขอบเขต: ${manual.label || manual.scope || "ที่สั่ง"} · งาน: ${manual.current_action || "รอคิว Chrome"}`));
    if (manual.current_group || manual.current_account) {
      box.append(el("span", "eg-collector-detail",
        `โปรไฟล์: ${manual.current_account || "ยังไม่ทราบ"} · กลุ่ม: ${manual.current_group || "ยังไม่ทราบ"}`));
    }
    const caption = String(manual.current_caption || "").trim().split(/\r?\n/)[0];
    if (manual.current_post_url || caption) {
      const line = el("span", "eg-collector-post",
        `โพสต์: ${caption ? (caption.length > 120 ? `${caption.slice(0, 120)}…` : caption) : "ลิงก์ที่เลือก"}`);
      if (manual.current_post_url) {
        const open = document.createElement("a");
        open.href = manual.current_post_url;
        open.target = "_blank";
        open.rel = "noreferrer";
        open.textContent = "🔗 เปิดโพสต์ที่กำลังเก็บ";
        line.append(document.createTextNode(" · "), open);
      }
      box.append(line);
    }
    syncManualButtons();
    return;
  }
  const cycle = data.collector_cycle || {};
  box.classList.toggle("is-active", Boolean(cycle.active && cycle.working));
  box.classList.toggle("is-waiting", Boolean(cycle.active && !cycle.working));
  box.replaceChildren();
  if (!cycle.active) {
    const last = manual.status === "complete"
      ? ` · Manual ล่าสุดเสร็จแล้ว: ${manual.label || "งานที่สั่ง"}`
      : (manual.status === "error" ? ` · Manual ล่าสุดมีปัญหา: ${manual.current_action || "ไม่ทราบสาเหตุ"}` : "");
    box.append(el("b", "", "⚪ Bot8 ว่างอยู่"),
      document.createTextNode(`${last} · จะตามเก็บอัตโนมัติทุก 6 ชั่วโมง`));
    syncManualButtons();
    return;
  }

  const headline = cycle.working ? "🟢 Bot8 กำลังทำงาน" : "🟡 Bot8 มีงานรอทำต่อ";
  const progress = `บัญชี ${data.account}`;
  const top = el("span", "eg-collector-top");
  top.append(el("b", "", headline), document.createTextNode(` · ${progress}`));
  box.append(top);

  const action = cycle.current_action || "กำลังเตรียมรอบ Bot8";
  const group = cycle.current_group || "ยังไม่ทราบกลุ่ม";
  const account = cycle.current_account || "ยังไม่ทราบโปรไฟล์";
  box.append(el("span", "eg-collector-detail",
    `งาน: ${action} · โปรไฟล์: ${account} · กลุ่ม: ${group}`));

  const caption = String(cycle.current_caption || "").trim().split(/\r?\n/)[0];
  const postLine = el("span", "eg-collector-post",
    caption ? `โพสต์: ${caption.length > 120 ? `${caption.slice(0, 120)}…` : caption}`
      : "โพสต์: กำลังอ่านจากลิงก์ที่บันทึกไว้");
  if (cycle.current_post_url) {
    const open = document.createElement("a");
    open.href = cycle.current_post_url;
    open.target = "_blank";
    open.rel = "noreferrer";
    open.textContent = "🔗 เปิดโพสต์ที่กำลังเก็บ";
    postLine.append(document.createTextNode(" · "), open);
  }
  box.append(postLine);
  syncManualButtons();
}

async function pollCollectorStatus() {
  const panel = $("#tab-groups");
  if (collectorBusy || document.hidden || panel?.hidden || !data) return;
  collectorBusy = true;
  const snapshot = data;
  try {
    const previousCycle = data.collector_cycle || {};
    const previousManual = data.collector_manual || {};
    const out = await api(`/api/fb/engage/status?account=${encodeURIComponent(data.account || "")}`);
    if (data !== snapshot || snapshot.account !== gfAccount()) return;
    data.collector_cycle = out.collector_cycle || {};
    data.collector_gate = out.collector_gate || {};
    data.collector_manual = out.collector_manual || {};
    data.collector_schedule = out.collector_schedule || {};
    data.mass_report = out.mass_report || {};
    data.mass_schedule = out.mass_schedule || {};
    data.mass_latest_report_url = out.mass_latest_report_url || "";
    data.reply_worker = out.reply_worker || {};
    if (out.work_priority) data.work_priority = out.work_priority;
    data.at = out.at || data.at;
    paintCollectorStatus();
    paintCollectSchedule();
    paintMassStatus();
    paintMassSchedule();
    paintReplyTimer();
    const cycleAdvanced = (
      data.collector_cycle.cycle_id
      && data.collector_cycle.cycle_id === previousCycle.cycle_id
      && Number(data.collector_cycle.completed) > Number(previousCycle.completed)
    );
    const cycleFinished = Boolean(previousCycle.active && !data.collector_cycle.active);
    const manualFinished = (
      ["queued", "running"].includes(previousManual.status)
      && data.collector_manual.status === "complete"
    );
    // ตัว polling เดิมวาดแค่สถานะ Bot8 จึงทำให้ฐานข้อมูลมีคอมเมนต์ใหม่แล้ว
    // แต่รายการบนจอยังค้าง snapshot เก่า. โหลดกระทู้ใหม่เมื่อมีโพสต์หนึ่งใบจบ
    // หรือ Manual จบ และรักษาข้อความที่เจ้าของกำลังพิมพ์ไว้ทุกช่อง.
    if (cycleAdvanced || cycleFinished || manualFinished) {
      await loadEngage({ preserveInputs: true });
      if (manualFinished) {
        manualFeedback("Bot8 เก็บเสร็จแล้ว — อัปเดตคอมเมนต์บนหน้าเว็บแล้ว");
      }
    }
  } catch {
    // สถานะสดพลาดหนึ่งรอบไม่ควรล้างข้อมูลเดิมหรือรบกวนช่องที่กำลังพิมพ์.
  } finally {
    collectorBusy = false;
  }
}

/** ตัวจับเวลาฝั่งจอใช้ deadline ของเครื่องที่เปิดเว็บ ไม่พึ่งนาฬิกามือถือ */
function syncReplyDeadline() {
  const seconds = Number(data?.reply_schedule?.wait_seconds) || 0;
  replyDeadline = data?.reply_schedule?.waiting && seconds > 0
    ? Date.now() + seconds * 1000 : 0;
  const dailySeconds = Number(data?.reply_daily?.wait_seconds) || 0;
  dailyDeadline = data?.reply_daily?.waiting && dailySeconds > 0
    ? Date.now() + dailySeconds * 1000 : 0;
  const prioritySeconds = Number(data?.work_priority?.wait_seconds) || 0;
  priorityDeadline = data?.work_priority?.blocked && prioritySeconds > 0
    ? Date.now() + prioritySeconds * 1000 : 0;
}

// เวลาบนแถบคิวต้องเป็นเพดานเผื่อ ไม่ใช่เวลาสวยเกินจริง: ระบบสุ่มพัก
// 10–15 นาทีต่อข้อความ จึงใช้ 15 นาทีเต็มกับทุกรายการที่ยังอยู่ในคิว.
// หนึ่งโพสต์อาจมีหลายคอมเมนต์และ comment 2; ทุกข้อความถูกนับแยก แต่จำนวน
// โพสต์ก็แสดงประกอบเพื่อให้เจ้าของตรวจได้ว่าคิวใหม่ถูกนำมารวมแล้วจริง.
const REPLY_ITEM_MAX_SECONDS = 15 * 60;

function etaClock(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (part) => String(part).padStart(2, "0");
  const time = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  const now = new Date();
  return date.toDateString() === now.toDateString()
    ? time : `${pad(date.getDate())}/${pad(date.getMonth() + 1)} ${time}`;
}

function replyQueueEta(rows, queuedCount) {
  const count = Math.max(0, Number(queuedCount) || 0);
  if (!count) return "";
  if (data?.reply_schedule?.reason === "safety_hold"
      && data.reply_schedule?.waiting) {
    return "ยังประเมินเวลาจบไม่ได้จนกว่า Facebook จะปลดข้อจำกัด";
  }
  const posts = new Set(rows.map((item) => String(item.post_url || "").trim())
    .filter(Boolean));
  const postCount = posts.size || count;
  const detail = `${count} ข้อความใน ${postCount} โพสต์ × สูงสุด 15 นาที/ข้อความ`;
  const waits = [replyDeadline, dailyDeadline, priorityDeadline]
    .filter(Boolean)
    .map((deadline) => Math.max(0, (deadline - Date.now()) / 1000));
  const currentWait = waits.length ? Math.max(...waits) : 0;
  // เพดานของรายการแรกคือค่าที่มากกว่าระหว่างเวลารอจริงกับ 15 นาที;
  // รายการที่เหลือเผื่อรายการละ 15 นาทีเต็ม. เมื่อคิวเพิ่ม count จะเปลี่ยนทันที.
  const seconds = Math.max(currentWait, REPLY_ITEM_MAX_SECONDS)
    + Math.max(0, count - 1) * REPLY_ITEM_MAX_SECONDS;
  if (data?.work_priority?.blocked && data.work_priority.reason === "post") {
    return `หลังงานโพสต์จบ คาดว่าใช้ต่อไม่เกิน ${longClock(seconds)} (${detail})`;
  }
  return `คาดว่าเสร็จไม่เกิน ${etaClock(Date.now() + seconds * 1000)} (${detail})`;
}

function paintDailyQuota() {
  const daily = $("#egDaily");
  if (!daily || !data?.reply_daily) return;
  const quota = data.reply_daily;
  const used = Number(quota.used) || 0;
  const limit = Number(quota.limit) || 50;
  const left = dailyDeadline ? Math.max(0, (dailyDeadline - Date.now()) / 1000) : 0;
  const account = quota.account || data.account || "โปรไฟล์นี้";
  daily.hidden = false;
  daily.classList.toggle("is-full", Boolean(quota.waiting));
  if (!quota.window_started_at) {
    daily.textContent = `💬 ${account} · รอบ 24 ชม. ${used}/${limit} · เริ่มนับเมื่อส่งคำตอบแรกสำเร็จ`;
  } else if (quota.waiting && left > 0) {
    const reset = String(quota.reset_at_text || "").replace("T", " ").slice(11, 19);
    daily.textContent = `🔒 ${account} ตอบครบ ${used}/${limit} · คิวที่เกินเพดานยังเก็บไว้ · รีเซ็ตใน ${longClock(left)}`
      + (reset ? ` (ประมาณ ${reset})` : "");
  } else {
    const reset = String(quota.reset_at_text || "").replace("T", " ").slice(11, 19);
    daily.textContent = `💬 ${account} · รอบ 24 ชม. ${used}/${limit} · เหลือ ${Math.max(0, limit - used)}`
      + (reset ? ` · รีเซ็ตประมาณ ${reset}` : "");
  }
}

/** ปุ่ม "เริ่มเลย" — ข้ามการเว้นระยะแล้วยิงคอมเมนต์แรกทันที
 *
 *  **เจ้าของสั่ง 20 ก.ย. 2569** *"เพิ่มปุ่ม เริ่มเลย เพื่อเริ่มคอมเมนต์แรกให้หน่อย"*
 *
 *  โผล่เฉพาะตอนที่ข้ามได้จริง — ถ้างานโพสต์ยังทำอยู่จะไม่ขึ้นปุ่ม เพราะ
 *  สองงานนี้แย่งจอมือถือกัน กดไปก็ยิงไม่ออก **ปุ่มที่กดแล้วไม่เกิดอะไร
 *  แย่กว่าไม่มีปุ่ม** เพราะคนจะกดซ้ำแล้วสงสัยว่าระบบค้าง
 *
 *  ข้ามโควตารายวันไม่ได้ ตรงนั้นเป็นเพดานกันบัญชีโดนตีธง ไม่ใช่แค่จังหวะรอ
 */
function startNowButton() {
  const button = el("button", "eg-start-now",
    startNowBusy ? "กำลังสั่ง…" : "▶ เริ่มเลย");
  button.type = "button";
  button.disabled = startNowBusy;
  button.title = "ข้ามเวลารอ แล้วส่งคอมเมนต์แรกในรอบตรวจถัดไป (ไม่เกิน 20 วินาที)";
  button.addEventListener("click", async () => {
    if (startNowBusy) return;
    startNowBusy = true;
    button.disabled = true;
    button.textContent = "กำลังสั่ง…";
    const account = data?.reply_schedule?.account || data?.account || "";
    try {
      const out = await api("/api/fb/engage/start-now", {
        method: "POST", body: JSON.stringify({ account }),
      });
      startNowBusy = false;
      if (account !== gfAccount()) return;
      // ดันเส้นตายให้หมดทันที ไม่ต้องรอรอบดึงถัดไป หน้าจอจะได้ไม่ค้างเลขเก่า
      priorityDeadline = 0;
      replyDeadline = 0;
      if (out.work_priority) data.work_priority = out.work_priority;
      if (out.reply_schedule) data.reply_schedule = out.reply_schedule;
      paintReplyTimer();
    } catch (error) {
      startNowBusy = false;
      // ข้อความไทยมาจากเซิร์ฟเวอร์ครบแล้ว แสดงตรงๆ
      if (account !== gfAccount()) return;
      const timer = $("#egTimer");
      if (timer) {
        timer.textContent = error.message;
        timer.classList.add("is-bad");
      }
      button.disabled = false;
      button.textContent = "▶ เริ่มเลย";
    }
  });
  return button;
}

/** ปลดพักจากข้อจำกัด Facebook แล้วให้คิวปกติลองใหม่หนึ่งรอบ.
 *
 * ไม่ใช้ endpoint เริ่มเลยตัวเดิม เพราะสถานะ safety hold เป็นด่านคนละชนิด:
 * เจ้าของต้องเห็นคำเตือนและยืนยันชัด ๆ ก่อน ระบบยังรักษาโควตา ล็อกมือถือ
 * และเครื่องหมายส่งแล้วแต่ยังยืนยันไม่ได้เหมือนเดิมทุกข้อ.
 */
function resumeAfterRestrictionButton() {
  const button = el("button", "eg-start-now",
    restrictionResumeBusy ? "กำลังปลดพัก…" : "▶ ลองรันต่อ");
  button.type = "button";
  button.disabled = restrictionResumeBusy;
  button.title = "ปลดช่วงพักของบัญชีนี้ แล้วให้ระบบลองเฉพาะคิวที่ยังไม่เคยส่ง";
  button.addEventListener("click", async () => {
    if (restrictionResumeBusy) return;
    const account = data?.reply_schedule?.account || data?.account || "";
    const confirmed = window.confirm(
      `ลองรันคิวตอบของ ${account || "บัญชีนี้"} ต่อหรือไม่?\n\n`
      + "ระบบจะไม่ส่งซ้ำรายการที่รอยืนยัน และจะพักใหม่เองถ้า Facebook ยังจำกัดอยู่"
    );
    if (!confirmed) return;
    restrictionResumeBusy = true;
    button.disabled = true;
    button.textContent = "กำลังปลดพัก…";
    try {
      const out = await api("/api/fb/engage/resume-after-restriction", {
        method: "POST", body: JSON.stringify({ account }),
      });
      restrictionResumeBusy = false;
      if (account !== gfAccount()) return;
      priorityDeadline = 0;
      replyDeadline = 0;
      if (out.work_priority) data.work_priority = out.work_priority;
      if (out.reply_schedule) data.reply_schedule = out.reply_schedule;
      paintReplyTimer();
    } catch (error) {
      restrictionResumeBusy = false;
      if (account !== gfAccount()) return;
      button.disabled = false;
      button.textContent = "▶ ลองรันต่อ";
      button.title = error.message;
      const summary = $("#egTimer .eg-timer-summary");
      if (summary) summary.textContent = `${summary.textContent} · ${error.message}`;
    }
  });
  return button;
}

function paintReplyTimer() {
  paintDailyQuota();
  paintReplyAlerts();
  const timer = $("#egTimer");
  if (!timer || !data) return;
  const render = (message, {bad = false, action = null, hidden = false} = {}) => {
    const worker = data.reply_worker || {};
    timer.hidden = hidden && !worker.active;
    timer.classList.toggle("is-bad", bad);
    timer.classList.toggle("is-working", Boolean(worker.active));
    timer.replaceChildren();
    if (worker.active) {
      const work = el("span", "eg-timer-work");
      const job = worker.job_id ? ` · ใบงาน ${worker.job_id}` : "";
      const group = worker.group_name ? ` · กลุ่ม ${worker.group_name}` : "";
      work.append(el("b", "", `🟢 กำลังตอบ ${worker.author || "คอมเมนต์"}${job}`),
        document.createTextNode(`${group} · ${worker.action || "กำลังทำงานบนมือถือ"}`));
      const open = replyPostLink(worker.post_url || "");
      if (open) work.append(document.createTextNode(" · "), open);
      timer.append(work);
    }
    const eta = replyQueueEta(queuedRows, queuedCount);
    const summary = message && eta ? `${message} · ${eta}` : message;
    if (summary) timer.append(el("span", "eg-timer-summary", summary));
    if (action) timer.append(action);
  };
  const rows = replyRows();
  const firstQueued = rows.filter((c) => c.reply_queued_at && !c.reply_sent_at && !c.reply_error);
  const followupQueued = rows.filter((c) => c.followup_queued_at && !c.followup_sent_at && !c.followup_error);
  const queuedRows = [...firstQueued, ...followupQueued];
  const queuedCount = firstQueued.length + followupQueued.length;
  const uncertainCount = rows.filter((c) => c.reply_submitted_at && !c.reply_sent_at).length
    + rows.filter((c) => c.followup_submitted_at && !c.followup_sent_at).length;
  const failedCount = rows.filter((c) => c.reply_error && !c.reply_submitted_at).length
    + rows.filter((c) => c.followup_error && !c.followup_submitted_at).length;
  if (data.reply_schedule?.reason === "safety_hold" && data.reply_schedule?.waiting) {
    render(`⛔ ${data.reply_schedule.note} · ระบบพักเพื่อความปลอดภัย ไม่ใช่เวลาที่ Facebook รับรองว่าจะปลด · คิวและคำตอบยังอยู่ · รอยืนยัน ${uncertainCount} รายการ ห้ามส่งซ้ำ`, {
      bad: true, action: resumeAfterRestrictionButton(),
    });
    return;
  }
  if (!queuedCount) {
    if (failedCount || uncertainCount) {
      render(`⚠️ ยังไม่สำเร็จ ${failedCount} · ส่งแล้วแต่ยังยืนยันไม่ได้ ${uncertainCount}${uncertainCount ? " (ตรวจผลเท่านั้น ห้ามส่งซ้ำ)" : ""} · กดทำต่อหรือตรวจผลได้จากรายการด้านล่าง`, {bad: true});
    } else {
      render("", {hidden: true});
    }
    return;
  }
  if (data.work_priority?.blocked) {
    if (data.work_priority.reason === "post") {
      render(`⏸ คิวตอบคอมเมนต์บนมือถือพักไว้ · ให้งานโพสต์ทำจนจบใบงานก่อน · คิว ${queuedCount} รายการไม่หาย · Bot8 บนคอมยังเก็บข้อมูลตามปกติ`);
    } else {
      const left = priorityDeadline
        ? Math.max(0, (priorityDeadline - Date.now()) / 1000) : 0;
      render(`⏳ งานโพสต์จบแล้ว · เว้นระยะอีก ${longClock(left)} ก่อนตอบคอมเมนต์บนมือถือ · คิว ${queuedCount} รายการ · ตัวเก็บข้อมูลบนคอมยังทำงานตามปกติ`, {action: startNowButton()});
    }
    return;
  }
  const dailyLeft = dailyDeadline ? Math.max(0, (dailyDeadline - Date.now()) / 1000) : 0;
  if (data.reply_daily?.waiting && dailyLeft > 0) {
    render(`⏳ คิว ${queuedCount} รายการกำลังรอโควตารอบใหม่ · เหลือ ${longClock(dailyLeft)}`);
    return;
  }
  const waitingFollowup = followupQueued
    .filter((c) => Number(c.followup_due_at) > Date.now() / 1000)
    .sort((a, b) => Number(a.followup_due_at) - Number(b.followup_due_at));
  const readyFollowup = followupQueued.length - waitingFollowup.length;
  if (!firstQueued.length && waitingFollowup.length && !readyFollowup) {
    const followupLeft = Number(waitingFollowup[0].followup_due_at) - Date.now() / 1000;
    render(`⏳ comment 2 กำลังสุ่มเว้นจาก comment แรก ${clock(followupLeft)} · คิว ${queuedCount} รายการ · ยังรักษาโควตาและคิวมือถือเดิม`);
    return;
  }
  if (!firstQueued.length && readyFollowup > 0) {
    render(`🎲 comment 2 ครบเวลาสุ่ม 1–5 นาทีแล้ว · รอคิวมือถือ ${readyFollowup} รายการในรอบตรวจถัดไป (ไม่เกิน 20 วินาที)`);
    return;
  }
  const left = replyDeadline ? Math.max(0, (replyDeadline - Date.now()) / 1000) : 0;
  const account = data.reply_schedule?.account || data.account || "โปรไฟล์นี้";
  if (left > 0) {
    const next = String(data.reply_schedule?.next_at_text || "").replace("T", " ").slice(11, 19);
    const message = `⏳ ${account} กำลังพัก ${clock(left)} · คิว ${queuedCount} รายการ`
      + (next ? ` · เริ่มได้ประมาณ ${next}` : "")
      + ` · ${data.reply_schedule?.reason === "hourly_quota"
        ? data.reply_schedule.note : "สุ่มพัก 10–15 นาที"}`;
    // พักเพราะโควตารายชั่วโมงข้ามไม่ได้ — ขึ้นปุ่มเฉพาะตอนพักแบบสุ่มปกติ
    render(message, {action: data.reply_schedule?.reason !== "hourly_quota"
      ? startNowButton() : null});
  } else {
    render(`🎲 ${account} ครบเวลาพักแล้ว · รอสุ่มคิว ${queuedCount} รายการในรอบตรวจถัดไป (ไม่เกิน 20 วินาที)`);
  }
}

function box() {
  return $("#egList");
}

/** ย่อลิงก์ให้พออ่านออกว่าเป็นโพสต์ไหน โดยไม่กินทั้งบรรทัด */
function shortLink(url) {
  return String(url || "").replace(/^https?:\/\/(www\.)?facebook\.com\//, "");
}

function hasFollowupState(item) {
  return Boolean(item.followup_draft || item.followup_queued_at
    || item.followup_submitted_at || item.followup_sent_at || item.followup_error);
}

function followupReply(item) {
  const shell = el("div", "eg-followup");
  const toggle = el("button", "eg-add-comment", "+ เพิ่ม comment");
  toggle.type = "button";
  toggle.title = "เพิ่ม comment 2 ใต้คอมเมนต์เดิม โดยสุ่มเว้นจาก comment แรก 1–5 นาที";
  const hasState = hasFollowupState(item);
  const buildEditor = () => {
    const editor = el("div", "eg-followup-editor");
    const field = document.createElement("textarea");
    field.className = "eg-input";
    field.rows = 2;
    field.placeholder = `comment 2 ต่อจากคำตอบของ ${item.author || "คนนี้"}…`;
    field.value = item.followup_draft || "";
    const send = el("button", "eg-send", "↩ เข้าคิว comment 2");
    send.type = "button";
    const note = el("span", "eg-note");

    if (item.followup_sent_at) {
      note.textContent = `comment 2 ขึ้น Facebook แล้ว ${item.followup_sent_at}`;
      note.classList.add("is-sent");
      field.disabled = true;
      send.disabled = true;
    } else if (item.followup_submitted_at) {
      note.textContent = `comment 2 ส่งแล้วแต่ยังยืนยันไม่ได้ ${item.followup_submitted_at} · ตรวจผลเท่านั้น ห้ามส่งซ้ำ`;
      note.classList.add("is-bad");
      field.disabled = true;
      send.disabled = true;
    } else if (item.followup_error) {
      note.textContent = `comment 2 ยังไม่สำเร็จ · ${item.followup_error}`;
      note.classList.add("is-bad");
      send.textContent = "↩ สั่ง comment 2 ใหม่";
    } else if (item.followup_queued_at) {
      const due = Number(item.followup_due_at) > 0
        ? new Date(Number(item.followup_due_at) * 1000).toLocaleTimeString("th-TH") : "หลัง comment แรกยืนยัน";
      note.textContent = `comment 2 เข้าคิวแล้ว · สุ่มเว้น 1–5 นาที · เริ่มได้ ${due}`;
      field.disabled = true;
      send.disabled = true;
      send.textContent = "✓ comment 2 เข้าคิวแล้ว";
    }

    send.addEventListener("click", async () => {
      if (!field.value.trim()) {
        note.textContent = "ยังไม่ได้พิมพ์ comment 2";
        note.classList.add("is-bad");
        field.focus();
        return;
      }
      send.disabled = true;
      field.disabled = true;
      send.textContent = "กำลังเข้าคิว…";
      try {
        const out = await api("/api/fb/engage/followup", {
          method: "POST",
          body: JSON.stringify({comment_key: item.comment_key, text: field.value}),
        });
        Object.assign(item, {
          followup_draft: out.followup_draft,
          followup_queued_at: out.followup_queued_at,
          followup_due_at: out.followup_due_at,
          followup_delay_seconds: out.followup_delay_seconds,
          followup_error: "",
        });
        if (out.reply_daily) data.reply_daily = out.reply_daily;
        note.classList.remove("is-bad");
        note.textContent = out.message || "comment 2 เข้าคิวแล้ว · สุ่มเว้น 1–5 นาที";
        send.textContent = "✓ comment 2 เข้าคิวแล้ว";
        field.disabled = true;
        send.disabled = true;
        paintHead();
      } catch (error) {
        note.textContent = `ไม่สำเร็จ — ${error.message}`;
        note.classList.add("is-bad");
        send.textContent = "↩ เข้าคิว comment 2";
        field.disabled = false;
        send.disabled = false;
      }
    });

    const foot = el("div", "eg-reply-foot");
    foot.append(send, note);
    editor.append(field, foot);
    return editor;
  };

  if (hasState) {
    shell.append(buildEditor());
  } else {
    toggle.addEventListener("click", () => {
      toggle.replaceWith(buildEditor());
      shell.querySelector("textarea")?.focus();
    });
    shell.append(toggle);
  }
  return shell;
}

function commentRow(item) {
  const row = el("div", "eg-comment" + (item.is_ours ? " is-ours" : ""));
  if (item.comment_key) row.dataset.commentKey = item.comment_key;

  const head = el("div", "eg-c-head");
  head.append(el("b", "eg-c-who", item.is_ours ? "เรา" : (item.author || "(ไม่รู้ชื่อ)")));
  if (item.when_text) head.append(el("span", "eg-c-when", item.when_text));
  if (item.reply_to) head.append(el("span", "eg-c-to", `↩ ตอบ ${item.reply_to}`));
  if (item.answered) head.append(el("span", "eg-tag eg-done", "ตอบแล้ว"));
  row.append(head, el("p", "eg-c-body", item.body || ""));

  // คอมเมนต์ของเราเองไม่ต้องตอบ และรายการที่ตอบแล้วถือว่าจบทันที.
  // ยกเว้น comment 2 ที่ผู้ใช้ตั้งคิวไว้ก่อนหน้า: ต้องคงสถานะให้เห็นและทำต่อ
  // เพราะการซ่อนทิ้งจะทำให้คำสั่งที่รับไปแล้วดูเหมือนหาย.
  if (item.is_ours) return row;
  if (item.answered || item.reply_sent_at) {
    if (hasFollowupState(item)) row.append(followupReply(item));
    return row;
  }

  const wrap = el("div", "eg-reply");
  const field = document.createElement("textarea");
  field.className = "eg-input";
  field.rows = 2;
  field.placeholder = `ตอบ ${item.author || "คนนี้"}…`;
  field.value = item.reply_draft || "";

  /* **สองปุ่ม เจ้าของสั่ง 15 ก.ย. 2569**
   *   ตอบกลับ  = สั่งให้บอทไปพิมพ์ตอบตามที่พิมพ์ไว้
   *   เพิกเฉย  = ไม่ทำอะไรกับคอมเมนต์นี้ และไม่ต้องเอามาโชว์อีก
   *
   * ของเดิมมีปุ่มเดียวคือ "เก็บคำตอบ" ซึ่งไม่ได้บอกว่าจะเกิดอะไรต่อ —
   * พิมพ์แล้วเก็บไว้เฉยๆ แล้วก็ค้างอยู่อย่างนั้น ไม่มีทางบอกระบบว่า
   * "อันนี้ไม่ตอบ" ได้เลย คอมเมนต์ที่ไม่มีวันตอบจึงค้างอยู่ตลอดกาล
   */
  const send = el("button", "eg-send", "↩ ตอบกลับ");
  send.type = "button";
  send.title = "สั่งให้บอทไปพิมพ์ตอบคอมเมนต์นี้ตามข้อความที่พิมพ์ไว้";
  const skip = el("button", "eg-skip", "🚫 เพิกเฉย");
  skip.type = "button";
  skip.title = "ไม่ตอบคอมเมนต์นี้ และไม่ต้องเอามาโชว์อีก";
  const note = el("span", "eg-note");

  const lock = (on) => { send.disabled = on; skip.disabled = on; field.disabled = on || Boolean(item.reply_submitted_at); };

  if (item.reply_sent_at) {
    note.textContent = `ส่งขึ้น Facebook แล้ว ${item.reply_sent_at}`;
    note.classList.add("is-sent");
    lock(true);
  } else if (item.reply_submitted_at) {
    note.textContent = `${item.author} · ส่งแล้วแต่ยังยืนยันไม่ได้ · ${item.reply_submitted_at} · ตรวจผลเท่านั้น ไม่ส่งซ้ำ`;
    note.classList.add("is-bad");
    send.textContent = "🔎 ตรวจผล";
    field.disabled = true;
  } else if (item.reply_error) {
    note.textContent = `${item.author} · ${item.reply_attempted_at || ""} · ${item.reply_error} · ตรวจแล้วกดสั่งใหม่ได้`;
    note.classList.add("is-bad");
    send.textContent = "↩ สั่งใหม่";
  } else if (item.reply_queued_at) {
    // **สั่งแล้ว ≠ ขึ้นแล้ว** ต้องเขียนให้ชัด ไม่งั้นนึกว่าตอบไปเรียบร้อย
    note.textContent = data?.reply_daily?.waiting
      ? `เข้าคิวแล้ว ${item.reply_queued_at} · รอเพดาน 50 รายการรีเซ็ต คิวไม่หาย`
      : `เข้าคิวแล้ว ${item.reply_queued_at} · สุ่มตอบแยกโปรไฟล์ เว้น 10–15 นาที`;
    send.textContent = "↩ สั่งใหม่";
  } else if (item.reply_draft) {
    note.textContent = `พิมพ์เก็บไว้ ${item.reply_saved_at} · ยังไม่ได้สั่งตอบ`;
  }

  /** ยิงคำสั่งหนึ่งครั้ง — ล็อกปุ่มไว้ระหว่างรอ แล้วบอกผลตรงๆ ไม่ว่าสำเร็จหรือไม่ */
  const fire = async (button, busyText, url, body, done) => {
    const was = button.textContent;
    lock(true);
    button.textContent = busyText;
    try {
      const out = await api(url, { method: "POST", body: JSON.stringify(body) });
      note.classList.remove("is-bad");
      done(out);
    } catch (error) {
      // **ห้ามทำเหมือนสำเร็จ** ไม่งั้นคำสั่งหายโดยไม่มีใครรู้
      note.textContent = `ไม่สำเร็จ — ${error.message}`;
      note.classList.add("is-bad");
      button.textContent = was;
      lock(false);
    }
  };

  send.addEventListener("click", () => {
    if (!field.value.trim()) {
      note.textContent = "ยังไม่ได้พิมพ์คำตอบ — พิมพ์ก่อนแล้วค่อยกดตอบกลับ";
      note.classList.add("is-bad");
      field.focus();
      return;
    }
    fire(send, "กำลังสั่ง…", "/api/fb/engage/send",
      { comment_key: item.comment_key, text: field.value }, (out) => {
        item.reply_draft = out.reply_draft;
        item.reply_queued_at = out.reply_queued_at;
        item.reply_error = "";
        if (out.reply_daily) {
          data.reply_daily = out.reply_daily;
          syncReplyDeadline();
        }
        note.textContent = out.reply_daily?.waiting
          ? "เข้าคิวแล้ว · ครบเพดาน 50 รายการ คิวนี้จะรอรอบ 24 ชั่วโมงรีเซ็ต"
          : "เข้าคิวแล้ว · สุ่มตอบแยกโปรไฟล์ เว้น 10–15 นาที";
        send.textContent = "↩ สั่งใหม่";
        lock(false);
        paintHead();
      });
  });

  skip.addEventListener("click", () => {
    fire(skip, "กำลังซ่อน…", "/api/fb/engage/ignore",
      { comment_key: item.comment_key, on: true }, () => {
        // หายไปจากจอทันที ไม่ต้องรอโหลดใหม่ — กดแล้วต้องเห็นผลเดี๋ยวนั้น
        item.ignored = 1;
        const card = row.closest(".eg-post");
        row.remove();
        if (card && !card.querySelector(".eg-comment")) {
          card.querySelector(".eg-comments")?.append(
            el("p", "eg-empty", "เพิกเฉยครบทุกคอมเมนต์ในโพสต์นี้แล้ว"));
        }
        paintHead();
      });
  });

  const foot = el("div", "eg-reply-foot");
  foot.append(send, skip, note);
  wrap.append(field, foot);
  row.append(wrap, followupReply(item));
  return row;
}

/** เนื้อหาโพสต์ — รูป · แคปชัน · คอมเมนต์ของเราเอง
 *
 * **เจ้าของสั่ง 15 ก.ย. 2569** — *"หน้าที่โชว์คอมเมนต์ ให้โชว์รูป กับแคปชันด้วย
 * ทั้งหมดรวมคอมเมนต์ของผมให้ทำเป็น drop down คลิ้กแล้วค่อยโชว์"*
 *
 * คอมเมนต์ของเราเอง (ลิงก์สินค้า) ยาวและซ้ำทุกโพสต์ กินที่จนคอมเมนต์ของคนอื่น
 * ซึ่งเป็นตัวที่ต้องตอบ ถูกดันตกลงไปข้างล่าง — ยุบเข้ากล่องแล้วสิ่งที่ต้องทำ
 * จะอยู่บนสุดเสมอ ปัจจุบันตัวการ์ดโพสต์เป็น dropdown อยู่แล้ว จึงไม่ซ้อน
 * dropdown อีกชั้น: กดชื่อโพสต์ครั้งเดียวต้องเห็นทั้งรายละเอียดและคอมเมนต์.
 */
function postContent(post) {
  const ours = (post.comments_list || []).filter((c) => c.is_ours);
  const shots = Number(post.images) || 0;
  const caption = (post.caption || "").trim();
  if (!shots && !caption && !ours.length) return null;

  const body = el("div", "eg-content");
  if (shots && post.job_id) {
    const strip = el("div", "eg-shots");
    for (let i = 0; i < shots; i += 1) {
      const img = document.createElement("img");
      // **ห้ามใส่ loading="lazy"** เคยใส่แล้วรูปไม่โหลดเลยสักใบ เพราะรูปอยู่ใน
      // กล่องที่ปิดอยู่ เบราว์เซอร์จึงถือว่ายังไม่ต้องโหลด แล้วไม่โหลดอีกเลย
      img.alt = `รูปโพสต์ใบที่ ${i + 1}`;
      img.src = `/api/fb/jobs/${encodeURIComponent(post.job_id)}/media/post/${i}`;
      img.title = "กดเพื่อเปิดรูปเต็ม";
      img.addEventListener("click", () => window.open(img.src, "_blank", "noreferrer"));
      strip.append(img);
    }
    body.append(el("small", "eg-part", "รูปที่โพสต์"), strip);
  } else if (shots) {
    body.append(el("small", "eg-part", `มีรูป ${shots} ใบ แต่ใบงานถูกลบไปแล้ว — เปิดดูไม่ได้`));
  }
  if (caption) {
    body.append(el("small", "eg-part", "แคปชัน"), el("p", "eg-caption", caption));
  }
  if (ours.length) {
    body.append(el("small", "eg-part", `คอมเมนต์ของเราเอง ${ours.length} อัน`));
    ours.forEach((c) => body.append(commentRow(c)));
  }
  return body;
}

/** คุมการตามเก็บรายโพสต์ — หยุดเฉพาะ Bot8 ไม่ลบลิงก์หรือประวัติเดิม */
function watchPanel(post) {
  const panel = el("div", "eg-watch");

  const render = () => {
    const active = post.active !== false && Number(post.active) !== 0;
    panel.classList.toggle("is-stopped", !active);
    panel.classList.toggle("is-suggested", active && Boolean(post.suggest_stop));

    const note = el("span", "eg-watch-note");
    if (!active) {
      note.textContent = `⏹ หยุดตามเก็บแล้ว${post.stopped_at ? ` · ${String(post.stopped_at).replace("T", " ").slice(5, 16)}` : ""}`;
    } else if (post.suggest_stop) {
      note.textContent = `💤 Bot8 แนะนำให้เลิกเก็บ — ${post.suggest_reason || "engagement เปลี่ยนแปลงน้อยใน 24 ชั่วโมง"}`;
    } else if (post.keep_until) {
      note.textContent = `▶ เก็บต่ออยู่ · ประเมินใหม่หลัง ${String(post.keep_until).replace("T", " ").slice(5, 16)}`;
    } else {
      note.textContent = "Bot8 ตามเก็บทุก 6 ชั่วโมง";
    }

    const stop = el("button", "eg-watch-stop", "🛑 เลิกเก็บ");
    const keep = el("button", "eg-watch-keep", active ? "▶ เก็บต่อ" : "▶ กลับมาเก็บต่อ");
    stop.type = keep.type = "button";
    stop.title = "หยุดเปิดลิงก์นี้ในรอบ Bot8 ถัดไป แต่ไม่ลบประวัติเดิม";
    keep.title = "เก็บโพสต์นี้ต่อ และประเมิน engagement ใหม่หลังครบ 24 ชั่วโมง";
    stop.hidden = !active;
    keep.hidden = active && !post.suggest_stop;

    const decide = async (action) => {
      stop.disabled = keep.disabled = true;
      try {
        const wasActive = isPostActive(post);
        const out = await api("/api/fb/engage/watch", {
          method: "POST",
          body: JSON.stringify({
            post_url: post.post_url,
            watch_key: post.watch_key,
            account: post.account || "",
            action,
          }),
        });
        Object.assign(post, out);
        const nowActive = isPostActive(post);
        if (wasActive !== nowActive) {
          const key = postGroupKey(post);
          const siblings = (data?.posts || []).filter((item) => postGroupKey(item) === key);
          const group = panel.closest(".eg-group");
          const before = Number(group?.dataset.activeCount ?? groupActiveCount(siblings));
          const after = Math.max(0, before + (nowActive ? 1 : -1));
          siblings.forEach((item) => { item.group_active_posts = after; });
          if (group) group.dataset.activeCount = String(after);
        }
        if (action === "stop" && !nowActive) {
          removeStoppedPost(post, panel);
          return;
        }
        render();
        const card = panel.closest(".eg-post");
        if (card) card.dataset.active = nowActive ? "1" : "0";
        refreshGroupSummary(panel.closest(".eg-group"));
      } catch (error) {
        note.textContent = `เปลี่ยนการตามเก็บไม่สำเร็จ — ${error.message}`;
        note.classList.add("is-bad");
        stop.disabled = keep.disabled = false;
      }
    };
    stop.addEventListener("click", () => decide("stop"));
    keep.addEventListener("click", () => decide("keep"));
    panel.replaceChildren(note, stop, keep);
    const head = panel.closest(".eg-post")?.querySelector(".eg-p-head");
    if (head) {
      const oldBadge = head.querySelector(".eg-stopped");
      if (!active && !oldBadge) head.append(el("span", "eg-tag eg-stopped", "หยุดเก็บแล้ว"));
      if (active && oldBadge) oldBadge.remove();
    }
  };
  render();
  return panel;
}

function postCard(post) {
  const card = document.createElement("details");
  card.className = "eg-post";
  card.dataset.postUrl = post.post_url || "";
  card.dataset.active = isPostActive(post) ? "1" : "0";
  // รายการที่ต้องตอบเปิดรายละเอียดไว้ตรงกลุ่มทันที ไม่ต้องกดแล้วเลื่อนลงไปหา.
  card.open = openPosts.has(post.post_url) || postHasActionableComments(post);
  card.addEventListener("toggle", () => {
    if (card.open) openPosts.add(post.post_url);
    else openPosts.delete(post.post_url);
  });

  const summary = document.createElement("summary");
  summary.className = "eg-p-summary";
  const head = el("div", "eg-p-head");
  const checked = post.checked_at
    ? String(post.checked_at).replace("T", " ").slice(5, 16) : "ไม่ทราบเวลา";
  const caption = String(post.caption || "").trim().split(/\r?\n/)[0];
  const label = caption
    ? (caption.length > 72 ? `${caption.slice(0, 72)}…` : caption)
    : shortLink(post.post_url);
  head.append(el("b", "eg-p-title", `โพสต์ ${checked} — ${label || "ไม่ทราบโพสต์"}`));
  if (post.pending) head.append(el("span", "eg-tag eg-wait", `ค้าง ${post.pending}`));
  if (post.drafted) head.append(el("span", "eg-tag eg-draft", `พิมพ์ไว้ ${post.drafted}`));
  if (post.active === false || Number(post.active) === 0) {
    head.append(el("span", "eg-tag eg-stopped", "หยุดเก็บแล้ว"));
  }
  const collect = el("button", "eg-manual eg-manual-post", "▶ เก็บโพสต์นี้ใหม่");
  collect.type = "button";
  collect.title = "สั่ง Chrome Bot8 อ่านคอมเมนต์ของโพสต์นี้ใหม่";
  collect.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    collectManual("post", {
      account: post.account || "",
      post_url: post.post_url || "",
    }, collect);
  });
  head.append(collect);
  const open = document.createElement("a");
  open.className = "eg-p-link";
  open.href = post.post_url;
  open.target = "_blank";
  open.rel = "noreferrer";
  open.textContent = "🔗 เปิดโพสต์";
  open.title = shortLink(post.post_url);
  open.addEventListener("click", (event) => event.stopPropagation());
  head.append(open);
  summary.append(head);
  card.append(summary);

  const body = el("div", "eg-post-body");

  const stat = [];
  if (post.reactions !== null) stat.push(`👍 ${post.reactions}`);
  if (post.comments !== null) stat.push(`💬 ${post.comments}`);
  if (post.shares !== null) stat.push(`↗ ${post.shares}`);
  if (post.checked_at) stat.push(`อ่านล่าสุด ${String(post.checked_at).replace("T", " ").slice(5, 16)}`);
  body.append(el("p", "eg-p-stat", stat.join(" · ")));
  if (post.note) body.append(el("p", "eg-note is-bad", post.note));
  body.append(watchPanel(post));

  const content = postContent(post);
  if (content) body.append(content);

  // โหมดค้างตอบต้องไม่เอาคอมเมนต์ที่หน้า Facebook ยืนยันว่าโปรไฟล์นี้ตอบแล้ว
  // กลับมาโชว์อีก; โหมด "ดูทุกโพสต์" ยังเก็บไว้ดูเป็นประวัติได้
  const others = (post.comments_list || []).filter((c) =>
    !c.is_ours && (!onlyPending || !c.answered));
  const list = el("div", "eg-comments");
  others.forEach((item) => list.append(commentRow(item)));
  if (!others.length) {
    list.append(el("p", "eg-empty", "ยังไม่มีคอมเมนต์จากคนอื่นในโพสต์นี้"));
  }
  body.append(list);
  card.append(body);
  return card;
}

function refreshGroupSummary(group) {
  if (!group) return;
  const key = group.dataset.groupKey || "";
  const posts = (data?.posts || []).filter((post) => postGroupKey(post) === key);
  const active = Number(group.dataset.activeCount ?? groupActiveCount(posts));
  const shown = group.querySelectorAll(":scope > .eg-group-body > .eg-post").length;
  const pending = posts.reduce((sum, post) => sum + (Number(post.pending) || 0), 0);
  const activeBadge = group.querySelector(".eg-g-active");
  const shownBadge = group.querySelector(".eg-g-shown");
  const pendingBadge = group.querySelector(".eg-g-pending");
  if (activeBadge) activeBadge.textContent = `กำลังตามเก็บ ${active} โพสต์`;
  if (shownBadge) shownBadge.textContent = `แสดง ${shown} โพสต์`;
  if (pendingBadge) {
    pendingBadge.textContent = `ค้าง ${pending}`;
    pendingBadge.hidden = pending < 1;
  }
}

function groupCard(posts) {
  const first = posts[0] || {};
  const key = postGroupKey(first);
  const group = document.createElement("details");
  group.className = "eg-group";
  group.dataset.groupKey = key;
  group.dataset.activeCount = String(groupActiveCount(posts));
  group.open = openGroups.has(key) || posts.some(postHasActionableComments);
  group.addEventListener("toggle", () => {
    if (group.open) openGroups.add(key);
    else openGroups.delete(key);
  });

  const summary = document.createElement("summary");
  summary.className = "eg-g-summary";
  const head = el("div", "eg-g-head");
  head.append(el("b", "eg-g-name", first.group_name || "(ไม่รู้ชื่อกลุ่ม)"));
  const trackedButton = el("button", "eg-tag eg-g-active",
    `กำลังตามเก็บ ${groupActiveCount(posts)} โพสต์`);
  trackedButton.type = "button";
  trackedButton.title = "กดดูทุกโพสต์ที่ตามเก็บ พร้อมลิงก์และปุ่มเลิกเก็บ";
  trackedButton.setAttribute("aria-expanded", "false");
  const tracked = el("div", "eg-tracked-list");
  tracked.hidden = true;
  trackedButton.addEventListener("click", async (event) => {
    event.preventDefault();
    event.stopPropagation();
    tracked.hidden = !tracked.hidden;
    if (tracked.hidden) openTracked.delete(key);
    else openTracked.add(key);
    trackedButton.setAttribute("aria-expanded", String(!tracked.hidden));
    if (tracked.hidden) return;
    group.open = true;
    trackedButton.disabled = true;
    tracked.replaceChildren(el("p", "eg-empty", "กำลังโหลดรายการโพสต์…"));
    try {
      const query = new URLSearchParams({account: first.account || "",
        job_id: first.job_id || "__unlinked__", group_id: first.group_id || "",
        group_name: first.group_name || ""});
      const out = await api(`/api/fb/engage/tracked?${query}`);
      if (!group.isConnected) return;
      const activePosts = (out.posts || []).filter(isPostActive);
      group.dataset.activeCount = String(activePosts.length);
      posts.forEach((post) => { post.group_active_posts = activePosts.length; });
      tracked.replaceChildren(el("p", "eg-empty",
        "ทุกโพสต์ที่ตามเก็บในกลุ่มนี้ รวมโพสต์ที่ไม่มีคอมเมนต์ค้าง · เลิกเก็บไม่ลบโพสต์บน Facebook"));
      activePosts.forEach((post) => {
        const row = el("div", "eg-tracked-row");
        row.dataset.postUrl = post.post_url;
        const link = el("a", "eg-tracked-link",
          `🔗 เปิดโพสต์ — ${String(post.caption || "").trim() || shortLink(post.post_url)}`);
        // Stored links must never become script/data navigation targets.
        try {
          const url = new URL(post.post_url);
          if (["https:", "http:"].includes(url.protocol)) link.href = url.href;
        } catch (_) { /* leave invalid links inert */ }
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        row.append(link, el("small", "eg-p-stat", `อ่านล่าสุด ${post.checked_at || "—"}`),
          watchPanel(post));
        tracked.append(row);
      });
      if (!activePosts.length) tracked.append(el("p", "eg-empty", "ไม่มีโพสต์ที่กำลังตามเก็บแล้ว"));
      refreshGroupSummary(group);
    } catch (error) {
      tracked.replaceChildren(el("p", "eg-note is-bad", `โหลดรายการไม่สำเร็จ — ${error.message} · กดปิดแล้วเปิดเพื่อลองใหม่`));
    } finally {
      trackedButton.disabled = false;
    }
  });
  head.append(trackedButton);
  head.append(el("span", "eg-tag eg-g-shown", `แสดง ${posts.length} โพสต์`));
  const pending = posts.reduce((sum, post) => sum + (Number(post.pending) || 0), 0);
  const pendingBadge = el("span", "eg-tag eg-wait eg-g-pending", `ค้าง ${pending}`);
  pendingBadge.hidden = pending < 1;
  head.append(pendingBadge);
  const collect = el("button", "eg-manual eg-manual-group", "▶ เก็บกลุ่มนี้ใหม่");
  collect.type = "button";
  collect.title = "สั่ง Chrome Bot8 อ่านทุกโพสต์ที่ยังตามเก็บในกลุ่มนี้ใหม่";
  collect.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    collectManual("group", {
      account: first.account || "",
      job_id: first.job_id || "__unlinked__",
      group_id: first.group_id || "",
      group_name: first.group_name || "",
    }, collect);
  });
  head.append(collect);
  summary.append(head);

  const body = el("div", "eg-group-body");
  posts.forEach((post) => body.append(postCard(post)));
  group.append(summary, tracked, body);
  if (openTracked.has(key)) queueMicrotask(() => {
    if (group.isConnected) trackedButton.click();
  });
  return group;
}

/** ชั้นบนสุดของหน้าติดตาม: ใบงาน → กลุ่ม → โพสต์ → คอมเมนต์. */
function jobCard(posts) {
  const first = posts[0] || {};
  const key = postJobKey(first);
  const jobId = String(first.job_id || "").trim();
  const card = document.createElement("details");
  card.className = "eg-job";
  card.dataset.jobKey = key;
  card.dataset.jobId = jobId;
  card.dataset.jobAccount = first.account || "";
  card.open = openJobs.has(key) || posts.some(postHasActionableComments);
  card.addEventListener("toggle", () => {
    if (card.open) openJobs.add(key);
    else openJobs.delete(key);
  });

  const summary = document.createElement("summary");
  summary.className = "eg-j-summary";
  const head = el("div", "eg-j-head");
  const caption = String(first.caption || "").trim().split(/\r?\n/)[0];
  head.append(el("b", "eg-j-name", jobId ? `ใบงาน ${jobId}` : "โพสต์ที่ไม่พบใบงานต้นทาง"));
  head.append(el("span", "eg-job-account", `👤 ${first.account || "ไม่ทราบโปรไฟล์"}`));
  if (caption) head.append(el("span", "eg-j-caption",
    caption.length > 90 ? `${caption.slice(0, 90)}…` : caption));
  const groupCount = new Set(posts.map(postGroupKey)).size;
  const pending = posts.reduce((sum, post) => sum + (Number(post.pending) || 0), 0);
  head.append(el("span", "eg-tag eg-g-shown", `${groupCount} กลุ่ม`));
  head.append(el("span", "eg-tag eg-g-active", `ตามเก็บ ${posts.filter(isPostActive).length} โพสต์`));
  if (pending) head.append(el("span", "eg-tag eg-wait", `ค้าง ${pending}`));

  if (jobId) {
    const collect = el("button", "eg-manual eg-manual-job", "▶ เก็บใบงานนี้ใหม่");
    collect.type = "button";
    collect.title = "สั่ง Chrome Bot8 อ่านทุกโพสต์ในใบงานนี้ใหม่";
    collect.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      collectManual("job", {account: first.account || "", job_id: jobId}, collect);
    });

    const stop = el("button", "eg-job-stop", "🛑 ยกเลิกตามเก็บใบงาน");
    stop.type = "button";
    stop.title = "หยุด Bot8 ตามเก็บทุกโพสต์ในใบงานนี้ แต่ไม่ลบโพสต์หรือประวัติ";
    stop.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (!window.confirm(`ยกเลิกการตามเก็บทุกโพสต์ของใบงาน ${jobId} ใช่ไหม?\n\nโพสต์บน Facebook และประวัติเดิมจะไม่ถูกลบ`)) return;
      stop.disabled = collect.disabled = true;
      try {
        const out = await api("/api/fb/engage/watch", {
          method: "POST",
          body: JSON.stringify({action: "stop", account: first.account || "", job_id: jobId}),
        });
        const stopped = new Set(out.post_urls || []);
        data.posts = (data.posts || []).filter((post) => !stopped.has(post.post_url));
        openJobs.delete(key);
        card.remove();
        paintHead();
        const wrap = box();
        if (wrap && !wrap.querySelector(".eg-job")) {
          wrap.replaceChildren(el("p", "eg-empty", "ไม่มีใบงานที่กำลังตามเก็บในบัญชีนี้"));
        }
      } catch (error) {
        stop.disabled = collect.disabled = false;
        manualFeedback(`ยกเลิกใบงาน ${jobId} ไม่สำเร็จ — ${error.message}`, true);
      }
    });
    head.append(collect, stop);
  }
  summary.append(head);

  const body = el("div", "eg-job-body");
  // รายละเอียดใบงานต้องอยู่ก่อนรายชื่อกลุ่ม/โพสต์เสมอ เพื่อเห็นบริบทก่อนตอบ.
  if (jobId) body.append(jobDetail(first, posts));
  const groups = new Map();
  posts.forEach((post) => {
    const groupKey = postGroupKey(post);
    if (!groups.has(groupKey)) groups.set(groupKey, []);
    groups.get(groupKey).push(post);
  });
  const groupList = el("div", "eg-job-groups");
  groupList.append(el("strong", "eg-part", "โพสต์ในแต่ละกลุ่ม · เปิดรายละเอียดและตอบได้ตรงนี้"));
  groupList.append(...Array.from(groups.values(), groupCard));
  body.append(groupList);
  card.append(summary, body);
  return card;
}

function paintHead() {
  const note = $("#egNote");
  if (!note || !data) return;
  // **นับจากของที่อยู่บนจอจริง ไม่ใช่เลขที่เซิร์ฟเวอร์ส่งมาตอนโหลด**
  // กดเพิกเฉยแล้วแถวหายไปเดี๋ยวนั้น ถ้ายังโชว์เลขเดิมจะขัดกับสิ่งที่ตาเห็น
  const live = (data.posts || []).flatMap((p) => (p.comments_list || [])
    .filter((c) => !c.is_ours && !c.ignored));
  const pending = live.filter((c) => !c.answered && !c.reply_sent_at && !c.reply_queued_at);
  const firstQueued = live.filter((c) => c.reply_queued_at && !c.reply_sent_at && !c.reply_error);
  const followupQueued = live.filter((c) => c.followup_queued_at && !c.followup_sent_at && !c.followup_error);
  const queuedCount = firstQueued.length + followupQueued.length;
  const failedCount = live.filter((c) => c.reply_error && !c.reply_sent_at).length
    + live.filter((c) => c.followup_error && !c.followup_sent_at).length;
  const draftedCount = pending.filter((c) => c.reply_draft).length
    + live.filter((c) => c.followup_draft && !c.followup_queued_at && !c.followup_sent_at).length;
  const tail = [
    firstQueued.length ? (data.reply_daily?.waiting
      ? `comment แรกเข้าคิว ${firstQueued.length} รายการ (รอเพดาน 50 รายการรีเซ็ต)`
      : `comment แรกเข้าคิว ${firstQueued.length} รายการ (เว้น 10–15 นาที)`) : "",
    followupQueued.length ? `comment 2 เข้าคิว ${followupQueued.length} รายการ (เว้นจาก comment แรก 1–5 นาที)` : "",
    failedCount ? `ส่งไม่สำเร็จ ${failedCount} รายการ` : "",
    draftedCount ? `พิมพ์ไว้แต่ยังไม่สั่ง ${draftedCount} รายการ` : "",
  ].filter(Boolean);
  note.textContent = pending.length
    ? `💬 มีคอมเมนต์รอตอบ ${pending.length} รายการ ใน ${data.posts.length} โพสต์`
      + (tail.length ? ` · ${tail.join(" · ")}` : "")
    : (queuedCount
      ? `⏳ ตัดสินใจครบแล้ว — ${tail.join(" · ")}`
      : (failedCount
        ? `⚠️ ไม่มีคิวที่กำลังรอเวลา — ส่งไม่สำเร็จ ${failedCount} รายการและถูกพักไว้`
        : "✅ ไม่มีคอมเมนต์ค้าง — จัดการครบทุกอันแล้ว"));
  const stamp = $("#egStamp");
  if (stamp) stamp.textContent = `อัปเดต ${data.at || ""}`;
  paintCollectorStatus();
  paintCollectSchedule();
  paintMassStatus();
  paintMassSchedule();
  paintReplyTimer();
}

function paint() {
  const wrap = box();
  if (!wrap || !data) return;
  paintHead();
  const posts = data.posts || [];
  if (!posts.length) {
    wrap.replaceChildren(el("p", "eg-empty", onlyPending
      ? "ไม่มีโพสต์ที่มีคอมเมนต์ค้าง — กด \"ดูทุกโพสต์\" เพื่อดูของที่ตอบไปแล้ว"
      : "ยังไม่มีโพสต์ที่เก็บคอมเมนต์มา — บอทเก็บคอมเมนต์ยังไม่เคยรัน"));
    return;
  }
  const jobs = new Map();
  posts.forEach((post) => {
    const key = postJobKey(post);
    if (!jobs.has(key)) jobs.set(key, []);
    jobs.get(key).push(post);
  });
  wrap.replaceChildren(...Array.from(jobs.values(), jobCard));
  syncManualButtons();
}

/**
 * ลบแถวที่บอทมือถือยืนยันว่าตอบขึ้น Facebook แล้ว โดยไม่วาดหน้าทั้งก้อน.
 *
 * ห้ามใช้ loadEngage() ทุก 5 วินาที: การวาดใหม่จะลบข้อความที่ผู้ใช้กำลังพิมพ์
 * ใน textarea อื่น ตัว poll นี้จึงถามเฉพาะ comment_key ที่มองเห็นและแตะ DOM
 * เฉพาะแถวที่เสร็จจริง (`reply_sent_at` หรือ `answered`) เท่านั้น.
 */
async function pruneCompletedReplies() {
  const panel = $("#tab-groups");
  if (completionBusy || document.hidden || panel?.hidden || !data) return;
  const rows = Array.from(document.querySelectorAll(
    "#egList .eg-comments > .eg-comment[data-comment-key]",
  ));
  const keys = [...new Set([...resumedReplies].filter(([, info]) => info.account === data.account)
    .map(([key]) => key).concat(rows.map((row) => row.dataset.commentKey).filter(Boolean)))];
  if (!keys.length) return;

  completionBusy = true;
  const snapshot = data;
  try {
    const out = await api("/api/fb/engage/reply-status", {
      method: "POST",
      body: JSON.stringify({
        comment_keys: keys.slice(0, 500),
        account: data.account || "",
      }),
    });
    if (data !== snapshot || snapshot.account !== gfAccount()) return;
    if (out.reply_daily) data.reply_daily = out.reply_daily;
    if (out.reply_schedule) data.reply_schedule = out.reply_schedule;
    if (out.work_priority) data.work_priority = out.work_priority;
    if (out.reply_worker) data.reply_worker = out.reply_worker;
    syncReplyDeadline();
    const states = new Map((out.comments || []).map((state) => [state.comment_key, state]));
    for (const [key, state] of states) completeResumedReply(key, state);
    const completed = new Set();
    for (const [key, state] of states) {
      const followupPending = Boolean(state.followup_queued_at && !state.followup_sent_at);
      if ((state.reply_sent_at || Number(state.answered) || Number(state.ignored))
          && !followupPending) completed.add(key);
    }

    // อัปเดตข้อมูลในหน่วยความจำก่อน เพื่อให้ยอดหัวกล่อง/ตัวจับเวลาตรงกับแถวจริง.
    for (const post of data.posts || []) {
      for (const item of post.comments_list || []) {
        const state = states.get(item.comment_key);
        if (!state) continue;
        item.answered = Number(state.answered) || 0;
        item.reply_sent_at = state.reply_sent_at || "";
        item.reply_error = state.reply_error || "";
        item.reply_submitted_at = state.reply_submitted_at || "";
        item.reply_attempted_at = state.reply_attempted_at || "";
        item.ignored = Number(state.ignored) || 0;
        item.followup_draft = state.followup_draft || "";
        item.followup_queued_at = state.followup_queued_at || "";
        item.followup_due_at = Number(state.followup_due_at) || 0;
        item.followup_delay_seconds = Number(state.followup_delay_seconds) || 0;
        item.followup_sent_at = state.followup_sent_at || "";
        item.followup_error = state.followup_error || "";
        item.followup_submitted_at = state.followup_submitted_at || "";
        item.followup_attempted_at = state.followup_attempted_at || "";
      }
      post.pending = (post.comments_list || []).filter((item) =>
        !item.is_ours && !item.ignored && (
          (!item.answered && !item.reply_sent_at && !item.reply_queued_at)
          || (item.followup_queued_at && !item.followup_sent_at))).length;
    }
    paintReplyTimer();
    if (!onlyPending) return;

    const touchedCards = new Set();
    const touchedGroups = new Set();
    for (const row of rows) {
      const status = states.get(row.dataset.commentKey);
      const item = (data.posts || []).flatMap(p => p.comments_list || [])
        .find(c => c.comment_key === row.dataset.commentKey);
      if (status && item && (status.reply_sent_at || Number(status.answered))
          && status.followup_queued_at && !status.followup_sent_at) {
        // คำตอบแรกเสร็จแต่ comment 2 ยังรอ: เปลี่ยนแถวเป็นสถานะ comment 2
        // แทนการปล่อยปุ่มตอบครั้งแรกไว้ให้กดซ้ำ.
        row.replaceWith(commentRow(item));
        continue;
      }
      if (status && !completed.has(row.dataset.commentKey)) {
        if (item && (status.reply_error || status.reply_submitted_at)) {
          const note = row.querySelector('.eg-note');
          const button = row.querySelector('.eg-send');
          if (note) note.textContent = `${item.author} · ${item.reply_attempted_at || item.reply_submitted_at} · ${item.reply_error || (item.reply_submitted_at ? "ส่งแล้วแต่ยังยืนยันไม่ได้ — ตรวจผลก่อน ห้ามส่งซ้ำ" : "ยังทำไม่สำเร็จ")}`;
          if (button) button.textContent = item.reply_submitted_at ? "🔎 ตรวจผล" : "↩ สั่งใหม่";
          if (item.reply_submitted_at) {
            const field = row.querySelector('textarea');
            if (field) field.disabled = true;
          }
        }
        if (item?.followup_queued_at) {
          const followupNote = row.querySelector('.eg-followup .eg-note');
          if (followupNote) {
            followupNote.textContent = item.followup_sent_at
              ? `comment 2 ขึ้น Facebook แล้ว ${item.followup_sent_at}`
              : item.followup_error
                ? `comment 2 ยังไม่สำเร็จ · ${item.followup_error}`
                : item.followup_submitted_at
                  ? `comment 2 ส่งแล้วแต่ยังยืนยันไม่ได้ ${item.followup_submitted_at} · ห้ามส่งซ้ำ`
                  : "comment 2 เข้าคิวแล้ว · สุ่มเว้น 1–5 นาที";
          }
        }
      }
      if (!completed.has(row.dataset.commentKey)) continue;
      const card = row.closest(".eg-post");
      if (card) {
        touchedCards.add(card);
        const group = card.closest(".eg-group");
        if (group) touchedGroups.add(group);
      }
      row.remove();
    }
    for (const card of touchedCards) {
      const liveRows = Array.from(card.querySelector(".eg-comments")?.children || [])
        .filter((node) => node.classList.contains("eg-comment"));
      const post = (data.posts || []).find((item) => item.post_url === card.dataset.postUrl);
      if (post) card.dataset.pending = String(post.pending || 0);
      const badge = card.querySelector(".eg-p-head .eg-wait");
      if (badge && post?.pending) badge.textContent = `ค้าง ${post.pending}`;
      else if (badge) badge.remove();
      if (!liveRows.length) card.remove();
    }

    data.posts = (data.posts || []).filter((post) =>
      (post.comments_list || []).some((item) =>
        !item.is_ours && !item.ignored && !item.answered && !item.reply_sent_at));
    for (const group of touchedGroups) {
      if (!group.querySelector(":scope > .eg-group-body > .eg-post")) group.remove();
      else refreshGroupSummary(group);
    }
    data.at = out.at || data.at;
    paintHead();
    const wrap = box();
    if (wrap && !wrap.querySelector(".eg-post")) {
      wrap.replaceChildren(el("p", "eg-empty",
        "ไม่มีโพสต์ที่มีคอมเมนต์ค้าง — รายการที่ตอบแล้วถูกนำออกจากหน้านี้"));
    }
  } catch {
    // รอบตรวจสถานะพลาดให้ลองใหม่รอบหน้า หน้าเดิมยังใช้ได้และข้อความไม่หาย.
  } finally {
    completionBusy = false;
  }
}

function typedReplySnapshot() {
  const drafts = new Map();
  document.querySelectorAll(
    "#egList .eg-comment[data-comment-key] textarea.eg-input",
  ).forEach((field) => {
    const key = field.closest(".eg-comment")?.dataset.commentKey;
    const kind = field.closest(".eg-followup") ? "followup" : "first";
    if (key) drafts.set(`${key}:${kind}`, field.value);
  });
  return drafts;
}

let engageAccount = null;
let engageRequest = 0;
export async function loadEngage({ preserveInputs = false } = {}) {
  const account = gfAccount();
  const request = ++engageRequest;
  if (engageAccount !== account) {
    engageAccount = account;
    data = null;
    for (const id of ["#egList", "#egDaily", "#egTimer", "#egReplyAlerts", "#egCollector", "#egManualFeedback", "#egStamp", "#egNote"]) $(id)?.replaceChildren();
  }
  const wrap = box();
  if (!wrap) return;
  if (!account) return;
  const typed = preserveInputs ? typedReplySnapshot() : new Map();
  try {
    const result = await api(gfQuery(`/api/fb/engage/threads?pending=${onlyPending ? 1 : 0}&limit=500`));
    if (account !== gfAccount() || request !== engageRequest) return;
    if (result.account !== account) throw new Error("บัญชีในผลตอบกลับไม่ตรงกับบัญชีที่เลือก");
    data = result;
    // API เก็บโพสต์ที่หยุดไว้เป็นประวัติ แต่หน้าทำงานต้องไม่ดึงกลับมาอีก
    // หลังผู้ใช้กดเลิกเก็บ แม้โหลดหน้าใหม่หรือสลับโหมดดูทุกโพสต์.
    data.posts = (data.posts || []).filter(isPostActive);
    if (typed.size) {
      for (const post of data.posts) {
        for (const item of post.comments_list || []) {
          const firstKey = `${item.comment_key}:first`;
          const followupKey = `${item.comment_key}:followup`;
          if (typed.has(firstKey)) item.reply_draft = typed.get(firstKey);
          if (typed.has(followupKey)) item.followup_draft = typed.get(followupKey);
        }
      }
    }
  } catch (error) {
    // **แยก "อ่านไม่ได้" ออกจาก "ไม่มีคอมเมนต์"** สองอย่างนี้ต่างกันสิ้นเชิง
    if (account !== gfAccount() || request !== engageRequest) return;
    const note = $("#egNote");
    if (note) note.textContent = `อ่านคอมเมนต์ไม่ได้ — ${error.message}`;
    return;
  }
  syncReplyDeadline();
  paint();
}

export function wireEngage() {
  if (!replyTimer) replyTimer = window.setInterval(paintReplyTimer, 1000);
  if (!completionTimer) completionTimer = window.setInterval(pruneCompletedReplies, 5000);
  if (!collectorTimer) collectorTimer = window.setInterval(pollCollectorStatus, 3000);
  const reload = $("#egReload");
  if (reload && !reload.dataset.wired) {
    reload.dataset.wired = "1";
    reload.addEventListener("click", () => loadEngage());
  }
  const collectAll = $("#egCollectAll");
  if (collectAll && !collectAll.dataset.wired) {
    collectAll.dataset.wired = "1";
    collectAll.addEventListener("click", () => {
      if (!window.confirm("ให้ Bot8 เก็บคอมเมนต์ทุกโพสต์ที่ยังติดตามใหม่ทั้งหมดใช่ไหม?")) return;
      collectManual("all", {account: data?.account || gfAccount()}, collectAll);
    });
  }
  const schedule = $("#egCollectSchedule");
  if (schedule && !schedule.dataset.wired) {
    schedule.dataset.wired = "1";
    schedule.addEventListener("submit", saveCollectSchedule);
    schedule.addEventListener("input", () => { schedule.dataset.dirty = "1"; });
  }
  const clearSchedule = $("#egScheduleClear");
  if (clearSchedule && !clearSchedule.dataset.wired) {
    clearSchedule.dataset.wired = "1";
    clearSchedule.addEventListener("click", clearCollectSchedule);
  }
  const massStart = $("#egMassStart");
  if (massStart && !massStart.dataset.wired) {
    massStart.dataset.wired = "1";
    massStart.addEventListener("click", startMassReport);
  }
  const massSchedule = $("#egMassSchedule");
  if (massSchedule && !massSchedule.dataset.wired) {
    massSchedule.dataset.wired = "1";
    massSchedule.addEventListener("submit", saveMassSchedule);
    massSchedule.addEventListener("input", () => { massSchedule.dataset.dirty = "1"; });
  }
  const massClear = $("#egMassScheduleClear");
  if (massClear && !massClear.dataset.wired) {
    massClear.dataset.wired = "1";
    massClear.addEventListener("click", clearMassSchedule);
  }
  const all = $("#egAll");
  if (all && !all.dataset.wired) {
    all.dataset.wired = "1";
    all.textContent = onlyPending ? "ดูทุกโพสต์" : "ดูเฉพาะที่ค้าง";
    all.addEventListener("click", () => {
      onlyPending = !onlyPending;
      all.textContent = onlyPending ? "ดูทุกโพสต์" : "ดูเฉพาะที่ค้าง";
      loadEngage();
    });
  }
}
