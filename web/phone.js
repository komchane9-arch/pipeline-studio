/* จอมือถือ: สตรีม H.264 · แตะ/ลาก · ปุ่มลัด · ลิงก์คอม↔มือถือ · ส่งคลิป · Wi-Fi · อนุญาตอุปกรณ์ */

import { $, api, hooks, onScreen } from "./core.js";

// ========================================================== จอมือถือ (A)
//
// **หลายจอพร้อมกัน** ของเดิมมีจอเดียวทั้งหน้า: canvas ใบเดียว · socket ตัวเดียว ·
// decoder ตัวเดียว สลับเครื่องทีก็ปิดของเก่าทิ้ง พอมีมือถือสองเครื่องจึงดูพร้อมกัน
// ไม่ได้เลย ตอนนี้ทุกอย่างย้ายเข้า `PhoneScreen` ซึ่งมีของครบชุดเป็นของตัวเอง
// จะเปิดกี่จอก็ได้ ไม่มีที่ไหนผูกกับเลข 1 หรือ 2
//
// จำนวนจอ**ล้อตามเครื่องที่เปิดใช้จริง** เสียบเครื่องที่สามแล้วเปิดใช้ จอที่สาม
// ขึ้นเอง ส่วนปุ่ม ＋ / − ไว้เพิ่ม-ลดด้วยมือเมื่ออยากดูไม่ครบทุกเครื่อง
//
// `#deviceSelect` ยังอยู่เหมือนเดิมและแปลว่า "จอที่กำลังโฟกัส" — หน้า Publish
// (post.js) อ่านค่านี้อยู่ 20 กว่าที่ ถ้าถอดทิ้งการเทรนตำแหน่งจะพังทั้งหน้า
export const deviceSelect = $("#deviceSelect");
const screensBox = $("#phoneScreens");
const phoneNote = $("#phoneNote");

// ตัวดักการแตะจอ — ฝั่ง Publish (post.js) เป็นคนตั้ง ไฟล์นี้เป็นคนเรียกตอนมีคนแตะจอ
// เก็บเป็น property ของ object เพราะ ESM ห้ามไฟล์อื่นเขียนทับ "ตัวแปร" ที่ import มา
export const touchIntercept = { fn: null };

const screens = new Map();          // serial -> PhoneScreen
const dismissed = new Set();        // จอที่ผู้ใช้กดปิดเอง — ห้ามเปิดคืนให้เอง
let deviceRows = [];                // คำตอบล่าสุดของ /api/devices
let focused = "";

const supportsWebCodecs = typeof window.VideoDecoder === "function";
// หลุดแล้วต่อใหม่กี่ครั้งก่อนยอมถอยไปภาพนิ่ง — มีเพดานเสมอ ห้ามวนไม่จบ
const STREAM_RETRIES = 3;
// รหัสปิดที่ "ต่อใหม่ไปก็ไม่ติด" — 1008 เซิร์ฟเวอร์ไม่อนุญาต · 4404 เครื่องไม่พร้อม
const PERMANENT_CLOSE = new Set([1008, 4404]);
// ตกไปใช้ภาพนิ่งแล้ว ยังลองกลับมาใช้ท่อเร็วทุกกี่มิลลิวินาที
const STREAM_RECOVER_MS = 15000;
// ภาพนิ่ง: ถ่ายหนึ่งใบใช้ ~600 ms อยู่แล้ว รออีก 900 ms คือเสียเปล่า
// (ของเดิมรวมเป็น ~1,500 ms/ภาพ) เหลือ 120 ms พอกัน ADB ไม่ให้อ่วม
const POLL_GAP_MS = 120;
const MOVE_INTERVAL_MS = 8;         // ~120 event/วินาที เท่านิ้วจริง

function labelOf(serial) {
  const row = deviceRows.find((d) => d.serial === serial);
  return row ? (row.label || row.serial) : serial;
}

/** จอหนึ่งใบ — มี socket · decoder · canvas · ช่องแตะ เป็นของตัวเองครบชุด */
class PhoneScreen {
  constructor(serial) {
    this.serial = serial;
    this.socket = null;
    this.decoder = null;
    this.context = null;
    this.waitingKeyFrame = true;
    this.frameCounter = 0;
    this.timer = null;
    this.touchSocket = null;
    this.hold = null;
    this.lastMove = 0;
    this.live = false;
    this.build();
  }

