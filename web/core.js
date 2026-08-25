/* Pipeline Studio — ตัวช่วยและสถานะที่ใช้ร่วมกัน + แท็บ / บอท Telegram / ฟาร์มโปรไฟล์ / log / ตั้งค่า
 * แยกจาก app.js เดิม (ระยะ 2.3) เพื่อให้แต่ละแชทแก้คนละไฟล์โดยไม่ชนกัน
 * ไฟล์นี้ห้าม import จากไฟล์อื่น — เป็นฐานของทุกไฟล์ ถ้า import กลับจะเกิดวงกลม */

export const $ = (selector) => document.querySelector(selector);

// สายเจนคลิปแยกไปเป็นเซิร์ฟเวอร์ของตัวเองคนละพอร์ต (clip_app.py)
// หน้าเว็บยังเป็นหน้าเดียว แค่แท็บสตอรีบอร์ดยิงถามข้ามพอร์ตไป
// ถ้าเซิร์ฟเวอร์ตัวนั้นไม่ได้เปิด แท็บนั้นจะบอกให้เปิด ส่วนแท็บอื่นทำงานปกติ
//
// **ต้องอิงโฮสต์ของหน้าที่เปิดอยู่ ห้าม hardcode 127.0.0.1**
// เดิมเขียนตายไว้ พอเปิดหน้านี้จากเครื่องอื่น (ผ่าน Tailscale) คำว่า 127.0.0.1
// จะหมายถึง "เครื่องที่เปิดดู" ไม่ใช่เครื่องที่รันเซิร์ฟเวอร์ — แท็บสตอรีบอร์ด
// จึงพังทั้งแท็บทั้งที่แท็บอื่นใช้ได้ปกติ
export const CLIP_API = `${location.protocol}//${location.hostname}:8877`;

export async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || "ดำเนินการไม่สำเร็จ");
  return payload;
}

export let config = null;
export let system = null;

// ESM ต่างจาก IIFE เดิม: ไฟล์ที่ import ค่าไปจะ "อ่านได้อย่างเดียว" เขียนทับเองไม่ได้
// ค่าที่ไฟล์อื่นต้องเปลี่ยนจึงต้องผ่าน setter ของเจ้าของค่าเสมอ
export function setConfig(value) { config = value; }
export function setSystem(value) { system = value; }

// ทางเดียวสำหรับ "เรียกย้อนขึ้นไปหาไฟล์ที่โหลดทีหลัง" โดยไม่ทำให้ import เป็นวงกลม
// (วงกลมใน ESM = ตัวแปร const ของไฟล์ต้นทางยังไม่ถูกสร้าง → ReferenceError ตอนโหลด)
// เจ้าของฟังก์ชันลงทะเบียนไว้ตอนโหลด ฝั่งที่อยู่ก่อนหน้าเรียกผ่าน hooks แทน import
//   core (ตั้งค่า) → phone.loadAccessDevices   ·   video (GEMS) → boot.reloadConfig
export const hooks = {};

// ============================================================= แท็บ (B)
// เปิดทีละแท็บ พื้นที่ใครพื้นที่มัน — ตามผัง (C)
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    document.querySelectorAll(".tab-area").forEach((area) => {
      area.hidden = area.id !== `tab-${tab.dataset.tab}`;
    });
    // กล่อง log ของแท็บที่เพิ่งเปิดยังไม่เคยถูกถาม (รอบก่อนๆ ข้ามไปเพราะถูกซ่อนอยู่)
    // ถ้าไม่เติมตรงนี้จะเห็นกล่องว่างค้างได้ถึง 3 วินาที
    pollLogs();
  });
});

// ------------------------------------------------ ตั้งค่าบอท Telegram
// dropdown รวมบอททุกตัวที่เชื่อมต่อ — ข้อมูลมาจากสอง API แยกกัน เก็บรวมไว้ก่อนค่อยเรนเดอร์
const connectedBots = { main: null, clip: null, clipUsesMain: false, extras: [] };

function renderBotOverview() {
  const select = $("#botOverview");
  if (!select) return;
  const options = [];
  const label = (info) =>
    info.ok ? `@${info.username}` : "โทเคนใช้ไม่ได้";
  if (connectedBots.main?.saved) {
    options.push(new Option(`บอทหลัก (โพสต์ Facebook) · ${label(connectedBots.main)}`, "main"));
  }
  if (connectedBots.clip?.saved) {
    options.push(new Option(`บอทเจนคลิป · ${label(connectedBots.clip)}`, "clip"));
  } else if (connectedBots.clipUsesMain && connectedBots.main?.saved) {
    options.push(new Option("บอทเจนคลิป · ใช้บอทหลักตัวเดียวกัน", "clip"));
  }
  for (const bot of connectedBots.extras) {
    const state = bot.chat_id ? `chat ${bot.chat_id}` : "ยังไม่ได้ทัก /start";
    options.push(new Option(
      `${bot.name} (${BOT_ROLE_LABEL[bot.role] || bot.role}) · ${state}`,
      `extra-${bot.id}`,
    ));
  }
  select.replaceChildren(
    options.length
      ? new Option(`บอทที่เชื่อมต่อ ${options.length} ตัว — เลือกดูรายชื่อ`, "")
      : new Option("— ยังไม่มีบอทเชื่อมต่อ —", ""),
    ...options,
  );
}

