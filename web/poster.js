/* สายโปสเตอร์ — Picture-post → Poster → Caption → Comment → Facebook
 *
 * เจ้าของสั่ง 23 ก.ย. 2569 (สเปค SPEC-สายโปสเตอร์.md) งานจริงอยู่ที่เซิร์ฟเวอร์
 * (poster_api.py · poster_worker.py) ไฟล์นี้แค่แสดงกระดานกับส่งคำสั่ง —
 * **ห้ามตัดสินอะไรเองที่นี่** ป้ายทุกอันต้องมาจากสิ่งที่เซิร์ฟเวอร์ตอบ (ข้อ 2.3.1)
 */
import { api } from "./core.js";

const $ = (id) => document.getElementById(id);
const POLL_MS = 5000;
const BOX_LABEL = { poster: "Poster", caption: "Caption", comment: "Comment" };
let last = null;
let timer = 0;

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
  box.textContent = message;
  box.classList.toggle("warn", Boolean(bad));
}

async function send(path, body, method = "POST") {
  try {
    const res = await api(path, { method, headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body) });
    if (res && res.note) note(res.note);
    await loadPoster();
    return res;
  } catch (error) {
    note(String(error.message || error), true);
    return null;
  }
}

const fileUrl = (id, rel) => `/api/poster/file/${encodeURIComponent(id)}/${rel.split("/").map(encodeURIComponent).join("/")}`;

// ---------------------------------------------------------------- การ์ด

function editor(card, field) {
  const value = field === "comments" ? (card.comments || []).join("\n\n———\n\n") : (card[field] || "");
  const box = el("textarea", { rows: 4, value, class: "ps-edit" });
  const save = el("button", { type: "button", class: "ghost tiny", textContent: "บันทึก",
    on: { click: () => {
      const text = box.value;
      const body = field === "comments"
        ? { comments: text.split(/\n\s*———\s*\n/) }
        : { [field]: text };
      send(`/api/poster/${encodeURIComponent(card.id)}`, body, "PUT");
    } } });
  return el("div", { class: "ps-field" }, box, save);
}

function renderCard(card) {
  const thumb = (card.poster_images || [])[0] || (card.images || [])[0];
  const kids = [];
  if (thumb) kids.push(el("img", { src: fileUrl(card.id, thumb), alt: "", loading: "lazy", class: "ps-thumb" }));
  kids.push(el("b", { textContent: card.name }));
  if (card.error) kids.push(el("p", { class: "note warn", textContent: `⚠ ${card.error}` }));
  if (!card.lazada_url && ["comment", "caption", "poster", "picture"].includes(card.stage)) {
    kids.push(el("p", { class: "note", textContent: "ยังไม่มีลิงก์ Lazada — คอมเมนต์จะมีแค่ลิงก์ Shopee" }));
  }
  const id = encodeURIComponent(card.id);
  const row = el("div", { class: "row ps-actions" });
  if (card.stage === "picture") {
    row.append(el("button", { type: "button", class: "tiny", textContent: "→ ส่งเข้า Poster",
      on: { click: () => send(`/api/poster/${id}/move`, { stage: "poster" }) } }));
  }
  if (BOX_LABEL[card.stage]) {
    row.append(el("button", { type: "button", class: "tiny", textContent: `▶ ทำ ${BOX_LABEL[card.stage]} ใบนี้`,
      on: { click: () => send(`/api/poster/${id}/run`, { box: card.stage }) } }));
  }
  const back = { poster: "picture", caption: "poster", comment: "caption", facebook: "comment" }[card.stage];
  if (back) {
    row.append(el("button", { type: "button", class: "ghost tiny", textContent: "↩ ถอยไปทำใหม่",
      title: "ย้ายกลับไปกล่องก่อนหน้า ของเดิมยังอยู่",
      on: { click: () => send(`/api/poster/${id}/move`, { stage: back }) } }));
  }
  kids.push(row);
  if (["comment", "facebook"].includes(card.stage) && card.caption) kids.push(el("small", { textContent: "แคปชัน" }), editor(card, "caption"));
  if (card.stage === "facebook") {
    kids.push(el("small", { textContent: "คอมเมนต์" }), editor(card, "comments"));
    kids.push(el("p", { class: "note", textContent: "ขั้นลงเพจยังไม่เปิดใช้ — ต้องล็อกอินโปรไฟล์เพจก่อน" }));
  }
  if (card.stage === "done" && card.posted?.url) {
    kids.push(el("a", { href: card.posted.url, target: "_blank", rel: "noopener", textContent: "เปิดโพสต์" }));
  }
  return el("article", { class: `ps-card${card.error ? " bad" : ""}` }, kids);
}

function renderBoard(data) {
  const board = $("psBoard");
  board.replaceChildren(...data.stages.map((stage) => {
    const cards = data.cards.filter((c) => c.stage === stage.key);
    const custom = data.customs[stage.key];
    const using = custom && custom.items.find((i) => i.id === custom.selected);
    return el("section", { class: "ps-col" },
      el("header", {}, el("b", { textContent: stage.label }), el("span", { class: "ps-count", textContent: String(cards.length) })),
      custom ? el("p", { class: using ? "note" : "note warn",
        textContent: using ? `ใช้: ${using.name}` : "ยังไม่ได้เลือก custom" }) : null,
      cards.length ? cards.map(renderCard) : el("p", { class: "note", textContent: "— ว่าง —" }));
  }));
}