  build() {
    const card = document.createElement("article");
    card.className = "screen-card";
    card.dataset.serial = this.serial;
    card.innerHTML = `
      <header class="screen-head">
        <span class="screen-dot" aria-hidden="true"></span>
        <span class="screen-name"></span>
        <button class="ghost screen-cog" type="button" title="ตั้งค่าเฉพาะจอนี้">⚙</button>
        <button class="ghost screen-close" type="button" title="ปิดจอนี้">✕</button>
      </header>
      <div class="screen-viewer">
        <canvas hidden></canvas>
        <img hidden alt="หน้าจอมือถือ" />
        <div class="phone-placeholder">กำลังเปิด…</div>
      </div>
      <div class="screen-foot">
        <button class="ghost screen-toggle" type="button">หยุด</button>
        <span class="note screen-note" aria-live="polite"></span>
      </div>`;
    this.card = card;
    this.canvas = card.querySelector("canvas");
    this.image = card.querySelector("img");
    this.placeholder = card.querySelector(".phone-placeholder");
    this.viewer = card.querySelector(".screen-viewer");
    this.note = card.querySelector(".screen-note");
    this.nameBox = card.querySelector(".screen-name");
    this.toggle = card.querySelector(".screen-toggle");

    card.addEventListener("pointerdown", () => focus(this.serial), true);
    card.querySelector(".screen-close").addEventListener("click", (event) => {
      event.stopPropagation();
      dismissed.add(this.serial);
      removeScreen(this.serial);
    });
    card.querySelector(".screen-cog").addEventListener("click", (event) => {
      event.stopPropagation();
      openScreenSettings(this.serial);
    });
    this.toggle.addEventListener("click", (event) => {
      event.stopPropagation();
      if (this.live) this.stop();
      else this.start();
    });
    this.bindTouch();
    this.rename();
    screensBox.append(card);
  }

  rename() {
    const row = deviceRows.find((d) => d.serial === this.serial);
    this.nameBox.textContent = labelOf(this.serial);
    const busy = row && (row.holder || row.job);
    this.card.classList.toggle("is-busy", Boolean(busy));
    // **เครื่องที่ไม่ได้เสียบสาย ต้องบอกตั้งแต่แรกเห็น** ของเดิมปล่อยให้กด
    // "เริ่มดูจอ" ได้ตามปกติ แล้วไปล้มที่เซิร์ฟเวอร์เป็นรหัสที่ผู้ใช้อ่านไม่ออก
    // (ข้อมูลนี้มีอยู่แล้วใน /api/devices — แค่ไม่เคยเอามาใช้กับการ์ดจอ)
    const ready = !row || row.ready !== false;
    this.card.classList.toggle("is-offline", !ready);
    if (this.toggle) this.toggle.disabled = !ready;
    if (!ready && !this.live) {
      this.say("🔌 ยังไม่ได้เสียบสาย — เสียบแล้วกดรีเฟรชรายการอุปกรณ์");
    }
    this.card.title = busy
      ? `${labelOf(this.serial)} — ${row.holder || "งานโพสต์ " + row.job} ใช้อยู่`
      : labelOf(this.serial);
  }

  say(text) {
    this.note.textContent = text;
  }

  // ------------------------------------------------------------- เปิด/ปิดจอ
  async start() {
    if (this.live) return;
    this.live = true;
    this.toggle.textContent = "หยุด";
    this.card.classList.add("is-live");
    this.say("กำลังเปิด…");
    // เปิดช่องแตะเรียลไทม์ล่วงหน้า — push scrcpy-server กินเวลาหลักวินาที
    // ถ้าไปทำตอนแตะครั้งแรกผู้ใช้จะรู้สึกว่าคลิกแรกหน่วง
    try {
      const session = await api("/api/phone/session", {
        method: "POST",
        body: JSON.stringify({ serial: this.serial }),
      });
      this.realtime = session.realtime;
      this.say(session.realtime
        ? "แตะเรียลไทม์พร้อม (กดค้าง/ลากได้)"
        : `แตะทีละครั้ง — ${session.reason || "ไม่มีช่องเรียลไทม์"}`);
      if (session.realtime) this.openTouchSocket();
    } catch (error) {
      this.say(error.message);
    }
    if (!this.live) return;         // ผู้ใช้กดปิดระหว่างรอ
    this.streamTries = 0;
    if (supportsWebCodecs) this.startStream();
    else {
      // **ต้องบอกให้ชัดว่าทำไม** ภาพนิ่งช้ากว่าท่อวิดีโอราว 9 เท่า
      // (วัดจริง 22 ส.ค. 2569: ท่อวิดีโอ 169 ms/ภาพ · ภาพนิ่ง ~1,500 ms/ภาพ)
      // ถ้าตกมาทางนี้เงียบๆ ผู้ใช้จะนึกว่าระบบพังทั้งที่แค่เลือกทางผิด
      this.say("⚠️ เบราว์เซอร์นี้ใช้ท่อวิดีโอไม่ได้ (ไม่มี WebCodecs) — "
        + "ใช้ภาพนิ่งซึ่งช้ากว่ามาก · เปิดหน้านี้ผ่าน http://127.0.0.1:8866 จะใช้ท่อเร็วได้");
      this.startPolling();
    }
  }