async function loadTelegram() {
  try {
    const payload = await api("/api/telegram/config");
    $("#telegramChat").value = payload.chat_id || "";
    $("#telegramAuto").checked = payload.auto_send;
    const ready = payload.token_saved && payload.chat_id;
    $("#telegramDot").className = `status-dot ${ready ? "ok" : payload.token_saved ? "fail" : ""}`;
    if (payload.token_saved) {
      $("#telegramToken").placeholder = "บันทึกโทเคนไว้แล้ว (ใส่ใหม่เพื่อเปลี่ยน)";
    }
    // ป้ายบอกว่าช่องนี้เป็นบอทตัวไหนจริงๆ — กันวางโทเคนผิดช่อง
    renderBotBadge("#mainBotWho", payload.bots?.main, "");
    renderBotBadge("#clipBotWho", payload.bots?.clip,
      payload.clip_uses_main ? "ไม่ได้ตั้ง — สายเจนคลิปใช้บอทหลักตัวเดียวกัน" : "");

    // บอทเจนคลิป — ตัวที่สอง ไม่ตั้งก็ใช้บอทข้างบนตัวเดียวเหมือนเดิม
    $("#clipBotChat").value = payload.clip_chat_id || "";
    const clipReady = payload.clip_token_saved && payload.clip_chat_id;
    $("#clipBotDot").className =
      `status-dot ${clipReady ? "ok" : payload.clip_token_saved ? "fail" : ""}`;
    if (payload.clip_token_saved) {
      $("#clipBotToken").placeholder = "บันทึกโทเคนไว้แล้ว (ใส่ใหม่เพื่อเปลี่ยน)";
    }
    connectedBots.main = payload.bots?.main || null;
    connectedBots.clip = payload.bots?.clip || null;
    connectedBots.clipUsesMain = Boolean(payload.clip_uses_main);
    renderBotOverview();
  } catch { /* ยังไม่ตั้งค่าก็ไม่ต้องรบกวน */ }
}

function renderBotBadge(target, info, emptyText) {
  const box = $(target);
  if (!box) return;
  if (!info || !info.saved) {
    box.textContent = emptyText || "ยังไม่ได้ตั้งบอทตัวนี้";
    box.className = "bot-who";
    return;
  }
  if (info.ok) {
    box.textContent = `@${info.username}` + (info.chat_id ? ` · chat ${info.chat_id}` : " · ยังไม่รู้ chat id");
    box.className = "bot-who ok";
  } else {
    box.textContent = `โทเคนใช้ไม่ได้ — ${info.error || "Telegram ปฏิเสธ"}`;
    box.className = "bot-who fail";
  }
}

async function saveBot(which, tokenId, chatId, noteId, buttonId) {
  $(buttonId).disabled = true;
  $(noteId).textContent = "กำลังเชื่อมบอท…";
  try {
    const payload = await api("/api/telegram/config", {
      method: "POST",
      body: JSON.stringify({
        bot: which,
        token: $(tokenId).value.trim(),
        chat_id: $(chatId).value.trim(),
        auto_send: $("#telegramAuto").checked,
      }),
    });
    $(tokenId).value = "";
    $(noteId).textContent = payload.message;
    await loadTelegram();
  } catch (error) {
    $(noteId).textContent = error.message;
  } finally {
    $(buttonId).disabled = false;
  }
}

async function testBot(which, noteId) {
  try {
    const payload = await api("/api/telegram/test", {
      method: "POST",
      body: JSON.stringify({ bot: which }),
    });
    $(noteId).textContent = payload.message;
  } catch (error) {
    $(noteId).textContent = error.message;
  }
}

// ---- บอทเพิ่มเติม (หลายตัว)
//
// รายการหน้าที่ **ต้องมาจากเซิร์ฟเวอร์** (`payload.roles` = BOT_ROLES ใน app.py)
// ห้าม hardcode ที่นี่ เดิมเขียนไว้แค่ 2 อัน (facebook/clip) ทั้งที่ระบบมี 4 อัน
// ผลคือผู้ใช้เลือก "engage" ไม่ได้เลย จึงตั้งบอทตามยอดเป็น role facebook แทน
// แล้ว app.py ไปเฝ้าอ่าน getUpdates ของโทเคนนั้น พอ fb_engage_bot.py อ่านด้วย
// = 409 Conflict ข้อความหายสลับไปมา (14 ส.ค. 2026)
let BOT_ROLE_LABEL = { facebook: "รับงานโพสต์", clip: "สายเจนคลิป" };

/** เติมตัวเลือกหน้าที่ในช่อง "เพิ่มบอทใหม่" ให้ตรงกับที่เซิร์ฟเวอร์รองรับจริง */
function syncBotRoles(roles) {
  if (!roles || !Object.keys(roles).length) return;
  BOT_ROLE_LABEL = roles;
  const picker = $("#botRole");
  if (!picker) return;
  const keep = picker.value;
  picker.replaceChildren(
    ...Object.entries(roles).map(([value, label]) => new Option(label, value)),
  );
  if (keep && roles[keep]) picker.value = keep;
}

