import { api } from "./core.js";

const button = document.querySelector("#reelsDownload");
const input = document.querySelector("#reelsDownloadLinks");
const note = document.querySelector("#reelsDownloadNote");
const running = document.querySelector("#reelsRunning");
const results = document.querySelector("#reelsDownloadResults");
const listNote = document.querySelector("#reelsListNote");
const checkButton = document.querySelector("#reelsCheck");
const folderButton = document.querySelector("#reelsOpenFolder");
const folderNote = document.querySelector("#reelsFolderNote");
const folderPath = document.querySelector("#reelsFolderPath");
const folderSave = document.querySelector("#reelsFolderSave");

/* เลือกโฟลเดอร์เก็บคลิปเอง (เจ้าของสั่ง 21 ก.ย. 2569)
 *
 * **ใช้ช่องพิมพ์ที่อยู่ ไม่ใช่กล่องเลือกโฟลเดอร์ของเครื่อง** เพราะหน้าเว็บ
 * เปิดจากคอมอีกเครื่องผ่าน Tailscale กล่องเลือกไฟล์ของเบราว์เซอร์จะได้ที่อยู่
 * ของเครื่องที่เปิดหน้าเว็บ ซึ่งคนละเครื่องกับที่เก็บไฟล์จริง — เลือกมาก็ผิดที่
 *
 * เซิร์ฟเวอร์ตรวจให้ว่าโฟลเดอร์นั้นเขียนไฟล์ได้จริง ไม่ใช่แค่มีอยู่
 */
function showFolder(data, extra = "") {
  if (!folderNote) return;
  const where = data?.path || "";
  folderNote.textContent = (extra ? `${extra} · ` : "")
    + `ตอนนี้เก็บลง ${where}${data?.is_default ? " (ที่เดิม)" : ""}`;
  if (folderPath && document.activeElement !== folderPath) {
    folderPath.value = data?.is_default ? "" : where;
    folderPath.placeholder = `เว้นว่างไว้ = ใช้ที่เดิม (${data?.default || ""})`;
  }
}

api("/api/facebook-reels/folder")
  .then((data) => showFolder(data))
  .catch(() => { /* อ่านไม่ได้ก็ไม่ต้องขึ้นอะไร ปุ่มอื่นยังใช้ได้ */ });

folderSave?.addEventListener("click", async () => {
  folderSave.disabled = true;
  const was = folderSave.textContent;
  folderSave.textContent = "กำลังบันทึก…";
  try {
    const data = await api("/api/facebook-reels/folder", {
      method: "POST", body: JSON.stringify({ path: folderPath?.value || "" }),
    });
    showFolder(data, data.message || "บันทึกแล้ว");
    folderNote.classList.remove("is-bad");
  } catch (error) {
    // ข้อความไทยมาจากเซิร์ฟเวอร์ครบแล้ว แสดงตรงๆ ไม่ต้องแปลเอง
    folderNote.textContent = error.message;
    folderNote.classList.add("is-bad");
  } finally {
    folderSave.disabled = false;
    folderSave.textContent = was;
  }
});

folderButton?.addEventListener("click", async () => {
  folderButton.disabled = true;
  folderNote.textContent = "กำลังเปิด Folder คลิป…";
  try {
    const data = await api("/api/facebook-reels/open-folder", { method: "POST" });
    folderNote.textContent = `เปิดแล้ว: ${data.path}`;
  } catch (error) {
    folderNote.textContent = `เปิด Folder ไม่สำเร็จ: ${error.message}`;
  } finally {
    folderButton.disabled = false;
  }
});

function readLinks(value) {
  const matches = value.match(/https:\/\/[^\s,]+/g) || [];
  return [...new Set(matches.map((link) => link.replace(/[)\]}>,.;]+$/g, "")))];
}

function megabytes(bytes) {
  const mb = (Number(bytes) || 0) / 1048576;
  if (mb >= 1024) return `${(mb / 1024).toFixed(2)} GB`;
  return `${mb.toFixed(1)} MB`;
}

