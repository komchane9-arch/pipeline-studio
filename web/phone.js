/* จอมือถือ: สตรีม H.264 · แตะ/ลาก · ปุ่มลัด · ลิงก์คอม↔มือถือ · ส่งคลิป · Wi-Fi · อนุญาตอุปกรณ์ */

import { $, api, hooks, onScreen } from "./core.js";

// ========================================================== จอมือถือ (A)
export const deviceSelect = $("#deviceSelect");
const phoneScreen = $("#phoneScreen");
const phoneCanvas = $("#phoneCanvas");
const placeholder = $("#phonePlaceholder");
const phoneNote = $("#phoneNote");
let screenTimer = null;

// ---- สตรีม H.264 หน่วงต่ำ (ยกจากโปรเจกต์เดิม)
// ถอดด้วย WebCodecs ในเบราว์เซอร์ — เบราว์เซอร์ที่ไม่รองรับถอยไปภาพนิ่ง
let streamSocket = null;
let decoder = null;
let canvasContext = null;
let waitingKeyFrame = true;
let frameCounter = 0;

const supportsWebCodecs = typeof window.VideoDecoder === "function";

function closeStream() {
  if (streamSocket) {
    streamSocket.onclose = null;
    streamSocket.close();
    streamSocket = null;
  }
  if (decoder && decoder.state !== "closed") {
    try { decoder.close(); } catch { /* ปิดซ้ำไม่เป็นไร */ }
  }
  decoder = null;
  waitingKeyFrame = true;
}

function startStream(serial) {
  closeStream();
  canvasContext = canvasContext || phoneCanvas.getContext("2d");
  decoder = new VideoDecoder({
    output: (frame) => {
      if (phoneCanvas.width !== frame.displayWidth) {
        phoneCanvas.width = frame.displayWidth;
        phoneCanvas.height = frame.displayHeight;
      }
      canvasContext.drawImage(frame, 0, 0);
      frame.close();
      phoneCanvas.hidden = false;
      phoneScreen.hidden = true;
      placeholder.hidden = true;
      $("#phoneHint").hidden = false;
    },
    error: () => { waitingKeyFrame = true; },
  });
  decoder.configure({ codec: "avc1.42E01E", optimizeForLatency: true });

  const protocol = location.protocol === "https:" ? "wss" : "ws";
  streamSocket = new WebSocket(
    `${protocol}://${location.host}/ws/phone/stream?serial=${encodeURIComponent(serial)}`,
  );
  streamSocket.binaryType = "arraybuffer";
  // เซิร์ฟเวอร์ส่งมาทีละ NAL แต่ VideoDecoder ต้องได้ "ทั้งเฟรม" ต่อ chunk
  // ป้อน SPS เดี่ยวๆ = decoder error แล้วปิดตัวทันที (อาการที่เจอจริง: ภาพไม่ขึ้นเลย)
  // จึงเก็บ SPS/PPS ไว้แล้วแปะหน้า IDR เป็นคีย์เฟรมก้อนเดียว
  let sps = null;
  let pps = null;
  streamSocket.onmessage = (event) => {
    if (typeof event.data === "string") {
      phoneNote.textContent = JSON.parse(event.data).error || "";
      return;
    }
    const data = new Uint8Array(event.data);
    const nalType = data[4] & 0x1f;
    if (nalType === 7) { sps = data; return; }
    if (nalType === 8) { pps = data; return; }
    if (!decoder || decoder.state !== "configured") return;

    let chunkData = data;
    let type = "delta";
    if (nalType === 5) {
      type = "key";
      if (sps && pps) {
        chunkData = new Uint8Array(sps.length + pps.length + data.length);
        chunkData.set(sps, 0);
        chunkData.set(pps, sps.length);
        chunkData.set(data, sps.length + pps.length);
      }
      waitingKeyFrame = false;
    } else if (waitingKeyFrame || nalType !== 1) {
      return;   // ยังไม่เจอคีย์เฟรม หรือเป็น NAL ที่ไม่ใช่ภาพ (SEI/AUD)
    }
    try {
      decoder.decode(new EncodedVideoChunk({
        type,
        timestamp: (frameCounter += 1) * 16666,   // ต้องเพิ่มขึ้นเรื่อยๆ
        data: chunkData,
      }));
    } catch {
      waitingKeyFrame = true;
    }
  };
  streamSocket.onclose = () => {
    if ($("#stopScreen").disabled) return;   // ผู้ใช้กดหยุดเอง
    phoneNote.textContent = "สตรีมหลุด — ถอยไปใช้ภาพนิ่ง";
    startPolling();
  };
}