  stop() {
    this.live = false;
    this.clearRecover();
    this.toggle.textContent = "เริ่มดูจอ";
    this.card.classList.remove("is-live");
    if (this.timer) window.clearTimeout(this.timer);
    this.timer = null;
    this.closeStream();
    this.closeTouchSocket();
    this.canvas.hidden = true;
    this.image.hidden = true;
    this.placeholder.hidden = false;
    this.placeholder.textContent = "หยุดอยู่ — กด “เริ่มดูจอ”";
  }

  destroy() {
    this.stop();
    this.card.remove();
  }

  // --------------------------------------------------- สตรีม H.264 หน่วงต่ำ
  closeStream() {
    if (this.socket) {
      this.socket.onclose = null;
      this.socket.close();
      this.socket = null;
    }
    if (this.decoder && this.decoder.state !== "closed") {
      try { this.decoder.close(); } catch { /* ปิดซ้ำไม่เป็นไร */ }
    }
    this.decoder = null;
    this.waitingKeyFrame = true;
  }

  startStream() {
    this.closeStream();
    this.context = this.context || this.canvas.getContext("2d");
    this.decoder = new VideoDecoder({
      output: (frame) => {
        if (this.canvas.width !== frame.displayWidth) {
          this.canvas.width = frame.displayWidth;
          this.canvas.height = frame.displayHeight;
          this.fitViewer(frame.displayWidth, frame.displayHeight);
        }
        this.context.drawImage(frame, 0, 0);
        frame.close();
        this.canvas.hidden = false;
        this.image.hidden = true;
        this.placeholder.hidden = true;
        // ภาพมาถึงแล้ว = ท่อใช้ได้จริง ล้างตัวนับความพยายามทิ้ง ไม่งั้นครั้งหน้า
        // ที่หลุดจะเหลือโควตาต่อใหม่ไม่ครบ
        this.streamTries = 0;
        this.clearRecover();
      },
      error: (issue) => {
        this.waitingKeyFrame = true;
        this.say(`ตัวถอดรหัสภาพสะดุด: ${issue && issue.message ? issue.message : issue}`);
      },
    });
    try {
      this.decoder.configure({ codec: "avc1.42E01E", optimizeForLatency: true });
    } catch (issue) {
      // **ห้ามล้มเงียบ** ถ้า configure พังแล้วไม่มีใครบอก หน้าเว็บจะค้างจอเปล่า
      // โดยไม่มีทั้งภาพและข้อความ ซึ่งไล่สาเหตุไม่ได้เลย
      this.say(`⚠️ เบราว์เซอร์ตั้งค่าตัวถอดรหัสไม่ได้ (${issue.message}) — ใช้ภาพนิ่งแทน`);
      this.startPolling();
      return;
    }

    const protocol = location.protocol === "https:" ? "wss" : "ws";
    this.socket = new WebSocket(
      `${protocol}://${location.host}/ws/phone/stream`
      + `?serial=${encodeURIComponent(this.serial)}`,
    );
    this.socket.binaryType = "arraybuffer";
    // เซิร์ฟเวอร์ส่งมาทีละ NAL แต่ VideoDecoder ต้องได้ "ทั้งเฟรม" ต่อ chunk
    // ป้อน SPS เดี่ยวๆ = decoder error แล้วปิดตัวทันที (เจอจริง: ภาพไม่ขึ้นเลย)
    // จึงเก็บ SPS/PPS ไว้แล้วแปะหน้า IDR เป็นคีย์เฟรมก้อนเดียว
    let sps = null;
    let pps = null;
    this.socket.onmessage = (event) => {
      if (typeof event.data === "string") {
        // จำเหตุผลไว้ด้วย — เดี๋ยว onclose จะเขียนข้อความทับ ถ้าไม่จำไว้
        // ผู้ใช้จะเห็นแค่ "สตรีมหลุด (รหัส …)" ซึ่งบอกอะไรไม่ได้เลย
        let why = "";
        try { why = JSON.parse(event.data).error || ""; } catch { why = event.data; }
        this.lastStreamError = why;
        this.say(why);
        return;
      }
      const data = new Uint8Array(event.data);
      const nalType = data[4] & 0x1f;
      if (nalType === 7) { sps = data; return; }
      if (nalType === 8) { pps = data; return; }
      if (!this.decoder || this.decoder.state !== "configured") return;

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
        this.waitingKeyFrame = false;
      } else if (this.waitingKeyFrame || nalType !== 1) {
        return;   // ยังไม่เจอคีย์เฟรม หรือเป็น NAL ที่ไม่ใช่ภาพ (SEI/AUD)
      }
      try {
        this.decoder.decode(new EncodedVideoChunk({
          type,
          timestamp: (this.frameCounter += 1) * 16666,   // ต้องเพิ่มขึ้นเรื่อยๆ
          data: chunkData,
        }));
      } catch {
        this.waitingKeyFrame = true;
      }
    };
    this.socket.onclose = (event) => {
      if (!this.live) return;                 // ผู้ใช้กดหยุดเอง
      // **ของเดิมตกไปใช้ภาพนิ่งถาวร แล้วไม่ลองกลับมาอีกเลย** หลุดครั้งเดียว
      // = ช้าไปตลอดจนกว่าจะปิดหน้าเว็บแล้วเปิดใหม่เอง ซึ่งผู้ใช้ไม่มีทางรู้
      // **บางสาเหตุต่อใหม่ไปก็ไม่มีทางติด** — เครื่องไม่ได้เสียบสาย หรือเปิดหน้านี้
      // จากเครื่องอื่นที่เซิร์ฟเวอร์ไม่อนุญาต ต่อใหม่ 3 ครั้งมีแต่ทำให้ข้อความจริง
      // ถูกกลบ ผู้ใช้เห็นแต่ "สตรีมหลุด (รหัส 1008)" แล้วไล่สาเหตุไม่ได้
      const why = event.reason || this.lastStreamError || "";
      if (PERMANENT_CLOSE.has(event.code)) {
        this.say(`⛔ เปิดจอไม่ได้ — ${why || "เซิร์ฟเวอร์ปฏิเสธ (รหัส " + event.code + ")"}`);
        this.stop();
        return;
      }
      this.streamTries = (this.streamTries || 0) + 1;
      if (this.streamTries <= STREAM_RETRIES) {
        this.say(`สตรีมหลุด (รหัส ${event.code}${event.reason ? " " + event.reason : ""})`
          + ` — ต่อใหม่ครั้งที่ ${this.streamTries}`);
        window.setTimeout(() => { if (this.live) this.startStream(); },
          300 * this.streamTries);
        return;
      }
      this.say(`⚠️ สตรีมหลุดซ้ำ ${this.streamTries} ครั้ง (รหัสล่าสุด ${event.code})`
        + " — ใช้ภาพนิ่งชั่วคราว จะลองท่อเร็วใหม่เรื่อยๆ");
      this.startPolling();
    };
  }

  // ------------------------------------------------------ ภาพนิ่ง (ทางถอย)
  refreshFrame() {
    if (!this.live) return;
    const probe = new Image();
    probe.onload = () => {
      if (!this.live) return;
      this.fitViewer(probe.naturalWidth, probe.naturalHeight);
      this.image.src = probe.src;
      this.image.hidden = false;
      this.canvas.hidden = true;
      this.placeholder.hidden = true;
      // เฟรมถัดไปหลังเฟรมนี้โหลดเสร็จ — ไม่ยิงถี่เกินให้ ADB อ่วม
      this.timer = window.setTimeout(() => this.refreshFrame(), POLL_GAP_MS);
    };
    probe.onerror = () => {
      this.say("อ่านหน้าจอไม่ได้ — เช็คสาย/สิทธิ์ debugging");
      this.stop();
    };
    probe.src = `/api/screen?serial=${encodeURIComponent(this.serial)}&t=${Date.now()}`;
  }

  startPolling() {
    if (this.timer) window.clearTimeout(this.timer);
    this.refreshFrame();
    // **ห้ามยอมแพ้ถาวร** ภาพนิ่งเป็นทางประคองไว้ไม่ให้จอดำ ไม่ใช่ทางที่ควรอยู่
    // ยาว — ลองกลับไปใช้ท่อเร็วเรื่อยๆ เผื่อสาเหตุที่ทำให้หลุดหายไปแล้ว
    if (!supportsWebCodecs || this.recoverTimer) return;
    this.recoverTimer = window.setInterval(() => {
      if (!this.live) { this.clearRecover(); return; }
      if (this.socket && this.socket.readyState === WebSocket.OPEN) return;
      this.streamTries = 0;
      this.say("ลองกลับไปใช้ท่อเร็วอีกครั้ง…");
      this.startStream();
    }, STREAM_RECOVER_MS);
  }

  clearRecover() {
    if (this.recoverTimer) window.clearInterval(this.recoverTimer);
    this.recoverTimer = null;
  }

  // ------------------------------------------ แตะ/กดค้าง/ลาก (แยกรายจอ)
  openTouchSocket() {
    this.closeTouchSocket();
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    this.touchSocket = new WebSocket(
      `${protocol}://${location.host}/ws/phone/input`
      + `?serial=${encodeURIComponent(this.serial)}`,
    );
    this.touchSocket.onmessage = (event) => {
      const payload = JSON.parse(event.data || "{}");
      if (payload.error) this.say(payload.error);
    };
    this.touchSocket.onclose = () => { this.touchSocket = null; };
  }

  closeTouchSocket() {
    if (this.touchSocket) {
      this.touchSocket.onclose = null;
      this.touchSocket.close();
      this.touchSocket = null;
    }
    this.hold = null;
  }

  /**
   * ปรับกรอบให้เท่าสัดส่วนจอจริงของเครื่องนั้น
   *
   * เดิม CSS ตั้งไว้ตายตัวที่ 9:19 ซึ่งไม่ตรงกับเครื่องไหนเลย — REDMI 15C
   * เป็น 720x1600 และ Xiaomi 11T pro เป็น 1080x2400 ทั้งคู่คือ 9:20 ภาพจึงมี
   * ขอบดำคาดบนล่างตลอด และกรอบไม่เท่าจอจริง
   *
   * **ห้ามกลับไปตั้งเป็นเลขตายตัวอีก** (กติกาข้อ 8) เสียบเครื่องรุ่นใหม่ที่จอ
   * สัดส่วนอื่นเมื่อไร ค่าตายตัวจะผิดทันทีโดยไม่มีอะไรฟ้อง — อ่านจากภาพจริง
   * ที่เครื่องส่งมาเท่านั้น
   */
  fitViewer(width, height) {
    if (!this.viewer || !width || !height) return;
    const ratio = `${width} / ${height}`;
    if (this.viewer.style.aspectRatio === ratio) return;
    this.viewer.style.aspectRatio = ratio;
  }

  /** ภาพที่กำลังแสดงอยู่ (canvas สตรีม หรือ img ภาพนิ่ง) */
  surface() {
    return this.canvas.hidden ? this.image : this.canvas;
  }

  pointFrom(event) {
    const surface = this.surface();
    const width = surface === this.canvas ? surface.width : surface.naturalWidth;
    const height = surface === this.canvas ? surface.height : surface.naturalHeight;
    const rect = surface.getBoundingClientRect();
    if (!width || !height || !rect.width || !rect.height) return null;
    // ภาพ object-fit:contain — พื้นที่จริงของภาพเล็กกว่ากรอบ ต้องหักขอบดำออก
    const scale = Math.min(rect.width / width, rect.height / height);
    if (!Number.isFinite(scale) || scale <= 0) return null;
    const offsetX = rect.left + (rect.width - width * scale) / 2;
    const offsetY = rect.top + (rect.height - height * scale) / 2;
    const x = Math.round((event.clientX - offsetX) / scale);
    const y = Math.round((event.clientY - offsetY) / scale);
    if (x < 0 || y < 0 || x >= width || y >= height) return null;
    return { x, y, source_width: width, source_height: height };
  }

  async sendTouch(action, point) {
    const body = { serial: this.serial, action, ...point };
    // ช่อง WebSocket เร็วกว่ามาก — ยิง HTTP ทีละ event ได้แค่ ~50 ครั้ง/วินาที
    if (this.touchSocket && this.touchSocket.readyState === WebSocket.OPEN) {
      this.touchSocket.send(JSON.stringify(body));
      return;
    }
    try {
      const payload = await api("/api/phone/touch", {
        method: "POST",
        body: JSON.stringify(body),
      });
      if (payload.supported === false) {
        this.say("เครื่องนี้กดค้างไม่ได้ (ต้อง Android 10 ขึ้นไป)");
      }
    } catch (error) {
      this.say(error.message);
    }
  }

  bindTouch() {
    const viewer = this.viewer;
    viewer.addEventListener("pointerdown", async (event) => {
      if (!this.live) return;
      const point = this.pointFrom(event);
      if (!point) return;
      event.preventDefault();
      focus(this.serial);
      // โหมดเทรนตำแหน่ง: เก็บพิกัดอย่างเดียว ไม่ส่งไปเครื่องจริง
      if (typeof touchIntercept.fn === "function") {
        touchIntercept.fn(point);
        return;
      }
      viewer.setPointerCapture(event.pointerId);
      this.hold = { point, moved: false };
      await this.sendTouch("DOWN", point);
    });

    viewer.addEventListener("pointermove", async (event) => {
      if (!this.hold) return;
      const now = performance.now();
      if (now - this.lastMove < MOVE_INTERVAL_MS) return;
      const point = this.pointFrom(event);
      if (!point) return;
      this.lastMove = now;
      this.hold.moved = true;
      this.hold.point = point;    // จำจุดล่าสุดไว้ใช้ตอนปล่อยนอกกรอบ
      await this.sendTouch("MOVE", point);
    });

    const release = async (event) => {
      if (!this.hold) return;
      const held = this.hold;
      this.hold = null;
      // ปล่อยนอกภาพ → ใช้จุดสุดท้ายที่ยังอยู่ในกรอบ ไม่ใช่จุดเริ่ม
      const point = this.pointFrom(event) || held.point;
      try { viewer.releasePointerCapture(event.pointerId); } catch { /* ปล่อยแล้ว */ }
      await this.sendTouch("UP", point);
    };
    viewer.addEventListener("pointerup", release);
    viewer.addEventListener("pointercancel", release);
  }
}

