/* Pipeline Studio — หน้าเดียวตามผัง: จอมือถือซ้าย แท็บขวา ตั้งค่าในโมดัล */

(() => {
  const $ = (selector) => document.querySelector(selector);

  // เวอร์ชันที่หน้านี้ "ควรคู่กับ" เซิร์ฟเวอร์ = อ่านจาก ?v= ของ <script> ตัวเองอัตโนมัติ
  // (เดิม hardcode ไว้ ต้องแก้ 3 ที่ให้ตรง พอลืมที่นี่ = ขึ้นแบนเนอร์ผิดรุ่นทั้งที่ของใหม่)
  // เหลือ sync แค่ 2 ที่: APP_VERSION (app.py) กับ ?v= (index.html) ซึ่งต้องเท่ากันอยู่แล้ว
  const EXPECTED_SERVER_VERSION = (() => {
    const tag = document.querySelector('script[src*="app.js"]');
    const match = tag && tag.src.match(/[?&]v=([^&]+)/);
    return match ? match[1] : "";
  })();

  // สายเจนคลิปแยกไปเป็นเซิร์ฟเวอร์ของตัวเองคนละพอร์ต (clip_app.py)
  // หน้าเว็บยังเป็นหน้าเดียว แค่แท็บสตอรีบอร์ดยิงถามข้ามพอร์ตไป
  // ถ้าเซิร์ฟเวอร์ตัวนั้นไม่ได้เปิด แท็บนั้นจะบอกให้เปิด ส่วนแท็บอื่นทำงานปกติ
  const CLIP_API = "http://127.0.0.1:8877";

  async function api(url, options = {}) {
    const response = await fetch(url, {
      headers: options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
      ...options,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "ดำเนินการไม่สำเร็จ");
    return payload;
  }

  let config = null;
  let system = null;

  // ============================================================= แท็บ (B)
  // เปิดทีละแท็บ พื้นที่ใครพื้นที่มัน — ตามผัง (C)
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
      document.querySelectorAll(".tab-area").forEach((area) => {
        area.hidden = area.id !== `tab-${tab.dataset.tab}`;
      });
    });
  });

  // ========================================================== จอมือถือ (A)
  const deviceSelect = $("#deviceSelect");
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

  async function loadDevices() {
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
  let tapInterceptor = null;      // Publish ใช้ดักตอนเทรนตำแหน่ง
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
    if (typeof tapInterceptor === "function") {
      tapInterceptor(point);
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

  // ลิงก์ใหม่จากมือถือควรโผล่เองโดยไม่ต้องกดรีเฟรช
  window.setInterval(loadLinks, 5000);

  // ------------------------------------- ส่งคลิปเข้ามือถือ + เปิดแอปโพสต์
  const clipNote = $("#clipNote");
  let pushedClip = null;   // {remote_path, content_uri, serial}

  async function loadTargets() {
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
  const BOT_ROLE_LABEL = { facebook: "รับงานโพสต์", clip: "สายเจนคลิป" };

  async function loadBots() {
    try {
      const payload = await api("/api/telegram/bots");
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

  // ------------------------------------------------ อนุญาตอุปกรณ์จากมือถือ
  const deviceNote = $("#deviceNote");

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

  // =============================================================== log
  const LOG_TABS = ["input", "gems", "gen_pic", "gen_video", "judge", "release", "publish"];

  async function pollLogs() {
    for (const tab of LOG_TABS) {
      const box = document.querySelector(`#log-${tab}`);
      if (!box) continue;
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

  // ============================================================ Input ①
  function fillInput() {
    const excel = config.excel;
    document.querySelector(`input[name="excelSource"][value="${excel.source}"]`).checked = true;
    $("#excelPath").value = excel.file_path;
    $("#excelUrl").value = excel.online_url;
    $("#loopRounds").value = excel.loop_rounds;
    $("#productCount").textContent = `ใน list ตอนนี้ ${config.products.length} รายการ`;
    const single = config.single;
    $("#singleName").value = single.name;
    $("#singleDetail").value = single.detail;
    $("#stripText").checked = single.strip_text;
    if (single.image) {
      $("#singleThumb").src = `/api/single/image?t=${Date.now()}`;
      $("#singleThumb").hidden = false;
      $("#singlePlus").hidden = true;
    }
  }

  async function saveExcel() {
    const payload = await api("/api/excel", {
      method: "POST",
      body: JSON.stringify({
        source: document.querySelector('input[name="excelSource"]:checked')?.value || "file",
        file_path: $("#excelPath").value,
        online_url: $("#excelUrl").value,
        loop_rounds: Number($("#loopRounds").value) || 1,
      }),
    });
    config.excel = payload.excel;
  }

  $("#excelSave").addEventListener("click", async () => {
    try {
      await saveExcel();
      $("#productCount").textContent = "บันทึกแล้ว";
    } catch (error) {
      $("#productCount").textContent = error.message;
    }
  });

  // ------------------------------------------- ดึงข้อมูลจากลิงก์ Shopee
  let shopeeData = null;

  $("#shopeeFetch").addEventListener("click", async () => {
    const link = $("#shopeeLink").value.trim();
    if (!link) {
      $("#shopeeNote").textContent = "วางลิงก์ Shopee ก่อน";
      return;
    }
    $("#shopeeFetch").disabled = true;
    $("#shopeeNote").textContent = "กำลังเปิดหน้าสินค้า… (ใช้เวลาราวครึ่งนาที)";
    try {
      const payload = await api("/api/shopee/fetch", {
        method: "POST",
        body: JSON.stringify({ link, all_images: $("#shopeeAllImages").checked }),
      });
      shopeeData = payload;
      $("#shopeeName").textContent = payload.name;
      $("#shopeeDetail").value = payload.detail || "";
      $("#shopeeGallery").replaceChildren(
        ...(payload.picked || []).map((image, index) => {
          const box = document.createElement("figure");
          box.className = `shopee-shot ${image.kind}`;
          const img = document.createElement("img");
          // เสิร์ฟจากเครื่องเราเอง ไม่ดึงจาก Shopee ซ้ำตอนแสดงผล
          img.src = `/api/shopee/image?path=${encodeURIComponent(image.file)}`;
          img.alt = image.label || `รูปที่ ${index + 1}`;
          img.loading = "lazy";
          const caption = document.createElement("figcaption");
          caption.textContent =
            image.kind === "overview" ? "ภาพรวม" : (image.label || "ตัวเลือก");
          caption.title = caption.textContent;
          box.append(img, caption);
          return box;
        }),
      );
      $("#shopeeHighlights").replaceChildren(
        ...(payload.highlights || []).map((text) => {
          const item = document.createElement("li");
          item.textContent = text;
          return item;
        }),
      );
      $("#shopeeFolder").textContent = `เก็บรูปไว้ที่ ${payload.folder}`;
      $("#shopeeResult").hidden = false;
      watchApproval(payload.approval);
      const variants = (payload.picked || []).filter((i) => i.kind === "variant").length;
      $("#shopeeNote").textContent =
        `ดึงสำเร็จ — รูป ${payload.saved_images.length} ใบ` +
        (variants ? ` (ภาพรวม 1 + ${payload.variation_name || "ตัวเลือก"} ${variants})` : "");
    } catch (error) {
      $("#shopeeNote").textContent = error.message;
    } finally {
      $("#shopeeFetch").disabled = false;
    }
  });

  // ---- สถานะอนุมัติ: กดใน Telegram แล้วหน้านี้ต้องเปลี่ยนตามเอง
  let approvalTimer = null;
  let approvalId = "";

  function paintApproval(entry) {
    const badge = $("#approvalBadge");
    const actions = $("#approvalActions");
    if (!entry || !entry.id) {
      badge.hidden = true;
      actions.hidden = true;
      return;
    }
    badge.hidden = false;
    const label = {
      pending: entry.channel === "telegram" ? "⏳ รออนุมัติใน Telegram" : "⏳ รออนุมัติ",
      approved: entry.edited ? "✅ อนุมัติ (แก้ข้อความแล้ว)" : "✅ อนุมัติแล้ว",
      rejected: "❌ ไม่อนุมัติ",
    }[entry.status] || entry.status;
    badge.textContent = label;
    badge.className = `approval-badge ${entry.status}`;
    // ปุ่มบนหน้าเว็บเป็นทางสำรอง โผล่เฉพาะตอนที่ยังไม่ตัดสิน
    actions.hidden = entry.status !== "pending";
    if (entry.status === "approved" && Array.isArray(entry.highlights)) {
      shopeeData = { ...(shopeeData || {}), highlights: entry.highlights };
      $("#shopeeHighlights").replaceChildren(
        ...entry.highlights.map((text) => {
          const item = document.createElement("li");
          item.textContent = text;
          return item;
        }),
      );
    }
  }

  function watchApproval(entry) {
    if (approvalTimer) window.clearInterval(approvalTimer);
    approvalId = entry?.id || "";
    paintApproval(entry);
    if (!approvalId || entry.status !== "pending") return;
    approvalTimer = window.setInterval(async () => {
      try {
        const fresh = await api(`/api/approvals/${approvalId}`);
        paintApproval(fresh);
        if (fresh.status !== "pending") window.clearInterval(approvalTimer);
      } catch {
        window.clearInterval(approvalTimer);
      }
    }, 3000);
  }

  async function decide(status) {
    if (!approvalId) return;
    const fresh = await api(`/api/approvals/${approvalId}`, {
      method: "POST",
      body: JSON.stringify({ status }),
    });
    paintApproval(fresh);
    if (approvalTimer) window.clearInterval(approvalTimer);
  }

  $("#approveWeb").addEventListener("click", () => decide("approved"));
  $("#rejectWeb").addEventListener("click", () => decide("rejected"));

  $("#shopeeUse").addEventListener("click", () => {
    if (!shopeeData) return;
    $("#singleName").value = shopeeData.name;
    // ส่งจุดขาย 3 ข้อไปให้ขั้นเจน ไม่ใช่รายละเอียดดิบ 5 พันตัวอักษร
    // (prompt ที่ยาวเกินทำให้ Gemini หลุดประเด็นไปพูดเรื่องใบกำกับภาษี)
    const highlights = (shopeeData.highlights || []).join("\n");
    $("#singleDetail").value = highlights || $("#shopeeDetail").value;
    // เปิดบล็อกสินค้าเดียวให้เห็นว่าค่าถูกใส่แล้วจริง
    const block = [...document.querySelectorAll("#tab-input details.block")]
      .find((d) => d.textContent.includes("สินค้าเดียวลองเทส"));
    if (block) block.open = true;
    $("#shopeeNote").textContent = "ใส่ชื่อและรายละเอียดลงช่องสินค้าเดียวแล้ว";
  });

  $("#excelBrowse").addEventListener("click", async () => {
    $("#excelBrowse").disabled = true;
    $("#productCount").textContent = "เปิดหน้าต่างเลือกไฟล์แล้ว — ดูที่ taskbar ถ้าไม่เด้งขึ้นมา";
    try {
      const payload = await api("/api/pick-file", {
        method: "POST",
        body: JSON.stringify({ kind: "excel" }),
      });
      if (payload.path) {
        $("#excelPath").value = payload.path;
        document.querySelector('input[name="excelSource"][value="file"]').checked = true;
        $("#productCount").textContent = "เลือกไฟล์แล้ว — กดบันทึกหรือสแกนต่อได้เลย";
      } else {
        $("#productCount").textContent = "ยกเลิกการเลือกไฟล์";
      }
    } catch (error) {
      $("#productCount").textContent = error.message;
    } finally {
      $("#excelBrowse").disabled = false;
    }
  });

  $("#excelScan").addEventListener("click", async () => {
    $("#excelScan").disabled = true;
    try {
      // บันทึกค่าที่กรอกก่อนเสมอ — ไม่งั้นสแกนจะไปอ่าน path เก่าที่ค้างในเซิร์ฟเวอร์
      await saveExcel();
      const payload = await api("/api/excel/scan", { method: "POST" });
      config.products = payload.products;
      $("#productCount").textContent =
        `ใน list ${payload.total} รายการ (ใหม่ ${payload.new})`;
    } catch (error) {
      $("#productCount").textContent = error.message;
    } finally {
      $("#excelScan").disabled = false;
    }
  });

  $("#singleImage").addEventListener("change", () => {
    const file = $("#singleImage").files[0];
    if (!file) return;
    $("#singleThumb").src = URL.createObjectURL(file);
    $("#singleThumb").hidden = false;
    $("#singlePlus").hidden = true;
  });

  $("#singleSave").addEventListener("click", async () => {
    const form = new FormData();
    form.append("name", $("#singleName").value);
    form.append("detail", $("#singleDetail").value);
    form.append("strip_text", $("#stripText").checked ? "true" : "false");
    const file = $("#singleImage").files[0];
    if (file) form.append("image", file);
    $("#singleSave").disabled = true;
    try {
      await api("/api/single", { method: "POST", body: form });
      $("#singleSave").textContent = "บันทึกแล้ว ✓";
      window.setTimeout(() => { $("#singleSave").textContent = "บันทึกสินค้าเดียว"; }, 1500);
    } catch (error) {
      window.alert(error.message);
    } finally {
      $("#singleSave").disabled = false;
    }
  });

  // =============================================================== GEMS
  function fillGems() {
    const select = $("#gemsSelect");
    select.replaceChildren(
      ...(config.gems.length
        ? config.gems.map((gems) => {
            const option = document.createElement("option");
            option.value = gems.id;
            option.textContent = gems.name;
            if (gems.id === config.gems_selected) option.selected = true;
            return option;
          })
        : [new Option("— ยังไม่มี GEMS —", "")]),
    );
    showProbe();
  }

  function showProbe() {
    const gems = config.gems.find((g) => g.id === $("#gemsSelect").value);
    // ผลของ test 1 รอบเด้งโชว์ทุกครั้งที่เลือก — ตามผัง
    $("#gemsProbeNote").textContent = gems?.probe
      ? `GEMS นี้: คลิป ${gems.probe.seconds} วินาที ${gems.probe.scenes} ฉาก`
      : "ยังไม่ได้ test — กด test เพื่อรู้ความยาว/จำนวนฉาก";
  }

  $("#gemsSelect").addEventListener("change", async () => {
    if (!$("#gemsSelect").value) return;
    try {
      await api("/api/gems/select", {
        method: "POST",
        body: JSON.stringify({ id: $("#gemsSelect").value }),
      });
      config.gems_selected = $("#gemsSelect").value;
      showProbe();
    } catch (error) {
      $("#gemsProbeNote").textContent = error.message;
    }
  });

  $("#gemsAdd").addEventListener("click", async () => {
    try {
      const payload = await api("/api/gems", {
        method: "POST",
        body: JSON.stringify({ name: $("#gemsName").value, link: $("#gemsLink").value }),
      });
      config.gems.push(payload.gems);
      if (!config.gems_selected) config.gems_selected = payload.gems.id;
      $("#gemsName").value = "";
      $("#gemsLink").value = "";
      fillGems();
    } catch (error) {
      $("#gemsProbeNote").textContent = error.message;
    }
  });

  $("#gemsDelete").addEventListener("click", async () => {
    const gems = config.gems.find((g) => g.id === $("#gemsSelect").value);
    if (!gems) return;
    if (!window.confirm(`ลบ GEMS "${gems.name}" ไหม`)) return;
    try {
      await api("/api/gems/delete", {
        method: "POST",
        body: JSON.stringify({ id: gems.id }),
      });
      config.gems = config.gems.filter((g) => g.id !== gems.id);
      config.gems_selected = config.gems[0]?.id || "";
      fillGems();
    } catch (error) {
      $("#gemsProbeNote").textContent = error.message;
    }
  });

  $("#gemsProbe").addEventListener("click", async () => {
    if (!$("#gemsSelect").value) return;
    try {
      await api("/api/gems/probe", {
        method: "POST",
        body: JSON.stringify({ id: $("#gemsSelect").value }),
      });
      $("#gemsProbeNote").textContent = "กำลัง test 1 รอบ — ดูความคืบหน้าใน Log";
      // ผลจะมากับ config รอบถัดไป
      window.setTimeout(reloadConfig, 20000);
    } catch (error) {
      $("#gemsProbeNote").textContent = error.message;
    }
  });

  // ============================================================ Release ③
  const SUBTITLE_SAMPLES = {
    none: "—",
    thai: "“ทิชชู่หนา 3 ชั้น ซับน้ำดีมาก”",
    thai_english: "“ทิชชู่หนา 3 ชั้น / 3-ply, super absorbent”",
  };

  function fillRelease() {
    const release = config.release;
    $("#trimSilence").checked = release.trim_silence;
    $("#subtitleMode").value = release.subtitle;
    $("#headlineAi").checked = release.headline_ai;
    $("#headlineText").value = release.headline_text;
    $("#subtitleSample").textContent = SUBTITLE_SAMPLES[release.subtitle];
  }

  $("#subtitleMode").addEventListener("change", () => {
    $("#subtitleSample").textContent = SUBTITLE_SAMPLES[$("#subtitleMode").value];
  });

  $("#releaseSave").addEventListener("click", async () => {
    try {
      await api("/api/release", {
        method: "POST",
        body: JSON.stringify({
          trim_silence: $("#trimSilence").checked,
          subtitle: $("#subtitleMode").value,
          headline_ai: $("#headlineAi").checked,
          headline_text: $("#headlineText").value,
        }),
      });
      $("#releaseSave").textContent = "บันทึกแล้ว ✓";
      window.setTimeout(() => { $("#releaseSave").textContent = "บันทึกตัวเลือก"; }, 1500);
    } catch (error) {
      window.alert(error.message);
    }
  });

  async function loadClips() {
    try {
      const payload = await api("/api/release/clips");
      $("#clipStrip").replaceChildren(
        ...payload.clips.map((clip) => {
          const item = document.createElement("div");
          item.className = "clip";
          item.textContent = `${clip.job} · ${clip.file} · ${clip.size_mb}MB`;
          return item;
        }),
      );
    } catch { /* ไม่มีคลิปไม่ใช่ข้อผิดพลาด */ }
  }

  // ====================================================== สตอรีบอร์ด 🎬
  // งานที่บอท @ClipAiABot เก็บไว้ — สตอรีบอร์ดจาก GPT + คำสั่งสำหรับ Google Flow
  //
  // ชื่อ loadClips ถูกใช้ไปแล้วกับคลิปวิดีโอในแท็บ Release คนละเรื่องกันสิ้นเชิง
  // ตรงนี้จึงเรียกว่า "story" ทั้งชุด กันสับสนตอนกลับมาแก้ทีหลัง
  // ---- คิวงาน + จุดอนุมัติ (สั่งได้ทั้งจากหน้านี้และจากแชท)
  //
  // ทุกปุ่มตรงนี้ยิงไปที่ clip_app.py ซึ่งเรียก **ตรรกะตัวเดียวกับปุ่มในแชท**
  // กดทางไหนก็ได้ผลเหมือนกัน อีกทางจะเห็นผลในรอบ refresh ถัดไป (ทุก 6 วิ)
  let jobCards = [];
  let openJobId = "";
  let detailKey = "";
  const reviseDraft = {};        // เก็บข้อความที่พิมพ์ค้างไว้ กัน refresh ลบทิ้ง

  const el = (tag, props = {}, ...kids) => {
    const node = Object.assign(document.createElement(tag), props);
    node.append(...kids.filter((kid) => kid !== null && kid !== undefined && kid !== false));
    return node;
  };

  const clipFile = (itemId, name) =>
    `${CLIP_API}/api/clips/${encodeURIComponent(itemId)}/file/${name}`;

  const jobPost = (path, body) =>
    api(`${CLIP_API}/api/jobs/${path}`, { method: "POST", body: JSON.stringify(body || {}) });

  function textBtn(label, className, handler) {
    const button = el("button", { className, type: "button", textContent: label });
    button.addEventListener("click", handler);
    return button;
  }

  function iconBtn(label, title, handler) {
    const button = el("button", { className: "icon-btn", type: "button", textContent: label, title });
    button.addEventListener("click", handler);
    return button;
  }

  /** ยิงคำสั่งแล้วโหลดสถานะใหม่ — ทุกปุ่มผ่านทางนี้ทางเดียว จะได้ไม่มีปุ่มไหน
   *  เปลี่ยนของฝั่งเซิร์ฟเวอร์แล้วหน้าเว็บยังโชว์ของเก่าค้างอยู่ */
  async function act(work) {
    try {
      const payload = await work();
      $("#storyNote").textContent = payload.message || "เรียบร้อย";
    } catch (error) {
      $("#storyNote").textContent = `ไม่สำเร็จ: ${error.message}`;
      return false;
    }
    await loadJobQueue();
    if (openJobId) await showJob(openJobId, true);
    return true;
  }

  const STAGE_TONE = {
    queued: "wait", collecting: "run", image_review: "review",
    ready_storyboard: "wait", making_storyboard: "run",
    storyboard_review: "review", script_review: "review", revising: "run",
    ready_flow: "wait", generating: "run", video_review: "review",
    tiktok_post_review: "review", tiktok_posting: "run",
    done: "ok", failed: "fail", cancelled: "off",
  };

  function jobRow(job) {
    const row = el("li", { className: `story-queue-item ${STAGE_TONE[job.stage] || ""}` });
    if (job.id === openJobId) row.classList.add("active");
    const bits = [job.running ? "▶ " : "", job.stage_label];
    if (job.source === "web") bits.push(" · จากเว็บ");
    if (job.error) bits.push(` · ${job.error.slice(0, 60)}`);
    row.append(
      el("b", { textContent: job.name || job.link || job.id }),
      el("small", { textContent: bits.join("") }),
    );

    const tools = el("span", { className: "story-queue-tools" });
    if (job.stage === "queued") {
      tools.append(
        iconBtn("↑", "แซงขึ้นก่อน", () => act(() => jobPost(`${job.id}/move`, { delta: -1 }))),
        iconBtn("↓", "เลื่อนลงทีหลัง", () => act(() => jobPost(`${job.id}/move`, { delta: 1 }))),
      );
    }
    if (job.open && !job.running) {
      tools.append(iconBtn("✕", "ยกเลิกงานนี้", () => act(() => jobPost(`${job.id}/cancel`))));
    }
    if (!job.open) {
      tools.append(
        iconBtn("↻", "สั่งทำใหม่", () => act(() => jobPost(`${job.id}/retry`))),
        iconBtn("🗑", "ลบแถวออกจากคิว (ไฟล์งานไม่หาย)", () => act(() =>
          api(`${CLIP_API}/api/jobs/${encodeURIComponent(job.id)}`, { method: "DELETE" }))),
      );
    }
    row.append(tools);

    row.addEventListener("click", (event) => {
      if (event.target.closest("button")) return;   // กดปุ่มในแถวไม่ใช่กดเลือกแถว
      openJobId = job.id;
      showJob(job.id, true);
      loadJobQueue();
    });
    return row;
  }

  async function loadJobQueue() {
    const list = $("#storyQueueList");
    if (!list) return;
    let payload;
    try {
      payload = await api(`${CLIP_API}/api/jobs`);
    } catch {
      $("#storyQueueCount").textContent = "ต่อไม่ติด";
      list.replaceChildren(el("li", {
        className: "note",
        textContent: `เปิดเซิร์ฟเวอร์สายคลิปก่อน — python clip_app.py`,
      }));
      return;
    }
    jobCards = payload.jobs || [];
    $("#storyFlowOn").checked = !!payload.flow_enabled;

    const open = jobCards.filter((job) => job.open);
    const closed = jobCards.filter((job) => !job.open).slice(-8).reverse();
    $("#storyQueueCount").textContent = open.length
      ? `${open.length} งานค้าง${payload.busy ? " · กำลังทำอยู่" : ""}`
      : "ว่าง";
    list.replaceChildren(...open.map(jobRow), ...closed.map(jobRow));
  }

  /** แถวอนุมัติ + ช่องสั่งแก้ ของสตอรีบอร์ดหรือบทพูด */
  function approveBlock(job, target, done) {
    const what = target === "storyboard" ? "สตอรีบอร์ด" : "บทพูด";
    const action = target === "storyboard" ? "sb_ok" : "sc_ok";
    const key = `${job.id}:${target}`;
    const box = el("textarea", {
      rows: 2, value: reviseDraft[key] || "",
      placeholder: `จะแก้${what}ตรงไหน — พิมพ์บอกได้เลย แล้วกดสั่งแก้`,
    });
    box.addEventListener("input", () => { reviseDraft[key] = box.value; });

    const top = el("div", { className: "inline-row" });
    top.append(done
      ? el("small", { className: "note ok", textContent: `✅ อนุมัติ${what}แล้ว` })
      : textBtn(`✅ อนุมัติ${what}`, "primary",
          () => act(() => jobPost(`${job.id}/action`, { action }))));
    top.append(textBtn(`✏️ สั่งแก้${what}`, "ghost", async () => {
      const instruction = box.value.trim();
      if (!instruction) {
        $("#storyNote").textContent = `พิมพ์ก่อนว่าจะแก้${what}ตรงไหน`;
        return;
      }
      if (await act(() => jobPost(`${job.id}/revise`, { target, instruction }))) {
        delete reviseDraft[key];
      }
    }));
    return el("div", { className: "story-approve" }, top, box);
  }

  function imageReview(job, run, meta) {
    const images = run.images || [];
    const pool = run.image_pool || [];
    const out = [el("h4", { textContent: `🖼 ชุดรูปที่จะส่งเข้า GPT (${images.length} ใบ)` })];

    const grid = el("div", { className: "story-grid" });
    images.forEach((name, index) => {
      const tools = el("span", { className: "story-cell-tools" });
      if (images.length > 1) {
        tools.append(iconBtn("🗑", "เอาใบนี้ออก (ย้ายไปคลัง)", () =>
          act(() => jobPost(`${job.id}/action`, { action: "img_del", index: index + 1 }))));
      }
      if (pool.length) {
        tools.append(iconBtn("🔄", "เปลี่ยนเป็นใบในคลัง", () =>
          act(() => jobPost(`${job.id}/action`, { action: "img_swap", index: index + 1 }))));
      }
      grid.append(el("figure", { className: "story-cell" },
        el("img", {
          className: "story-thumb", loading: "lazy", alt: `รูปที่ ${index + 1}`,
          src: clipFile(run.item_id, name),
        }), tools));
    });
    out.push(grid);

    const tools = el("div", { className: "inline-row" });
    if (pool.length && images.length < meta.max_images) {
      tools.append(textBtn("➕ เพิ่มรูปจากคลัง", "ghost",
        () => act(() => jobPost(`${job.id}/action`, { action: "img_add" }))));
    }
    tools.append(
      textBtn("✅ ใช้ชุดรูปนี้", "primary",
        () => act(() => jobPost(`${job.id}/action`, { action: "img_ok" }))),
      el("small", { className: "note", textContent: `คลังสำรอง ${pool.length} ใบ` }),
    );
    out.push(tools);

    const highlights = run.highlights || [];
    out.push(el("h4", { textContent: `✨ จุดเด่นที่จะส่งเข้า GPT (${highlights.length} ข้อ)` }));
    const list = el("ol", { className: "story-highlights" });
    highlights.forEach((text, index) => {
      const item = el("li", {}, el("span", { textContent: text }));
      item.append(iconBtn("✏️", "แก้ข้อนี้", () => {
        const next = window.prompt(`แก้จุดเด่นข้อ ${index + 1}`, text);
        if (next && next.trim() && next.trim() !== text) {
          act(() => jobPost(`${job.id}/highlight`, { index: index + 1, text: next.trim() }));
        }
      }));
      if (highlights.length > 1) {
        item.append(iconBtn("🗑", "ลบข้อนี้", () =>
          act(() => jobPost(`${job.id}/action`, { action: "hl_del", index: index + 1 }))));
      }
      list.append(item);
    });
    out.push(list);

    const hlTools = el("div", { className: "inline-row" });
    if (highlights.length < meta.max_highlights) {
      hlTools.append(textBtn("➕ เพิ่มจุดเด่น", "ghost", () => {
        const next = window.prompt("จุดเด่นข้อใหม่");
        if (next && next.trim()) {
          act(() => jobPost(`${job.id}/highlight`, { text: next.trim() }));
        }
      }));
    }
    hlTools.append(textBtn("✅ ใช้จุดเด่นชุดนี้", "primary",
      () => act(() => jobPost(`${job.id}/action`, { action: "hl_ok" }))));
    out.push(hlTools);
    return out;
  }

  function storyboardReview(job, run) {
    const frames = run.storyboard || [];
    const script = run.script || [];
    const out = [el("h4", { textContent: `🖼 สตอรีบอร์ด (${frames.length} ภาพ)` })];
    frames.forEach((name) => out.push(el("img", {
      className: "story-frame", loading: "lazy", alt: "สตอรีบอร์ด",
      src: clipFile(run.item_id, name),
    })));
    out.push(approveBlock(job, "storyboard", job.storyboard_ok));

    out.push(el("h4", { textContent: `🗣 บทพูด (${script.length} ฉาก)` }));
    const list = el("ol", { className: "story-highlights" });
    script.forEach((line) => list.append(el("li", { textContent: line })));
    out.push(list, approveBlock(job, "script", job.script_ok));
    return out;
  }

  function videoReview(job, run) {
    const out = [el("h4", { textContent: "🎬 คลิปที่เจนได้" })];
    (run.videos || []).forEach((name) => out.push(el("video", {
      className: "story-video", controls: true, src: clipFile(run.item_id, name),
    })));
    out.push(el("div", { className: "inline-row" },
      textBtn("✅ อนุมัติคลิป", "primary",
        () => act(() => jobPost(`${job.id}/action`, { action: "vid_ok" }))),
      textBtn("🔄 ลบแล้วเจนใหม่", "ghost",
        () => act(() => jobPost(`${job.id}/action`, { action: "vid_edit" })))));
    return out;
  }

  async function showJob(jobId, force = false) {
    const box = $("#storyDetail");
    let payload;
    try {
      payload = await api(`${CLIP_API}/api/jobs/${encodeURIComponent(jobId)}`);
    } catch (error) {
      detailKey = "";
      box.replaceChildren(el("p", { className: "note", textContent: `เปิดงานไม่สำเร็จ: ${error.message}` }));
      return;
    }
    const { job, run } = payload;
    // ไม่วาดใหม่ถ้าไม่มีอะไรเปลี่ยน — วาดทุก 6 วิจะทำให้ที่เลื่อนดูอยู่กระโดดกลับ
    const key = [job.id, job.stage, job.updated_at, job.storyboard_ok, job.script_ok].join("|");
    if (!force && key === detailKey) return;
    detailKey = key;

    const parts = [
      el("h4", { textContent: job.name || job.link || job.id }),
      el("p", { className: "note", textContent: job.stage_label + (job.note ? ` · ${job.note}` : "") }),
    ];
    if (job.error) parts.push(el("p", { className: "note fail", textContent: `❌ ${job.error}` }));

    if (job.stage === "image_review") parts.push(...imageReview(job, run, payload));
    else if (job.stage === "storyboard_review" || job.stage === "script_review") {
      parts.push(...storyboardReview(job, run));
    } else if (job.stage === "video_review") parts.push(...videoReview(job, run));
    else if (job.stage === "tiktok_post_review") {
      parts.push(el("p", { className: "note", textContent: "ขั้นยืนยันก่อนโพสต์ TikTok ยังต้องกดในแชท" }));
    } else if (job.open) {
      parts.push(el("p", { className: "note", textContent: "ยังไม่ถึงจุดที่ต้องตัดสินใจ — รอระบบทำต่อ" }));
    }

    parts.push(...runExtras(run));
    box.replaceChildren(...parts);
  }

  let storyRuns = [];

  function storyMarks(run) {
    const marks = [];
    marks.push(run.storyboard_count ? `🖼 ${run.storyboard_count}` : "🖼 —");
    marks.push(run.flow_prompt_count ? `🎥 ${run.flow_prompt_count}` : "🎥 —");
    if (run.refused) marks.push("⚠️ โดนปฏิเสธ");
    return marks.join(" · ");
  }

  async function loadStoryRuns() {
    const list = $("#storyList");
    if (!list) return;
    try {
      const payload = await api(`${CLIP_API}/api/clips`);
      storyRuns = payload.runs || [];
      if (!storyRuns.length) {
        list.replaceChildren();
        $("#storyNote").textContent = "ยังไม่มีงานที่เก็บไว้";
        return;
      }
      $("#storyNote").textContent = `${storyRuns.length} ชิ้น`;
      list.replaceChildren(
        ...storyRuns.map((run) => {
          const item = document.createElement("li");
          item.className = "story-item";
          item.dataset.itemId = run.item_id;
          const when = (run.storyboard_at || run.product_at || "").slice(5, 16).replace("T", " ");
          const title = document.createElement("b");
          title.textContent = run.name || run.item_id;
          const meta = document.createElement("small");
          meta.textContent = `${storyMarks(run)} · ${when}`;
          item.append(title, meta);
          item.addEventListener("click", () => showStoryRun(run.item_id));
          return item;
        }),
      );
    } catch (error) {
      // ยิงข้ามพอร์ตแล้วต่อไม่ติด = เซิร์ฟเวอร์สายคลิปไม่ได้เปิด ไม่ใช่โค้ดพัง
      // ต้องบอกวิธีแก้ให้ตรง ไม่ใช่โยน error ดิบๆ ที่อ่านไม่รู้เรื่อง
      $("#storyNote").textContent =
        `เชื่อมเซิร์ฟเวอร์สายคลิป (${CLIP_API}) ไม่ได้ — เปิดด้วย python clip_app.py`;
    }
  }

  async function showStoryRun(itemId) {
    const box = $("#storyDetail");
    document.querySelectorAll(".story-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.itemId === String(itemId));
    });
    box.replaceChildren(Object.assign(document.createElement("p"), {
      className: "note", textContent: "กำลังโหลด…",
    }));
    let run;
    try {
      run = await api(`${CLIP_API}/api/clips/${encodeURIComponent(itemId)}`);
    } catch (error) {
      box.replaceChildren(Object.assign(document.createElement("p"), {
        className: "note", textContent: `เปิดงานไม่สำเร็จ: ${error.message}`,
      }));
      return;
    }

    const parts = [];
    const head = document.createElement("h4");
    head.textContent = run.name || run.item_id;
    parts.push(head);

    if (run.highlights?.length) {
      const ol = document.createElement("ol");
      ol.className = "story-highlights";
      run.highlights.forEach((text) => {
        const li = document.createElement("li");
        li.textContent = text;
        ol.append(li);
      });
      parts.push(ol);
    }

    (run.storyboard || []).forEach((name) => {
      parts.push(el("img", {
        className: "story-frame", loading: "lazy", alt: "สตอรีบอร์ด",
        src: clipFile(run.item_id, name),
      }));
    });
    parts.push(...runExtras(run));
    box.replaceChildren(...parts);
  }

  /** ของที่ดูได้เสมอไม่ว่างานอยู่ขั้นไหน — ลิงก์ แชท GPT และคำสั่ง Flow
   *  ใช้ร่วมกันระหว่างหน้ารายละเอียดของคิว กับรายการงานที่เก็บไว้ */
  function runExtras(run) {
    if (!run || !run.item_id) return [];
    const parts = [];
    if (run.affiliate_url) {
      parts.push(el("a", {
        href: run.affiliate_url, target: "_blank", rel: "noreferrer",
        textContent: `🔗 ${run.affiliate_url}`,
      }));
    }
    if (run.chat_url) {
      parts.push(el("a", {
        href: run.chat_url, target: "_blank", rel: "noreferrer",
        textContent: "💬 เปิดแชท GPT ที่คุยไว้",
      }));
    }

    const prompts = run.flow_prompts || [];
    if (prompts.length) {
      parts.push(el("h4", { textContent: `คำสั่งสำหรับ Google Flow (${prompts.length} ชุด)` }));
    }
    prompts.forEach((prompt, index) => {
      const copy = textBtn(`คัดลอกชุดที่ ${index + 1}`, "ghost", async () => {
        // เขียนคลิปบอร์ดล้มได้เมื่อหน้าไม่ได้อยู่ในโฟกัส หรือเปิดผ่าน http บนเครื่องอื่น
        // ต้องบอกผู้ใช้ตรงๆ ไม่ใช่ขึ้น "คัดลอกแล้ว" ทั้งที่ยังไม่ได้คัดลอก
        try {
          await navigator.clipboard.writeText(prompt);
          copy.textContent = "คัดลอกแล้ว ✓";
        } catch {
          copy.textContent = "คัดลอกไม่ได้ — ลากเลือกเอง";
        }
        window.setTimeout(() => { copy.textContent = `คัดลอกชุดที่ ${index + 1}`; }, 1800);
      });
      parts.push(el("div", { className: "story-prompt" },
        el("pre", { textContent: prompt }), copy));
    });

    if (run.gpt_flow_reply) {
      parts.push(el("details", {},
        el("summary", { textContent: "คำตอบดิบของ GPT (เผื่อตัวตัดคำสั่งพลาด)" }),
        el("pre", { className: "story-raw", textContent: run.gpt_flow_reply })));
    }
    return parts;
  }

  $("#storyRefresh")?.addEventListener("click", () => {
    loadJobQueue();
    loadStoryRuns();
    if (openJobId) showJob(openJobId, true);
  });

  $("#storyQueueAdd")?.addEventListener("click", async () => {
    const box = $("#storyLinks");
    const links = box.value.trim();
    if (!links) {
      $("#storyAddNote").textContent = "วางลิงก์ Shopee หรือ TikTok ก่อน";
      return;
    }
    $("#storyQueueAdd").disabled = true;
    try {
      const payload = await api(`${CLIP_API}/api/jobs`, {
        method: "POST", body: JSON.stringify({ links }),
      });
      $("#storyAddNote").textContent =
        `เข้าคิวแล้ว ${payload.count} งาน · ค้างในคิวทั้งหมด ${payload.waiting} งาน`;
      box.value = "";
      await loadJobQueue();
    } catch (error) {
      $("#storyAddNote").textContent = error.message;
    } finally {
      $("#storyQueueAdd").disabled = false;
    }
  });

  $("#storyFlowOn")?.addEventListener("change", async (event) => {
    const on = event.target.checked;
    try {
      await api(`${CLIP_API}/api/flow-enabled`, {
        method: "POST", body: JSON.stringify({ on }),
      });
      $("#storyNote").textContent = on
        ? "เปิดขั้นเจนคลิปใน Google Flow แล้ว — อนุมัติครบจะเจนต่อทันที"
        : "ปิดขั้นเจนคลิปแล้ว — อนุมัติครบจะจบที่สตอรีบอร์ด ไม่เผาเครดิต";
    } catch (error) {
      // สลับกลับให้ตรงความจริง ไม่ปล่อยให้สวิตช์โชว์สถานะที่ไม่ได้เกิดขึ้นจริง
      event.target.checked = !on;
      $("#storyNote").textContent = `สลับไม่สำเร็จ: ${error.message}`;
    }
  });

  // เฝ้าคิวเฉพาะตอนเปิดแท็บนี้อยู่ — งานสายคลิปกินเวลาเป็นนาที ไม่ต้องถามถี่
  window.setInterval(() => {
    if ($("#tab-story")?.hidden) return;
    loadJobQueue();
    if (openJobId) showJob(openJobId);
  }, 6000);

  // ============================================================ Publish 💰
  const ACTIONS = [
    ["train", "เทรนตำแหน่ง"],
    ["shopee", "พิมพ์ link Shopee"],
    ["lazada", "พิมพ์ link Lazada"],
    ["hashtags", "พิมพ์ # แฮชแท็ก"],
  ];
  let queue = [];
  let armedStep = null;

  function fixedFirstStep() {
    // ขั้นแรกตายตัว: เปิดแอป Facebook เสมอ — ลบ/แก้ไม่ได้ (ผู้ใช้สั่ง fix ไว้)
    const row = document.createElement("li");
    row.className = "publish-step fixed";
    const order = document.createElement("span");
    order.className = "order";
    order.textContent = "1";
    const label = document.createElement("span");
    label.className = "fixed-label";
    label.textContent = "เปิดแอป Facebook — ขั้นตายตัว ไม่ใช้พิกัด";
    const test = document.createElement("button");
    test.type = "button";
    test.className = "ghost";
    test.textContent = "▶";
    test.title = "ลองเปิดแอป Facebook บนมือถือ";
    test.addEventListener("click", async () => {
      if (!deviceSelect.value) {
        $("#publishNote").textContent = "เลือกมือถือก่อน";
        return;
      }
      test.disabled = true;
      try {
        const payload = await api("/api/publish/open-facebook", {
          method: "POST",
          body: JSON.stringify({ serial: deviceSelect.value }),
        });
        $("#publishNote").textContent = payload.message;
      } catch (error) {
        $("#publishNote").textContent = error.message;
      } finally {
        test.disabled = false;
      }
    });
    row.append(order, label, test);
    return row;
  }

  function renderQueue() {
    $("#publishList").replaceChildren(
      fixedFirstStep(),
      ...queue.map((step, index) => {
        const row = document.createElement("li");
        row.className = "publish-step" + (armedStep === step.id ? " armed" : "");

        const order = document.createElement("span");
        order.className = "order";
        // ขั้นของผู้ใช้เริ่มนับต่อจากขั้นตายตัว
        order.textContent = String(index + 2);
        row.append(order);

        const name = document.createElement("input");
        name.type = "text";
        name.placeholder = "ชื่อขั้น";
        name.value = step.name;
        name.addEventListener("input", () => { step.name = name.value; });
        row.append(name);

        const action = document.createElement("select");
        for (const [value, label] of ACTIONS) {
          const option = new Option(label, value, false, step.action === value);
          action.append(option);
        }
        action.addEventListener("change", () => {
          step.action = action.value;
          renderQueue();
        });
        row.append(action);

        if (step.action === "train") {
          const train = document.createElement("button");
          train.type = "button";
          train.className = "ghost";
          train.textContent = armedStep === step.id ? "ยกเลิก" : "TR";
          train.title = "กดแล้วคลิกจุดบนจอมือถือ";
          train.addEventListener("click", () => armTrain(step));
          row.append(train);
          if (step.trained) {
            const mark = document.createElement("span");
            mark.className = "trained-mark";
            mark.textContent = "✓ จำแล้ว";
            row.append(mark);
          }
        } else {
          const value = document.createElement("input");
          value.type = "text";
          value.placeholder = ACTIONS.find(([v]) => v === step.action)[1];
          value.value = step.value;
          value.addEventListener("input", () => { step.value = value.value; });
          row.append(value);
        }

        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "ghost danger";
        remove.textContent = "ลบ";
        remove.addEventListener("click", () => {
          queue = queue.filter((s) => s.id !== step.id);
          renderQueue();
        });
        row.append(remove);
        return row;
      }),
    );
  }

  function armTrain(step) {
    if (armedStep === step.id) {
      armedStep = null;
      tapInterceptor = null;
      renderQueue();
      return;
    }
    if (!deviceSelect.value) {
      $("#publishNote").textContent = "เลือกมือถือแล้วเริ่มดูจอก่อน";
      return;
    }
    armedStep = step.id;
    renderQueue();
    $("#publishNote").textContent = `กำลังเทรน "${step.name || step.id}" — คลิกจุดบนจอมือถือ`;
    tapInterceptor = async (point) => {
      tapInterceptor = null;
      armedStep = null;
      try {
        await api("/api/publish/train", {
          method: "POST",
          body: JSON.stringify({
            serial: deviceSelect.value, slot: step.id, step: step.action, ...point,
          }),
        });
        step.trained = true;
        $("#publishNote").textContent = `จำตำแหน่ง "${step.name || step.id}" แล้ว`;
      } catch (error) {
        $("#publishNote").textContent = error.message;
      }
      renderQueue();
    };
  }

  $("#publishAdd").addEventListener("click", () => {
    if (queue.length >= 6) {
      $("#publishNote").textContent = "ครบ 6 ขั้นแล้ว";
      return;
    }
    queue.push({
      id: `step_${Date.now() % 100000}`,
      name: "",
      action: "train",
      value: "",
    });
    renderQueue();
  });

  $("#publishSave").addEventListener("click", async () => {
    try {
      const payload = await api("/api/publish/queue", {
        method: "POST",
        body: JSON.stringify({ items: queue }),
      });
      queue = payload.items;
      renderQueue();
      $("#publishNote").textContent = `บันทึกแล้ว ${queue.length} ขั้น`;
    } catch (error) {
      $("#publishNote").textContent = error.message;
    }
  });

  // ================= ผังโพสต์วิดีโอ — Shopee Video / Facebook Reels
  // ผังคนละชุดต่อปลายทาง เก็บพิกัดแยกต่อเครื่อง เพิ่ม/ลบ/สลับขั้นได้
  // ทุกขั้นมี "ตัวตรวจ" ว่าทำสำเร็จจริงก่อนไปขั้นถัดไป — ไม่เชื่อว่าแตะแล้วติด
  //
  // ใช้ตัวช่วยร่วมกับของเดิม (api / tapInterceptor / pointFrom) โดยตั้งใจ
  // ถ้าแยกไปไฟล์อื่นจะต้องทำสำเนาสูตรคำนวณพิกัด แล้ววันหนึ่งจะเพี้ยนคนละจุด
  if ($("#pfList")) setupPublishFlow();

  function setupPublishFlow() {
    let pfSteps = [];
    let pfKinds = {};
    let pfVerify = {};
    let pfArmed = null;                 // ขั้นที่รอให้คลิกจอเพื่อจำพิกัด

    const pfNote = (text) => { $("#pfNote").textContent = text; };
    const pfTarget = () => $("#pfTarget").value;

    function pfButton(label, title, onClick, className = "ghost") {
      const element = document.createElement("button");
      element.type = "button";
      element.className = className;
      element.textContent = label;
      element.title = title;
      element.addEventListener("click", onClick);
      return element;
    }

    function pfApply(data) {
      pfSteps = data.steps || [];
      pfKinds = data.kinds || pfKinds;
      pfVerify = data.verify_kinds || pfVerify;
      pfRender();
    }

    function pfRender() {
      $("#pfList").replaceChildren(
        ...pfSteps.map((step) => {
          const row = document.createElement("li");
          row.className = "publish-step" + (pfArmed === step.id ? " armed" : "");

          const head = document.createElement("div");
          const name = document.createElement("b");
          name.textContent = step.name;
          const kind = document.createElement("small");
          kind.textContent = ` — ${pfKinds[step.kind] || step.kind}`;
          head.append(name, kind);

          // บอกให้ครบว่าขั้นนี้ "เล็งเป้ายังไง" กับ "ตรวจยังไง" — สองอย่างนี้คือ
          // สิ่งที่ต้องแก้บ่อยสุดเวลาแอปเปลี่ยนหน้าตา ซ่อนไว้แล้วผู้ใช้แก้ไม่ถูกจุด
          const aim = [];
          if (step.find) aim.push(`เกาะป้าย “${step.find}”`);
          if (step.needs_position) {
            const point = step.position || {};
            aim.push(step.trained
              ? `พิกัด ${Math.round((point.rx || 0) * 1080)},${Math.round((point.ry || 0) * 2400)}`
              : "ยังไม่ได้เทรนพิกัด");
          }
          if (step.value) aim.push(`ค่า: ${step.value.slice(0, 40)}`);

          const meta = document.createElement("small");
          meta.className = "note";
          meta.textContent =
            `เล็งเป้า: ${aim.join(" · ") || "ไม่ต้องเล็ง"}` +
            ` │ ตรวจ: ${pfVerify[step.verify_kind] || step.verify_kind}` +
            (step.verify_text ? ` (${step.verify_text})` : "") +
            (step.optional ? " · ข้ามได้" : "");

          const tools = document.createElement("div");
          tools.className = "inline-row";
          if (step.needs_position) {
            tools.append(pfButton(
              pfArmed === step.id ? "ยกเลิก"
                : (step.trained ? "เทรนใหม่" : "เทรน"),
              "กดแล้วคลิกจุดบนจอมือถือด้านซ้าย",
              () => pfArmTrain(step),
              pfArmed === step.id ? "ghost danger" : "ghost",
            ));
          }
          tools.append(
            pfButton("▶", "ทดลองเฉพาะขั้นนี้", () => pfRun(step.order)),
            pfButton("▲", "เลื่อนขึ้น", () => pfMove(step.id, "up")),
            pfButton("▼", "เลื่อนลง", () => pfMove(step.id, "down")),
            pfButton("✎", "แก้ชื่อ / ชนิด / วิธีตรวจ", () => pfEdit(step)),
            pfButton("✕", "ลบขั้นนี้", () => pfRemove(step), "ghost danger"),
          );

          row.append(head, meta, tools);
          if (step.result) {
            const result = document.createElement("small");
            result.className = "note";
            result.textContent =
              (step.result.ok ? "✓ " : "✗ ") + step.result.message;
            row.append(result);
          }
          return row;
        }),
      );
    }

    async function pfLoad() {
      if (!deviceSelect.value) { pfNote("เลือกมือถือก่อน"); return; }
      try {
        pfApply(await api(
          `/api/publish/flow?serial=${encodeURIComponent(deviceSelect.value)}` +
          `&target=${encodeURIComponent(pfTarget())}`,
        ));
        pfNote(`ผัง ${pfSteps.length} ขั้น`);
      } catch (error) { pfNote(error.message); }
    }

    function pfArmTrain(step) {
      if (pfArmed === step.id) {
        pfArmed = null; tapInterceptor = null; pfRender();
        pfNote("ยกเลิกการเทรนแล้ว");
        return;
      }
      if (!deviceSelect.value) { pfNote("เลือกมือถือแล้วเริ่มดูจอก่อน"); return; }
      pfArmed = step.id;
      armedStep = null;               // กันชนกับตัวเทรนแบบเดิมที่ใช้ตัวดักตัวเดียวกัน
      pfRender();
      pfNote(`กำลังเทรน "${step.name}" — คลิกจุดบนจอมือถือ`);
      tapInterceptor = async (point) => {
        tapInterceptor = null;
        const id = pfArmed;
        pfArmed = null;
        try {
          pfApply(await api("/api/publish/flow/train", {
            method: "POST",
            body: JSON.stringify({
              serial: deviceSelect.value, target: pfTarget(), id, ...point,
            }),
          }));
          pfNote(`จำตำแหน่ง "${step.name}" แล้ว (${point.x}, ${point.y})`);
        } catch (error) { pfRender(); pfNote(error.message); }
      };
    }

    async function pfMove(id, direction) {
      try {
        pfApply(await api("/api/publish/flow/move", {
          method: "POST",
          body: JSON.stringify({
            serial: deviceSelect.value, target: pfTarget(), id, direction,
          }),
        }));
      } catch (error) { pfNote(error.message); }
    }

    async function pfRemove(step) {
      if (!window.confirm(`ลบขั้น "${step.name}" ?`)) return;
      try {
        pfApply(await api(
          `/api/publish/flow/step?serial=${encodeURIComponent(deviceSelect.value)}` +
          `&target=${encodeURIComponent(pfTarget())}&id=${encodeURIComponent(step.id)}`,
          { method: "DELETE" },
        ));
        pfNote(`ลบ "${step.name}" แล้ว`);
      } catch (error) { pfNote(error.message); }
    }

    async function pfEdit(step) {
      const name = window.prompt("ชื่อขั้น", step.name);
      if (name === null) return;
      const kind = window.prompt(
        `ชนิดขั้น (${Object.keys(pfKinds).join(" / ")})`, step.kind,
      );
      if (kind === null) return;
      const verify = window.prompt(
        `วิธีตรวจว่าทำสำเร็จ (${Object.keys(pfVerify).join(" / ")})`,
        step.verify || step.verify_kind,
      );
      if (verify === null) return;
      const verifyText = window.prompt(
        "ข้อความที่ใช้ตรวจ (ใช้กับ text_appears / text_gone)", step.verify_text || "",
      );
      if (verifyText === null) return;
      // คำใบ้หาปุ่ม — ทนกว่าพิกัดมากเมื่อปุ่มเลื่อนตำแหน่งหรือแอปอัปเดต
      // ใส่ได้ทั้ง resource-id / content-desc / ข้อความบนปุ่ม
      const find = window.prompt(
        "คำใบ้ไว้หาปุ่ม (resource-id / content-desc / ข้อความ) — เว้นว่างได้ ถ้าเว้นจะใช้พิกัดอย่างเดียว",
        step.find || "",
      );
      if (find === null) return;
      const value = window.prompt(
        "ค่าประจำขั้น (ข้อความที่พิมพ์ / ปุ่มระบบ BACK / ทิศปัด down|up / วินาทีที่รอ)",
        step.value || "",
      );
      if (value === null) return;
      try {
        pfApply(await api("/api/publish/flow/step", {
          method: "PATCH",
          body: JSON.stringify({
            serial: deviceSelect.value, target: pfTarget(), id: step.id,
            name, kind, verify, verify_text: verifyText || "",
            find: find || "", value: value || "",
          }),
        }));
        pfNote(`แก้ "${name}" แล้ว`);
      } catch (error) { pfNote(error.message); }
    }

    async function pfRun(only) {
      if (!deviceSelect.value) { pfNote("เลือกมือถือก่อน"); return; }
      // รันทั้งผังจบที่ "กดโพสต์" ซึ่งเรียกคืนไม่ได้ — ต้องให้คนยืนยันก่อนเสมอ
      if (!only && !window.confirm(
        "รันทั้งผังบนมือถือจริง — ขั้นสุดท้ายคือกดโพสต์ ยืนยันไหม?",
      )) return;
      pfNote(only ? `กำลังทดลองขั้นที่ ${only}…` : "กำลังเดินผังทั้งชุด…");
      try {
        const data = await api("/api/publish/flow/run", {
          method: "POST",
          body: JSON.stringify({
            serial: deviceSelect.value, target: pfTarget(),
            item_id: $("#pfItem").value, only: only || null,
          }),
        });
        const byId = new Map((data.results || []).map((item) => [item.step, item]));
        pfSteps = pfSteps.map((step) => ({ ...step, result: byId.get(step.id) || null }));
        pfRender();
        const tags = (data.tags || []).map((tag) =>
          `#${tag.tag} ${tag.count === null ? "อ่านยอดไม่ได้" : tag.count.toLocaleString()}` +
          (tag.used ? " ✓" : " ✗")).join(" · ");
        pfNote(
          `${data.ok ? "สำเร็จ" : "หยุดกลางทาง"} — ทำได้ ${data.done}/${data.total} ขั้น` +
          (tags ? ` · แท็ก: ${tags}` : ""),
        );
      } catch (error) { pfNote(error.message); }
    }

    // ----------------------------------------------------------- แฮชแท็ก

    function pfShowPlan(plan) {
      $("#pfBrand").value = plan.brand || "";
      $("#pfKind").value = plan.kind || "";
      const details = plan.details || [];
      $("#pfDetail1").value = details[0] || "";
      $("#pfDetail2").value = details[1] || "";
      $("#pfDetail3").value = details[2] || "";
      $("#pfTags").textContent =
        (plan.tags || []).map((tag) => `#${tag}`).join("　") || "(ยังไม่มีแท็ก)";
    }

    async function pfLoadTags(rebuild) {
      const item = $("#pfItem").value;
      if (!item) return;
      if (rebuild) pfNote("กำลังให้ AI สกัดยี่ห้อ/ชนิดสินค้า…");
      try {
        const data = await api(
          `/api/publish/hashtags?item_id=${encodeURIComponent(item)}` +
          (rebuild ? "&rebuild=true" : ""),
        );
        pfShowPlan(data.plan || {});
        if (rebuild) pfNote("สกัดใหม่แล้ว — ตรวจแล้วกดบันทึก");
      } catch (error) { pfNote(error.message); }
    }

    async function pfLoadItems() {
      try {
        const data = await api("/api/publish/items");
        const select = $("#pfItem");
        const keep = select.value;
        select.replaceChildren(...(data.items || []).map((item) => {
          const option = document.createElement("option");
          option.value = item.item_id;
          option.textContent =
            (item.has_video ? "🎥 " : "") + (item.has_tags ? "🏷 " : "") + item.name;
          return option;
        }));
        if (keep) select.value = keep;
        if (select.value) pfLoadTags(false);
      } catch (error) { pfNote(error.message); }
    }

    $("#pfTarget").addEventListener("change", pfLoad);
    $("#pfRun").addEventListener("click", () => pfRun(null));
    $("#pfAdd").addEventListener("click", async () => {
      const name = window.prompt("ชื่อขั้นใหม่", "");
      if (!name) return;
      const kind = window.prompt(
        `ชนิดขั้น (${Object.keys(pfKinds).join(" / ")})`, "tap",
      );
      if (!kind) return;
      try {
        pfApply(await api("/api/publish/flow/step", {
          method: "POST",
          body: JSON.stringify({
            serial: deviceSelect.value, target: pfTarget(), name, kind,
            after: pfSteps.length ? pfSteps[pfSteps.length - 1].id : "",
          }),
        }));
        pfNote(`เพิ่ม "${name}" ต่อท้ายแล้ว — กด ▲ เลื่อนไปตำแหน่งที่ต้องการได้`);
      } catch (error) { pfNote(error.message); }
    });
    $("#pfReset").addEventListener("click", async () => {
      if (!window.confirm("คืนผังตั้งต้น? (พิกัดที่เทรนไว้ยังอยู่)")) return;
      try {
        pfApply(await api("/api/publish/flow/reset", {
          method: "POST",
          body: JSON.stringify({ serial: deviceSelect.value, target: pfTarget() }),
        }));
        pfNote("คืนผังตั้งต้นแล้ว");
      } catch (error) { pfNote(error.message); }
    });
    $("#pfItem").addEventListener("change", () => pfLoadTags(false));
    $("#pfTagBuild").addEventListener("click", () => pfLoadTags(true));
    $("#pfTagSave").addEventListener("click", async () => {
      const item = $("#pfItem").value;
      if (!item) { pfNote("เลือกสินค้าก่อน"); return; }
      try {
        const data = await api("/api/publish/hashtags", {
          method: "POST",
          body: JSON.stringify({
            item_id: item,
            brand: $("#pfBrand").value,
            kind: $("#pfKind").value,
            details: [
              $("#pfDetail1").value, $("#pfDetail2").value, $("#pfDetail3").value,
            ],
          }),
        });
        pfShowPlan(data.plan || {});
        pfNote("บันทึกชุดแท็กแล้ว");
      } catch (error) { pfNote(error.message); }
    });
    deviceSelect.addEventListener("change", pfLoad);

    // รายชื่อเครื่องถูกเติมแบบ async — รอจนมีค่าจริงค่อยโหลดผัง
    // ไม่งั้นจะขึ้น "เลือกมือถือก่อน" ทุกครั้งที่เปิดหน้า ทั้งที่มีเครื่องต่ออยู่
    let waited = 0;
    const timer = setInterval(() => {
      waited += 1;
      if (deviceSelect.value) { clearInterval(timer); pfLoad(); }
      else if (waited > 40) clearInterval(timer);
    }, 500);

    pfLoadItems();
  }

  // ================================ โพสต์ลงกลุ่ม Facebook (งานมาจาก Telegram)
  // หน้าเว็บทำหน้าที่ "จัดรายการกลุ่ม + ดูสถานะงาน" ส่วนการสั่งโพสต์ทำได้ทั้ง
  // ที่นี่และในแชท — ข้อมูลอยู่ที่เซิร์ฟเวอร์ที่เดียว ไม่มีสำเนาสองชุดให้เพี้ยน
  let fbGroups = [];
  let fbTimer = null;

  const FB_STATUS_TEXT = {
    waiting_caption: "รอแคปชัน",
    waiting_image: "รอรูป",
    ready: "พร้อมโพสต์",
    running: "กำลังโพสต์…",
    done: "เสร็จแล้ว",
    failed: "ล้มเหลว",
    cancelled: "ยกเลิก",
  };

  function renderFbGroups() {
    $("#fbGroupList").replaceChildren(
      ...fbGroups.map((group) => {
        const row = document.createElement("li");
        row.className = "fb-group";

        const use = document.createElement("input");
        use.type = "checkbox";
        use.checked = group.enabled !== false;
        use.title = "ติ๊กไว้ = งานใหม่จะเลือกกลุ่มนี้ให้เอง";
        use.addEventListener("change", async () => {
          try {
            await api(`/api/fb/groups/${group.group_id}`, {
              method: "POST",
              body: JSON.stringify({ enabled: use.checked }),
            });
            group.enabled = use.checked;
          } catch (error) {
            use.checked = !use.checked;
            $("#fbNote").textContent = error.message;
          }
        });

        const name = document.createElement("input");
        name.type = "text";
        name.value = group.name || "";
        name.placeholder = "ชื่อกลุ่ม";
        name.addEventListener("change", async () => {
          try {
            await api(`/api/fb/groups/${group.group_id}`, {
              method: "POST",
              body: JSON.stringify({ name: name.value }),
            });
            group.name = name.value;
            $("#fbNote").textContent = "เปลี่ยนชื่อกลุ่มแล้ว";
          } catch (error) {
            $("#fbNote").textContent = error.message;
          }
        });

        const id = document.createElement("span");
        id.className = "fb-id";
        id.textContent = group.group_id;

        // ผลล่าสุด + ลิงก์โพสต์ที่เก็บมาได้ (กดเปิดดูได้เลย)
        const last = document.createElement("span");
        last.className = "note";
        if (group.last_link) {
          const open = document.createElement("a");
          open.href = group.last_link;
          open.target = "_blank";
          open.rel = "noreferrer";
          open.textContent = "🔗 เปิดโพสต์ล่าสุด";
          open.title = group.last_link;
          last.append(`${group.last_result || ""} `, open);
        } else {
          last.textContent = group.last_result || "";
        }

        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "ghost danger";
        remove.textContent = "ลบ";
        remove.addEventListener("click", async () => {
          // ลบกลุ่มออกจากรายการอย่างเดียว ไม่ได้ไปแตะโพสต์ที่ลงไปแล้ว
          if (!confirm(`ลบ "${group.name}" ออกจากรายการ?`)) return;
          try {
            const payload = await api(`/api/fb/groups/${group.group_id}`, { method: "DELETE" });
            fbGroups = payload.groups;
            renderFbGroups();
          } catch (error) {
            $("#fbNote").textContent = error.message;
          }
        });

        row.append(use, name, id, last, remove);
        return row;
      }),
    );
  }

  async function loadFbGroups() {
    try {
      const payload = await api("/api/fb/groups");
      fbGroups = payload.groups;
      $("#fbGapMin").value = payload.gap_min;
      $("#fbGapMax").value = payload.gap_max;
      $("#fbAutoStart").checked = payload.auto_start;
      // เตือนให้เห็นชัด — ไม่งั้นส่งงานเข้าบอทแล้วเงียบโดยไม่รู้สาเหตุ
      $("#fbNote").textContent = payload.bot_ready
        ? ""
        : "⚠️ บอทหลักยังไม่ได้ตั้งโทเคน — งานที่ส่งเข้า Telegram จะไม่เข้าระบบ " +
          "(ตั้งที่ ⚙ ตั้งค่า → อนุมัติทาง Telegram)";
      renderFbGroups();
    } catch (error) {
      $("#fbNote").textContent = error.message;
    }
  }

  function renderFbJobs(jobs, running) {
    $("#fbJobs").replaceChildren(
      ...jobs.slice(0, 3).map((job) => {
        const card = document.createElement("div");
        card.className = "fb-job";

        if (job.has_image) {
          const image = document.createElement("img");
          image.src = `/api/fb/jobs/${job.id}/image`;
          image.alt = "รูปที่จะโพสต์";
          card.append(image);
        }

        const body = document.createElement("div");
        body.className = "fb-job-body";

        const head = document.createElement("strong");
        head.textContent = `${job.id} · ${FB_STATUS_TEXT[job.status] || job.status}`;
        body.append(head);

        const caption = document.createElement("p");
        caption.className = "fb-caption";
        caption.textContent = job.caption || "(ยังไม่มีแคปชัน)";
        body.append(caption);

        const groups = document.createElement("p");
        groups.className = "note";
        groups.textContent = job.group_names.length
          ? `กลุ่ม: ${job.group_names.join(" · ")}`
          : "ยังไม่ได้เลือกกลุ่ม";
        body.append(groups);

        for (const result of job.results || []) {
          const line = document.createElement("p");
          line.className = "note";
          const name = fbGroups.find((g) => g.group_id === result.group_id);
          line.textContent =
            (result.posted ? "✅ " : "❌ ") +
            (name ? name.name : result.group_id) +
            (result.error ? ` — ${result.error}` : result.liked ? " · ❤️" : "");
          if (result.link) {
            const open = document.createElement("a");
            open.href = result.link;
            open.target = "_blank";
            open.rel = "noreferrer";
            open.textContent = " 🔗 ดูโพสต์";
            open.title = result.link;
            line.append(open);
          }
          body.append(line);
        }

        const actions = document.createElement("div");
        actions.className = "inline-row";
        if (job.status === "ready") {
          const run = document.createElement("button");
          run.type = "button";
          run.className = "primary";
          run.textContent = "🚀 โพสต์เลย";
          run.disabled = running;
          run.addEventListener("click", async () => {
            run.disabled = true;
            try {
              const payload = await api(`/api/fb/jobs/${job.id}/run`, { method: "POST" });
              $("#fbNote").textContent = payload.message;
              startFbPolling();
            } catch (error) {
              $("#fbNote").textContent = error.message;
              run.disabled = false;
            }
          });
          actions.append(run);
        }
        if (job.status === "running" || job.status === "ready") {
          const cancel = document.createElement("button");
          cancel.type = "button";
          cancel.className = "ghost danger";
          cancel.textContent = job.status === "running" ? "สั่งหยุด" : "ยกเลิก";
          cancel.addEventListener("click", async () => {
            try {
              const payload = await api(`/api/fb/jobs/${job.id}/cancel`, { method: "POST" });
              $("#fbNote").textContent = payload.message;
              loadFbJobs();
            } catch (error) {
              $("#fbNote").textContent = error.message;
            }
          });
          actions.append(cancel);
        }
        body.append(actions);
        card.append(body);
        return card;
      }),
    );
    if (!jobs.length) {
      $("#fbJobs").textContent = "ยังไม่มีงาน — ส่งรูปพร้อมแคปชันเข้าบอทใน Telegram";
    }
  }

  async function loadFbJobs() {
    try {
      const payload = await api("/api/fb/jobs");
      renderFbJobs(payload.jobs, payload.running);
      // กำลังโพสต์อยู่ค่อยถามถี่ — ไม่งั้นปล่อยให้เงียบ ไม่ยิงทิ้งทุก 3 วินาทีทั้งวัน
      // (เปิดหน้าเว็บตอนงานรันค้างอยู่ก็ต้องเริ่มถามเองด้วย ไม่ใช่เฉพาะตอนกดปุ่ม)
      if (payload.running) startFbPolling();
      else stopFbPolling();
    } catch (error) {
      $("#fbNote").textContent = error.message;
    }
  }

  function startFbPolling() {
    if (fbTimer) return;
    fbTimer = setInterval(loadFbJobs, 3000);
  }

  function stopFbPolling() {
    if (!fbTimer) return;
    clearInterval(fbTimer);
    fbTimer = null;
  }

  $("#fbGroupAdd").addEventListener("click", async () => {
    const link = $("#fbGroupLink").value.trim();
    if (!link) {
      $("#fbNote").textContent = "วางลิงก์กลุ่มก่อน";
      return;
    }
    try {
      const payload = await api("/api/fb/groups", {
        method: "POST",
        body: JSON.stringify({ link, name: $("#fbGroupName").value }),
      });
      fbGroups = payload.groups;
      $("#fbGroupLink").value = "";
      $("#fbGroupName").value = "";
      $("#fbNote").textContent = payload.group.duplicated
        ? "กลุ่มนี้มีอยู่แล้ว — อัปเดตชื่อให้"
        : `เพิ่ม "${payload.group.name}" แล้ว`;
      renderFbGroups();
    } catch (error) {
      $("#fbNote").textContent = error.message;
    }
  });

  $("#fbSettingsSave").addEventListener("click", async () => {
    try {
      const payload = await api("/api/fb/settings", {
        method: "POST",
        body: JSON.stringify({
          gap_min: Number($("#fbGapMin").value),
          gap_max: Number($("#fbGapMax").value),
          auto_start: $("#fbAutoStart").checked,
        }),
      });
      $("#fbGapMin").value = payload.gap_min;
      $("#fbGapMax").value = payload.gap_max;
      $("#fbNote").textContent = "บันทึกค่าแล้ว";
    } catch (error) {
      $("#fbNote").textContent = error.message;
    }
  });

  // ============================================================ ตั้งค่า (D)
  const dialog = $("#settingsDialog");
  $("#openSettings").addEventListener("click", () => {
    fillSettings();
    dialog.showModal();
    testKeys();
    loadAccessDevices();
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

  // ============================================================== เริ่มต้น
  async function reloadConfig() {
    config = await api("/api/config");
    fillInput();
    fillGems();
    fillRelease();
    queue = config.publish_queue.map((step) => ({ ...step }));
    renderQueue();
  }

  (async () => {
    try {
      system = await api("/api/system");
      if (EXPECTED_SERVER_VERSION && system.app_version !== EXPECTED_SERVER_VERSION) {
        document.body.insertAdjacentHTML(
          "afterbegin",
          `<p style="color:#cf7a68;padding:8px 16px;border-bottom:1px solid #cf7a68">` +
            `หน้าเว็บกับเซิร์ฟเวอร์เป็นคนละรุ่น (หน้า ${EXPECTED_SERVER_VERSION} / ` +
            `เซิร์ฟเวอร์ ${system.app_version}) — ปิดเซิร์ฟเวอร์แล้วเปิดใหม่ หรือกด Ctrl+F5</p>`,
        );
      }
      await reloadConfig();
      await loadDevices();
      await loadTargets();
      await loadClips();
      await loadStoryRuns();
      await loadJobQueue();
      await loadFbGroups();
      await loadFbJobs();
      await pollLogs();
    } catch (error) {
      document.body.insertAdjacentHTML(
        "afterbegin",
        `<p style="color:#f8a0a0;padding:8px 16px">โหลดไม่สำเร็จ: ${error.message}</p>`,
      );
    }
  })();
})();
