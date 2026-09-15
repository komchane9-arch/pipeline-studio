/**
 * Pipeline Remote — สคริปต์ควบคุมและสตรีมจอมือถือสำหรับมือถือและแท็บเล็ต
 * รองรับ WebCodecs H.264 ถอดรหัสฮาร์ดแวร์หน่วงต่ำ, สัมผัสเรียลไทม์ และปุ่มลัดครบชุด
 */

(() => {
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  // Elements
  const stage = $("#stage");
  const canvas = $("#screenCanvas");
  const image = $("#screenImage");
  const placeholder = $("#placeholder");
  const placeholderName = $("#placeholderName");
  const placeholderNote = $("#placeholderNote");
  const btnStartStream = $("#btnStartStream");
  const btnFullscreen = $("#btnFullscreen");
  const fsOverlay = $("#fullscreenOverlay");
  const btnExitFs = $("#btnExitFs");
  const devicesList = $("#devicesList");
  const badgeDot = $("#badgeDot");
  const badgeText = $("#badgeText");
  const badgeFps = $("#badgeFps");
  const toast = $("#toast");
  const drawer = $("#drawer");
  const drawerBody = $("#drawerBody");
  const drawerArrow = $("#drawerArrow");

  // State
  let devices = [];
  let currentSerial = "";
  let isLive = false;
  let isFullscreen = false;
  let fsIdleTimer = null;
  let videoSocket = null;
  let touchSocket = null;
  let decoder = null;
  let context = null;
  let waitingKeyFrame = true;
  let frameCount = 0;
  let lastFpsCalc = Date.now();
  let fpsTimer = null;
  let isTouching = false;
  let pollTimer = null;

  // Utility: Toast notification
  function showToast(msg, duration = 2500) {
    if (!toast) return;
    toast.textContent = msg;
    toast.classList.add("show");
    window.clearTimeout(toast._timer);
    toast._timer = window.setTimeout(() => toast.classList.remove("show"), duration);
  }

  const TOKEN_KEY = "pipelineStudioToken";

  function authHeaders() {
    const token = localStorage.getItem(TOKEN_KEY);
    return token ? { "x-device-token": token } : {};
  }

  // API helper
  async function api(path, options = {}) {
    const res = await fetch(path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(),
        ...(options.headers || {})
      }
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || res.statusText);
    }
    return res.json();
  }

  // ------------------------------------------------------------- 1. จัดการอุปกรณ์
  async function ensureToken() {
    if (!localStorage.getItem(TOKEN_KEY)) {
      try {
        const res = await fetch("/api/access/status", { headers: authHeaders() });
        const payload = await res.json();
        if (payload && payload.token) localStorage.setItem(TOKEN_KEY, payload.token);
      } catch (e) {}
    }
  }

  async function loadDevices() {
    await ensureToken();
    try {
      const data = await api("/api/devices");
      devices = data.devices || [];
      renderDevicePills();

      if (!currentSerial && devices.length > 0) {
        // เลือกเครื่องแรกที่เปิดใช้และเสียบสายอยู่ หรือเครื่องแรกในลิสต์
        const firstReady = devices.find((d) => d.enabled && d.ready) || devices[0];
        selectDevice(firstReady.serial);
      } else if (currentSerial) {
        renderCurrentDeviceStatus();
      }
    } catch (err) {
      showToast("อ่านรายชื่ออุปกรณ์ไม่สำเร็จ: " + err.message);
      if (err.message.includes("ยังไม่ได้รับอนุญาต") || err.message.includes("403")) {
        checkAccessAndPrompt();
      }
    }
  }

  async function checkAccessAndPrompt() {
    try {
      const res = await fetch("/api/access/status", { headers: authHeaders() });
      const payload = await res.json();
      if (payload.token) localStorage.setItem(TOKEN_KEY, payload.token);

      placeholder.hidden = false;
      canvas.hidden = true;
      image.hidden = true;
      badgeText.textContent = "รออนุญาต";
      badgeDot.className = "status-dot busy";
      placeholderName.textContent = "อุปกรณ์นี้ยังไม่ได้รับอนุญาต";

      if (payload.can_approve) {
        placeholderNote.innerHTML = `ตรวจพบการเชื่อมต่อผ่านเส้นทาง <strong>Tailscale</strong><br><button id="btnRemoteApprove" style="margin-top: 10px; background: #2ea043; color: white; border: none; border-radius: 8px; padding: 10px 18px; font-weight: 600; cursor: pointer;">✅ อนุมัติอุปกรณ์นี้ทันที (ผ่าน Tailscale)</button>`;
        const btn = document.getElementById("btnRemoteApprove");
        if (btn) {
          btn.onclick = async () => {
            btn.disabled = true;
            btn.textContent = "กำลังอนุมัติ…";
            const ares = await fetch("/api/access/quick-approve", { method: "POST", headers: authHeaders() });
            const adata = await ares.json();
            if (adata.ok) {
              showToast("อนุมัติอุปกรณ์เรียบร้อยแล้ว!");
              placeholderNote.textContent = "แตะปุ่มด้านล่างเพื่อเริ่มสตรีม";
              loadDevices();
            } else {
              showToast(adata.detail || "อนุมัติไม่สำเร็จ");
              btn.disabled = false;
              btn.textContent = "✅ อนุมัติอุปกรณ์นี้ทันที (ผ่าน Tailscale)";
            }
          };
        }
      } else {
        placeholderNote.textContent = `เปิด Pipeline Studio บนคอม หรือผ่าน Tailscale → ⚙ ตั้งค่า → อุปกรณ์ที่ขอเข้าใช้ → กดอนุญาต (${payload.device || "อุปกรณ์นี้"})`;
      }
      btnStartStream.hidden = true;
    } catch (e) {}
  }

  function renderDevicePills() {
    devicesList.innerHTML = "";
    if (devices.length === 0) {
      devicesList.innerHTML = '<div class="device-pill"><span class="status-dot offline"></span><span>ไม่พบอุปกรณ์</span></div>';
      return;
    }

    devices.forEach((d) => {
      const pill = document.createElement("div");
      pill.className = `device-pill ${d.serial === currentSerial ? "active" : ""}`;
      
      let statusClass = "offline";
      if (d.ready && d.enabled) {
        statusClass = (d.holder || d.job) ? "busy" : "online";
      }

      pill.innerHTML = `
        <span class="status-dot ${statusClass}"></span>
        <span>${d.label || d.serial}</span>
      `;

      pill.addEventListener("click", () => {
        if (d.serial !== currentSerial) {
          selectDevice(d.serial);
        }
      });

      devicesList.appendChild(pill);
    });
  }

  function selectDevice(serial) {
    if (currentSerial === serial && isLive) return;
    currentSerial = serial;
    renderDevicePills();
    stopStream();

    const d = devices.find((x) => x.serial === serial);
    placeholderName.textContent = d ? (d.label || d.serial) : serial;
    /* **บอกสาเหตุจริง ไม่ใช่เดาว่าสายหลุด** (เจ้าของเจอเอง 15 ก.ย. 2569)
     *
     * เครื่องเสียบสายอยู่จริง แต่หน้านี้ขึ้นว่า "ยังไม่ได้เสียบสายหรือหลุดการ
     * เชื่อมต่อ" เจ้าของจึงไปไล่เช็คสาย ทั้งที่ของจริงคือ **มือถือยังไม่ได้กด
     * อนุญาต USB debugging** (หลังคอมรีบูต Android ถามใหม่ทุกครั้ง)
     *
     * เซิร์ฟเวอร์แยกสองสถานะนี้ให้อยู่แล้วและส่ง `note` มาบอกวิธีแก้เป็นภาษาคน
     * — หน้านี้แค่ทิ้งมันแล้วเขียนข้อความเดาเอาเองทับ (กติกาข้อ 2.3.1:
     * "ไม่พร้อม" มีหลายสาเหตุ ห้ามยุบเหลือข้อความเดียว)
     */
    placeholderNote.textContent = d && !d.ready
      ? (d.note ? `⚠️ ${d.note}` : "🔌 ยังไม่ได้เสียบสายหรือหลุดการเชื่อมต่อ")
      : "แตะปุ่มเพื่อเริ่มดูจอ";
    btnStartStream.disabled = d && !d.ready;

    renderCurrentDeviceStatus();

    // เริ่มสตรีมอัตโนมัติถ้าอุปกรณ์พร้อม
    if (d && d.ready && d.enabled) {
      startStream();
    }
  }

  function renderCurrentDeviceStatus() {
    const d = devices.find((x) => x.serial === currentSerial);
    if (!d) return;
    if (d.holder || d.job) {
      badgeDot.className = "status-dot busy";
      badgeText.textContent = `งานบอท: ${d.holder || d.job}`;
    } else if (isLive) {
      badgeDot.className = "status-dot online";
      badgeText.textContent = "กำลังสตรีม";
    } else {
      badgeDot.className = "status-dot";
      badgeText.textContent = "หยุดอยู่";
    }
  }

  // ------------------------------------------------------------- 2. วิดีโอสตรีมมิ่ง (WebCodecs H.264)
  function startStream() {
    if (!currentSerial || isLive) return;
    stopStream();
    isLive = true;
    document.body.classList.add("is-streaming");
    placeholder.hidden = true;
    placeholder.style.display = "none";
    btnStartStream.hidden = true;
    badgeDot.className = "status-dot busy";
    badgeText.textContent = "กำลังเชื่อมต่อ…";

    // อุ่นเครื่องเซสชัน scrcpy ล่วงหน้าเพื่อความลื่นไหลของการสัมผัส
    api("/api/phone/session", {
      method: "POST",
      body: JSON.stringify({ serial: currentSerial })
    }).catch(() => {});

    if (typeof window.VideoDecoder === "function") {
      setupWebCodecsStream();
    } else {
      showToast("เบราว์เซอร์ไม่รองรับ WebCodecs สลับไปใช้ภาพนิ่ง");
      setupImagePolling();
    }

    openTouchSocket();
  }

  function stopStream() {
    isLive = false;
    document.body.classList.remove("is-streaming");
    btnStartStream.hidden = false;
    placeholderNote.textContent = "แตะปุ่มด้านล่างเพื่อเริ่มสตรีม";
    if (videoSocket) {
      videoSocket.onclose = null;
      videoSocket.close();
      videoSocket = null;
    }
    if (touchReconnectTimer) {
      window.clearTimeout(touchReconnectTimer);
      touchReconnectTimer = null;
    }
    if (touchSocket) {
      touchSocket.onclose = null;
      touchSocket.close();
      touchSocket = null;
    }
    if (decoder && decoder.state !== "closed") {
      try { decoder.close(); } catch (e) {}
      decoder = null;
    }
    if (pollTimer) {
      window.clearTimeout(pollTimer);
      pollTimer = null;
    }
    canvas.hidden = true;
    image.hidden = true;
    placeholder.hidden = false;
    placeholder.style.display = "";
    badgeFps.textContent = "";
    badgeText.textContent = "หยุดอยู่";
    badgeDot.className = "status-dot";
  }

  function setupWebCodecsStream() {
    context = canvas.getContext("2d");
    waitingKeyFrame = true;
    frameCount = 0;
    lastFpsCalc = Date.now();

    decoder = new VideoDecoder({
      output: (frame) => {
        if (canvas.width !== frame.displayWidth || canvas.height !== frame.displayHeight) {
          canvas.width = frame.displayWidth;
          canvas.height = frame.displayHeight;
        }
        context.drawImage(frame, 0, 0);
        frame.close();
        canvas.hidden = false;
        image.hidden = true;
        placeholder.hidden = true;
        placeholder.style.display = "none";
        document.body.classList.add("is-streaming");

        // คำนวณ FPS
        frameCount++;
        const now = Date.now();
        if (now - lastFpsCalc >= 1000) {
          const fps = Math.round((frameCount * 1000) / (now - lastFpsCalc));
          badgeFps.textContent = `· ${fps} fps`;
          frameCount = 0;
          lastFpsCalc = now;
        }
      },
      error: (e) => {
        waitingKeyFrame = true;
        badgeText.textContent = "เฟรมสะดุด กำลังรอคีย์เฟรม…";
      }
    });

    try {
      decoder.configure({ codec: "avc1.42E01E", optimizeForLatency: true });
    } catch (e) {
      showToast("ตั้งค่า VideoDecoder ล้มเหลว สลับใช้ภาพนิ่ง");
      setupImagePolling();
      return;
    }

    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const token = localStorage.getItem(TOKEN_KEY) || "";
    const url = `${proto}//${location.host}/ws/phone/stream?serial=${encodeURIComponent(currentSerial)}&take=1&token=${encodeURIComponent(token)}`;
    videoSocket = new WebSocket(url);
    videoSocket.binaryType = "arraybuffer";

    let sps = null;
    let pps = null;

    let streamRetries = 0;

    videoSocket.onopen = () => {
      streamRetries = 0;
      badgeDot.className = "status-dot online";
      badgeText.textContent = "สตรีมสด";
    };

    videoSocket.onmessage = (event) => {
      if (typeof event.data === "string") {
        try {
          const info = JSON.parse(event.data);
          if (info.error) showToast(info.error);
        } catch (e) {}
        return;
      }

      const data = new Uint8Array(event.data);
      const nalType = data[4] & 0x1f;

      if (nalType === 7) { sps = data; return; }
      if (nalType === 8) { pps = data; return; }
      if (!decoder || decoder.state !== "configured") return;

      let chunkData = data;
      let type = "delta";

      if (nalType === 5) { // IDR Keyframe
        type = "key";
        if (sps && pps) {
          chunkData = new Uint8Array(sps.length + pps.length + data.length);
          chunkData.set(sps, 0);
          chunkData.set(pps, sps.length);
          chunkData.set(data, sps.length + pps.length);
        }
        waitingKeyFrame = false;
      } else if (waitingKeyFrame || nalType !== 1) {
        return;
      }

      try {
        decoder.decode(new EncodedVideoChunk({
          type,
          timestamp: performance.now() * 1000,
          data: chunkData
        }));
      } catch (e) {
        waitingKeyFrame = true;
      }
    };

    videoSocket.onclose = (event) => {
      if (!isLive) return;
      if (event.code === 4409) {
        badgeDot.className = "status-dot busy";
        badgeText.textContent = "ภาพสด (มีคนดูอยู่)";
        showToast("มีหน้าต่างอื่นดูเครื่องนี้อยู่ — สลับไปใช้โหมดภาพนิ่งอัตโนมัติ");
        setupImagePolling();
        return;
      }
      streamRetries++;
      if (streamRetries >= 2) {
        badgeDot.className = "status-dot online";
        badgeText.textContent = "ภาพสด (สำรอง)";
        showToast("สตรีมสะดุด — สลับใช้โหมดภาพนิ่งอัตโนมัติ");
        setupImagePolling();
        return;
      }
      badgeDot.className = "status-dot busy";
      badgeText.textContent = `สตรีมปิด (${event.code})`;
      showToast(`สตรีมหลุด (รหัส ${event.code}) กำลังต่อใหม่…`);
      window.setTimeout(() => {
        if (isLive) setupWebCodecsStream();
      }, 1200);
    };
  }

  // ทางสำรอง: Polling ภาพนิ่ง
  function setupImagePolling() {
    image.hidden = false;
    canvas.hidden = true;
    placeholder.hidden = true;
    placeholder.style.display = "none";
    document.body.classList.add("is-streaming");
    badgeDot.className = "status-dot online";
    badgeText.textContent = "ภาพสด";
    function poll() {
      if (!isLive) return;
      const img = new Image();
      img.onload = () => {
        if (!isLive) return;
        image.src = img.src;
        image.hidden = false;
        placeholder.hidden = true;
        placeholder.style.display = "none";
        document.body.classList.add("is-streaming");
        badgeDot.className = "status-dot online";
        badgeText.textContent = "ภาพสด";
        pollTimer = window.setTimeout(poll, 150);
      };
      img.onerror = () => {
        badgeDot.className = "status-dot busy";
        badgeText.textContent = "กำลังโหลดภาพ…";
        pollTimer = window.setTimeout(poll, 500);
      };
      const token = localStorage.getItem(TOKEN_KEY) || "";
      img.src = `/api/screen?serial=${encodeURIComponent(currentSerial)}&t=${Date.now()}&token=${encodeURIComponent(token)}`;
    }
    poll();
  }

  // ------------------------------------------------------------- 3. สัมผัสและลากจอ (Touch Input)
  // ------------------------------------------------------------- 3. สัมผัสและลากจอ (Touch Input)
  let touchReconnectTimer = null;

  function openTouchSocket() {
    if (touchSocket && (touchSocket.readyState === WebSocket.OPEN || touchSocket.readyState === WebSocket.CONNECTING)) {
      return;
    }
    if (touchReconnectTimer) {
      window.clearTimeout(touchReconnectTimer);
      touchReconnectTimer = null;
    }
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const token = localStorage.getItem(TOKEN_KEY) || "";
    const url = `${proto}//${location.host}/ws/phone/input?serial=${encodeURIComponent(currentSerial)}&token=${encodeURIComponent(token)}`;
    try {
      touchSocket = new WebSocket(url);
      touchSocket.onopen = () => {};
      touchSocket.onerror = () => {};
      touchSocket.onclose = () => {
        touchSocket = null;
        if (isLive && !touchReconnectTimer) {
          touchReconnectTimer = window.setTimeout(() => {
            touchReconnectTimer = null;
            if (isLive) openTouchSocket();
          }, 1500);
        }
      };
    } catch (e) {
      touchSocket = null;
    }
  }

  function pointFrom(clientX, clientY) {
    const targetElement = canvas.hidden ? image : canvas;
    const rect = targetElement.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;

    // หาขนาดกรอบภาพจริง (Intrinsic Frame Size)
    let frameWidth = rect.width;
    let frameHeight = rect.height;

    if (targetElement === canvas && canvas.width && canvas.height) {
      frameWidth = canvas.width;
      frameHeight = canvas.height;
    } else if (targetElement === image && image.naturalWidth && image.naturalHeight) {
      frameWidth = image.naturalWidth;
      frameHeight = image.naturalHeight;
    }

    const scale = Math.min(rect.width / frameWidth, rect.height / frameHeight);
    if (!Number.isFinite(scale) || scale <= 0) return null;

    const offsetX = rect.left + (rect.width - frameWidth * scale) / 2;
    const offsetY = rect.top + (rect.height - frameHeight * scale) / 2;

    let x = Math.round((clientX - offsetX) / scale);
    let y = Math.round((clientY - offsetY) / scale);

    x = Math.max(0, Math.min(frameWidth - 1, x));
    y = Math.max(0, Math.min(frameHeight - 1, y));

    return {
      x,
      y,
      source_width: Math.round(frameWidth),
      source_height: Math.round(frameHeight)
    };
  }

  function sendTouch(action, clientX, clientY) {
    const point = pointFrom(clientX, clientY);
    if (!point || !currentSerial) return;

    const payload = {
      action,
      x: point.x,
      y: point.y,
      source_width: point.source_width,
      source_height: point.source_height
    };

    if (touchSocket && touchSocket.readyState === WebSocket.OPEN) {
      touchSocket.send(JSON.stringify(payload));
    } else {
      // Fallback via HTTP POST
      api("/api/phone/touch", {
        method: "POST",
        body: JSON.stringify({
          serial: currentSerial,
          action,
          x: payload.x,
          y: payload.y,
          source_width: payload.source_width,
          source_height: payload.source_height,
          width: payload.source_width,
          height: payload.source_height
        })
      }).catch(() => {});
    }
  }

  // ผูกการสัมผัสบน stage (รองรับทั้งนิ้วบนมือถือ/แท็บเล็ตและเมาส์บนคอม)
  stage.addEventListener("pointerdown", (e) => {
    if (!isLive) return;
    e.preventDefault();
    isTouching = true;
    try {
      stage.setPointerCapture(e.pointerId);
    } catch (err) {}
    sendTouch("DOWN", e.clientX, e.clientY);
  }, { passive: false });

  let lastMoveTime = 0;
  stage.addEventListener("pointermove", (e) => {
    if (!isLive || !isTouching) return;
    e.preventDefault();
    const now = Date.now();
    if (now - lastMoveTime < 10) return; // limit ~100Hz
    lastMoveTime = now;
    sendTouch("MOVE", e.clientX, e.clientY);
  }, { passive: false });

  stage.addEventListener("pointerup", (e) => {
    if (!isTouching) return;
    e.preventDefault();
    isTouching = false;
    sendTouch("UP", e.clientX, e.clientY);
  }, { passive: false });

  stage.addEventListener("pointercancel", (e) => {
    if (!isTouching) return;
    e.preventDefault();
    isTouching = false;
    sendTouch("UP", e.clientX, e.clientY);
  }, { passive: false });

  // ------------------------------------------------------------- 4. ปุ่มฮาร์ดแวร์จำลอง
  $$(".nav-btn[data-key]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const key = btn.dataset.key;
      if (!currentSerial) return;
      try {
        await api("/api/phone/key", {
          method: "POST",
          body: JSON.stringify({ serial: currentSerial, key })
        });
        showToast(`กดปุ่ม ${btn.textContent.trim()}`);
      } catch (err) {
        showToast(`กดปุ่มล้มเหลว: ${err.message}`);
      }
    });
  });

  $("#btnWake").addEventListener("click", async () => {
    if (!currentSerial) return;
    try {
      await api("/api/phone/wake", {
        method: "POST",
        body: JSON.stringify({ serial: currentSerial })
      });
      showToast("☀ ปลุกจอและปลดล็อกเรียบร้อย");
    } catch (err) {
      showToast("ปลุกจอล้มเหลว: " + err.message);
    }
  });

  // ------------------------------------------------------------- 5. เครื่องมือเพิ่มเติม (Drawer)
  let drawerExpanded = false;
  $("#drawerHeader").addEventListener("click", (e) => {
    if (e.target.classList.contains("drawer-tab")) return;
    drawerExpanded = !drawerExpanded;
    drawerBody.style.display = drawerExpanded ? "block" : "none";
    drawerArrow.textContent = drawerExpanded ? "▲" : "▼";
  });

  // Default hide drawer body
  drawerBody.style.display = "none";

  $("#btnToggleDrawer").addEventListener("click", () => {
    drawerExpanded = !drawerExpanded;
    drawerBody.style.display = drawerExpanded ? "block" : "none";
    drawerArrow.textContent = drawerExpanded ? "▲" : "▼";
  });

  // Drawer Tabs
  $$(".drawer-tab").forEach((tab) => {
    tab.addEventListener("click", (e) => {
      e.stopPropagation();
      $$(".drawer-tab").forEach((t) => t.classList.remove("active"));
      $$(".tab-pane").forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      const target = $(`#${tab.dataset.tab}`);
      if (target) target.classList.add("active");

      // Open drawer if closed
      drawerExpanded = true;
      drawerBody.style.display = "block";
      drawerArrow.textContent = "▲";
    });
  });

  // พิมพ์ข้อความตรง
  $("#btnSendDirect").addEventListener("click", async () => {
    const text = $("#txtDirect").value;
    if (!text || !currentSerial) return;
    try {
      await api("/api/phone/text", {
        method: "POST",
        body: JSON.stringify({ serial: currentSerial, text })
      });
      showToast("ส่งข้อความเรียบร้อย");
      $("#txtDirect").value = "";
    } catch (err) {
      showToast("ส่งข้อความไม่สำเร็จ: " + err.message);
    }
  });

  // คืนคีย์บอร์ด
  $("#btnRestoreKb").addEventListener("click", async () => {
    if (!currentSerial) return;
    try {
      await api("/api/phone/keyboard/restore", {
        method: "POST",
        body: JSON.stringify({ serial: currentSerial })
      });
      showToast("คืนคีย์บอร์ดปกติแล้ว");
    } catch (err) {
      showToast(err.message);
    }
  });

  $("#btnToggleLiveStream").addEventListener("click", () => {
    if (isLive) stopStream();
    else startStream();
  });

  btnStartStream.addEventListener("click", () => {
    startStream();
  });

  // แคปชัน
  $("#btnCaptionReplace").addEventListener("click", async () => {
    const text = $("#txtCaption").value;
    if (!text || !currentSerial) return;
    try {
      await api("/api/phone/caption", {
        method: "POST",
        body: JSON.stringify({ serial: currentSerial, text, mode: "replace" })
      });
      showToast("ทับแคปชันสำเร็จ");
    } catch (err) {
      showToast("ผิดพลาด: " + err.message);
    }
  });

  $("#btnCaptionInsert").addEventListener("click", async () => {
    const text = $("#txtCaption").value;
    if (!text || !currentSerial) return;
    try {
      await api("/api/phone/caption", {
        method: "POST",
        body: JSON.stringify({ serial: currentSerial, text, mode: "insert" })
      });
      showToast("แทรกข้อความสำเร็จ");
    } catch (err) {
      showToast("ผิดพลาด: " + err.message);
    }
  });

  $$("button[data-caret]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const caret = btn.dataset.caret;
      if (!currentSerial) return;
      try {
        await api("/api/phone/caption", {
          method: "POST",
          body: JSON.stringify({ serial: currentSerial, text: "", mode: "caret", direction: caret })
        });
      } catch (err) {}
    });
  });

  // คลิปบอร์ดบริดจ์
  $("#btnBridgeCopy").addEventListener("click", async () => {
    const text = $("#txtBridge").value;
    if (!text || !currentSerial) return;
    try {
      await api("/api/phone/clipboard", {
        method: "POST",
        body: JSON.stringify({ serial: currentSerial, text, paste: false })
      });
      showToast("คัดลอกลงคลิปบอร์ดมือถือแล้ว");
    } catch (err) {
      showToast(err.message);
    }
  });

  $("#btnBridgePaste").addEventListener("click", async () => {
    const text = $("#txtBridge").value;
    if (!text || !currentSerial) return;
    try {
      await api("/api/phone/clipboard", {
        method: "POST",
        body: JSON.stringify({ serial: currentSerial, text, paste: true })
      });
      showToast("วางลงช่องพิมพ์แล้ว");
    } catch (err) {
      showToast(err.message);
    }
  });

  // เช็คคิวบอท
  $("#btnCheckQueue").addEventListener("click", async () => {
    const resBox = $("#queueResult");
    resBox.textContent = "กำลังตรวจคิว…";
    try {
      const status = await api("/api/system");
      resBox.textContent = status.busy ? `⚠️ บอททำงานอยู่: ${status.busy}` : "✅ ไม่มีงานบอทค้างอยู่ — จอว่างพร้อมสั่งงาน";
    } catch (err) {
      resBox.textContent = "ตรวจไม่สำเร็จ: " + err.message;
    }
  });

  // ส่งคลิปเข้ามือถือ
  const fileClip = $("#fileClip");
  const btnPushClip = $("#btnPushClip");
  const btnLaunchClipApp = $("#btnLaunchClipApp");
  let lastPushedUri = "";

  btnPushClip.addEventListener("click", async () => {
    const file = fileClip.files[0];
    if (!file || !currentSerial) {
      showToast("กรุณาเลือกไฟล์วิดีโอก่อน");
      return;
    }
    btnPushClip.disabled = true;
    btnPushClip.textContent = "กำลังส่ง…";
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("serial", currentSerial);
      const res = await fetch("/api/phone-post/push", { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "ส่งคลิปไม่สำเร็จ");
      lastPushedUri = data.uri || "";
      showToast("ส่งคลิปเข้ามือถือสำเร็จ!");
      btnLaunchClipApp.disabled = false;
    } catch (err) {
      showToast("ส่งคลิปล้มเหลว: " + err.message);
    } finally {
      btnPushClip.disabled = false;
      btnPushClip.textContent = "ส่งเข้ามือถือ";
    }
  });

  btnLaunchClipApp.addEventListener("click", async () => {
    const target = $("#selClipTarget").value;
    if (!lastPushedUri || !currentSerial) return;
    try {
      await api("/api/phone-post/launch", {
        method: "POST",
        body: JSON.stringify({ serial: currentSerial, app: target, uri: lastPushedUri })
      });
      showToast(`เปิดแอป ${target} พร้อมโพสต์คลิปแล้ว`);
    } catch (err) {
      showToast(err.message);
    }
  });

  $("#btnRefreshDevices").addEventListener("click", () => {
    showToast("กำลังรีเฟรชอุปกรณ์…");
    loadDevices();
  });

  // ------------------------------------------------------------- 6. โหมดแสดงผลเต็มจอ (Fullscreen)
  function resetFsIdle() {
    if (!fsOverlay) return;
    fsOverlay.classList.remove("idle");
    window.clearTimeout(fsIdleTimer);
    fsIdleTimer = window.setTimeout(() => {
      if (isFullscreen) {
        fsOverlay.classList.add("idle");
      }
    }, 3500);
  }

  function setFullscreen(enable) {
    isFullscreen = enable;
    if (enable) {
      document.body.classList.add("is-fullscreen");
      if (fsOverlay) {
        fsOverlay.hidden = false;
        resetFsIdle();
      }
      if (btnFullscreen) {
        btnFullscreen.innerHTML = "🗗 ย่อจอ";
        btnFullscreen.title = "ออกจากเต็มจอ";
      }
      showToast("⛶ เข้าสู่โหมดเต็มจอ (แตะปุ่ม '🗗 ย่อจอ' เพื่อออก)");

      try {
        if (!document.fullscreenElement && document.documentElement.requestFullscreen) {
          document.documentElement.requestFullscreen().catch(() => {});
        }
      } catch (e) {}
    } else {
      document.body.classList.remove("is-fullscreen");
      if (fsOverlay) {
        fsOverlay.hidden = true;
      }
      if (btnFullscreen) {
        btnFullscreen.innerHTML = "⛶ เต็มจอ";
        btnFullscreen.title = "แสดงเต็มจอ (Fullscreen)";
      }
      window.clearTimeout(fsIdleTimer);

      try {
        if (document.fullscreenElement && document.exitFullscreen) {
          document.exitFullscreen().catch(() => {});
        }
      } catch (e) {}
    }
  }

  if (btnFullscreen) {
    btnFullscreen.addEventListener("click", () => setFullscreen(!isFullscreen));
  }

  if (btnExitFs) {
    btnExitFs.addEventListener("click", (e) => {
      e.stopPropagation();
      setFullscreen(false);
    });
  }

  // ปุ่มฮาร์ดแวร์จำลองในแถบควบคุมลอยตัว (Fullscreen Overlay)
  $$("#fullscreenOverlay [data-key]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      resetFsIdle();
      const key = btn.dataset.key;
      if (!currentSerial) return;
      try {
        await api("/api/phone/key", {
          method: "POST",
          body: JSON.stringify({ serial: currentSerial, key })
        });
        showToast(`กดปุ่ม ${btn.textContent.trim()}`);
      } catch (err) {
        showToast(`กดปุ่มล้มเหลว: ${err.message}`);
      }
    });
  });

  document.addEventListener("fullscreenchange", () => {
    if (!document.fullscreenElement && isFullscreen) {
      setFullscreen(false);
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && isFullscreen) {
      setFullscreen(false);
    }
  });

  // ปลุกแถบควบคุมลอยตัวเมื่อมีการสัมผัสจอ
  stage.addEventListener("pointerdown", () => {
    if (isFullscreen) resetFsIdle();
  });

  // ------------------------------------------------------------- 6.5. กล้องโฮสต์ (Camera Injection)
  const btnLaunchCam = $("#btnLaunchCameraSystem");
  const btnCheckCam = $("#btnCheckCameraStatus");
  const btnTestCam = $("#btnTestCameraApp");
  const camStatusBox = $("#camStatusBox");

  async function updateCamStatus() {
    if (!camStatusBox) return;
    camStatusBox.innerHTML = "กำลังตรวจสอบสถานะ...";
    try {
      const s = await api("/api/camera-injection/status");
      const iriunText = s.iriun_running ? "🟢 กำลังทำงาน (พร้อมรับภาพ)" : (s.iriun_installed ? "🟡 ติดตั้งแล้ว (ยังไม่เปิด)" : "🔴 ไม่พบในเครื่อง");
      const ldText = s.ldplayer_running ? "🟢 กำลังทำงาน" : (s.ldplayer_installed ? "🟡 ติดตั้งแล้ว (ยังไม่เปิด)" : "🔴 ไม่พบในเครื่อง");
      const adbText = s.adb_connected ? `🟢 ต่อติด (${s.emulator_serial || "127.0.0.1:5555"})` : "⚪ ยังไม่เชื่อมต่อ";
      
      camStatusBox.innerHTML = `
        <div>• <b>Iriun Webcam:</b> ${iriunText}</div>
        <div>• <b>LDPlayer Emulator:</b> ${ldText}</div>
        <div>• <b>สถานะ ADB:</b> ${adbText}</div>
        <div style="margin-top:4px; font-size:11px; color:var(--ink-dim);">*เมื่อเปิดแอป Iriun บนมือถือ ภาพจะส่งเข้ากล้อง LDPlayer อัตโนมัติ</div>
      `;
    } catch (err) {
      camStatusBox.innerHTML = `<span style="color:#f85149">ตรวจสถานะไม่สำเร็จ: ${err.message}</span>`;
    }
  }

  if (btnCheckCam) {
    btnCheckCam.addEventListener("click", updateCamStatus);
  }

  if (btnLaunchCam) {
    btnLaunchCam.addEventListener("click", async () => {
      showToast("กำลังส่งคำสั่งเปิดระบบกล้อง & LDPlayer...");
      btnLaunchCam.disabled = true;
      try {
        const res = await api("/api/camera-injection/launch", { method: "POST" });
        showToast(res.message || "เปิดระบบเรียบร้อย");
        setTimeout(updateCamStatus, 4000);
      } catch (err) {
        showToast(`เปิดระบบไม่สำเร็จ: ${err.message}`);
      } finally {
        btnLaunchCam.disabled = false;
      }
    });
  }

  if (btnTestCam) {
    btnTestCam.addEventListener("click", async () => {
      showToast("กำลังสั่งเปิดแอปกล้องบน LDPlayer...");
      try {
        const res = await api("/api/camera-injection/test-camera", { method: "POST" });
        showToast(res.message || "เปิดกล้องเรียบร้อย");
      } catch (err) {
        showToast(`เปิดกล้องไม่สำเร็จ: ${err.message}`);
      }
    });
  }

  // ------------------------------------------------------------- 7. PWA Service Worker
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/static/sw-remote.js").catch(() => {});
  }

  // เริ่มต้นทำงาน
  loadDevices();
  // อัปเดตสถานะคิว/อุปกรณ์ทุก 10 วินาที
  window.setInterval(loadDevices, 10000);
})();