function clockOf(stamp) {
  const when = new Date((Number(stamp) || 0) * 1000);
  if (!Number.isFinite(when.getTime()) || !stamp) return "";
  return when.toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit" });
}

/* ---------------------------------------------------- รายการคลิปที่เก็บไว้
 *
 * เจ้าของสั่ง 21 ก.ย. 2569 — "ให้ใบงานค้างไว้ โดยให้โชว์แค่ที่วง ที่เหลือทำเป็น
 * ดรอปดาวน์ ให้มีปุ่ม refresh คือ เช็คคลิป เผื่อมีอันไหนที่ถูกลบไป และให้มี
 * ปุ่มลบที่ลบทั้งคลิปทั้งไฟล์ที่โหลดมาแล้ว และที่แปล"
 *
 * **เนื้อในการ์ดสร้างตอนกดเปิดครั้งแรกเท่านั้น** ถ้าสร้าง <video> ไว้ล่วงหน้า
 * ทุกใบ เปิดหน้าเว็บทีเดียวจะยิงขอไฟล์วิดีโอพร้อมกันเท่าจำนวนคลิปที่มี
 */

// จำสคริปที่โชว์อยู่แยกจากตัวการ์ด — การ์ดถูกสร้างใหม่เมื่อไรข้อความจะได้ไม่หาย
// (บทเรียนซ้ำในโปรเจกต์นี้: อะไรที่เก็บไว้ในก้อน DOM ที่วาดใหม่ได้ = หายแน่)
const scriptShown = new Map();

const STATE_LOOK = {
  ok: { css: "is-success", word: "สำเร็จ" },
  gone: { css: "is-failed", word: "⚠️ ไฟล์คลิปหายไปแล้ว" },
  offline: { css: "is-unknown", word: "⏳ ยังตรวจไม่ได้" },
};

function clipCard(clip) {
  const look = STATE_LOOK[clip.state] || STATE_LOOK.gone;
  const card = document.createElement("details");
  card.className = `reels-item reels-download-card ${look.css}`;
  card.dataset.id = clip.id;
  card.dataset.state = clip.state;

  const head = document.createElement("summary");
  const no = document.createElement("span");
  no.className = "reels-item-no";

  const lines = document.createElement("span");
  lines.className = "reels-item-head";

  const state = document.createElement("strong");
  state.className = "reels-item-state";
  state.textContent = clip.state === "ok"
    ? `${look.word} · ${megabytes(clip.size)}`
    : look.word;

  const url = document.createElement("span");
  url.className = "note reels-item-url";
  url.textContent = clip.source_url || "(ไม่ได้บันทึกลิงก์ต้นทางไว้)";

  const title = document.createElement("span");
  title.className = "reels-item-title";
  title.textContent = clip.title || "(ไม่มีชื่อคลิป)";

  lines.append(state, url, title);
  head.append(no, lines);

  const body = document.createElement("div");
  body.className = "reels-item-body";
  card.append(head, body);

  // สร้างเนื้อในครั้งเดียวตอนกางออก
  card.addEventListener("toggle", () => {
    if (!card.open || body.dataset.built) return;
    body.dataset.built = "1";
    fillBody(body, clip, card);
  });
  return card;
}

function fillBody(body, clip, card) {
  let video = null;

  if (clip.state === "offline") {
    const why = document.createElement("p");
    why.className = "note is-bad";
    why.textContent = `ยังเข้าโฟลเดอร์ ${clip.folder} ไม่ได้ —`
      + " อาจถอดไดรฟ์ออกหรือย้ายที่เก็บ จึงยังบอกไม่ได้ว่าไฟล์หายจริงหรือไม่";
    body.append(why);
  } else if (clip.state === "gone") {
    const why = document.createElement("p");
    why.className = "note is-bad";
    why.textContent = "โฟลเดอร์ยังอยู่แต่ไม่มีไฟล์คลิปแล้ว — ถูกลบหรือย้ายออกไป"
      + " กดปุ่มล้างรายการเพื่อเอาชื่อนี้ออก แล้วโหลดใหม่จากลิงก์เดิมได้";
    body.append(why);
  } else {
    video = document.createElement("video");
    video.controls = true;
    video.preload = "metadata";
    video.src = clip.video_url;
    const save = document.createElement("a");
    save.href = clip.download_url;
    save.download = "";
    save.textContent = "บันทึกคลิปลงเครื่องนี้";
    body.append(video, save);
  }

  const path = document.createElement("p");
  path.className = "note reels-download-path";
  path.textContent = clip.path || "";
  body.append(path);

  if (clip.state === "ok") body.append(transcribeBlock(clip, video));
  body.append(deleteRow(clip, card));
}

