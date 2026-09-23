/* สายโปสเตอร์ — อยู่ในแท็บ 🎬 สตอรีบอร์ด ใต้สายเจนคลิป
 *
 *   Picture-post → Poster → Caption → Comment → Facebook → ลงเพจแล้ว
 *
 * เจ้าของสั่ง 23 ก.ย. 2569 — *"แก้หน้า flow ให้อยู่ในหน้าเดียวกับสตอรี่บอร์ด
 * หลักการทำงานในแต่ละกล่องให้เหมือนกับของเดิม"* จึงใช้โครงเดียวกับกระดาน
 * สายเจนคลิป (web/video.js) ทุกชิ้น:
 *
 *   แถวกล่องเรียงยาวด้านบน · ☐ อัตโนมัติบนหัวกล่อง · ตัวเลข (ค้าง/10)
 *   กดกล่อง → รายการใบทางซ้าย · กดใบ → รายละเอียด + ปุ่มตัดสินใจทางขวา
 *   ✅ อนุมัติ · ✏️ สั่งแก้ · 🔁 ทำใหม่ · 🅿 พักไว้รอแก้ · ↩ เอากลับ
 *
 * ใช้คลาส CSS ชุดเดียวกับกระดานเดิม (clip-board · board-cell · board-tab ·
 * board-auto · story-layout · story-queue-item · story-detail) หน้าตาจึงตรงกัน
 * โดยไม่ต้องก๊อปสไตล์มา — แก้หน้าตากระดานเดิมเมื่อไร สายนี้เปลี่ยนตามเอง
 *
 * **แยกไฟล์ ไม่ยัดเข้า video.js** เพราะ video.js ยาว 4,500 บรรทัดและวาดกระดาน
 * ของตัวเองใหม่ทุก 6 วินาที ถ้าใช้กล่องรายการร่วมกัน สองตัววาดทับกันไปมา
 *
 * **ห้ามตัดสินอะไรเองที่นี่** ป้ายทุกอันมาจากสิ่งที่เซิร์ฟเวอร์ตอบ (ข้อ 2.3.1)
 */
import { api } from "./core.js";

const $ = (id) => document.getElementById(id);
const POLL_MS = 6000;                  // จังหวะเดียวกับกระดานสายคลิป
const PICK_KEY = "posterBoardPick";
const MAKE = new Set(["poster", "caption", "comment"]);
const BACK = { poster: "picture", caption: "poster", comment: "caption", facebook: "comment" };
const TONE = { queued: "wait", running: "run", review: "review", failed: "fail", blocked: "off" };
const APPROVE_LABEL = {
  picture: "✅ อนุมัติชุดรูป ส่งเข้าทำโปสเตอร์",
  poster: "✅ อนุมัติโปสเตอร์",
  caption: "✅ อนุมัติแคปชัน",
  comment: "✅ อนุมัติคอมเมนต์",
};
const BOX_LABEL = { poster: "Poster", caption: "Caption", comment: "Comment" };

let pick = "";
try { pick = localStorage.getItem(PICK_KEY) || ""; } catch { /* โหมดส่วนตัว */ }
let data = null;
let openId = "";
let detailKey = "";
let busy = false;
const draft = {};                      // ที่พิมพ์ค้างไว้ — หน้าวาดใหม่ทุก 6 วิ ห้ามหาย
const imgDraft = {};                   // ชุดรูปที่กำลังแก้ ยังไม่กดบันทึก

function el(tag, props = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key === "on") for (const [ev, fn] of Object.entries(value)) node.addEventListener(ev, fn);
    else if (key in node) node[key] = value;
    else node.setAttribute(key, value);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) node.append(kid);
  return node;
}

function note(message, bad = false) {
  const box = $("psNote");
  if (!box) return;
  box.textContent = message || "";
  box.classList.toggle("warn", Boolean(bad));
}

