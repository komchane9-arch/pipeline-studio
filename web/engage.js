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
/* กล่องไหนถูกกางไว้ — ต้องจำข้ามการวาดใหม่
 *
 * เคยเจอมาแล้วกับแผงงานโพสต์: วาดใหม่ทุกครั้งแล้วกล่องที่กางอยู่หุบเอง
 * เจ้าของกำลังดูรูปอยู่แล้วมันหุบใส่หน้า = ใช้งานไม่ได้จริง
 */
const openDrops = new Set();

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

  const lock = (on) => { send.disabled = on; skip.disabled = on; field.disabled = on; };

  if (item.reply_sent_at) {
    note.textContent = `ส่งขึ้น Facebook แล้ว ${item.reply_sent_at}`;
    note.classList.add("is-sent");
    lock(true);
  } else if (item.reply_queued_at) {
    // **สั่งแล้ว ≠ ขึ้นแล้ว** ต้องเขียนให้ชัด ไม่งั้นนึกว่าตอบไปเรียบร้อย
    note.textContent = `สั่งตอบแล้ว ${item.reply_queued_at} · รอบอทมือถือไปพิมพ์ ยังไม่ขึ้น Facebook`;
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
        note.textContent = "สั่งตอบแล้ว · รอบอทมือถือไปพิมพ์ ยังไม่ขึ้น Facebook";
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
  row.append(wrap);
  return row;
}

/** กล่องเนื้อหาโพสต์ — รูป · แคปชัน · คอมเมนต์ของเราเอง กดแล้วค่อยกาง
 *
 * **เจ้าของสั่ง 15 ก.ย. 2569** — *"หน้าที่โชว์คอมเมนต์ ให้โชว์รูป กับแคปชันด้วย
 * ทั้งหมดรวมคอมเมนต์ของผมให้ทำเป็น drop down คลิ้กแล้วค่อยโชว์"*
 *
 * คอมเมนต์ของเราเอง (ลิงก์สินค้า) ยาวและซ้ำทุกโพสต์ กินที่จนคอมเมนต์ของคนอื่น
 * ซึ่งเป็นตัวที่ต้องตอบ ถูกดันตกลงไปข้างล่าง — ยุบเข้ากล่องแล้วสิ่งที่ต้องทำ
 * จะอยู่บนสุดเสมอ
 */
function postContent(post) {
  const ours = (post.comments_list || []).filter((c) => c.is_ours);
  const shots = Number(post.images) || 0;
  const caption = (post.caption || "").trim();
  if (!shots && !caption && !ours.length) return null;

  const drop = document.createElement("details");
  drop.className = "eg-drop";
  drop.open = openDrops.has(post.post_url);
  drop.addEventListener("toggle", () => {
    if (drop.open) openDrops.add(post.post_url);
    else openDrops.delete(post.post_url);
  });

  const inside = [];
  if (shots) inside.push(`รูป ${shots} ใบ`);
  if (caption) inside.push("แคปชัน");
  if (ours.length) inside.push(`คอมเมนต์ของเรา ${ours.length} อัน`);
  const sum = document.createElement("summary");
  sum.textContent = `ดูเนื้อหาโพสต์ — ${inside.join(" · ")}`;
  drop.append(sum);

  const body = el("div", "eg-drop-body");
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
  drop.append(body);
  return drop;
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

  const content = postContent(post);
  if (content) card.append(content);

  // นอกกล่องเหลือเฉพาะคอมเมนต์ของคนอื่น ซึ่งคือของที่ต้องตอบ
  const others = (post.comments_list || []).filter((c) => !c.is_ours);
  const list = el("div", "eg-comments");
  others.forEach((item) => list.append(commentRow(item)));
  if (!others.length) {
    list.append(el("p", "eg-empty", "ยังไม่มีคอมเมนต์จากคนอื่นในโพสต์นี้"));
  }
  card.append(list);
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
  const queued = live.filter((c) => c.reply_queued_at && !c.reply_sent_at);
  const drafted = pending.filter((c) => c.reply_draft);
  const tail = [
    queued.length ? `สั่งตอบแล้ว ${queued.length} รายการ (รอบอทไปพิมพ์)` : "",
    drafted.length ? `พิมพ์ไว้แต่ยังไม่สั่ง ${drafted.length} รายการ` : "",
  ].filter(Boolean);
  note.textContent = pending.length
    ? `💬 มีคอมเมนต์รอตอบ ${pending.length} รายการ ใน ${data.posts.length} โพสต์`
      + (tail.length ? ` · ${tail.join(" · ")}` : "")
    : (queued.length
      ? `⏳ ตัดสินใจครบแล้ว — สั่งตอบไว้ ${queued.length} รายการ รอบอทมือถือไปพิมพ์`
      : "✅ ไม่มีคอมเมนต์ค้าง — จัดการครบทุกอันแล้ว");
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