export async function loadDevices() {
  try {
    const payload = await api("/api/devices");
    const devices = payload.devices || [];
    deviceSelect.replaceChildren(
      ...(devices.length
        ? devices.map((device) => {
            const option = document.createElement("option");
            option.value = device.serial;
            // ชื่อที่ผู้ใช้ตั้งมาก่อนชื่อรุ่น — ตั้งไว้เพื่อให้จำเครื่องออก
            option.textContent =
              `${device.custom_name || device.model || device.serial} · ${device.serial}`;
            return option;
          })
        : [new Option("ไม่พบมือถือ — เสียบสายแล้วกดรีเฟรช", "")]),
    );
    $("#startScreen").disabled = !deviceSelect.value;
  } catch (error) {
    phoneNote.textContent = error.message;
  }
}

$("#renameDevice").addEventListener("click", async () => {
  if (!deviceSelect.value) {
    phoneNote.textContent = "เลือกมือถือก่อน";
    return;
  }
  const current = deviceSelect.selectedOptions[0]?.textContent.split(" · ")[0] || "";
  const name = window.prompt("ตั้งชื่อเครื่องนี้ (เว้นว่าง = ลบชื่อ)", current);
  if (name === null) return;
  try {
    await api("/api/device-name", {
      method: "POST",
      body: JSON.stringify({ serial: deviceSelect.value, name }),
    });
    const keep = deviceSelect.value;
    await loadDevices();
    deviceSelect.value = keep;
    phoneNote.textContent = name.trim() ? `ตั้งชื่อ "${name.trim()}" แล้ว` : "ลบชื่อแล้ว";
  } catch (error) {
    phoneNote.textContent = error.message;
  }
});

function refreshFrame() {
  if (!deviceSelect.value) return;
  const image = new Image();
  image.onload = () => {
    phoneScreen.src = image.src;
    phoneScreen.hidden = false;
    phoneCanvas.hidden = true;
    placeholder.hidden = true;
    $("#phoneHint").hidden = false;
    // เฟรมถัดไปหลังเฟรมนี้โหลดเสร็จ — ไม่ยิงถี่เกินให้ ADB อ่วม
    screenTimer = window.setTimeout(refreshFrame, 900);
  };
  image.onerror = () => {
    phoneNote.textContent = "อ่านหน้าจอไม่ได้ — เช็คสาย/สิทธิ์ debugging";
    stopScreen();
  };
  image.src = `/api/screen?serial=${encodeURIComponent(deviceSelect.value)}&t=${Date.now()}`;
}

function startPolling() {
  if (screenTimer) window.clearTimeout(screenTimer);
  refreshFrame();
}

function stopScreen() {
  if (screenTimer) window.clearTimeout(screenTimer);
  screenTimer = null;
  closeStream();
  closeTouchSocket();
  $("#startScreen").disabled = !deviceSelect.value;
  $("#stopScreen").disabled = true;
}

$("#startScreen").addEventListener("click", async () => {
  const serial = deviceSelect.value;
  if (!serial) return;
  $("#startScreen").disabled = true;
  $("#stopScreen").disabled = false;
  phoneNote.textContent = "กำลังเปิด…";
  // เปิดช่องแตะเรียลไทม์ล่วงหน้า — push scrcpy-server กินเวลาหลักวินาที
  // ถ้าไปทำตอนแตะครั้งแรกผู้ใช้จะรู้สึกว่าคลิกแรกหน่วง
  try {
    const session = await api("/api/phone/session", {
      method: "POST",
      body: JSON.stringify({ serial }),
    });
    realtimeTouch = session.realtime;
    phoneNote.textContent = session.realtime
      ? "แตะแบบเรียลไทม์พร้อม (กดค้าง/ลากได้)"
      : `แตะทีละครั้ง — ${session.reason || "ไม่มีช่องเรียลไทม์"}`;
    if (session.realtime) openTouchSocket(serial);
  } catch (error) {
    phoneNote.textContent = error.message;
  }
  if (supportsWebCodecs) startStream(serial);
  else {
    phoneNote.textContent += " · เบราว์เซอร์ไม่รองรับ WebCodecs ใช้ภาพนิ่ง";
    startPolling();
  }
});
$("#stopScreen").addEventListener("click", stopScreen);
$("#refreshDevices").addEventListener("click", loadDevices);
deviceSelect.addEventListener("change", () => {
  stopScreen();
  $("#startScreen").disabled = !deviceSelect.value;
});