// ปิดแท็บระหว่างกดค้าง — ปล่อยนิ้วทุกจอก่อน ไม่งั้นมือถือค้างจนกว่า watchdog จะทำงาน
window.addEventListener("pagehide", () => {
  for (const screen of screens.values()) {
    if (screen.hold) screen.sendTouch("UP", screen.hold.point);
    screen.closeTouchSocket();
  }
});

// ------------------------------------------------------------ จัดการชุดจอ

function focus(serial) {
  if (!serial || focused === serial) return;
  focused = serial;
  deviceSelect.value = serial;
  for (const [key, screen] of screens) {
    screen.card.classList.toggle("is-focused", key === serial);
  }
}

function addScreen(serial, { autoStart = true } = {}) {
  if (!serial || screens.has(serial)) return screens.get(serial);
  dismissed.delete(serial);
  const screen = new PhoneScreen(serial);
  screens.set(serial, screen);
  if (!focused) focus(serial);
  syncCount();
  if (autoStart) screen.start();
  return screen;
}

function removeScreen(serial) {
  const screen = screens.get(serial);
  if (!screen) return;
  screen.destroy();
  screens.delete(serial);
  if (focused === serial) {
    focused = "";
    focus([...screens.keys()][0] || "");
  }
  syncCount();
}

function syncCount() {
  const shown = screens.size;
  const total = deviceRows.filter((d) => d.enabled).length;
  screensBox.classList.toggle("many", shown > 1);
  screensBox.dataset.count = String(shown);
  $("#screenCount").textContent = `${shown}/${total} จอ`;
  $("#removeScreen").disabled = shown === 0;
  $("#addScreen").disabled = shown >= total;
  $("#screensEmpty").hidden = shown > 0;
}