// ---------------------------------------------------------------- custom · เพจ

function renderCustoms(data) {
  const wrap = $("psCustoms");
  wrap.replaceChildren(...Object.entries(BOX_LABEL).map(([box, label]) => {
    const group = data.customs[box] || { items: [], selected: "" };
    const name = el("input", { placeholder: "ตั้งชื่อ", class: "ps-in" });
    const url = el("input", { placeholder: "https://chatgpt.com/g/g-…", class: "ps-in wide" });
    return el("div", { class: "ps-group" },
      el("h4", { textContent: `กล่อง ${label}` }),
      group.items.length ? group.items.map((item) => el("div", { class: "row ps-item" },
        el("label", {},
          el("input", { type: "radio", name: `ps-${box}`, checked: item.id === group.selected,
            on: { change: () => send(`/api/poster/customs/${box}/${item.id}/use`) } }),
          ` ${item.name}`),
        el("a", { href: item.url, target: "_blank", rel: "noopener", textContent: "เปิด", class: "note" }),
        item.id === group.selected ? null : el("button", { type: "button", class: "ghost tiny danger", textContent: "ลบ",
          on: { click: () => send(`/api/poster/customs/${box}/${item.id}`, undefined, "DELETE") } }),
      )) : el("p", { class: "note warn", textContent: "ยังไม่มี custom — กล่องนี้ยังทำงานไม่ได้" }),
      el("div", { class: "row" }, name, url, el("button", { type: "button", class: "tiny", textContent: "＋ เพิ่ม",
        on: { click: () => send(`/api/poster/customs/${box}`, { name: name.value, url: url.value }) } })));
  }));
}

function renderPages(data) {
  const wrap = $("psPages");
  const pages = data.pages || { items: [], selected: "" };
  const name = el("input", { placeholder: "ชื่อเพจ", class: "ps-in" });
  const url = el("input", { placeholder: "https://www.facebook.com/…", class: "ps-in wide" });
  wrap.replaceChildren(el("div", { class: "ps-group" },
    el("h4", { textContent: "เพจ Facebook ที่จะลง" }),
    pages.items.length ? pages.items.map((item) => el("div", { class: "row ps-item" },
      el("label", {},
        el("input", { type: "radio", name: "ps-page", checked: item.id === pages.selected,
          on: { change: () => send(`/api/poster/pages/${item.id}/use`) } }),
        ` ${item.name}`),
      el("a", { href: item.url, target: "_blank", rel: "noopener", textContent: "เปิด", class: "note" }),
      item.id === pages.selected ? null : el("button", { type: "button", class: "ghost tiny danger", textContent: "ลบ",
        on: { click: () => send(`/api/poster/pages/${item.id}`, undefined, "DELETE") } }),
    )) : el("p", { class: "note warn", textContent: "ยังไม่ได้ผูกเพจ" }),
    el("div", { class: "row" }, name, url, el("button", { type: "button", class: "tiny", textContent: "＋ ผูกเพจ",
      on: { click: () => send("/api/poster/pages", { name: name.value, url: url.value }) } })),
    el("div", { class: "row" },
      el("button", { type: "button", class: "ghost", textContent: "🔑 เปิด Chrome โปรไฟล์เพจเพื่อล็อกอิน",
        on: { click: () => send("/api/poster/fb-profile/open") } }),
      el("span", { class: "note", textContent: "หน้าต่างจะเปิดที่จอคอมเครื่องที่รันเซิร์ฟเวอร์ — ล็อกอินเองได้เลย ระบบไม่กรอกรหัสให้" }))));
}

// ---------------------------------------------------------------- โหลด

export async function loadPoster() {
  if (!$("psBoard")) return;
  try {
    const data = await api("/api/poster/board");
    last = data;
    $("psAuto").checked = data.auto;
    renderBoard(data);
    if (!document.activeElement || !$("tab-poster").contains(document.activeElement)
        || !document.activeElement.classList.contains("ps-in")) {
      renderCustoms(data);
      renderPages(data);
    }
    const busy = data.busy ? `กำลังทำ ${data.busy} (${data.busy_seconds} วิ)` : "ว่าง";
    const queued = data.queue.length ? ` · รอคิว ${data.queue.length} ใบ` : "";
    $("psLog").textContent = [`สถานะ: ${busy}${queued} · แตกใบ -post อัตโนมัติตั้งแต่ ${data.since.slice(0, 16).replace("T", " ")}`,
      ...data.lines].join("\n");
  } catch (error) {
    note(`โหลดกระดานสายโปสเตอร์ไม่ได้: ${error.message || error}`, true);
  }
}

function poll() {
  clearTimeout(timer);
  timer = setTimeout(async () => {
    if (!$("tab-poster")?.hidden && !document.hidden) await loadPoster();
    poll();
  }, POLL_MS);
}

$("psRefresh")?.addEventListener("click", loadPoster);
$("psAuto")?.addEventListener("change", (e) => send("/api/poster/auto", { on: e.target.checked }));
document.querySelector('.tab[data-tab="poster"]')?.addEventListener("click", loadPoster);
poll();