async function loadBots() {
  try {
    const payload = await api("/api/telegram/bots");
    syncBotRoles(payload.roles);
    $("#botList").replaceChildren(
      ...payload.bots.map((bot) => {
        const row = document.createElement("li");
        row.className = "fb-group";

        const dot = document.createElement("span");
        dot.className = "status-dot " + (bot.watching && bot.chat_id ? "ok" : "fail");
        dot.title = bot.watching ? "กำลังรับข้อความ" : "ยังไม่ทำงาน";

        const name = document.createElement("input");
        name.type = "text";
        name.value = bot.name;
        name.addEventListener("change", () => saveExtraBot({ id: bot.id, name: name.value, role: bot.role }));

        const role = document.createElement("select");
        for (const [value, label] of Object.entries(BOT_ROLE_LABEL)) {
          role.append(new Option(label, value, false, bot.role === value));
        }
        role.addEventListener("change", () => saveExtraBot({ id: bot.id, name: name.value, role: role.value }));

        const chat = document.createElement("span");
        chat.className = "note";
        chat.textContent = bot.chat_id ? `chat ${bot.chat_id}` : "ยังไม่ได้ทัก /start";

        const test = document.createElement("button");
        test.type = "button";
        test.className = "ghost";
        test.textContent = "ทดสอบ";
        test.addEventListener("click", async () => {
          try {
            const result = await api(`/api/telegram/bots/${bot.id}/test`, { method: "POST" });
            $("#botNote").textContent = result.message;
          } catch (error) {
            $("#botNote").textContent = error.message;
          }
        });

        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "ghost danger";
        remove.textContent = "ลบ";
        remove.addEventListener("click", async () => {
          if (!confirm(`ลบบอท "${bot.name}" และโทเคนของมัน?`)) return;
          try {
            await api(`/api/telegram/bots/${bot.id}`, { method: "DELETE" });
            await loadBots();
            $("#botNote").textContent = "ลบบอทแล้ว";
          } catch (error) {
            $("#botNote").textContent = error.message;
          }
        });

        row.append(dot, name, role, chat, test, remove);
        return row;
      }),
    );
    if (!payload.bots.length) $("#botList").textContent = "";
    connectedBots.extras = payload.bots;
    renderBotOverview();
  } catch (error) {
    $("#botNote").textContent = error.message;
  }
}

// ชื่อต้องไม่ซ้ำกับ saveBot ของบอทหลัก/บอทคลิป — ประกาศชื่อเดียวกันสองที่
// ตัวหลังจะทับตัวแรกทั้งสโคป แล้วปุ่มบันทึกของบอทหลักจะส่ง "main" เป็น body
async function saveExtraBot(body) {
  try {
    const payload = await api("/api/telegram/bots", {
      method: "POST",
      body: JSON.stringify(body),
    });
    $("#botNote").textContent = payload.message;
    await loadBots();
  } catch (error) {
    $("#botNote").textContent = error.message;
  }
}

$("#botAdd").addEventListener("click", async () => {
  const token = $("#botToken").value.trim();
  if (!token) {
    $("#botNote").textContent = "วางโทเคนก่อน";
    return;
  }
  $("#botAdd").disabled = true;
  $("#botNote").textContent = "กำลังเชื่อมบอท…";
  await saveExtraBot({ token, name: $("#botName").value, role: $("#botRole").value });
  $("#botToken").value = "";
  $("#botName").value = "";
  $("#botAdd").disabled = false;
});

/* เอาบอทออกจากช่องตายตัว
 *
 * จำเป็นต้องมี เพราะเซิร์ฟเวอร์ **ห้ามเขียนทับบอทคนละตัว** แล้ว (ตอบ 409)
 * ถ้าไม่มีปุ่มนี้จะเปลี่ยนบอทของช่องไม่ได้เลย
 * การเปลี่ยนบอทจึงเป็นสองจังหวะ: ลบก่อน แล้วค่อยวางโทเคนใหม่ — วางผิดช่อง
 * จะไม่ทำให้บอทที่ใช้งานอยู่หายอีก (เคยหายมาแล้วสองครั้ง)
 */
async function deleteBotSlot(which, noteSelector, buttonSelector) {
  const label = which === "main" ? "บอทหลัก" : "บอทเจนคลิป";
  if (!window.confirm(
    `เอาบอทออกจากช่อง "${label}" ?\n\n` +
    "โทเคนจะถูกสำรองไว้ที่ data/bots_backup/ ก่อนลบ จึงกู้กลับได้"
  )) return;
  const button = $(buttonSelector);
  button.disabled = true;
  $(noteSelector).textContent = "กำลังลบ…";
  try {
    const payload = await api(`/api/telegram/config?bot=${which}`, { method: "DELETE" });
    $(noteSelector).textContent = payload.message;
    await loadTelegram();
  } catch (error) {
    $(noteSelector).textContent = error.message;
  }
  button.disabled = false;
}

$("#telegramSave").addEventListener("click", () =>
  saveBot("main", "#telegramToken", "#telegramChat", "#telegramNote", "#telegramSave"));
$("#telegramTest").addEventListener("click", () => testBot("main", "#telegramNote"));
$("#telegramDelete").addEventListener("click", () =>
  deleteBotSlot("main", "#telegramNote", "#telegramDelete"));
$("#clipBotSave").addEventListener("click", () =>
  saveBot("clip", "#clipBotToken", "#clipBotChat", "#clipBotNote", "#clipBotSave"));