// ---------------------------------------------- แตะ/กดค้าง/ลาก (ยกจากของเดิม)
// ตัวดักการแตะจอ — ฝั่ง Publish (post.js) เป็นคนตั้ง ไฟล์นี้เป็นคนเรียกตอนมีคนแตะจอ
// เก็บเป็น property ของ object เพราะ ESM ห้ามไฟล์อื่นเขียนทับ "ตัวแปร" ที่ import มา
export const touchIntercept = { fn: null };   // Publish ใช้ดักตอนเทรนตำแหน่ง
let realtimeTouch = false;
let touchSocket = null;
let holdState = null;
let lastMoveSent = 0;
const MOVE_INTERVAL_MS = 8;     // ~120 event/วินาที เท่านิ้วจริง

function openTouchSocket(serial) {
  closeTouchSocket();
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  touchSocket = new WebSocket(
    `${protocol}://${location.host}/ws/phone/input?serial=${encodeURIComponent(serial)}`,
  );
  touchSocket.onmessage = (event) => {
    const payload = JSON.parse(event.data || "{}");
    if (payload.error) phoneNote.textContent = payload.error;
  };
  touchSocket.onclose = () => { touchSocket = null; };
}

function closeTouchSocket() {
  if (touchSocket) {
    touchSocket.onclose = null;
    touchSocket.close();
    touchSocket = null;
  }
  holdState = null;
}

/** ภาพที่กำลังแสดงอยู่ (canvas สตรีม หรือ img ภาพนิ่ง) */
function activeSurface() {
  return phoneCanvas.hidden ? phoneScreen : phoneCanvas;
}

function pointFrom(event) {
  const surface = activeSurface();
  const width = surface === phoneCanvas ? surface.width : surface.naturalWidth;
  const height = surface === phoneCanvas ? surface.height : surface.naturalHeight;
  const rect = surface.getBoundingClientRect();
  if (!width || !height || !rect.width || !rect.height) return null;
  // ภาพ object-fit:contain — พื้นที่จริงของภาพเล็กกว่ากรอบ ต้องหักขอบดำออก
  const scale = Math.min(rect.width / width, rect.height / height);
  if (!Number.isFinite(scale) || scale <= 0) return null;
  const drawnW = width * scale;
  const drawnH = height * scale;
  const offsetX = rect.left + (rect.width - drawnW) / 2;
  const offsetY = rect.top + (rect.height - drawnH) / 2;
  const x = Math.round((event.clientX - offsetX) / scale);
  const y = Math.round((event.clientY - offsetY) / scale);
  if (x < 0 || y < 0 || x >= width || y >= height) return null;
  return { x, y, source_width: width, source_height: height };
}

async function sendTouch(action, point) {
  const body = { serial: deviceSelect.value, action, ...point };
  // ช่อง WebSocket เร็วกว่ามาก — ยิง HTTP ทีละ event ได้แค่ ~50 ครั้ง/วินาที
  if (touchSocket && touchSocket.readyState === WebSocket.OPEN) {
    touchSocket.send(JSON.stringify(body));
    return;
  }
  try {
    const payload = await api("/api/phone/touch", {
      method: "POST",
      body: JSON.stringify(body),
    });
    if (payload.supported === false) {
      phoneNote.textContent = "เครื่องนี้กดค้างไม่ได้ (ต้อง Android 10 ขึ้นไป)";
    }
  } catch (error) {
    phoneNote.textContent = error.message;
  }
}

const viewer = $("#phoneViewer");

viewer.addEventListener("pointerdown", async (event) => {
  if ($("#stopScreen").disabled) return;      // ยังไม่ได้เปิดจอ
  const point = pointFrom(event);
  if (!point) return;
  event.preventDefault();

  // โหมดเทรนตำแหน่ง: เก็บพิกัดอย่างเดียว ไม่ส่งไปเครื่องจริง
  if (typeof touchIntercept.fn === "function") {
    touchIntercept.fn(point);
    return;
  }
  viewer.setPointerCapture(event.pointerId);
  holdState = { point, moved: false };
  await sendTouch("DOWN", point);
});