/** ปุ่มลบคลิป — ลบไฟล์คลิป ไฟล์สคริปที่ถอดไว้ และชื่อในรายการ
 *
 *  **ต้องถามซ้ำก่อนลบ** ลบแล้วเอากลับไม่ได้ ต้องไปโหลดใหม่จากลิงก์เดิม
 *  ถามด้วยปุ่มในหน้าเว็บ ไม่ใช้ confirm() ของเบราว์เซอร์ เพราะกล่องนั้น
 *  ขึ้นมาบังทั้งจอและบอกไม่ได้ว่ากำลังจะลบใบไหน
 */
function deleteRow(clip, card) {
  const row = document.createElement("div");
  row.className = "reels-item-danger";

  const ask = document.createElement("button");
  ask.type = "button";
  ask.className = "ghost reels-item-del";
  ask.textContent = clip.state === "gone" ? "🧹 ล้างรายการนี้" : "🗑 ลบคลิปนี้";

  const warn = document.createElement("span");
  warn.className = "note reels-item-warn";
  warn.hidden = true;
  warn.textContent = clip.state === "gone"
    ? "เอาชื่อนี้ออกจากรายการ (ไฟล์ไม่มีอยู่แล้ว) —"
    : "ลบทั้งไฟล์คลิปและสคริปที่ถอดไว้ เอากลับไม่ได้ —";

  const yes = document.createElement("button");
  yes.type = "button";
  yes.className = "reels-item-yes";
  yes.textContent = "ลบเลย";
  yes.hidden = true;

  const no = document.createElement("button");
  no.type = "button";
  no.className = "ghost reels-item-no-btn";
  no.textContent = "ยกเลิก";
  no.hidden = true;

  // ไดรฟ์เข้าไม่ถึง = ยังไม่รู้ว่าไฟล์หายจริงไหม ห้ามให้ลบชื่อทิ้งตอนนี้
  // (เซิร์ฟเวอร์ปฏิเสธอยู่แล้ว แต่ซ่อนปุ่มไว้ด้วยจะได้ไม่ต้องกดแล้วเจอ error)
  if (clip.state === "offline") {
    const hint = document.createElement("span");
    hint.className = "note";
    hint.textContent = "ลบไม่ได้ตอนนี้ — ต้องเข้าโฟลเดอร์ให้ได้ก่อน"
      + " จะได้ไม่ลบรายการทิ้งทั้งที่ไฟล์ยังอยู่";
    row.append(hint);
    return row;
  }

  const reset = () => {
    ask.hidden = false;
    warn.hidden = yes.hidden = no.hidden = true;
  };
  ask.addEventListener("click", () => {
    ask.hidden = true;
    warn.hidden = yes.hidden = no.hidden = false;
  });
  no.addEventListener("click", reset);

  yes.addEventListener("click", async () => {
    yes.disabled = no.disabled = true;
    yes.textContent = "กำลังลบ…";
    try {
      const out = await api("/api/facebook-reels/clips/delete", {
        method: "POST", body: JSON.stringify({ id: clip.id }),
      });
      scriptShown.delete(clip.id);
      card.remove();
      renumber();
      const freed = out.files
        ? ` (${out.files} ไฟล์ · ${megabytes(out.bytes)})`
        : " (ไม่มีไฟล์เหลือให้ลบ เอาชื่อออกจากรายการแล้ว)";
      await refreshList(`ลบคลิปแล้ว${freed}`);
    } catch (error) {
      yes.disabled = no.disabled = false;
      yes.textContent = "ลบเลย";
      warn.textContent = error.message;
      warn.classList.add("is-bad");
    }
  });

  row.append(ask, warn, yes, no);
  return row;
}