$("#clipBotTest").addEventListener("click", () => testBot("clip", "#clipBotNote"));
$("#clipBotDelete").addEventListener("click", () =>
  deleteBotSlot("clip", "#clipBotNote", "#clipBotDelete"));

// ------------------------------------------------ ฟาร์มโปรไฟล์บอท (Chrome)
// เก็บผลโยง 2 ฝั่งไว้ให้ตัวช่วยอื่น (hint ใต้ dropdown) ใช้ต่อได้โดยไม่ต้อง fetch ซ้ำ
let farmSourceCounts = {};
let farmSourceNames = {};

function updateFarmSourceHint() {
  const folder = $("#farmSource").value;
  const n = farmSourceCounts[folder] || 0;
  const hint = $("#farmSourceHint");
  if (!hint) return;
  hint.textContent = n
    ? `โปรไฟล์นี้นำเข้าไปแล้ว ${n} ตัว — กดเพิ่มได้อีกถ้าต้องการหลายบอทจากบัญชีเดียวกัน`
    : "";
}

// stamp สำรองเก็บเป็น YYYYMMDD-HHMMSS — โชว์ให้อ่านง่ายเป็น วว/ดด HH:MM
function formatBackupStamp(stamp) {
  const m = String(stamp).match(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})/);
  return m ? `${m[3]}/${m[2]} ${m[4]}:${m[5]}` : stamp;
}

// แก้ชื่อบอทแบบ inline — คลิกชื่อ → กลายเป็นช่องพิมพ์ Enter บันทึก Esc ยกเลิก
// ไม่ reload ทั้งลิสต์ (แค่สลับ text กลับ) ตำแหน่งแถวจึงไม่ขยับ
function startRenameFarm(nameEl, prof) {
  const input = document.createElement("input");
  input.type = "text";
  input.value = prof.name;
  input.className = "farm-name-edit";
  input.setAttribute("aria-label", "แก้ชื่อบอท");
  nameEl.replaceWith(input);
  input.focus();
  input.select();
  let done = false;
  const finish = async (save) => {
    if (done) return;
    done = true;
    const newName = input.value.trim();
    if (save && newName && newName !== prof.name) {
      try {
        const result = await api(`/api/botfarm/${prof.id}/rename`, {
          method: "POST", body: JSON.stringify({ name: newName }),
        });
        prof.name = result.name;
        nameEl.textContent = result.name;
        $("#farmNote").textContent = result.message;
      } catch (error) {
        $("#farmNote").textContent = error.message;
      }
    }
    input.replaceWith(nameEl);
  };
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); finish(true); }
    else if (event.key === "Escape") { event.preventDefault(); finish(false); }
  });
  input.addEventListener("blur", () => finish(true));
}