viewer.addEventListener("pointermove", async (event) => {
  if (!holdState) return;
  const now = performance.now();
  if (now - lastMoveSent < MOVE_INTERVAL_MS) return;
  const point = pointFrom(event);
  if (!point) return;
  lastMoveSent = now;
  holdState.moved = true;
  holdState.point = point;      // จำจุดล่าสุดไว้ใช้ตอนปล่อยนอกกรอบ
  await sendTouch("MOVE", point);
});

async function releaseTouch(event) {
  if (!holdState) return;
  const held = holdState;
  holdState = null;
  // ปล่อยนอกภาพ → ใช้จุดสุดท้ายที่ยังอยู่ในกรอบ ไม่ใช่จุดเริ่ม
  const point = pointFrom(event) || held.point;
  try { viewer.releasePointerCapture(event.pointerId); } catch { /* ปล่อยไปแล้ว */ }
  await sendTouch("UP", point);
}

viewer.addEventListener("pointerup", releaseTouch);
viewer.addEventListener("pointercancel", releaseTouch);
// ปิดแท็บระหว่างกดค้าง — ปล่อยนิ้วก่อน ไม่งั้นมือถือค้างจนกว่า watchdog จะทำงาน
window.addEventListener("pagehide", () => {
  if (holdState) sendTouch("UP", holdState.point);
  closeTouchSocket();
});

// ---- ปุ่มลัด + พิมพ์ข้อความ
document.querySelectorAll("[data-key]").forEach((button) => {
  button.addEventListener("click", async () => {
    if (!deviceSelect.value) {
      phoneNote.textContent = "เลือกมือถือก่อน";
      return;
    }
    try {
      await api("/api/phone/key", {
        method: "POST",
        body: JSON.stringify({ serial: deviceSelect.value, key: button.dataset.key }),
      });
      phoneNote.textContent = `กด ${button.textContent.trim()} แล้ว`;
    } catch (error) {
      phoneNote.textContent = error.message;
    }
  });
});

async function sendPhoneText() {
  const text = $("#phoneText").value;
  if (!text || !deviceSelect.value) return;
  $("#sendPhoneText").disabled = true;
  try {
    await api("/api/phone/text", {
      method: "POST",
      body: JSON.stringify({ serial: deviceSelect.value, text }),
    });
    $("#phoneText").value = "";
    phoneNote.textContent = `พิมพ์ ${text.length} ตัวอักษรแล้ว`;
  } catch (error) {
    phoneNote.textContent = error.message;
  } finally {
    $("#sendPhoneText").disabled = false;
  }
}

$("#sendPhoneText").addEventListener("click", sendPhoneText);
$("#phoneText").addEventListener("keydown", (event) => {
  if (event.key === "Enter") sendPhoneText();
});

// ------------------------------------------- ลิงก์ คอม ↔ มือถือ
const linkNote = $("#linkNote");

async function sendToPhone(paste) {
  const text = $("#toPhoneText").value.trim();
  if (!text) {
    linkNote.textContent = "ใส่ข้อความก่อน";
    return;
  }
  if (!deviceSelect.value) {
    linkNote.textContent = "เลือกมือถือก่อน";
    return;
  }
  try {
    const payload = await api("/api/phone/clipboard", {
      method: "POST",
      body: JSON.stringify({ serial: deviceSelect.value, text, paste }),
    });
    linkNote.textContent = payload.message;
  } catch (error) {
    linkNote.textContent = error.message;
  }
}

$("#toPhoneCopy").addEventListener("click", () => sendToPhone(false));
$("#toPhonePaste").addEventListener("click", () => sendToPhone(true));

