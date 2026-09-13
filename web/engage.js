/* ตอบคอมเมนต์ — โพสต์อยู่บน คอมเมนต์อยู่ใต้โพสต์ แบบเดียวกับ Facebook
 *
 * **เจ้าของสั่ง 13 ก.ย. 2569** — *"ช่องพิมพ์อยู่บนหน้าเว็บ ทำคล้ายๆ กับ
 * โครงสร้างเฟสบุ๊ค โพสต์ - คอมเมนต์ใต้โพสต์"* และ *"ทำ Input ให้ผมพิมพ์
 * เพื่อตอบ comment"*
 *
 * ## ทำงานเป็นสองช่วง — หน้านี้คือช่วงแรกเท่านั้น
 *
 *   ① Bot10 (Chrome)  เปิดลิงก์โพสต์ทีละกลุ่ม อ่านคอมเมนต์ + ชื่อคนคอมเมนต์
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

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};

let data = null;
let onlyPending = true;

function box() {
  return $("#egList");
}

/** ย่อลิงก์ให้พออ่านออกว่าเป็นโพสต์ไหน โดยไม่กินทั้งบรรทัด */
function shortLink(url) {
  return String(url || "").replace(/^https?:\/\/(www\.)?facebook\.com\//, "");
}

function commentRow(item) {
  const row = el("div", "eg-comment" + (item.is_ours ? " is-ours" : ""));

  const head = el("div", "eg-c-head");
  head.append(el("b", "eg-c-who", item.is_ours ? "เรา" : (item.author || "(ไม่รู้ชื่อ)")));
  if (item.when_text) head.append(el("span", "eg-c-when", item.when_text));
  if (item.reply_to) head.append(el("span", "eg-c-to", `↩ ตอบ ${item.reply_to}`));
  if (item.answered) head.append(el("span", "eg-tag eg-done", "ตอบแล้ว"));
  row.append(head, el("p", "eg-c-body", item.body || ""));

  // คอมเมนต์ของเราเองไม่ต้องตอบ และคอมเมนต์ที่ตอบไปแล้วก็ไม่ต้อง — ไม่วางช่องพิมพ์
  if (item.is_ours || item.answered) return row;

  const wrap = el("div", "eg-reply");
  const field = document.createElement("textarea");
  field.className = "eg-input";
  field.rows = 2;
  field.placeholder = `ตอบ ${item.author || "คนนี้"}…`;
  field.value = item.reply_draft || "";

  const save = el("button", "eg-save", "เก็บคำตอบ");
  save.type = "button";
  const note = el("span", "eg-note");
  if (item.reply_sent_at) {
    note.textContent = `ส่งขึ้น Facebook แล้ว ${item.reply_sent_at}`;
    note.classList.add("is-sent");
    field.disabled = true;
    save.disabled = true;
  } else if (item.reply_draft) {
    // **ต้องเขียนว่ายังไม่ส่ง** ไม่งั้นเห็นข้อความอยู่ในช่องแล้วนึกว่าตอบไปแล้ว
    note.textContent = `พิมพ์เก็บไว้ ${item.reply_saved_at} · ยังไม่ได้ส่งขึ้น Facebook`;
  }

  save.addEventListener("click", async () => {
    save.disabled = true;
    const was = save.textContent;
    save.textContent = "กำลังเก็บ…";
    try {
      const out = await api("/api/fb/engage/reply", {
        method: "POST",
        body: JSON.stringify({ comment_key: item.comment_key, text: field.value }),
      });
      item.reply_draft = out.reply_draft;
      note.textContent = out.reply_draft
        ? "เก็บแล้ว · ยังไม่ได้ส่งขึ้น Facebook"
        : "ลบคำตอบที่เตรียมไว้แล้ว";
      note.classList.remove("is-bad");
      paintHead();          // ตัวเลข "พิมพ์ไว้แล้ว" ด้านบนต้องขยับตาม
    } catch (error) {
      // เก็บไม่สำเร็จต้องบอก **ห้ามทำเหมือนสำเร็จ** ไม่งั้นคำตอบหายโดยไม่มีใครรู้
      note.textContent = `เก็บไม่ได้ — ${error.message}`;
      note.classList.add("is-bad");
    } finally {
      save.textContent = was;
      save.disabled = false;
    }
  });

  const foot = el("div", "eg-reply-foot");
  foot.append(save, note);
  wrap.append(field, foot);
  row.append(wrap);
  return row;
}

function postCard(post) {
  const card = el("article", "eg-post");

  const head = el("div", "eg-p-head");
  head.append(el("b", "eg-p-group", post.group_name || "(ไม่รู้ชื่อกลุ่ม)"));
  if (post.pending) head.append(el("span", "eg-tag eg-wait", `ค้าง ${post.pending}`));
  if (post.drafted) head.append(el("span", "eg-tag eg-draft", `พิมพ์ไว้ ${post.drafted}`));
  const open = document.createElement("a");
  open.className = "eg-p-link";
  open.href = post.post_url;
  open.target = "_blank";
  open.rel = "noreferrer";
  open.textContent = "🔗 เปิดโพสต์";
  open.title = shortLink(post.post_url);
  head.append(open);
  card.append(head);

  const stat = [];
  if (post.reactions !== null) stat.push(`👍 ${post.reactions}`);
  if (post.comments !== null) stat.push(`💬 ${post.comments}`);
  if (post.shares !== null) stat.push(`↗ ${post.shares}`);
  if (post.checked_at) stat.push(`อ่านล่าสุด ${String(post.checked_at).replace("T", " ").slice(5, 16)}`);
  card.append(el("p", "eg-p-stat", stat.join(" · ")));

  const list = el("div", "eg-comments");
  (post.comments_list || []).forEach((item) => list.append(commentRow(item)));
  if (!(post.comments_list || []).length) {
    list.append(el("p", "eg-empty", "ยังไม่มีคอมเมนต์ในโพสต์นี้"));
  }
  card.append(list);
  return card;
}

function paintHead() {
  const note = $("#egNote");
  if (!note || !data) return;
  const drafted = (data.posts || []).reduce(
    (sum, p) => sum + (p.comments_list || []).filter(
      (c) => c.reply_draft && !c.reply_sent_at).length, 0);
  note.textContent = data.pending_total
    ? `💬 มีคอมเมนต์รอตอบ ${data.pending_total} รายการ ใน ${data.posts.length} โพสต์`
      + (drafted ? ` · พิมพ์คำตอบไว้แล้ว ${drafted} รายการ (ยังไม่ได้ส่ง)` : "")
    : "✅ ไม่มีคอมเมนต์ค้าง — ตอบครบทุกอันแล้ว";
  const stamp = $("#egStamp");
  if (stamp) stamp.textContent = `อัปเดต ${data.at || ""}`;
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
  wrap.replaceChildren(...posts.map(postCard));
}

export async function loadEngage() {
  const wrap = box();
  if (!wrap) return;
  try {
    data = await api(`/api/fb/engage/threads?pending=${onlyPending ? 1 : 0}`);
  } catch (error) {
    // **แยก "อ่านไม่ได้" ออกจาก "ไม่มีคอมเมนต์"** สองอย่างนี้ต่างกันสิ้นเชิง
    const note = $("#egNote");
    if (note) note.textContent = `อ่านคอมเมนต์ไม่ได้ — ${error.message}`;
    return;
  }
  paint();
}

export function wireEngage() {
  const reload = $("#egReload");
  if (reload && !reload.dataset.wired) {
    reload.dataset.wired = "1";
    reload.addEventListener("click", () => loadEngage());
  }
  const all = $("#egAll");
  if (all && !all.dataset.wired) {
    all.dataset.wired = "1";
    all.addEventListener("click", () => {
      onlyPending = !onlyPending;
      all.textContent = onlyPending ? "ดูทุกโพสต์" : "ดูเฉพาะที่ค้าง";
      loadEngage();
    });
  }
}