async function loadFarm() {
  try {
    const payload = await api("/api/botfarm");
    $("#farmMax").value = payload.max_concurrent;
    $("#farmRunning").textContent =
      payload.running_count ? `กำลังวิ่ง ${payload.running_count} ตัว` : "";
    $("#farmDot").className = `status-dot ${payload.running_count ? "ok" : ""}`;
    $("#farmChromeWarn").hidden = !payload.chrome_running;

    // โยงข้อมูล 2 ฝั่ง: นับว่าแต่ละโปรไฟล์ Chrome ถูกนำเข้าไปแล้วกี่ตัว + ชื่อจริง
    farmSourceCounts = {};
    farmSourceNames = {};
    for (const p of payload.chrome_profiles) farmSourceNames[p.folder] = p.name;
    for (const prof of payload.profiles) {
      farmSourceCounts[prof.source] = (farmSourceCounts[prof.source] || 0) + 1;
    }

    // dropdown ต้นทาง — ติดเครื่องหมายว่าตัวไหน "นำเข้าแล้ว" (พร้อมจำนวนถ้าซ้ำ)
    const keep = $("#farmSource").value;
    $("#farmSource").replaceChildren(...payload.chrome_profiles.map((p) => {
      const n = farmSourceCounts[p.folder] || 0;
      const mark = n ? `  ✓ นำเข้าแล้ว${n > 1 ? ` ×${n}` : ""}` : "";
      return new Option(
        `${p.folder} — ${p.name}${p.email ? ` (${p.email})` : ""}${mark}`, p.folder);
    }));
    if ([...$("#farmSource").options].some((o) => o.value === keep)) {
      $("#farmSource").value = keep;
    }
    updateFarmSourceHint();

    // รายการโปรไฟล์บอทที่นำเข้าแล้ว
    $("#farmList").replaceChildren(...payload.profiles.map((prof) => {
      const row = document.createElement("li");
      row.className = "farm-row";

      const dot = document.createElement("span");
      dot.className = "status-dot " + (prof.running ? "ok" : "");
      dot.title = prof.running ? "กำลังวิ่ง" : "ปิดอยู่";

      const name = document.createElement("strong");
      name.textContent = prof.name;
      name.className = "farm-name";
      name.title = "คลิกเพื่อแก้ชื่อ";
      name.addEventListener("click", () => startRenameFarm(name, prof));

      const src = document.createElement("span");
      src.className = "note";
      const srcName = farmSourceNames[prof.source];
      src.textContent =
        (prof.source
          ? `จาก ${prof.source}` + (srcName ? ` (${srcName})` : " · ต้นทางหายจาก Chrome แล้ว")
          : "สร้างเอง") +
        (prof.refreshed ? ` · รีเฟรช ${prof.refreshed}` : "") +
        (prof.backed_up ? ` · สำรอง ${formatBackupStamp(prof.backed_up)}` : "");

      // ติ๊ก "รีเฟรชก่อนเปิด" — ดึงล็อกอินล่าสุดจาก Chrome จริงมาทับก่อนเปิดทุกครั้ง
      const refWrap = document.createElement("label");
      refWrap.className = "farm-refresh";
      const refBox = document.createElement("input");
      refBox.type = "checkbox";
      refBox.checked = prof.auto_refresh !== false;
      refBox.addEventListener("change", async () => {
        try {
          await api(`/api/botfarm/${prof.id}/auto-refresh`, {
            method: "POST", body: JSON.stringify({ value: refBox.checked }),
          });
        } catch (error) {
          $("#farmNote").textContent = error.message;
        }
      });
      refWrap.append(refBox, document.createTextNode(" รีเฟรชก่อนเปิด"));

      const open = document.createElement("button");
      open.type = "button";
      open.className = prof.running ? "ghost" : "primary";
      open.textContent = prof.running ? "เปิดอยู่" : "เปิดล็อกอิน";
      open.disabled = prof.running;
      open.title = "เปิด Chrome ของบอทตัวนี้ขึ้นมาใช้มือล็อกอินเว็บทิ้งไว้";
      open.addEventListener("click", async () => {
        open.disabled = true;
        try {
          const result = await api(`/api/botfarm/${prof.id}/launch`, {
            method: "POST", body: JSON.stringify({}),
          });
          $("#farmNote").textContent = result.message;
        } catch (error) {
          $("#farmNote").textContent = error.message;
        }
        await loadFarm();
      });

      const refresh = document.createElement("button");
      refresh.type = "button";
      refresh.className = "ghost";
      refresh.textContent = "รีเฟรช";
      refresh.title = "ดึงล็อกอินล่าสุดจาก Chrome จริงมาทับเดี๋ยวนี้";
      refresh.disabled = prof.running;
      refresh.addEventListener("click", async () => {
        refresh.disabled = true;
        try {
          const result = await api(`/api/botfarm/${prof.id}/refresh`, {
            method: "POST", body: JSON.stringify({}),
          });
          $("#farmNote").textContent = result.message;
        } catch (error) {
          $("#farmNote").textContent = error.message;
        }
        await loadFarm();
      });

      const stop = document.createElement("button");
      stop.type = "button";
      stop.className = "ghost";
      stop.textContent = "ปิด";
      stop.disabled = !prof.running;
      stop.addEventListener("click", async () => {
        try {
          const result = await api(`/api/botfarm/${prof.id}/stop`, {
            method: "POST", body: JSON.stringify({}),
          });
          $("#farmNote").textContent = result.message;
        } catch (error) {
          $("#farmNote").textContent = error.message;
        }
        await loadFarm();
      });

      // กู้ล็อกอินจากชุดสำรองล่าสุด — โผล่เฉพาะโปรไฟล์ที่เคยสำรองไว้แล้ว
      const restore = document.createElement("button");
      restore.type = "button";
      restore.className = "ghost";
      restore.textContent = "กู้ล็อกอิน";
      restore.title = "เอาคุกกี้/ล็อกอินจากชุดสำรองล่าสุดกลับมา";
      restore.hidden = !prof.backed_up;
      restore.disabled = prof.running;
      restore.addEventListener("click", async () => {
        if (!confirm(`กู้ล็อกอินของ "${prof.name}" จากชุดสำรองล่าสุด? ของที่อยู่ตอนนี้จะถูกทับ`)) return;
        restore.disabled = true;
        try {
          const result = await api(`/api/botfarm/${prof.id}/restore`, {
            method: "POST", body: JSON.stringify({}),
          });
          $("#farmNote").textContent = result.message;
        } catch (error) {
          $("#farmNote").textContent = error.message;
        }
        await loadFarm();
      });

      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "ghost danger";
      remove.textContent = "ลบ";
      remove.addEventListener("click", async () => {
        if (!confirm(`ลบโปรไฟล์บอท "${prof.name}"? (ย้ายลงถังขยะ กู้คืนได้ที่ data/bot_profiles/_trash)`)) return;
        try {
          const result = await api(`/api/botfarm/${prof.id}`, { method: "DELETE" });
          $("#farmNote").textContent = result.message;
        } catch (error) {
          $("#farmNote").textContent = error.message;
        }
        await loadFarm();
      });

      row.append(dot, name, src, refWrap, open, refresh, stop, restore, remove);
      return row;
    }));
    // ข้อความ "ยังว่าง" ใส่ในลิสต์ ไม่ใช่ #farmNote — ไม่งั้นมันจะเขียนทับ
    // ผลของการกดนำเข้า/error ที่เพิ่งแสดง (นี่คือเหตุที่บอทนำเข้าแล้วดู "ไม่ขึ้น")
    if (!payload.profiles.length) {
      const empty = document.createElement("li");
      empty.className = "note";
      empty.textContent = "ยังไม่มีโปรไฟล์บอท — เลือกโปรไฟล์ Chrome ข้างล่างแล้วกดนำเข้า";
      $("#farmList").replaceChildren(empty);
    }
  } catch (error) {
    $("#farmNote").textContent = error.message;
  }
}