async function loadLinks() {
  try {
    const payload = await api("/api/links");
    $("#linkInbox").replaceChildren(
      ...payload.items.slice(0, 15).map((item) => {
        const row = document.createElement("li");
        const tag = document.createElement("span");
        tag.className = "link-tag";
        tag.textContent = item.platform;
        const link = document.createElement("a");
        link.href = item.url;
        link.target = "_blank";
        link.rel = "noreferrer";
        link.textContent = item.url;
        const copy = document.createElement("button");
        copy.type = "button";
        copy.className = "ghost compact";
        copy.textContent = "คัดลอก";
        copy.addEventListener("click", async () => {
          await navigator.clipboard.writeText(item.url);
          linkNote.textContent = "คัดลอกลงคลิปบอร์ดคอมแล้ว";
        });
        row.append(tag, link, copy);
        return row;
      }),
    );
    if (!payload.count) linkNote.textContent = "ยังไม่มีลิงก์จากมือถือ";
  } catch (error) {
    linkNote.textContent = error.message;
  }
}

$("#linksRefresh").addEventListener("click", loadLinks);
$("#linksClear").addEventListener("click", async () => {
  if (!window.confirm("ล้างลิงก์ทั้งหมดไหม")) return;
  await api("/api/links", { method: "DELETE" });
  await loadLinks();
});

$("#bridgeOpen").addEventListener("click", async () => {
  if (!deviceSelect.value) {
    linkNote.textContent = "เลือกมือถือก่อน";
    return;
  }
  $("#bridgeOpen").disabled = true;
  try {
    const payload = await api("/api/bridge/open", {
      method: "POST",
      body: JSON.stringify({ serial: deviceSelect.value }),
    });
    linkNote.textContent = `เปิดหน้าบนมือถือแล้ว (${payload.url}) — วางลิงก์แล้วกดส่ง`;
  } catch (error) {
    linkNote.textContent = error.message;
  } finally {
    $("#bridgeOpen").disabled = false;
  }
});

// ---------------------------------------- แก้แคปชันโดยไม่ต้องลากตัวชี้
// วางตัวชี้ด้วยการลากนิ้วผ่านสายต้องอาศัยภาพที่ทันนิ้ว ซึ่งผ่าน ADB ไม่มีวันเท่าจอจริง
// (วัดจริง 19 ส.ค. 2026: ภาพนิ่ง screencap 414 ms/เฟรม = เพดาน 2.4 fps)
// ปุ่มพวกนี้เลื่อนทีละตัวอักษรผ่าน scrcpy จึงแม่นเสมอไม่ว่าภาพจะช้าแค่ไหน
const captionNote = $("#captionNote");

async function captionCall(url, body) {
  if (!deviceSelect.value) {
    captionNote.textContent = "เลือกมือถือก่อน";
    return null;
  }
  try {
    return await api(url, {
      method: "POST",
      body: JSON.stringify({ serial: deviceSelect.value, ...body }),
    });
  } catch (error) {
    captionNote.textContent = error.message;
    return null;
  }
}

for (const button of document.querySelectorAll("[data-caret]")) {
  button.addEventListener("click", async () => {
    const key = button.dataset.caret;
    const done = await captionCall("/api/phone/key", { key });
    if (done) captionNote.textContent = "";
  });
}

$("#captionReplace").addEventListener("click", async () => {
  const text = $("#captionText").value;
  if (!text.trim()) { captionNote.textContent = "ยังไม่ได้พิมพ์แคปชัน"; return; }
  const done = await captionCall("/api/phone/caption", { text, replace: true });
  if (done) captionNote.textContent = `ทับแล้ว ${done.chars} ตัวอักษร (${done.how})`;
});

$("#captionInsert").addEventListener("click", async () => {
  const text = $("#captionText").value;
  if (!text.trim()) { captionNote.textContent = "ยังไม่ได้พิมพ์แคปชัน"; return; }
  const done = await captionCall("/api/phone/caption", { text, replace: false });
  if (done) captionNote.textContent = `แทรกแล้ว ${done.chars} ตัวอักษร (${done.how})`;
});

// ลิงก์ใหม่จากมือถือควรโผล่เองโดยไม่ต้องกดรีเฟรช — แต่เฉพาะตอนกล่องอยู่บนจอจริง
// (12 request/นาที ที่เดิมยิงทิ้งตลอดแม้เปิดค้างไว้แท็บอื่น)
window.setInterval(() => {
  if (document.hidden || !onScreen($("#linkInbox"))) return;
  loadLinks();
}, 5000);

// ------------------------------------- ส่งคลิปเข้ามือถือ + เปิดแอปโพสต์
const clipNote = $("#clipNote");
let pushedClip = null;   // {remote_path, content_uri, serial}

