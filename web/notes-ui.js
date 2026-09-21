/* สมุดโน้ต — ตัวหน้าตา ใช้ร่วมกันทั้งหน้า Studio และหน้าเดี่ยวบนมือถือ
 *
 * เจ้าของสั่ง 21 ก.ย. 2569 — "เขียนแอพแอนดรอยที่ซิ้งข้อมูลในโน้ตขึ้นบนเว็บ
 * ให้หน่อย แล้วถ้าวางข้อมูลบนเว็ปให้สามารถเปิดดูในมือถือได้ด้วย"
 *
 * **ข้อมูลอยู่ที่เซิร์ฟเวอร์ที่เดียว ไม่มีการซิงก์สองทางให้ต้องแก้ชนกัน**
 * ทั้งเว็บและมือถืออ่านเขียนกองเดียวกันผ่าน /api/notes พิมพ์ฝั่งไหนอีกฝั่ง
 * เปิดมาก็เห็นทันที ซึ่งง่ายกว่าและพังยากกว่าการเก็บสองที่แล้วมาเทียบกันทีหลัง
 *
 * ไฟล์นี้ **ไม่รู้จัก core.js และไม่รู้จัก <dialog>** เพราะหน้าเดี่ยวบนมือถือ
 * ไม่ควรต้องโหลด core.js ทั้งก้อน (50 KB + ตัวดึงสถานะที่วิ่งเป็นระยะ)
 * คนเรียกส่งตัวยิง API เข้ามาเอง
 */

const SAVE_AFTER = 800;     // หยุดพิมพ์กี่มิลลิวินาทีถึงบันทึก

const SHOPS = [
  [/(^|\.)shopee\./i, "Shopee", "shopee"],
  [/(^|\.)lazada\./i, "Lazada", "lazada"],
  [/(^|\.)tiktok\.com$|(^|\.)vt\.tiktok\.com$/i, "TikTok", "tiktok"],
  [/(^|\.)facebook\.com$|(^|\.)fb\.watch$/i, "Facebook", "facebook"],
];

const SHELL = `
  <div class="notes-wrap">
    <aside class="notes-side">
      <div class="notes-side-top">
        <strong class="notes-brand">📝 โน้ต</strong>
        <button type="button" class="ghost notes-new" title="โน้ตใหม่">＋</button>
      </div>
      <input type="search" class="notes-find" placeholder="ค้นหาในโน้ตทั้งหมด"
             aria-label="ค้นหาโน้ต" spellcheck="false" />
      <div class="notes-list" role="list"></div>
      <button type="button" class="ghost notes-trash-toggle"></button>
    </aside>
    <section class="notes-main">
      <div class="notes-main-top">
        <button type="button" class="ghost notes-back" title="กลับไปรายการ">‹ รายการ</button>
        <span class="note notes-state" aria-live="polite"></span>
        <button type="button" class="ghost notes-del" title="ลบโน้ตนี้">🗑</button>
        <button type="button" class="ghost notes-close" title="ปิด">✕</button>
      </div>
      <textarea class="notes-text" spellcheck="false"
                placeholder="พิมพ์หรือวางที่นี่ได้เลย&#10;&#10;บรรทัดแรกจะกลายเป็นชื่อโน้ต&#10;วางลิงก์ Shopee / Lazada ไว้ ระบบจะแยกออกมาให้ข้างล่าง"></textarea>
      <div class="notes-links"></div>
    </section>
  </div>`;

function firstLine(text) {
  for (const line of String(text || "").split("\n")) {
    if (line.trim()) return line.trim().slice(0, 80);
  }
  return "";
}

function secondLine(text) {
  const hits = String(text || "").split("\n").map((s) => s.trim()).filter(Boolean);
  return hits.length > 1 ? hits[1].slice(0, 90) : "";
}

function whenText(stamp) {
  const when = new Date((Number(stamp) || 0) * 1000);
  if (!stamp || !Number.isFinite(when.getTime())) return "";
  const sameDay = when.toDateString() === new Date().toDateString();
  return sameDay
    ? when.toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit" })
    : when.toLocaleDateString("th-TH", { day: "numeric", month: "short" });
}

function shopOf(url) {
  let host = "";
  try { host = new URL(url).hostname; } catch { return ["ลิงก์", "other"]; }
  for (const [pattern, label, key] of SHOPS) {
    if (pattern.test(host)) return [label, key];
  }
  return [host.replace(/^www\./, ""), "other"];
}