$("#farmImport").addEventListener("click", async () => {
  $("#farmImport").disabled = true;
  $("#farmNote").textContent = "กำลังคัดลอกโปรไฟล์… (โปรไฟล์ใหญ่อาจใช้เวลาเป็นนาที)";
  try {
    const result = await api("/api/botfarm/import", {
      method: "POST",
      body: JSON.stringify({ source: $("#farmSource").value, name: $("#farmName").value }),
    });
    $("#farmNote").textContent = result.message;
    $("#farmName").value = "";
  } catch (error) {
    $("#farmNote").textContent = error.message;
  } finally {
    $("#farmImport").disabled = false;
  }
  await loadFarm();
});

$("#farmSource").addEventListener("change", updateFarmSourceHint);

$("#farmMaxSave").addEventListener("click", async () => {
  try {
    const result = await api("/api/botfarm/settings", {
      method: "POST",
      body: JSON.stringify({ max_concurrent: Number($("#farmMax").value) || 3 }),
    });
    $("#farmNote").textContent = result.message;
  } catch (error) {
    $("#farmNote").textContent = error.message;
  }
});

// =============================================================== log
const LOG_TABS = ["input", "gems", "gen_pic", "gen_video", "judge", "release", "publish"];

// **ถามเฉพาะกล่องที่คนกำลังมองอยู่จริง**
// ของเดิมยิงครบทั้ง 7 กล่องทุก 3 วินาทีไม่ว่าจะเปิดค้างไว้ที่แท็บไหน วัดบนหน้าเว็บ
// จริงได้ 147 request/นาที จากทั้งหมด 177 — และตอนที่วัด แท็บที่เปิดอยู่คือ
// "สตอรีบอร์ด" ซึ่งไม่มีกล่อง log สักกล่อง แปลว่าเสียเปล่าทั้ง 147 ในจังหวะนั้น
// เรื่องนี้หนักขึ้นตั้งแต่เปิดใช้ผ่าน Tailscale เพราะกินเน็ต 5G ตลอดเวลาแม้ปิดจอทิ้งไว้
//
// จังหวะตอนกำลังดูอยู่ยังเป็น 3 วินาทีเท่าเดิม — ไม่ได้แลกความสดของ log ไปกับอะไรเลย
export function onScreen(el) {
  // offsetParent เป็น null เมื่อตัวมันเองหรือบรรพบุรุษถูกซ่อน ครอบคลุมทั้ง [hidden]
  // ของแท็บและ display:none ที่อาจมาจากที่อื่น — เช็คที่ผลลัพธ์จริงบนจอ ไม่ใช่เดาจาก id
  return !!el && el.offsetParent !== null;
}

export async function pollLogs() {
  if (document.hidden) return;   // สลับไปแท็บอื่นของเบราว์เซอร์ / ปิดจอมือถือ
  for (const tab of LOG_TABS) {
    const box = document.querySelector(`#log-${tab}`);
    if (!onScreen(box)) continue;
    try {
      const payload = await api(`/api/logs/${tab}`);
      const text = (payload.lines || []).join("\n");
      if (box.textContent !== text) {
        box.textContent = text;
        box.scrollTop = box.scrollHeight;
      }
    } catch { /* log อ่านไม่ได้ไม่ต้องพังหน้า */ }
  }
}
window.setInterval(pollLogs, 3000);

// ============================================================ ตั้งค่า (D)
const dialog = $("#settingsDialog");
$("#openSettings").addEventListener("click", () => {
  fillSettings();
  dialog.showModal();
  testKeys();
  hooks.loadAccessDevices();   // อยู่ใน phone.js — เรียกผ่าน hooks กัน import วงกลม
  loadTelegram();
  loadBots();
  loadFarm();
});
$("#settingsClose").addEventListener("click", () => dialog.close());

function fillSettings() {
  const settings = config.settings;
  document.querySelector(`input[name="videoMode"][value="${settings.video_mode}"]`).checked = true;
  document.querySelector(`input[name="frameRatio"][value="${settings.frame}"]`).checked = true;
  document.querySelector(`input[name="omniDur"][value="${settings.omni_duration}"]`).checked = true;
  $("#imageModel").value = settings.image_model;
  renderModels();
}

function renderModels() {
  const mode = document.querySelector('input[name="videoMode"]:checked')?.value || "frame";
  const list = $("#modelList");
  list.replaceChildren(
    ...Object.entries(system.video_models).map(([value, text]) => {
      const label = document.createElement("label");
      // ติ๊ก Common แล้วเหลือให้เลือกแค่ 2 ตัวตามผัง
      const allowed = mode === "frame" || system.common_models.includes(value);
      if (!allowed) label.className = "disabled";
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "videoModel";
      radio.value = value;
      radio.disabled = !allowed;
      radio.checked = config.settings.video_model === value && allowed;
      radio.addEventListener("change", updateDuration);
      label.append(radio, document.createTextNode(text));
      return label;
    }),
  );
  // โมเดลเดิมใช้ไม่ได้ในโหมดนี้ → เลือกตัวแรกที่อนุญาตให้แทน
  if (!list.querySelector("input:checked")) {
    const first = list.querySelector("input:not(:disabled)");
    if (first) first.checked = true;
  }
  updateDuration();
}