export async function loadTargets() {
  try {
    const payload = await api("/api/phone-post/targets");
    $("#clipTarget").replaceChildren(
      ...payload.targets.map((t) => new Option(t.label, t.key)),
    );
  } catch { /* ไม่มีรายการก็ยังส่งไฟล์ได้ */ }
}

$("#clipPush").addEventListener("click", async () => {
  const file = $("#clipFile").files[0];
  if (!file) {
    clipNote.textContent = "เลือกไฟล์คลิปก่อน";
    return;
  }
  if (!deviceSelect.value) {
    clipNote.textContent = "เลือกมือถือก่อน";
    return;
  }
  const form = new FormData();
  form.append("serial", deviceSelect.value);
  form.append("file", file);
  $("#clipPush").disabled = true;
  clipNote.textContent = `กำลังส่ง ${file.name} (${(file.size / 1e6).toFixed(1)} MB)…`;
  try {
    const payload = await api("/api/phone-post/push", { method: "POST", body: form });
    pushedClip = { ...payload, serial: deviceSelect.value };
    // ไม่เข้าแกลเลอรี = แชร์ตรงไม่ได้ ต้องบอกตั้งแต่ตอนนี้ ไม่ใช่ไปงงตอนเปิดแอป
    clipNote.textContent = payload.indexed
      ? `ส่งแล้ว ${payload.name} — เปิดแอปพร้อมคลิปได้เลย`
      : `ส่งแล้ว ${payload.name} แต่แกลเลอรียังไม่รู้จัก — เปิดแอปแล้วเลือกคลิปเองในเครื่อง`;
    $("#clipLaunch").disabled = false;
    $("#clipDelete").disabled = false;
  } catch (error) {
    clipNote.textContent = error.message;
  } finally {
    $("#clipPush").disabled = false;
  }
});

$("#clipLaunch").addEventListener("click", async () => {
  if (!pushedClip) return;
  $("#clipLaunch").disabled = true;
  try {
    const payload = await api("/api/phone-post/launch", {
      method: "POST",
      body: JSON.stringify({
        serial: deviceSelect.value,
        platform: $("#clipTarget").value,
        content_uri: pushedClip.serial === deviceSelect.value ? pushedClip.content_uri : "",
      }),
    });
    clipNote.textContent = `${payload.message} · ${payload.hint}`;
  } catch (error) {
    clipNote.textContent = error.message;
  } finally {
    $("#clipLaunch").disabled = false;
  }
});

$("#clipDelete").addEventListener("click", async () => {
  if (!pushedClip) return;
  try {
    await api("/api/phone-post/file", {
      method: "DELETE",
      body: JSON.stringify({
        serial: pushedClip.serial, remote_path: pushedClip.remote_path,
      }),
    });
    clipNote.textContent = "ลบคลิปออกจากมือถือแล้ว";
    pushedClip = null;
    $("#clipLaunch").disabled = true;
    $("#clipDelete").disabled = true;
  } catch (error) {
    clipNote.textContent = error.message;
  }
});

// ------------------------------------------------ เชื่อมต่อผ่าน Wi-Fi
const wifiNote = $("#wifiNote");

$("#wifiPair").addEventListener("click", async () => {
  try {
    const payload = await api("/api/wifi/pair", {
      method: "POST",
      body: JSON.stringify({
        endpoint: $("#pairEndpoint").value, code: $("#pairCode").value,
      }),
    });
    wifiNote.textContent = `${payload.message} — ต่อไปใส่พอร์ตเชื่อมต่อแล้วกดเชื่อมต่อ`;
    $("#pairCode").value = "";
  } catch (error) {
    wifiNote.textContent = error.message;
  }
});

$("#wifiConnect").addEventListener("click", async () => {
  try {
    const payload = await api("/api/wifi/connect", {
      method: "POST",
      body: JSON.stringify({ endpoint: $("#connectEndpoint").value }),
    });
    wifiNote.textContent = payload.message;
    await loadDevices();
  } catch (error) {
    wifiNote.textContent = error.message;
  }
});