function renumber() {
  const cards = results.querySelectorAll(".reels-item");
  cards.forEach((card, index) => {
    const slot = card.querySelector(".reels-item-no");
    if (slot) slot.textContent = String(index + 1);
  });
  results.hidden = cards.length === 0;
}

function tellList(data, extra = "") {
  if (!listNote) return;
  const t = data?.tally || {};
  const bits = [];
  if (extra) bits.push(extra);
  bits.push(`เก็บไว้ ${t.total || 0} คลิป`);
  if (t.bytes) bits.push(`รวม ${megabytes(t.bytes)}`);
  if (t.with_script) bits.push(`ถอดสคริปแล้ว ${t.with_script}`);
  // **สองอย่างนี้ต้องแยกกัน** "ไฟล์หายจริง" กับ "ยังตรวจไม่ได้" คนละเรื่อง
  if (t.gone) bits.push(`⚠️ ไฟล์หาย ${t.gone}`);
  if (t.offline) bits.push(`⏳ ยังตรวจไม่ได้ ${t.offline} (เข้าโฟลเดอร์ไม่ได้)`);
  const clock = clockOf(data?.checked_at);
  if (clock) bits.push(`ตรวจไฟล์เมื่อ ${clock}`);
  listNote.textContent = bits.join(" · ");
  listNote.classList.toggle("is-bad", Boolean(t.gone || t.offline));
}

function drawList(data) {
  const wasOpen = new Set(
    [...results.querySelectorAll(".reels-item[open]")].map((n) => n.dataset.id));
  results.replaceChildren();
  for (const clip of data.clips || []) {
    const card = clipCard(clip);
    if (wasOpen.has(clip.id)) card.open = true;
    results.append(card);
  }
  renumber();
  tellList(data);
}

async function refreshList(extra = "", method = "GET") {
  try {
    const data = method === "GET"
      ? await api("/api/facebook-reels/clips")
      : await api("/api/facebook-reels/clips/check", { method: "POST" });
    drawList(data);
    if (extra) tellList(data, extra);
    return data;
  } catch (error) {
    if (listNote) {
      listNote.textContent = `อ่านรายการคลิปไม่ได้: ${error.message}`;
      listNote.classList.add("is-bad");
    }
    return null;
  }
}

checkButton?.addEventListener("click", async () => {
  checkButton.disabled = true;
  const was = checkButton.textContent;
  checkButton.textContent = "กำลังเช็ค…";
  const data = await refreshList("", "POST");
  if (data) {
    const t = data.tally || {};
    tellList(data, t.gone || t.offline
      ? "เช็คแล้ว — มีที่ต้องดู"
      : "เช็คแล้ว ไฟล์อยู่ครบทุกใบ");
  }
  checkButton.disabled = false;
  checkButton.textContent = was;
});

refreshList();

/** ปุ่มถอดเสียงคลิปเป็นสคริป + ปุ่มคัดลอก (เจ้าของสั่ง 21 ก.ย. 2569)
 *
 *  ถอดในเครื่องด้วย faster-whisper ไม่ส่งคลิปออกไปไหนและไม่กินเครดิต AI
 *
 *  **ต้องบอกเวลาที่จะรอ** large-v3 ใช้เวลาราว 5 เท่าของความยาวคลิป คนกดแล้ว
 *  เห็นปุ่มเงียบไปเป็นนาทีจะนึกว่าค้างแล้วกดซ้ำ — จึงมีทั้งเวลาที่คาดและตัวนับ
 */