function updateDuration() {
  const model = document.querySelector('input[name="videoModel"]:checked')?.value;
  // เวลาเลือกได้เฉพาะ Omni Flash — ตามผัง
  $("#durationRow").hidden = model !== "omni_flash";
}

document.querySelectorAll('input[name="videoMode"]').forEach((radio) => {
  radio.addEventListener("change", renderModels);
});

$("#settingsSave").addEventListener("click", async () => {
  try {
    const payload = await api("/api/settings", {
      method: "POST",
      body: JSON.stringify({
        video_mode: document.querySelector('input[name="videoMode"]:checked').value,
        frame: document.querySelector('input[name="frameRatio"]:checked').value,
        video_model: document.querySelector('input[name="videoModel"]:checked')?.value,
        omni_duration: Number(document.querySelector('input[name="omniDur"]:checked').value),
        image_model: $("#imageModel").value,
      }),
    });
    config.settings = payload.settings;
    $("#settingsNote").textContent = "บันทึกตั้งค่าแล้ว ✓";
  } catch (error) {
    $("#settingsNote").textContent = error.message;
  }
});

async function saveKey(url, inputId, noteId) {
  const input = $(inputId);
  try {
    await api(url, { method: "POST", body: JSON.stringify({ key: input.value }) });
    input.value = "";
    $(noteId).textContent = "บันทึกแล้ว — กำลังทดสอบ";
    await testKeys();
  } catch (error) {
    $(noteId).textContent = error.message;
  }
}

$("#geminiSave").addEventListener("click", () => saveKey("/api/gemini-key", "#geminiKey", "#geminiNote"));
$("#claudeSave").addEventListener("click", () => saveKey("/api/claude-key", "#claudeKey", "#claudeNote"));
$("#geminiClear").addEventListener("click", async () => {
  await api("/api/gemini-key", { method: "POST", body: JSON.stringify({ clear: true }) });
  $("#geminiNote").textContent = "ลบ key แล้ว";
  testKeys();
});
$("#claudeClear").addEventListener("click", async () => {
  await api("/api/claude-key", { method: "POST", body: JSON.stringify({ clear: true }) });
  $("#claudeNote").textContent = "ลบ key แล้ว";
  testKeys();
});

// ====================================================== แถบสถานะระบบ
//
// **ทำไมต้องมี** ระบบนี้มีหลายโปรเซสที่ตายเงียบได้ (สายคลิป 8877 ตายมาแล้ว
// 2 ครั้งในสัปดาห์เดียว) ที่ผ่านมารู้ตัวตอน "พิมพ์คำสั่งแล้วบอทเงียบ" ซึ่งสายเกินไป
//
// **ตั้งใจให้เบามาก** ยิงแค่ 2 ปลายทางทุก 15 วินาที (8 ครั้ง/นาที)
//   · ห้ามยิง /api/devices — ปลายทางนั้นสั่ง `adb devices` จริง ถ้าถามทุก 15 วิ
//     จะไปแย่งจังหวะกับงานที่กำลังแตะจอมือถืออยู่ จำนวนมือถือจึงอ่านจาก
//     dropdown ที่โหลดไว้แล้วแทน (ฟรี ไม่มี request เพิ่ม)
//   · จำนวนงานรออนุมัติเอาจาก health ของสายคลิปที่ต้องถามอยู่แล้ว ไม่ถามเพิ่ม
const HEALTH_EVERY_MS = 15000;

function healthChip(ok, label, detail = "") {
  const chip = document.createElement("span");
  chip.className = "health-chip " + (ok ? "ok" : "down");
  chip.textContent = label;
  if (detail) chip.title = detail;
  return chip;
}