/** เปิดจอให้ครบตามเครื่องที่เปิดใช้จริง — เพิ่มเครื่องที่ 3 ก็ได้จอที่ 3 เอง */
function syncScreens() {
  const enabled = deviceRows.filter((d) => d.enabled).map((d) => d.serial);
  for (const serial of enabled) {
    if (screens.has(serial) || dismissed.has(serial)) continue;
    // เปิดจอให้ แต่ **ห้ามยิงสตรีมอัตโนมัติใส่เครื่องที่ยังไม่ได้เสียบสาย**
    // ของเดิมยิงทุกเครื่องที่ "เปิดใช้" โดยไม่ดูว่าเสียบอยู่ไหม เครื่องที่ถอดสาย
    // ไว้จึงล้มซ้ำๆ แล้วขึ้นข้อความรหัสที่อ่านไม่รู้เรื่องรัวๆ ตั้งแต่เปิดหน้าเว็บ
    const row = deviceRows.find((d) => d.serial === serial);
    addScreen(serial, { autoStart: !row || row.ready !== false });
  }
  for (const serial of [...screens.keys()]) {
    // เครื่องที่ถูกปิดใช้/ถอดออกจากทะเบียนแล้ว ต้องเก็บจอทิ้งด้วย ไม่งั้นจะเหลือ
    // จอค้างที่สตรีมไปหาเครื่องที่ไม่มีอยู่แล้ว แล้วขึ้น error รัวๆ
    if (!enabled.includes(serial)) removeScreen(serial);
  }
  for (const screen of screens.values()) screen.rename();
  syncCount();
}