async function send(path, body, method = "POST") {
  try {
    const res = await api(path, {
      method,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (res && (res.note || res.message)) note(res.note || res.message);
    await loadPoster(true);
    return res || {};
  } catch (error) {
    note(`สั่งไม่สำเร็จ — ${error.message || error}`, true);
    return null;
  }
}

const btn = (label, cls, fn, title = "") =>
  el("button", { type: "button", class: cls, textContent: label, title,
    on: { click: (e) => { e.stopPropagation(); fn(); } } });

const fileUrl = (id, rel) =>
  `/api/poster/file/${encodeURIComponent(id)}/${rel.split("/").map(encodeURIComponent).join("/")}`;
const cardPath = (id, tail = "") => `/api/poster/${encodeURIComponent(id)}${tail}`;

// ---------------------------------------------------------------- กล่อง

function autoToggle(bucket) {
  const auto = bucket.auto;
  const button = el("button", { type: "button", class: "board-auto" + (auto.on ? " is-on" : "") });
  button.setAttribute("role", "switch");
  const paint = (on) => {
    button.classList.toggle("is-on", on);
    button.setAttribute("aria-checked", on ? "true" : "false");
    const waiting = !on && auto.waiting ? ` · รอ ${auto.waiting}` : "";
    const held = auto.parked_skipped ? ` · พัก ${auto.parked_skipped}` : "";
    button.textContent = `${on ? "☑" : "☐"} อัตโนมัติ${waiting}${held}`;
  };
  paint(auto.on);
  button.title = `${auto.on ? "เปิดอยู่" : "ปิดอยู่"} — รอตรวจ ${auto.waiting || 0} ใบ`
    + (auto.parked_skipped ? ` · พักไว้ ${auto.parked_skipped} ใบ (อัตโนมัติจะข้ามใบที่พัก)` : "");
  button.addEventListener("click", async (event) => {
    event.stopPropagation();          // ห้ามทะลุไปเปลี่ยนกองที่เลือกอยู่
    const next = !button.classList.contains("is-on");
    button.disabled = true;
    paint(next);                      // ขยับให้เห็นทันที แล้วค่อยยืนยันกับเซิร์ฟเวอร์
    const out = await send("/api/poster/auto", { box: auto.key, on: next });
    if (!out) paint(!next);           // **ดีดกลับ** ห้ามดูเหมือนเปิดแล้วทั้งที่ไม่ได้เปิด
    button.disabled = false;
  });
  return button;
}

function paintBoard() {
  const box = $("psBoard");
  const buckets = data.buckets || [];
  if (!buckets.some((b) => b.key === pick)) {
    pick = (buckets.find((b) => b.count > 0) || buckets[0] || {}).key || "";
  }
  box.replaceChildren(...buckets.map((bucket) => {
    const tab = el("button", {
      type: "button",
      class: "board-tab" + (bucket.key === pick ? " is-on" : "") + (bucket.count ? "" : " is-empty")
        + (bucket.short ? " is-short" : ""),
      title: bucket.hint,
    });
    tab.dataset.key = `ps-${bucket.key}`;
    tab.append(
      el("span", { class: "board-name", textContent: bucket.title }),
      el("span", { class: "board-count",
        textContent: bucket.target ? `(${bucket.count}/${bucket.target})` : `(${bucket.count})` }),
    );
    tab.addEventListener("click", () => {
      pick = bucket.key;
      try { localStorage.setItem(PICK_KEY, pick); } catch { /* โหมดส่วนตัว */ }
      paintAll();
    });
    const cell = el("div", { class: "board-cell" });
    if (bucket.auto) cell.append(autoToggle(bucket));
    cell.append(tab);
    // บรรทัดใต้กล่อง: custom ที่ใช้อยู่ (กล่องที่คุยกับ ChatGPT) — ไม่มี = ขึ้นแดง
    if (MAKE.has(bucket.key)) {
      cell.append(el("small", {
        class: "board-quota" + (bucket.custom ? "" : " is-full"),
        textContent: bucket.custom ? `ใช้: ${bucket.custom.name}` : "ยังไม่ได้เลือก custom",
        title: bucket.custom ? bucket.custom.url : "เพิ่ม/เลือกที่ “ChatGPT custom · เพจ Facebook” ข้างล่าง",
      }));
    }
    return cell;
  }));

  const picked = buckets.find((b) => b.key === pick);
  const short = $("psShort");
  if (picked?.short) {
    short.textContent = `⚠️ ขั้นนี้ค้างอยู่ ${picked.count} ใบ — เส้นวัดคือ ${picked.target} ใบ `
      + `ขาดอีก ${picked.short} · ${picked.refill}`;
  } else if (picked) {
    short.textContent = picked.target
      ? `✅ ขั้นนี้มีงานค้าง ${picked.count} ใบ ถึงเส้นวัด ${picked.target} แล้ว`
      : `ลงเพจแล้ว ${picked.count} ใบ`;
  }
  return picked;
}

// ---------------------------------------------------------------- รายการใบ

function cardRow(card) {
  const tone = card.parked ? "off" : (TONE[card.status] || "");
  const row = el("li", { class: `story-queue-item ${tone}${card.id === openId ? " active" : ""}` });
  const bits = [card.status === "running" ? "▶ " : "", card.status_label];
  if (card.parked) bits.push(` · 🅿 ${card.park_why || "พักไว้รอแก้"}`);
  if (card.error) bits.push(` · ${card.error.slice(0, 60)}`);
  row.append(el("b", { textContent: card.name }), el("small", { textContent: bits.join("") }));
  const tools = el("span", { class: "story-queue-tools" });
  if (card.parked) {
    tools.append(btn("↩", "icon-btn", () => send(cardPath(card.id, "/unpark")), "เอากลับเข้ากล่อง"));
  }
  row.append(tools);
  row.addEventListener("click", () => { openId = card.id; detailKey = ""; paintAll(); });
  return row;
}

function paintList(picked) {
  const list = $("psList");
  const rows = (picked?.cards || []).map(cardRow);
  if (!rows.length) {
    rows.push(el("li", { class: "note", textContent: `ไม่มีงานค้างที่ขั้น "${picked?.title || "นี้"}"` }));
  }
  if (picked?.parked_count) {
    rows.push(el("li", { class: "note", textContent: `🅿 พักไว้รอแก้ ${picked.parked_count} ใบ — อัตโนมัติจะข้ามใบพวกนี้` }));
    rows.push(...picked.parked.map(cardRow));
  }
  list.replaceChildren(...rows);
  $("psCount").textContent = picked ? `${picked.count}${picked.parked_count ? ` · พัก ${picked.parked_count}` : ""}` : "";
}

// ---------------------------------------------------------------- รายละเอียด

function thumbs(card, names, onClick, dim = () => false) {
  return el("div", { class: "ps-thumbs" }, names.map((name) => {
    const img = el("img", { src: fileUrl(card.id, name), alt: "", loading: "lazy",
      class: "ps-thumb" + (dim(name) ? " is-out" : "") });
    const wrap = el("figure", { class: "ps-fig" }, img);
    wrap.addEventListener("click", () => onClick(name));
    return wrap;
  }));
}

function imageEditor(card) {
  const all = [...(card.images || []), ...(card.image_pool || [])];
  const d = imgDraft[card.id] || { images: [...(card.images || [])] };
  imgDraft[card.id] = d;
  const changed = d.images.join("|") !== (card.images || []).join("|");
  const grid = thumbs(card, all, (name) => {
    d.images = d.images.includes(name) ? d.images.filter((n) => n !== name) : [...d.images, name];
    detailKey = "";
    paintDetail();
  }, (name) => !d.images.includes(name));
  return el("div", { class: "ps-block" },
    el("small", { textContent: `ชุดรูปที่จะส่งเข้าทำโปสเตอร์ ${d.images.length}/${all.length} ใบ — กดรูปเพื่อเอาออก/ใส่กลับ` }),
    grid,
    changed ? el("div", { class: "inline-row" },
      btn("💾 บันทึกชุดรูป", "primary", async () => {
        const pool = all.filter((n) => !d.images.includes(n));
        if (await send(cardPath(card.id, "/images"), { images: d.images, pool })) delete imgDraft[card.id];
      }),
      btn("ยกเลิก", "ghost", () => { delete imgDraft[card.id]; detailKey = ""; paintDetail(); })) : null);
}

function textEditor(card, field, label) {
  const key = `${card.id}:${field}`;
  const value = field === "comments" ? (card.comments || []).join("\n\n———\n\n") : (card[field] || "");
  const box = el("textarea", { rows: field === "comments" ? 5 : 6, class: "ps-edit",
    value: draft[key] ?? value });
  box.addEventListener("input", () => { draft[key] = box.value; });
  return el("div", { class: "ps-block" },
    el("small", { textContent: label }),
    box,
    el("div", { class: "inline-row" },
      btn("💾 บันทึกที่แก้", "ghost", async () => {
        const text = box.value;
        const body = field === "comments" ? { comments: text.split(/\n\s*———\s*\n/) } : { [field]: text };
        if (await send(cardPath(card.id), body, "PUT")) delete draft[key];
      })));
}

function linkEditor(card) {
  const row = (field, label, placeholder) => {
    const key = `${card.id}:${field}`;
    const input = el("input", { class: "ps-in wide", placeholder, value: draft[key] ?? (card[field] || "") });
    input.addEventListener("input", () => { draft[key] = input.value; });
    return el("div", { class: "inline-row" }, el("small", { textContent: label }), input,
      btn("บันทึก", "ghost tiny", async () => {
        if (await send(cardPath(card.id), { [field]: input.value.trim() }, "PUT")) delete draft[key];
      }));
  };
  return el("div", { class: "ps-block" },
    row("shopee_url", "Shopee", "https://s.shopee.co.th/…"),
    row("lazada_url", "Lazada", "ยังไม่มี — ระบบหาลิงก์จะทำทีหลัง วางเองได้"));
}

function decideBlock(card) {
  const parts = [];
  const row = el("div", { class: "inline-row" });
  if (APPROVE_LABEL[card.stage]) {
    if (card.status === "review" && !card.parked) {
      row.append(btn(APPROVE_LABEL[card.stage], "primary", () => send(cardPath(card.id, "/approve"))));
    } else {
      row.append(el("small", { class: "note", textContent:
        card.parked ? "พักไว้อยู่ — เอากลับก่อนถึงจะอนุมัติได้" : `ยังอนุมัติไม่ได้ — ${card.status_label}` }));
    }
  }
  if (MAKE.has(card.stage) && ["review", "failed"].includes(card.status)) {
    row.append(btn("🔁 ทำใหม่", "ghost", () => send(cardPath(card.id, "/redo")),
      "ส่งกลับเข้า ChatGPT ทำใหม่ทั้งกล่อง (ของเดิมยังเก็บอยู่)"));
  }
  row.append(card.parked
    ? btn("↩ เอากลับเข้ากล่อง", "ghost", () => send(cardPath(card.id, "/unpark")))
    : btn("🅿 พักไว้รอแก้", "ghost", () => {
      const why = window.prompt("พักไว้เพราะอะไร (เว้นว่างได้)", "");
      if (why !== null) send(cardPath(card.id, "/park"), { text: why });
    }, "อัตโนมัติจะข้ามใบนี้จนกว่าจะเอากลับ"));
  if (BACK[card.stage]) {
    row.append(btn(`↤ ถอยไป ${BACK[card.stage] === "picture" ? "Picture-post" : BOX_LABEL[BACK[card.stage]]}`, "ghost",
      () => send(cardPath(card.id, "/move"), { stage: BACK[card.stage] }),
      "ย้ายกลับไปกล่องก่อนหน้า (ของที่ได้แล้วยังอยู่)"));
  }
  parts.push(row);

  // ✏️ สั่งแก้ — พิมพ์บอกแล้วส่งเข้าแชท ChatGPT เดิมที่ทำของชิ้นนี้ (เหมือนสั่งแก้สตอรีบอร์ด)
  if (MAKE.has(card.stage) && ["review", "failed"].includes(card.status)) {
    const key = `${card.id}:revise`;
    const box = el("textarea", { rows: 2, value: draft[key] || "",
      placeholder: `จะแก้${BOX_LABEL[card.stage]}ตรงไหน — พิมพ์บอกได้เลย แล้วกดสั่งแก้` });
    box.addEventListener("input", () => { draft[key] = box.value; });
    parts.push(el("div", { class: "story-approve" },
      el("div", { class: "inline-row" }, btn(`✏️ สั่งแก้ ${BOX_LABEL[card.stage]}`, "ghost", async () => {
        if (!box.value.trim()) { note(`พิมพ์ก่อนว่าจะแก้${BOX_LABEL[card.stage]}ตรงไหน`, true); return; }
        if (await send(cardPath(card.id, "/revise"), { text: box.value })) delete draft[key];
      })), box));
  }
  return parts;
}

async function paintDetail() {
  const box = $("psDetail");
  if (!openId) {
    box.replaceChildren(el("p", { class: "note", textContent: "เลือกใบทางซ้าย — ใบที่รอตรวจจะมีปุ่มอนุมัติ/สั่งแก้ให้ตรงนี้" }));
    return;
  }
  let card;
  try {
    card = await api(`/api/poster/card/${encodeURIComponent(openId)}`);
  } catch (error) {
    detailKey = "";
    box.replaceChildren(el("p", { class: "note", textContent: `เปิดใบไม่สำเร็จ: ${error.message}` }));
    return;
  }
  // ไม่วาดใหม่ถ้าไม่มีอะไรเปลี่ยน — วาดทุก 6 วิจะทำให้ที่เลื่อนดู/ที่พิมพ์อยู่กระโดด
  const key = [card.id, card.stage, card.status, card.updated_at, card.parked].join("|");
  if (key === detailKey) return;
  detailKey = key;

  const parts = [el("h4", { textContent: card.name }),
    el("small", { class: "note", textContent: `${card.stage_label} · ${card.status_label}${card.parked ? " · 🅿 พักไว้" : ""}` })];
  if (card.error) parts.push(el("p", { class: "note fail", textContent: `❌ ${card.error}` }));
  if (card.status === "running") parts.push(el("p", { class: "note", textContent: "⏳ กำลังคุยกับ ChatGPT — ใช้เวลาราว 1–3 นาที" }));
  if (card.status === "queued") parts.push(el("p", { class: "note", textContent: "รอคิวทำ — ระบบหยิบไปทำเองทีละใบ" }));
  parts.push(...decideBlock(card));

  // ของที่ได้ของแต่ละกล่อง — โชว์ของกล่องปัจจุบันก่อน ของกล่องก่อนหน้าไว้อ้างอิง
  if (card.stage === "picture") parts.push(imageEditor(card), linkEditor(card));
  if (card.poster_images?.length && card.stage !== "picture") {
    const pc = card.poster_custom || {};
    parts.push(el("div", { class: "ps-block" },
      el("small", { textContent: `โปสเตอร์${pc.name ? ` · จาก “${pc.name}”` : ""}` }),
      thumbs(card, card.poster_images, (name) => window.open(fileUrl(card.id, name), "_blank"))));
  }
  if (card.caption && ["caption", "comment", "facebook", "done"].includes(card.stage)) {
    parts.push(textEditor(card, "caption", "แคปชัน (แก้เองได้)"));
  }
  if (card.comments?.length && ["comment", "facebook", "done"].includes(card.stage)) {
    parts.push(textEditor(card, "comments", "คอมเมนต์ (หลายข้อความคั่นด้วยบรรทัด ———)"));
  }
  if (card.stage === "comment" || card.stage === "facebook") parts.push(linkEditor(card));
  if (card.stage === "facebook") {
    parts.push(el("p", { class: "note warn", textContent: "ขั้นลงเพจยังไม่เปิด — ต้องล็อกอิน Chrome โปรไฟล์เพจก่อน แล้วค่อยสร้างขั้นลงเพจจากหน้าจริง" }));
  }
  if (card.stage === "done" && card.posted?.url) {
    parts.push(el("a", { href: card.posted.url, target: "_blank", rel: "noopener", textContent: "เปิดโพสต์ ↗" }));
  }
  box.replaceChildren(...parts);
}

// ---------------------------------------------------------------- custom · เพจ

function renderSetup() {
  // ห้ามวาดทับตอนกำลังพิมพ์อยู่ในช่องตั้งค่า — ไม่งั้นที่พิมพ์หาย
  const setup = $("psSetup");
  if (setup.contains(document.activeElement) && document.activeElement.tagName === "INPUT") return;
  const groups = Object.entries(BOX_LABEL).map(([box, label]) => {
    const group = data.customs[box] || { items: [], selected: "" };
    const name = el("input", { placeholder: "ตั้งชื่อ", class: "ps-in" });
    const url = el("input", { placeholder: "https://chatgpt.com/g/g-…", class: "ps-in wide" });
    return el("div", { class: "ps-group" },
      el("h4", { textContent: `กล่อง ${label}` }),
      group.items.length ? group.items.map((item) => el("div", { class: "inline-row ps-item" },
        el("label", {},
          el("input", { type: "radio", name: `ps-${box}`, checked: item.id === group.selected,
            on: { change: () => send(`/api/poster/customs/${box}/${item.id}/use`) } }),
          ` ${item.name}`),
        el("a", { href: item.url, target: "_blank", rel: "noopener", textContent: "เปิด", class: "note" }),
        item.id === group.selected ? null
          : btn("ลบ", "ghost tiny danger", () => send(`/api/poster/customs/${box}/${item.id}`, undefined, "DELETE")),
      )) : el("p", { class: "note warn", textContent: "ยังไม่มี custom — กล่องนี้ยังทำงานไม่ได้" }),
      el("div", { class: "inline-row" }, name, url,
        btn("＋ เพิ่ม", "tiny", () => send(`/api/poster/customs/${box}`, { name: name.value, url: url.value }))));
  });
  const pages = data.pages || { items: [], selected: "" };
  const pName = el("input", { placeholder: "ชื่อเพจ", class: "ps-in" });
  const pUrl = el("input", { placeholder: "https://www.facebook.com/…", class: "ps-in wide" });
  groups.push(el("div", { class: "ps-group" },
    el("h4", { textContent: "เพจ Facebook ที่จะลง" }),
    pages.items.length ? pages.items.map((item) => el("div", { class: "inline-row ps-item" },
      el("label", {},
        el("input", { type: "radio", name: "ps-page", checked: item.id === pages.selected,
          on: { change: () => send(`/api/poster/pages/${item.id}/use`) } }),
        ` ${item.name}`),
      el("a", { href: item.url, target: "_blank", rel: "noopener", textContent: "เปิด", class: "note" }),
      item.id === pages.selected ? null
        : btn("ลบ", "ghost tiny danger", () => send(`/api/poster/pages/${item.id}`, undefined, "DELETE")),
    )) : el("p", { class: "note warn", textContent: "ยังไม่ได้ผูกเพจ" }),
    el("div", { class: "inline-row" }, pName, pUrl,
      btn("＋ ผูกเพจ", "tiny", () => send("/api/poster/pages", { name: pName.value, url: pUrl.value }))),
    btn("🔑 เปิด Chrome โปรไฟล์เพจเพื่อล็อกอิน", "ghost", () => send("/api/poster/fb-profile/open")),
    el("small", { class: "note", textContent: "หน้าต่างจะเปิดที่จอคอมเครื่องที่รันเซิร์ฟเวอร์ — ล็อกอินเองได้เลย ระบบไม่กรอกรหัสให้" })));
  $("psCustoms").replaceChildren(...groups);
}

// ---------------------------------------------------------------- โหลด

function paintAll() {
  if (!data) return;
  const picked = paintBoard();
  paintList(picked);
  paintDetail();
}

export async function loadPoster(force = false) {
  if (!$("psBoard")) return;
  if (busy && !force) return;          // รอบก่อนยังไม่กลับ ห้ามยิงซ้อน (บทเรียนกระดานสายคลิป)
  busy = true;
  try {
    data = await api("/api/poster/board");
    paintAll();
    renderSetup();
    const now = data.busy ? `⏳ กำลังทำ ${data.busy} (${data.busy_seconds} วิ)` : "ว่าง";
    const queued = data.queue.length ? ` · รอสั่งแก้ ${data.queue.length}` : "";
    $("psLog").textContent = [`สถานะ: ${now}${queued} · แตกใบ -post อัตโนมัติตั้งแต่ `
      + `${data.since.slice(0, 16).replace("T", " ")}`, ...data.lines].join("\n");
  } catch (error) {
    note(`โหลดกระดานสายโปสเตอร์ไม่ได้: ${error.message || error}`, true);
  } finally {
    busy = false;
  }
}

function poll() {
  setTimeout(async () => {
    if (!$("tab-story")?.hidden && !document.hidden) await loadPoster();
    poll();
  }, POLL_MS);
}

$("psRefresh")?.addEventListener("click", () => loadPoster(true));
document.querySelector('.tab[data-tab="story"]')?.addEventListener("click", () => loadPoster(true));
loadPoster();
poll();