export async function pollHealth() {
  if (document.hidden) return;   // ไม่มีคนดูแถบสถานะ ก็ไม่ต้องถาม
  const strip = $("#healthStrip");
  if (!strip) return;
  const chips = [];

  // 1) เซิร์ฟเวอร์หน้าเว็บเอง — ตัวนี้ล้ม = หน้าเว็บที่เห็นอยู่คือของค้าง
  let webOk = true;
  try {
    await api("/api/system");
  } catch (error) {
    webOk = false;
  }
  chips.push(healthChip(webOk, webOk ? "เว็บ" : "เว็บหลุด",
    webOk ? "เซิร์ฟเวอร์ 8866 ตอบปกติ"
          : "ต่อ 8866 ไม่ได้ — ที่เห็นอยู่บนจอคือข้อมูลค้าง"));

  // 2) สายคลิป (คนละโปรเซส คนละพอร์ต) + จำนวนงานที่รอคนตัดสิน
  let waiting = null;
  try {
    const clip = await (await fetch(`${CLIP_API}/api/health`)).json();
    const bot = (clip.clip_bot || {}).username || "";
    waiting = typeof clip.queue === "number" ? clip.queue : null;
    chips.push(healthChip(true, "คลิป",
      `8877 ปกติ${bot ? ` · บอท @${bot}` : ""}${clip.busy ? " · กำลังทำงาน" : ""}`));
  } catch (error) {
    chips.push(healthChip(false, "คลิปหลุด",
      "ต่อ 8877 ไม่ได้ — บอทสายคลิปจะเงียบ สั่งคำสั่งไปก็ไม่มีใครรับ"));
  }

  // 3) มือถือที่ต่ออยู่ — อ่านจาก dropdown ที่โหลดไว้แล้ว ไม่ยิง ADB ซ้ำ
  const phones = [...document.querySelectorAll("#deviceSelect option")]
    .filter((o) => o.value).length;
  chips.push(healthChip(phones > 0, phones ? `มือถือ ${phones}` : "ไม่มีมือถือ",
    phones ? "" : "ต่อ USB แล้วกดรีเฟรชรายการเครื่อง"));

  // 3.5) แรม/เนื้อที่ของมือถือแต่ละเครื่อง
  //
  // **ทำไมต้องอยู่บนหัวจอ** 25 ส.ค. 2569 มือถือขึ้น "หน่วยความจำไม่พอ" ตอนเปิดแอป
  // แล้วไล่หาสาเหตุอยู่นานเพราะไม่มีตัวเลขให้ดูเลย ต้องต่อ ADB เข้าไปอ่านเอง
  // ตัวเลขจริงตอนนั้น: แรมว่าง 0.11 GB จาก 5.52 GB แต่เนื้อที่เก็บของว่างตั้ง 85 GB
  // — **คนละเรื่องกันคนละตัว** ถ้าโชว์รวมเป็นค่าเดียวจะพาไปไล่ผิดทางอีก
  if (phones) {
    try {
      const health = await api("/api/phone/health");
      for (const device of (health.devices || []).filter((d) => d.ok)) {
        // ชื่อเครื่องยาว ("REDMI 15C - โพสต์ 2") ตัดให้พอดีแถบ รายละเอียดเต็มอยู่ใน title
        const short = String(device.label || device.serial).split(" - ").pop().slice(0, 12);
        const chip = healthChip(
          !device.need_clean,
          `📱 ${short} ${device.ram_pct}%`,
          `${device.label}\n${device.text}\n`
          + (device.need_clean
            ? `⚠️ ${device.why_clean || "เต็ม"} — ระบบจะเคลียร์ให้เอง `
              + "โดยรอจนงานที่ทำอยู่จบก่อน"
            : `ยังไม่ถึงเพดาน (แรม ${device.limit}% · `
              + `ที่ช้า ${device.swap_limit_gb} GB)`),
        );
        if (device.cleaning) {
          chip.textContent = `📱 ${short} กำลังเคลียร์…`;
          chip.className = "health-chip waiting";
        }
        chips.push(chip);
      }
    } catch {
      // อ่านไม่ได้ก็แค่ไม่โชว์ ห้ามทำให้แถบสถานะทั้งแถบหาย
    }
  }

  // 4) งานรออนุมัติ — ตัวเลขที่ค้างนานที่สุดในระบบ กดแล้วพาไปแท็บสตอรีบอร์ดเลย
  if (waiting) {
    const jump = document.createElement("button");
    jump.type = "button";
    jump.className = "health-chip waiting";
    // ตัวเลขนี้คือ "งานที่ยังไม่จบ" (clip_jobs.waiting = งานที่ stage ยังเปิดอยู่)
    // ไม่ใช่ "งานที่รอคนกดอนุมัติ" ซึ่งมักน้อยกว่ามาก — ป้ายเดิมเขียนว่า "รอตัดสิน"
    // ทำให้เข้าใจว่ามีงานรอกดเป็นสิบทั้งที่จริงรอกดใบเดียว
    jump.textContent = `⏳ คลิปค้าง ${waiting}`;
    jump.title = "งานคลิปที่ยังไม่จบ — กดเพื่อไปแท็บสตอรีบอร์ด";
    jump.addEventListener("click", () => {
      const tab = document.querySelector('.tab[data-tab="story"]');
      if (tab) tab.click();
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
    chips.push(jump);
  }

  strip.replaceChildren(...chips);
}

window.setInterval(pollHealth, HEALTH_EVERY_MS);

// กลับมาที่แท็บนี้เมื่อไรให้เห็นของสดทันที ไม่ต้องรอครบรอบ — ถ้าไม่มีบรรทัดนี้
// การหยุดถามตอนซ่อนจะกลายเป็น "กลับมาแล้วเห็นข้อมูลค้าง" ซึ่งแย่กว่าเดิม
document.addEventListener("visibilitychange", () => {
  if (document.hidden) return;
  pollLogs();
  pollHealth();
});

async function testKeys() {
  // ไฟสถานะ = ยิงเรียกจริง ไม่ใช่แค่เช็คว่ามีไฟล์ key
  for (const [url, dotId, noteId] of [
    ["/api/gemini-key/test", "#geminiStatus", "#geminiNote"],
    ["/api/claude-key/test", "#claudeStatus", "#claudeNote"],
  ]) {
    try {
      const payload = await api(url, { method: "POST" });
      $(dotId).className = "status-dot " + (payload.ok ? "ok" : "fail");
      $(noteId).textContent = payload.detail || "";
    } catch (error) {
      $(dotId).className = "status-dot fail";
      $(noteId).textContent = error.message;
    }
  }
}