$("#addScreen").addEventListener("click", () => {
  const next = deviceRows.find(
    (d) => d.enabled && !screens.has(d.serial),
  );
  if (!next) {
    phoneNote.textContent = "เปิดครบทุกเครื่องที่เปิดใช้แล้ว — "
      + "อยากได้อีกจอต้องเปิดใช้เครื่องเพิ่มในหน้าตั้งค่า";
    return;
  }
  addScreen(next.serial);
});

$("#removeScreen").addEventListener("click", () => {
  const target = focused || [...screens.keys()].pop();
  if (target) {
    dismissed.add(target);
    removeScreen(target);
  }
});

$("#refreshDevices").addEventListener("click", () => loadDevices());
deviceSelect.addEventListener("change", () => focus(deviceSelect.value));

export async function loadDevices() {
  try {
    const payload = await api("/api/devices");
    deviceRows = payload.devices || [];
    deviceSelect.replaceChildren(
      ...(deviceRows.length
        ? deviceRows.map((device) => {
            const option = document.createElement("option");
            option.value = device.serial;
            // ชื่อที่ผู้ใช้ตั้งมาก่อนชื่อรุ่น — ตั้งไว้เพื่อให้จำเครื่องออก
            // ต่อท้ายด้วยสถานะจริง เครื่องที่ถอดสายจะได้ไม่ดูเหมือนพร้อมใช้
            const mark = device.enabled ? "" : " · ปิดใช้";
            const plug = device.ready ? "" : " · ไม่ได้เสียบ";
            option.textContent = `${device.label}${mark}${plug}`;
            option.disabled = !device.enabled || !device.ready;
            return option;
          })
        : [new Option("ไม่พบมือถือ — เสียบสายแล้วกดรีเฟรช", "")]),
    );
    syncScreens();
    if (focused) deviceSelect.value = focused;
  } catch (error) {
    phoneNote.textContent = error.message;
  }
}