// ปุ่มฉุกเฉิน: งานที่ถูกฆ่ากลางคันจะทิ้ง ADBKeyboard ค้างไว้จนมือถือพิมพ์เองไม่ได้
$("#restoreKeyboard").addEventListener("click", async () => {
  if (!deviceSelect.value) {
    phoneNote.textContent = "เลือกมือถือก่อน";
    return;
  }
  try {
    const payload = await api("/api/phone/keyboard/restore", {
      method: "POST",
      body: JSON.stringify({ serial: deviceSelect.value }),
    });
    phoneNote.textContent = payload.message;
  } catch (error) {
    phoneNote.textContent = error.message;
  }
});

// ------------------------------------------------ อนุญาตอุปกรณ์จากมือถือ
const deviceNote = $("#deviceNote");

// หน้าตั้งค่า (core.js) ต้องเรียกตัวนี้ตอนเปิดโมดัล แต่ core โหลดก่อน phone
// จะ import ย้อนกลับไม่ได้ (เป็นวงกลม) จึงฝากไว้ที่ hooks ให้เรียกผ่านแทน
hooks.loadAccessDevices = () => loadAccessDevices();

async function loadAccessDevices() {
  try {
    const payload = await api("/api/access/devices");
    if (payload.mobile_url) {
      $("#mobileUrl").textContent = payload.mobile_url;
      const qr = $("#mobileQr");
      qr.src = `/api/qr.png?text=${encodeURIComponent(payload.mobile_url)}`;
      qr.hidden = false;
    } else {
      $("#mobileUrl").textContent = "หา IP ในวง LAN ไม่เจอ — เช็คว่าต่อ Wi-Fi อยู่";
    }

    const waiting = payload.devices.filter((d) => d.status === "pending").length;
    $("#deviceList").replaceChildren(
      ...payload.devices.map((device) => {
        const row = document.createElement("li");
        row.className = `device-row ${device.status}`;
        const info = document.createElement("span");
        info.className = "device-info";
        info.textContent = `${device.device} · ${device.ip}`;
        info.title = `เห็นล่าสุด ${device.last_seen || "-"}`;
        const state = document.createElement("span");
        state.className = "device-state";
        state.textContent = { pending: "รออนุญาต", approved: "อนุญาตแล้ว", revoked: "ถอนสิทธิ์" }[
          device.status
        ] || device.status;
        row.append(info, state);

        if (device.status !== "approved") {
          const allow = document.createElement("button");
          allow.type = "button";
          allow.className = "ghost compact";
          allow.textContent = "อนุญาต";
          allow.addEventListener("click", async () => {
            await api(`/api/access/devices/${device.id}/approve`, { method: "POST" });
            await loadAccessDevices();
            deviceNote.textContent = `อนุญาต ${device.device} แล้ว`;
          });
          row.append(allow);
        }
        if (device.status !== "revoked") {
          const deny = document.createElement("button");
          deny.type = "button";
          deny.className = "ghost compact danger";
          deny.textContent = "ถอนสิทธิ์";
          deny.addEventListener("click", async () => {
            if (!window.confirm(`ถอนสิทธิ์ ${device.device} (${device.ip}) ไหม`)) return;
            await api(`/api/access/devices/${device.id}`, { method: "DELETE" });
            await loadAccessDevices();
          });
          row.append(deny);
        }
        return row;
      }),
    );
    deviceNote.textContent = payload.devices.length
      ? (waiting ? `มี ${waiting} เครื่องรออนุญาต` : "")
      : "ยังไม่มีอุปกรณ์ขอเข้าใช้";
  } catch (error) {
    deviceNote.textContent = error.message;
  }
}

$("#devicesRefresh").addEventListener("click", loadAccessDevices);
$("#devicesPurge").addEventListener("click", async () => {
  const payload = await api("/api/access/devices/revoked", { method: "DELETE" });
  await loadAccessDevices();
  deviceNote.textContent = `ล้างแล้ว ${payload.removed} เครื่อง`;
});
$("#copyMobileUrl").addEventListener("click", async () => {
  await navigator.clipboard.writeText($("#mobileUrl").textContent);
  deviceNote.textContent = "คัดลอกลิงก์แล้ว";
});

$("#wifiDisconnect").addEventListener("click", async () => {
  try {
    const payload = await api("/api/wifi/disconnect", {
      method: "POST",
      body: JSON.stringify({ serial: deviceSelect.value }),
    });
    wifiNote.textContent = payload.message;
    await loadDevices();
  } catch (error) {
    wifiNote.textContent = error.message;
  }
});