function transcribeBlock(clip, video = null) {
  const wrap = document.createElement("div");
  wrap.className = "reels-stt";

  const button = document.createElement("button");
  button.type = "button";
  button.className = "ghost reels-stt-go";

  const state = document.createElement("span");
  state.className = "note reels-stt-state";

  const box = document.createElement("textarea");
  box.className = "reels-stt-text";
  box.rows = 5;
  box.readOnly = true;
  box.hidden = true;

  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "ghost reels-stt-copy";
  copy.textContent = "📋 คัดลอกสคริป";
  copy.hidden = true;
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(box.value);
      copy.textContent = "✅ คัดลอกแล้ว";
    } catch {
      // คลิปบอร์ดถูกห้ามในบางหน้า — เลือกข้อความให้แทน จะได้กด Ctrl+C เองได้
      box.readOnly = false; box.focus(); box.select(); box.readOnly = true;
      copy.textContent = "เลือกให้แล้ว — กด Ctrl+C";
    }
    window.setTimeout(() => { copy.textContent = "📋 คัดลอกสคริป"; }, 2500);
  });

  // สคริปที่เคยถอดไว้ต้องขึ้นให้เห็นเลย ไม่ต้องให้กดถอดใหม่แล้วรอฟรี
  const already = scriptShown.get(clip.id) ?? clip.script ?? "";
  if (already) {
    box.value = already;
    box.hidden = false;
    copy.hidden = false;
    button.textContent = "🔄 ถอดใหม่";
    state.textContent = `สคริปที่ถอดไว้แล้ว${clip.script_language ? ` · ภาษา ${clip.script_language}` : ""}`;
  } else {
    button.textContent = "📝 ถอดเสียงเป็นสคริป";
  }

  // วัดจริงกับ large-v3: ถอดใช้เวลาราว 5 เท่าของความยาวคลิป
  // คลิป 22 วินาที → 99 วินาที · คลิป 6 วินาที → 25 วินาที
  const SLOWDOWN = 5;

  function nice(seconds) {
    if (seconds < 90) return `${Math.round(seconds)} วินาที`;
    return `${Math.round(seconds / 60)} นาที`;
  }

  let ticker = 0;

  button.addEventListener("click", async () => {
    button.disabled = true;
    state.classList.remove("is-bad");

    // รอเป็นนาที ห้ามให้หน้าจอนิ่งจนแยกไม่ออกว่าค้างหรือกำลังทำ
    // ความยาวคลิปอ่านจาก <video> ได้ก็ต่อเมื่อเบราว์เซอร์โหลดหัวไฟล์แล้ว
    // แท็บที่อยู่เบื้องหลัง Chrome จะยังไม่โหลดให้ — ตอนนั้นค่าเป็น NaN
    // **ห้ามปล่อยให้ประโยคหายไปเฉยๆ** ไม่งั้นคนจะไม่รู้เลยว่าต้องรอนานแค่ไหน
    const clipSeconds = Number.isFinite(video?.duration) ? video.duration : 0;
    const guess = clipSeconds
      ? ` น่าจะราว ${nice(clipSeconds * SLOWDOWN)}`
      : ` ใช้เวลาราว ${SLOWDOWN} เท่าของความยาวคลิป`;
    const began = Date.now();
    const tick = () => {
      const past = (Date.now() - began) / 1000;
      state.textContent = `กำลังถอดเสียง…${guess} · ผ่านไป ${nice(past)}`
        + " · อย่าปิดหน้านี้";
    };
    tick();
    window.clearInterval(ticker);
    ticker = window.setInterval(tick, 1000);

    try {
      const out = await api("/api/facebook-reels/transcribe", {
        method: "POST", body: JSON.stringify({ token: clip.id }),
      });
      if (!out.text) {
        // **"ไม่มีเสียงพูด" ต้องไม่หน้าตาเหมือน "ถอดไม่สำเร็จ"**
        window.clearInterval(ticker);
        state.textContent = "ถอดเสร็จแล้วแต่ไม่พบเสียงพูดในคลิปนี้ (อาจมีแต่เสียงดนตรี)";
        button.disabled = false;
        return;
      }
      box.value = out.text;
      box.hidden = false;
      copy.hidden = false;
      scriptShown.set(clip.id, out.text);
      state.textContent = out.cached
        ? `สคริปที่ถอดไว้แล้ว · ภาษา ${out.language || "?"}`
        : `ถอดเสร็จใน ${out.took_seconds} วินาที · คลิปยาว ${out.clip_seconds} วินาที`
          + ` · ภาษา ${out.language || "?"}`;
      button.textContent = "🔄 ถอดใหม่";
    } catch (error) {
      // ข้อความไทยมาจากเซิร์ฟเวอร์ครบแล้ว แสดงตรงๆ
      state.textContent = error.message;
      state.classList.add("is-bad");
    } finally {
      window.clearInterval(ticker);
      button.disabled = false;
    }
  });

  wrap.append(button, copy, state, box);
  return wrap;
}