// ------------------------------------------------ ตั้งค่าแยกรายจอ (ปุ่ม ⚙)

const settingsBox = $("#screenSettings");
let settingsSerial = "";

function settingsField(name) {
  return settingsBox.querySelector(`[name="${name}"]`);
}

async function openScreenSettings(serial) {
  settingsSerial = serial;
  const row = deviceRows.find((d) => d.serial === serial) || {};
  $("#screenSettingsTitle").textContent = `ตั้งค่า ${labelOf(serial)}`;
  $("#screenSettingsSerial").textContent = serial;
  settingsField("name").value = row.name || "";
  settingsField("account").value = row.account || "";
  settingsField("enabled").checked = Boolean(row.enabled);
  settingsField("make_default").checked = Boolean(row.is_default);
  settingsBox.querySelectorAll("[name='lane']").forEach((box) => {
    box.checked = (row.lanes || []).includes(box.value);
  });
  // ค่าที่ใช้จริงของเครื่องนี้ = ค่ากลางซ้อนด้วยค่าที่เครื่องนี้ตั้งเอง
  const live = row.settings || {};
  const base = deviceRows.find((d) => d.is_default)?.settings || {};
  settingsField("gap_min").value = live.gap_min ?? base.gap_min ?? 15;
  settingsField("gap_max").value = live.gap_max ?? base.gap_max ?? 20;
  settingsField("screen_saver").checked = live.screen_saver !== false;
  settingsField("phone_clean").checked = live.phone_clean !== false;
  settingsField("auto_start").checked = Boolean(live.auto_start);

  const others = deviceRows.filter((d) => d.serial !== serial);
  $("#copyFrom").replaceChildren(
    ...(others.length
      ? others.map((d) => new Option(d.label, d.serial))
      : [new Option("ไม่มีเครื่องอื่นให้ก๊อป", "")]),
  );
  $("#copyFrom").disabled = others.length === 0;
  $("#copySettings").disabled = others.length === 0;
  $("#screenSettingsNote").textContent = "";
  settingsBox.showModal();
}