function linksIn(text) {
  const found = String(text || "").match(/https?:\/\/[^\s<>"')\]]+/g) || [];
  return [...new Set(found.map((link) => link.replace(/[.,;)\]]+$/, "")))];
}

/** สร้างสมุดโน้ตลงใน `root` — คืนตัวควบคุมให้คนเรียกสั่งต่อได้
 *
 *  @param root  ก้อนที่จะวางหน้าตาลงไป
 *  @param api   ตัวยิง API รูปแบบเดียวกับ core.js: api(path, options) -> ข้อมูล
 *  @param onClose  กดปุ่ม ✕ แล้วให้ทำอะไร (หน้าเดี่ยวไม่มีปุ่มนี้)
 */
export function mountNotes(root, api, { onClose = null } = {}) {
  root.innerHTML = SHELL;
  const $ = (cls) => root.querySelector(`.${cls}`);
  const wrap = $("notes-wrap");
  const listBox = $("notes-list");
  const findBox = $("notes-find");
  const textBox = $("notes-text");
  const linkBox = $("notes-links");
  const stateBox = $("notes-state");
  const trashToggle = $("notes-trash-toggle");

  // **สถานะอยู่ในตัวแปร ไม่ฝากไว้ในก้อน DOM** เพราะรายการถูกวาดใหม่บ่อย
  // (บทเรียนซ้ำในโปรเจกต์นี้: อะไรที่ฝากไว้ในก้อนที่วาดใหม่ได้ = หายแน่)
  let notes = [];
  let trash = [];
  let openId = "";
  const draft = new Map();   // id -> ข้อความที่พิมพ์ไว้แต่ยังไม่ได้บันทึก
  let saveTimer = 0;
  let saving = null;
  let showTrash = false;
  let filter = "";

  // ------------------------------------------------------------- ข้อความบอกสถานะ
  function tellState(words, bad = false) {
    stateBox.textContent = words;
    stateBox.classList.toggle("is-bad", bad);
  }

  // ------------------------------------------------------------- ลิงก์ในโน้ต
  async function copyText(value, button, back) {
    try {
      await navigator.clipboard.writeText(value);
      button.textContent = "✅ คัดลอกแล้ว";
    } catch {
      // คลิปบอร์ดถูกห้ามในบางหน้า — บอกตรงๆ ดีกว่าเงียบแล้วคนนึกว่าคัดลอกได้
      button.textContent = "คัดลอกไม่ได้ — เลือกเอง";
    }
    window.setTimeout(() => { button.textContent = back; }, 2000);
  }

  function drawLinks(text) {
    const links = linksIn(text);
    linkBox.replaceChildren();
    linkBox.hidden = links.length === 0;
    if (!links.length) return;

    const head = document.createElement("div");
    head.className = "notes-links-head";
    const label = document.createElement("span");
    label.className = "note";
    label.textContent = `ลิงก์ในโน้ตนี้ ${links.length} รายการ`;
    const all = document.createElement("button");
    all.type = "button";
    all.className = "ghost";
    all.textContent = "คัดลอกทุกลิงก์";
    all.addEventListener("click", () => copyText(links.join("\n"), all, "คัดลอกทุกลิงก์"));
    head.append(label, all);
    linkBox.append(head);

    for (const url of links) {
      const [name, key] = shopOf(url);
      const row = document.createElement("div");
      row.className = "notes-link";

      const chip = document.createElement("span");
      chip.className = `notes-chip is-${key}`;
      chip.textContent = name;

      const open = document.createElement("a");
      open.className = "notes-link-url";
      open.href = url;
      open.target = "_blank";
      open.rel = "noreferrer";
      open.textContent = url;

      const copy = document.createElement("button");
      copy.type = "button";
      copy.className = "ghost notes-link-copy";
      copy.textContent = "คัดลอก";
      copy.addEventListener("click", () => copyText(url, copy, "คัดลอก"));

      row.append(chip, open, copy);
      linkBox.append(row);
    }
  }

  // ------------------------------------------------------------- รายการ
  function stamp(text, cls = "notes-row-when") {
    const span = document.createElement("span");
    span.className = cls;
    span.textContent = text;
    return span;
  }

  function matches(note) {
    if (!filter) return true;
    return (note.text || "").toLowerCase().includes(filter.toLowerCase());
  }

  function drawList() {
    const rows = (showTrash ? trash : notes).filter(matches);
    listBox.replaceChildren();

    trashToggle.textContent = showTrash
      ? "‹ กลับไปโน้ตทั้งหมด"
      : `🗑 ถังขยะ${trash.length ? ` (${trash.length})` : ""}`;
    trashToggle.classList.toggle("is-on", showTrash);

    if (!rows.length) {
      const blank = document.createElement("p");
      blank.className = "note notes-blank";
      blank.textContent = showTrash
        ? "ถังขยะว่าง — ของที่ลบจะอยู่ที่นี่ 30 วันก่อนหายจริง"
        : (filter ? "ไม่เจอโน้ตที่มีคำนี้" : "ยังไม่มีโน้ต กด ＋ เพื่อเริ่มใบแรก");
      listBox.append(blank);
      return;
    }

    for (const note of rows) {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "notes-row";
      row.setAttribute("role", "listitem");
      row.classList.toggle("is-open", !showTrash && note.id === openId);

      // ชื่อของใบที่กำลังพิมพ์อยู่ต้องขยับตามทันที ไม่ต้องรอบันทึกเสร็จ
      const live = draft.has(note.id) ? draft.get(note.id) : note.text;

      const title = document.createElement("span");
      title.className = "notes-row-title";
      title.textContent = firstLine(live) || "โน้ตไม่มีชื่อ";
      if (!firstLine(live)) title.classList.add("is-empty");

      const sub = document.createElement("span");
      sub.className = "notes-row-sub";
      sub.append(stamp(whenText(showTrash ? note.deleted_at : note.updated_at)),
                 stamp(secondLine(live) || "ไม่มีข้อความเพิ่ม", "notes-row-peek"));

      row.append(title, sub);

      if (showTrash) {
        const back = document.createElement("span");
        back.className = "notes-row-restore";
        back.textContent = "กู้คืน";
        row.append(back);
        row.addEventListener("click", () => restoreNote(note.id));
      } else {
        row.addEventListener("click", () => openNote(note.id));
      }
      listBox.append(row);
    }
  }

  // ------------------------------------------------------------- บันทึก
  /** เขียนที่ค้างอยู่ให้จบ **ต้อง await ทุกครั้งที่จะสลับใบหรือปิดหน้าต่าง**
   *  ไม่งั้นตัวอักษรที่พิมพ์ไว้ 800 มิลลิวินาทีสุดท้ายจะหายไปเงียบๆ */
  async function flush() {
    window.clearTimeout(saveTimer);
    saveTimer = 0;
    if (saving) await saving.catch(() => {});
    const id = openId;
    if (!id || !draft.has(id)) return;
    const text = draft.get(id);
    saving = api(`/api/notes/${id}`, { method: "PUT", body: JSON.stringify({ text }) });
    try {
      const fresh = await saving;
      draft.delete(id);
      const at = notes.findIndex((row) => row.id === id);
      if (at >= 0) notes[at] = fresh;
      notes.sort((a, b) => b.updated_at - a.updated_at);
      tellState(`บันทึกแล้ว ${whenText(fresh.updated_at)}`);
      drawList();
    } catch (error) {
      tellState(`บันทึกไม่ได้: ${error.message}`, true);
    } finally {
      saving = null;
    }
  }

  textBox.addEventListener("input", () => {
    if (!openId) return;
    draft.set(openId, textBox.value);
    tellState("กำลังพิมพ์…");
    drawLinks(textBox.value);
    drawList();
    window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(flush, SAVE_AFTER);
  });

  // ------------------------------------------------------------- การกระทำ
  async function openNote(id) {
    if (id === openId) {
      // **ต้องสลับหน้าด้วย ไม่ใช่แค่โฟกัส** บนจอแคบรายการกับตัวเขียนอยู่คนละหน้า
      // ถ้าแตะใบที่เปิดค้างอยู่แล้วไม่ทำอะไรเลย จะติดอยู่ที่รายการ เข้าไปเขียนไม่ได้
      wrap.classList.add("is-reading");
      textBox.focus();
      return;
    }
    await flush();
    openId = id;
    const note = notes.find((row) => row.id === id);
    const text = draft.has(id) ? draft.get(id) : (note?.text || "");
    textBox.value = text;
    drawLinks(text);
    tellState(note?.updated_at ? `แก้ล่าสุด ${whenText(note.updated_at)}` : "");
    wrap.classList.add("is-reading");
    drawList();
    textBox.focus();
  }

  async function newNote() {
    await flush();
    try {
      const fresh = await api("/api/notes", { method: "POST", body: JSON.stringify({ text: "" }) });
      notes.unshift(fresh);
      showTrash = false;
      filter = "";
      findBox.value = "";
      await openNote(fresh.id);
    } catch (error) {
      tellState(error.message, true);
    }
  }

  async function deleteNote() {
    if (!openId) return;
    const id = openId;
    const saved = notes.find((row) => row.id === id);
    const title = firstLine(draft.has(id) ? draft.get(id) : saved?.text) || "โน้ตนี้";
    // ลบแล้วไปอยู่ถังขยะ กู้ได้ 30 วัน จึงไม่ต้องถามซ้ำให้เสียจังหวะ
    window.clearTimeout(saveTimer);
    draft.delete(id);
    openId = "";
    try {
      const gone = await api(`/api/notes/${id}`, { method: "DELETE" });
      notes = notes.filter((row) => row.id !== id);
      trash.unshift(gone);
      textBox.value = "";
      drawLinks("");
      wrap.classList.remove("is-reading");
      tellState(`ย้าย "${title}" ลงถังขยะแล้ว — กู้คืนได้ใน 30 วัน`);
      drawList();
    } catch (error) {
      tellState(error.message, true);
    }
  }

  async function restoreNote(id) {
    try {
      const back = await api(`/api/notes/${id}/restore`, { method: "POST" });
      trash = trash.filter((row) => row.id !== id);
      notes.unshift(back);
      showTrash = false;
      await openNote(back.id);
    } catch (error) {
      tellState(error.message, true);
    }
  }

  /** ดึงรายการใหม่จากเซิร์ฟเวอร์ — **ไม่ทับของที่กำลังพิมพ์ค้างอยู่**
   *  เพราะอีกเครื่องอาจแก้ใบอื่นอยู่ แต่ใบที่นิ้วเราวางอยู่ต้องไม่ถูกเขียนทับ */
  async function load() {
    const data = await api("/api/notes");
    notes = data.notes || [];
    trash = data.trash || [];
    if (openId && !notes.some((row) => row.id === openId) && !draft.has(openId)) {
      openId = "";
      textBox.value = "";
      drawLinks("");
      wrap.classList.remove("is-reading");
    }
    drawList();
    return data;
  }

  // ------------------------------------------------------------- ต่อสาย
  $("notes-new").addEventListener("click", newNote);
  $("notes-del").addEventListener("click", deleteNote);
  $("notes-back").addEventListener("click", async () => {
    await flush();
    wrap.classList.remove("is-reading");
  });
  $("notes-close").addEventListener("click", () => { if (onClose) onClose(); });
  trashToggle.addEventListener("click", () => {
    showTrash = !showTrash;
    wrap.classList.remove("is-reading");
    drawList();
  });
  findBox.addEventListener("input", () => { filter = findBox.value.trim(); drawList(); });

  // สลับแท็บ / ย่อหน้าต่าง = โอกาสที่จะไม่กลับมา บันทึกให้จบตรงนี้เลย
  // **ไม่ใช้ sendBeacon** เพราะมันส่ง text/plain ซึ่งที่อยู่ฝั่งเซิร์ฟเวอร์ของเรา
  // ไม่รับ ใส่ไว้จะได้ด่านหลอกที่ดูเหมือนกันข้อมูลหายแต่จริงๆ ไม่ได้กัน
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flush();
  });

  return {
    load,
    flush,
    tellState,
    get openId() { return openId; },
    get count() { return notes.length; },
    async openFirst() {
      if (notes.length && !openId) await openNote(notes[0].id);
    },
    showList() { wrap.classList.remove("is-reading"); },
    side: $("notes-side"),
    sideTop: $("notes-side-top"),
    wrap,
  };
}

/** ใส่ไฟล์สไตล์ของสมุดโน้ตให้หน้าที่เรียก — หน้า Studio ไม่ได้ผูกไว้ใน HTML
 *  (ตั้งใจ เพราะตอนนี้หลายแชทแก้ index.html พร้อมกัน ยิ่งแตะน้อยยิ่งดี) */
export function ensureNotesCss(href = "/static/notes.css") {
  if (document.querySelector(`link[href^="${href}"]`)) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  document.head.append(link);
}