/* ------------------------------------------------------ รอบดาวน์โหลดรอบนี้
 *
 * ใบที่กำลังโหลดกับใบที่โหลดไม่สำเร็จอยู่คนละกองกับรายการที่เก็บไว้ **โดยตั้งใจ**
 * เพราะใบที่ไม่สำเร็จไม่มีไฟล์ให้ลบ ถ้าเอาไปปนกันปุ่มลบจะมีสองความหมาย
 */
function makeRunning(url, index) {
  const card = document.createElement("article");
  card.className = "reels-download-card is-running";
  const heading = document.createElement("strong");
  heading.textContent = `${index + 1}. กำลังดาวน์โหลด…`;
  const source = document.createElement("p");
  source.className = "note reels-download-source";
  source.textContent = url;
  const detail = document.createElement("div");
  card.append(heading, source, detail);
  running.append(card);
  running.hidden = false;
  return { card, heading, detail };
}

function showFailure(view, error, index) {
  view.card.className = "reels-download-card is-failed";
  view.heading.textContent = `${index + 1}. ไม่สำเร็จ`;
  const message = document.createElement("p");
  message.className = "note";
  message.textContent = error.message;
  view.detail.append(message);
}

button?.addEventListener("click", async () => {
  const links = readLinks(input.value);
  if (!links.length) {
    note.textContent = "วางลิงก์คลิปอย่างน้อย 1 ลิงก์ครับ (Facebook · X · TikTok · Instagram · Reddit · YouTube)";
    return;
  }
  if (links.length > 50) {
    note.textContent = `พบ ${links.length} ลิงก์ — ดาวน์โหลดได้ครั้งละไม่เกิน 50 ลิงก์`;
    return;
  }

  button.disabled = true;
  running.replaceChildren();
  running.hidden = false;
  let succeeded = 0;
  let failed = 0;
  for (let index = 0; index < links.length; index += 1) {
    const url = links[index];
    note.textContent = `กำลังดาวน์โหลด ${index + 1}/${links.length} · สำเร็จ ${succeeded} · ไม่สำเร็จ ${failed}`;
    const view = makeRunning(url, index);
    try {
      const data = await api("/api/facebook-reels/download", {
        method: "POST",
        body: JSON.stringify({ url }),
      });
      succeeded += 1;
      // สำเร็จแล้วย้ายไปอยู่ในรายการที่เก็บไว้ ไม่ค้างอยู่กองรอบนี้
      view.card.remove();
      const fresh = clipCard({
        ...data, state: "ok", playable: true, script: "",
        script_known: true, size_live: true,
      });
      results.prepend(fresh);
      fresh.open = true;
      renumber();
    } catch (error) {
      failed += 1;
      showFailure(view, error, index);
    }
  }
  running.hidden = running.children.length === 0;
  note.textContent = `เสร็จแล้ว ${links.length} ลิงก์ · สำเร็จ ${succeeded} · ไม่สำเร็จ ${failed} — ยังไม่ส่งเข้าคิวโพสต์`;
  button.disabled = false;
  if (succeeded) refreshList();
});