$("#copySettings").addEventListener("click", async () => {
  const source = $("#copyFrom").value;
  if (!source || !settingsSerial) return;
  try {
    const payload = await api("/api/device/copy-settings", {
      method: "POST",
      body: JSON.stringify({ source, target: settingsSerial }),
    });
    // เอาค่าที่ก๊อปมาเติมลงช่องให้เห็นทันที — ก๊อปแล้วช่องยังเป็นค่าเก่า
    // ผู้ใช้จะนึกว่าปุ่มไม่ทำงาน แล้วกดซ้ำ
    const live = payload.settings || {};
    settingsField("gap_min").value = live.gap_min ?? 15;
    settingsField("gap_max").value = live.gap_max ?? 20;
    settingsField("screen_saver").checked = live.screen_saver !== false;
    settingsField("phone_clean").checked = live.phone_clean !== false;
    settingsField("auto_start").checked = Boolean(live.auto_start);
    $("#screenSettingsNote").textContent = payload.note
      + " (ชื่อ · บัญชี · สายงาน ไม่ถูกก๊อปตามมา)";
    await loadDevices();
  } catch (error) {
    $("#screenSettingsNote").textContent = error.message;
  }
});

$("#saveScreenSettings").addEventListener("click", async (event) => {
  event.preventDefault();
  if (!settingsSerial) return;
  const lanes = [...settingsBox.querySelectorAll("[name='lane']:checked")]
    .map((box) => box.value);
  try {
    await api("/api/device", {
      method: "POST",
      body: JSON.stringify({
        serial: settingsSerial,
        name: settingsField("name").value.trim(),
        account: settingsField("account").value.trim(),
        enabled: settingsField("enabled").checked,
        make_default: settingsField("make_default").checked,
        lanes,
      }),
    });
    await api("/api/fb/settings", {
      method: "POST",
      body: JSON.stringify({
        serial: settingsSerial,
        per_device: true,
        gap_min: Number(settingsField("gap_min").value) || 15,
        gap_max: Number(settingsField("gap_max").value) || 20,
        screen_saver: settingsField("screen_saver").checked,
        phone_clean: settingsField("phone_clean").checked,
        auto_start: settingsField("auto_start").checked,
      }),
    });
    settingsBox.close();
    await loadDevices();
    phoneNote.textContent = `บันทึกค่าของ ${labelOf(settingsSerial)} แล้ว`;
  } catch (error) {
    $("#screenSettingsNote").textContent = error.message;
  }
});

$("#forgetScreen").addEventListener("click", async () => {
  if (!settingsSerial) return;
  if (!window.confirm(`เอา ${labelOf(settingsSerial)} ออกจากทะเบียน?\n`
      + "ค่าที่ตั้งไว้จะหาย เสียบใหม่จะกลับมาแบบปิดไว้")) return;
  try {
    await api("/api/device/forget", {
      method: "POST",
      body: JSON.stringify({ serial: settingsSerial }),
    });
    settingsBox.close();
    await loadDevices();
  } catch (error) {
    $("#screenSettingsNote").textContent = error.message;
  }
});

$("#closeScreenSettings").addEventListener("click", () => settingsBox.close());

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
