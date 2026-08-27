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
// 4409 = มีหน้าต่างอื่นมาขอดูจอเครื่องนี้แทนเรา **ห้ามต่อกลับไปแย่ง**
// มือถือมีตัวเข้ารหัสวิดีโอชุดเดียว สองหน้าต่างดูพร้อมกันไม่ได้ ถ้าต่างคนต่างต่อใหม่
// จะกลายเป็นผลัดกันเตะออกไม่จบ (บั๊กที่ทำให้เซิร์ฟเวอร์วนเปิดสตรีม 795 ครั้ง)
const PERMANENT_CLOSE = new Set([1008, 4404, 4409]);
const SUPERSEDED_CLOSE = 4409;
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
    // **คนกดเองเท่านั้นถึงมีสิทธิ์แย่งจอ** การต่อใหม่อัตโนมัติไม่มีสิทธิ์
    // ไม่งั้นหน้าต่างที่เปิดค้างไว้จะคอยแย่งจอกลับไปเรื่อยๆ ทั้งที่ไม่มีคนดู
    // (วัดจริง 27 ส.ค. 2569: แท็บค้าง 1 แท็บทำให้เปิดช่องใหม่ 6.1 ครั้ง/นาที)
    this.forceTake = true;
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
      // **ห้ามบอกที่อยู่ที่คนอ่านเปิดไม่ได้** ของเดิมบอกให้ไปเปิด 127.0.0.1:8866
      // ซึ่งแปลว่า "เครื่องตัวเอง" — คนที่นั่งอยู่คอมอีกเครื่องเปิดแล้วเจอหน้า error
      // แน่นอน เพราะเครื่องเขาไม่มีอะไรฟังพอร์ตนั้น (เจอจริง 25 ส.ค. 2569
      // เสียเวลาไล่ผิดทางเพราะข้อความนี้) ต้องบอกทางที่ใช้ได้จากตรงไหนก็ได้
      this.say("⚠️ เบราว์เซอร์ปิดท่อวิดีโอเพราะหน้านี้ไม่ได้เปิดแบบปลอดภัย — "
        + "ใช้ภาพนิ่งซึ่งช้ากว่า 8 เท่า · เปิดหน้านี้ด้วย https:// "
        + "หรือเปิดบนเครื่องหลักที่ http://127.0.0.1:8866 จะได้ท่อเร็ว");
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
    // ใช้สิทธิ์แย่งจอได้ครั้งเดียวต่อการกดหนึ่งครั้ง — ต่อใหม่อัตโนมัติหลังจากนี้
    // จะไม่มีธงนี้ติดไป เซิร์ฟเวอร์จึงปฏิเสธแทนที่จะเตะคนที่ดูอยู่ออก
    const take = this.forceTake ? "&take=1" : "";
    this.forceTake = false;
    this.socket = new WebSocket(
      `${protocol}://${location.host}/ws/phone/stream`
      + `?serial=${encodeURIComponent(this.serial)}${take}`,
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
      if (event.code === SUPERSEDED_CLOSE) {
        // ไม่ใช่ความผิดพลาด — บอกให้รู้ว่าเกิดอะไรขึ้นและกดกลับมาดูได้เมื่อไร
        this.say(`👀 ${why || "มีหน้าต่างอื่นกำลังดูจอเครื่องนี้อยู่"}`
          + " — กด “เริ่มดูจอ” อีกครั้งเพื่อดึงกลับมาดูที่นี่");
        this.stop();
        return;
      }
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
    // ขนาดภาพจริงเพิ่งรู้ตอนเฟรมแรกมาถึง — โหมด "เท่าจริง" ใช้ตัวเลขนี้คิดความสูง
    // ถ้าไม่คิดใหม่ตรงนี้ จอจะค้างขนาดที่เดาไว้ก่อนรู้ความละเอียดจริง
    sizeSolo();
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

// -------------------------------------------------------- กระดานคิวจอมือถือ
//
// **ทำไมต้องขึ้นหน้าเว็บ** ของเดิมดูได้จาก `python phone_queue.py board` อย่างเดียว
// ซึ่งแปลว่าเจ้าของต้องนึกได้เองว่าต้องไปพิมพ์ดู — บทเรียนเดิมของโปรเจกต์บอกไว้แล้ว
// ว่าอะไรที่พึ่งความจำ สุดท้ายไม่มีใครทำ  ตรงนี้จึงโผล่เองเมื่อมีคนเข้าคิวจริง
// และ **ซ่อนตัวเองเมื่อไม่มีใครรอ** เพื่อไม่ให้กลายเป็นป้ายที่อยู่ตลอดจนคนเลิกมอง
const queueBox = $("#queueBoard");
const QUEUE_REFRESH_MS = 5000;

function agoText(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "";
  if (seconds < 60) return `${Math.round(seconds)} วิ`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} นาที`;
  return `${(seconds / 3600).toFixed(1)} ชม.`;
}

async function refreshQueueBoard() {
  if (!queueBox) return;
  let data;
  try {
    data = await api("/api/phone/queue");
  } catch {
    return;                       // กระดานล่มต้องไม่ส่งเสียงรบกวนงานหลัก
  }
  const busy = (data.devices || []).filter((d) => d.running || (d.waiting || []).length);
  if (!busy.length) {
    queueBox.hidden = true;
    queueBox.textContent = "";
    return;
  }
  const parts = ['<div class="queue-title">คิวใช้จอมือถือ</div>'];
  for (const device of busy) {
    parts.push(`<div class="queue-device"><b>${escapeHtml(device.label || device.serial)}</b>`);
    if (device.running) {
      parts.push(`<div class="queue-now">🟢 ${escapeHtml(device.running.owner)}`
        + ` — ${escapeHtml(device.running.task || "ไม่ได้บอกว่าทำอะไร")}`
        + ` <span class="note">(${agoText(device.running.seconds)})</span></div>`);
    }
    (device.waiting || []).forEach((row, index) => {
      parts.push(`<div class="queue-wait">คิวที่ ${index + 1} · ${escapeHtml(row.owner)}`
        + ` — ${escapeHtml(row.task || "—")}`
        + ` <span class="note">(รอมา ${agoText(row.seconds)})</span></div>`);
    });
    parts.push("</div>");
  }
  queueBox.innerHTML = parts.join("");
  queueBox.hidden = false;
}

function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

window.setInterval(refreshQueueBoard, QUEUE_REFRESH_MS);
refreshQueueBoard();

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
  screensBox.dataset.count = String(shown);
  $("#screenCount").textContent = `${shown}/${total} จอ`;
  $("#removeScreen").disabled = shown === 0;
  $("#addScreen").disabled = shown >= total;
  $("#screensEmpty").hidden = shown > 0;
  // ต้องมาหลังนับเสมอ — ปุ่มเลือกจอกับการซ่อน/โชว์อ่านจำนวนจอไปใช้
  applyView();
  renderTabs();
}

// ------------------------------------------------------- ปุ่มเลือกจอ 1·2·3
//
// **ทำไมต้องมี** ยัดสามจอลงคอลัมน์กว้าง 380px ได้จอละ ~150px กว้าง ซึ่งเล็กจน
// อ่านตัวหนังสือบนมือถือไม่ออกและกดปุ่มพลาดง่าย (วัดจริง 25 ส.ค. 2569:
// แสดงผลได้ 153x341 ทั้งที่ภาพที่ส่งมาคือ 460x1024)
//
// **เลขจอต้องหมายถึงเครื่องเดิมเสมอ** จึงเรียงตามลำดับในทะเบียน ไม่ใช่ลำดับที่
// เปิดจอ ปิด "จอ 2" แล้วเปิดใหม่มันต้องยังเป็นจอ 2 ไม่ใช่ไหลไปเป็นจอสุดท้าย
// (กติกาข้อ 8 — ห้าม hardcode เลข 1/2/3 ทุกที่ต้องวนตามรายชื่อจริงในทะเบียน)
const VIEW_KEY = "phoneView";       // "all" = เรียงทุกจอ · หรือ serial ของจอที่เลือก
const SIZE_KEY = "phoneSize";       // "fit" = พอดีหน้าต่าง · "full" = เท่าภาพจริง
// เผื่อไว้ใต้จอให้บรรทัดคำใบ้ยังโผล่พ้นขอบล่าง — ไม่ใช่ที่อยู่ของทุกอย่างข้างล่าง
const SOLO_TAIL_GAP = 56;
// เตี้ยกว่านี้ก็ไม่มีประโยชน์แล้ว ยอมให้หน้าเลื่อนดีกว่าได้จอจิ๋ว
const SOLO_MIN_HEIGHT = 240;
const tabsBox = $("#screenTabs");
let viewMode = localStorage.getItem(VIEW_KEY) || "";
let sizeMode = localStorage.getItem(SIZE_KEY) || "fit";

/** จอทั้งหมดเรียงตามลำดับในทะเบียน — คือที่มาของเลข "จอ 1 · 2 · 3" */
function screenOrder() {
  const rank = new Map(
    deviceRows.filter((d) => d.enabled).map((d, i) => [d.serial, i]),
  );
  return [...screens.keys()].sort(
    (a, b) => (rank.get(a) ?? 999) - (rank.get(b) ?? 999),
  );
}

function isReady(serial) {
  const row = deviceRows.find((d) => d.serial === serial);
  return !row || row.ready !== false;
}

/** จอที่จะโชว์ใบเดียว — คืนค่าว่างแปลว่าโหมดเรียงทุกจอ */
function soloTarget(order) {
  if (viewMode === "all") return "";
  // เลือกไว้เองต้องได้ตามนั้นเสมอ แม้เครื่องจะถอดสายอยู่ — ของที่ผู้ใช้สั่งเอง
  // ห้ามระบบเปลี่ยนให้เงียบๆ ไม่งั้นเสียบสายกลับมาแล้วงงว่าทำไมไปอยู่จออื่น
  if (screens.has(viewMode)) return viewMode;
  // มีจอเดียวก็ใหญ่ไปเลย ไม่ต้องให้กดอะไร — จะเรียงกับใครก็ไม่มี
  if (order.length === 1) return order[0];
  // **ยังไม่เคยเลือก → ต้องเปิดเครื่องที่เสียบสายอยู่ให้** ของเดิมหยิบตัวแรกใน
  // ทะเบียน ซึ่งบังเอิญเป็นเครื่องที่ถอดสายไว้ ผู้ใช้เปิดหน้าเว็บมาเจอจอเปล่า
  // แล้วนึกว่าระบบพัง ทั้งที่มีอีกเครื่องพร้อมใช้อยู่
  if (focused && screens.has(focused) && isReady(focused)) return focused;
  return order.find(isReady) || focused || order[0] || "";
}

function setView(key) {
  viewMode = key;
  try { localStorage.setItem(VIEW_KEY, key); } catch { /* โหมดส่วนตัวเขียนไม่ได้ */ }
  applyView();
  renderTabs();
}

function applyView() {
  const order = screenOrder();
  const solo = soloTarget(order);
  screensBox.classList.toggle("solo", Boolean(solo));
  screensBox.classList.toggle("many", !solo && screens.size > 1);
  for (const [serial, screen] of screens) {
    screen.card.hidden = Boolean(solo) && serial !== solo;
  }
  // จอที่เห็นอยู่ต้องเป็นจอที่ปุ่มลัด/ช่องพิมพ์/การเทรนตำแหน่งจะไปลงด้วย
  // ไม่งั้นกดปุ่มแล้วไปโผล่เครื่องที่มองไม่เห็นอยู่ = ความเสียหายที่กู้ไม่ได้
  if (solo) focus(solo);
  sizeSolo();
  // การ์ดที่เพิ่งถูกสร้างยังไม่ถูกจัดวาง วัดความสูงตอนนี้จะได้ 0 แล้วจอค้างขนาดสำรอง
  // วัดซ้ำหลังเบราว์เซอร์จัดวางเสร็จอีกรอบ
  requestAnimationFrame(sizeSolo);
}

function makeTab(key, text, serial) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "ghost";
  button.classList.toggle("is-on", key === screensBox.dataset.view);
  if (serial) {
    const row = deviceRows.find((d) => d.serial === serial);
    button.classList.toggle("is-ready", !row || row.ready !== false);
    button.title = labelOf(serial)
      + (row && row.ready === false ? " — ยังไม่ได้เสียบสาย" : "");
    const dot = document.createElement("span");
    dot.className = "tab-dot";
    button.append(dot);
  } else {
    button.title = "เรียงทุกจอให้เห็นพร้อมกัน (จอจะเล็กลง)";
  }
  button.append(document.createTextNode(text));
  button.addEventListener("click", () => setView(key));
  return button;
}

/** ปุ่มสลับขนาด — ป้ายบอก "จะไปโหมดไหน" ไม่ใช่ "ตอนนี้อยู่โหมดไหน" */
function makeSizeButton() {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "ghost size-tab";
  const toFull = sizeMode !== "full";
  button.textContent = toFull ? "⤢ เท่าจริง" : "⤡ พอดีหน้าต่าง";
  button.title = toFull
    ? "โชว์เท่าความละเอียดที่มือถือส่งมาจริง — หน้าต่างเตี้ยกว่านั้นต้องเลื่อนหน้าดู"
    : "ย่อให้พอดีหน้าต่าง ไม่ต้องเลื่อนหน้า";
  button.addEventListener("click", () => {
    sizeMode = toFull ? "full" : "fit";
    try { localStorage.setItem(SIZE_KEY, sizeMode); } catch { /* โหมดส่วนตัวเขียนไม่ได้ */ }
    sizeSolo();
    renderTabs();
  });
  return button;
}

function renderTabs() {
  if (!tabsBox) return;
  const order = screenOrder();
  tabsBox.hidden = order.length === 0;
  if (tabsBox.hidden) { tabsBox.replaceChildren(); return; }
  const solo = soloTarget(order);
  screensBox.dataset.view = solo || "all";
  const items = [];
  // จอเดียวไม่มีอะไรให้สลับ — ปุ่มที่กดแล้วไม่เกิดอะไรมีแต่ทำให้สับสน
  if (order.length > 1) {
    items.push(makeTab("all", "ทุกจอ", ""));
    for (const [index, serial] of order.entries()) {
      items.push(makeTab(serial, `จอ ${index + 1}`, serial));
    }
  }
  // ปุ่มขนาดใช้ได้เฉพาะตอนดูจอเดียว — เรียงทุกจอแล้วขยายทีละใบไม่ได้อยู่แล้ว
  if (solo) items.push(makeSizeButton());
  tabsBox.replaceChildren(...items);
}

/** ตั้งความสูงจอเดียวให้เต็มที่ว่างจริง — วัดสดทุกครั้ง ไม่ใช้เลขตายตัว */
function sizeSolo() {
  // พับแถบเก็บอยู่ วัดอะไรก็ได้ 0 หมด แล้วจะไปตั้งความสูงเป็นค่าต่ำสุดค้างไว้
  if (screensBox.closest(".phone-panel")?.classList.contains("folded")) return;
  if (!screensBox.classList.contains("solo")) {
    screensBox.style.removeProperty("--solo-h");
    document.body.style.removeProperty("--phone-col");
    return;
  }
  const screen = [...screens.values()].find((s) => !s.card.hidden);
  if (!screen) return;
  const panel = screensBox.closest(".phone-panel") || screensBox.parentElement;

  // ขอบทั้งหมดที่กินความกว้างไป = ความกว้างแผง ลบ ที่ว่างจริงข้างในการ์ด
  // **วัดเอา ไม่ไล่นับเอง** — ขอบมีทั้ง padding · border · ช่องไฟ · แถบเลื่อน
  // ซึ่งเปลี่ยนตามธีมและขนาดหน้าต่าง ตอนแรกผมไล่นับเองแล้วพลาดไป 16 จุด
  // จอเลยเหลือขอบขาวทั้งสองโหมด (พอดีหน้าต่าง 36 จุด · เท่าจริง 37 จุด)
  const edge = () => {
    const cs = getComputedStyle(screen.card);
    const px = (name) => parseFloat(cs.getPropertyValue(name)) || 0;
    const inner = screen.card.getBoundingClientRect().width
      - px("padding-left") - px("padding-right")
      - px("border-left-width") - px("border-right-width");
    return { inner, outside: panel.getBoundingClientRect().width - inner };
  };

  // **ห้ามหดคอลัมน์ให้แคบกว่าค่าปกติเด็ดขาด**
  //
  // เจอจริงตอนแก้บั๊กนี้: ผมหดคอลัมน์จาก 380 เหลือ 303 จุดเพื่อให้พอดีภาพ
  // ผลคือแถบปุ่มหัวแผง (ช่องเลือกเครื่อง · ปุ่มจอ 1/2/3 · ปุ่มขนาด) **ตัดบรรทัด
  // จาก 2 แถวเป็น 4 แถว** กินที่แนวตั้งเพิ่มอีกเกือบร้อยจุด ที่ว่างของจอจึงหดตาม
  // แล้วรอบถัดไปก็หดคอลัมน์ลงอีก — ยิ่งแก้ยิ่งเล็ก
  //
  // วัดค่าปกติด้วยการถอดค่าที่เราตั้งออกก่อน แล้วดูว่า CSS ให้มาเท่าไร
  document.body.style.removeProperty("--phone-col");
  const floorWidth = panel.getBoundingClientRect().width;

  // เต็มขนาด = โชว์เท่าความละเอียดที่เครื่องส่งมาจริง ไม่ย่อสักพิกเซล
  // หน้าต่างเตี้ยกว่านั้นก็ปล่อยให้หน้าเลื่อนเอา ดีกว่าบีบจนอ่านตัวหนังสือไม่ออก
  if (sizeMode === "full" && screen.canvas && screen.canvas.height > 1) {
    screensBox.style.setProperty("--solo-h", `${screen.canvas.height}px`);
    // **คอลัมน์ต้องกว้างพอด้วย** ไม่งั้น max-width บีบภาพลง แล้วอัตราส่วนก็ลาก
    // ความสูงลงตาม = กดว่า "เท่าจริง" แล้วได้ไม่เท่าจริง
    document.body.style.setProperty(
      "--phone-col",
      `${Math.ceil(Math.max(floorWidth, screen.canvas.width + edge().outside))}px`,
    );
    return;
  }
  const card = screen.card.getBoundingClientRect();
  const viewer = screen.viewer.getBoundingClientRect();
  if (!card.height) return;
  // ส่วนของการ์ดที่ไม่ใช่ตัวจอ (หัวจอ + แถบปุ่มล่าง + ขอบ) — เปลี่ยนได้ตามข้อความ
  const chrome = card.height - viewer.height;
  // **ต้องวัดจากตำแหน่งที่แผงจะไป "ติดหนึบ" ไม่ใช่ตำแหน่งตอนนี้**
  // แผงมือถือเป็น sticky พอเลื่อนหน้าลงมันจะขึ้นไปติดขอบบนแล้วมีที่ว่างเพิ่มอีกมาก
  // ถ้าวัดจากตำแหน่งตอนเพิ่งเปิดหน้า (ยังไม่เลื่อน · มีแถบเตือนเวอร์ชันคั่น)
  // จะได้จอเตี้ยค้างไว้ตลอด — เจอจริงรอบแรก: คำนวณได้ 240px ทั้งที่มีที่ว่าง 460px
  //
  // และ **ห้ามเอาของใต้ตารางจอมานับ** ปุ่มลัด · ช่องลิงก์ · ช่องแคปชัน อยู่ใต้
  // ลงไปทั้งแถบและเลื่อนดูได้ ถ้านับมันด้วยจะเหลือที่ว่างติดลบทุกครั้ง
  //
  // **แต่ก็ห้ามเชื่อว่ามันจะขึ้นไปติดขอบบนได้เสมอ** — แผงจะเลื่อนขึ้นได้ก็ต่อเมื่อ
  // หน้ามีที่ให้เลื่อนจริง ถ้าเนื้อหาทั้งหน้าสั้นกว่าหน้าต่าง แผงจะค้างอยู่ที่เดิม
  // ตลอดกาล แล้วจอที่คำนวณจากตำแหน่งติดหนึบจะยาวเลยขอบล่างออกไปโดยไม่มีทางเลื่อนดู
  //
  // เกิดจริงบนจอผู้ใช้ 2160x999 เมื่อ 26 ส.ค. 2569: แผงอยู่ที่ 149 และหน้าเลื่อน
  // ไม่ได้เลย (scrollHeight = innerHeight) แต่โค้ดคิดว่าแผงจะไปอยู่ที่ 12
  // จึงตั้งจอสูงเกินไป **137 จุด** ผลคือก้นการ์ดจมหายใต้ขอบล่าง 81 จุด
  // — ผู้ใช้เห็นเป็น "จอโดนตัด" ซึ่งคือคำถามที่ถามมาพอดี
  const stickyTop = parseFloat(getComputedStyle(panel).top) || 0;
  const canScroll = Math.max(
    0, document.documentElement.scrollHeight - window.innerHeight,
  );
  const panelTop = panel.getBoundingClientRect().top + window.scrollY;
  const settleTop = Math.max(stickyTop, panelTop - canScroll);
  const above = screensBox.getBoundingClientRect().top
    - panel.getBoundingClientRect().top;
  const room = Math.max(
    SOLO_MIN_HEIGHT,
    Math.round(window.innerHeight - settleTop - above - chrome - SOLO_TAIL_GAP),
  );

  // **ที่ว่างแนวตั้งอย่างเดียวตัดสินไม่ได้ — คอลัมน์ต้องกว้างพอด้วย**
  //
  // บั๊กที่แก้ตรงนี้ (วัดจริงบนจอผู้ใช้ 2160x999 เมื่อ 26 ส.ค. 2569):
  // ที่ว่างแนวตั้ง 813 จุด โค้ดจึงตั้งจอสูง 813 — แต่คอลัมน์กว้างแค่ 312
  // ภาพ 460x1024 ที่ `object-fit: contain` จึงขยายได้แค่ 312x694
  // เหลือ **แถบขาวบนล่างรวม 118 จุด** ทั้งที่พื้นที่ขวามือว่างอยู่ 1,714 จุด
  // ผู้ใช้เห็นเป็น "จอเล็กแล้วมีขอบขาว" โดยไม่รู้ว่าเพราะอะไร
  //
  // แก้โดยคิดกลับ: อยากได้สูง `room` ต้องกว้างเท่าไร แล้วขยายคอลัมน์ให้เท่านั้น
  const shape = screen.canvas && screen.canvas.height > 1
    ? screen.canvas.width / screen.canvas.height
    : 0;
  if (shape <= 0) {                 // ยังไม่รู้สัดส่วนจอ ทำได้แค่ตั้งความสูงไปก่อน
    document.body.style.removeProperty("--phone-col");
    screensBox.style.setProperty("--solo-h", `${room}px`);
    return;
  }

  // **เลิกเดาความหนาของขอบ — ให้เบราว์เซอร์บอกเอง**
  //
  // ตอนแรกผมคิดขอบเองด้วย `sideChrome()` แล้วพลาดไป 16 จุด จอเลยเหลือขอบขาว
  // 36 จุด และครั้งหนึ่งยังตั้งคอลัมน์ **แคบกว่าค่าปกติ** จนจอเล็กลงกว่าเดิมด้วย
  // ขอบมีทั้ง padding · border · ช่องไฟ · แถบเลื่อน ซึ่งเปลี่ยนไปตามธีมและ
  // ขนาดหน้าต่าง ไล่นับให้ครบทุกกรณีไม่มีทางถูกตลอด
  //
  // วิธีที่ถูกคือ **ตั้งให้สูงเกินไว้ก่อน** แล้ววัดว่าตัวจอถูกบีบเหลือกว้างเท่าไร
  // ค่าที่วัดได้ตอนนั้นคือความกว้างที่มีจริง รวมขอบทุกชนิดไปแล้วโดยไม่ต้องนับเอง
  // จังหวะ 1 — ขอคอลัมน์ให้กว้างพอสำหรับภาพที่สูงเต็มที่ว่าง
  const want = room * shape;
  document.body.style.setProperty(
    "--phone-col", `${Math.ceil(Math.max(floorWidth, want + edge().outside))}px`,
  );

  // จังหวะ 2 — วัดว่าได้จริงเท่าไร (CSS ยังกั้นเพดานไว้ที่ 46vw จอแคบจึงได้ไม่ครบ)
  // แล้วตัดความสูงลงมาให้พอดีกับความกว้างที่ได้ — ไม่เหลือขอบขาวไม่ว่าจอกว้างแค่ไหน
  const room2 = Math.floor(Math.min(want, edge().inner) / shape);
  screensBox.style.setProperty(
    "--solo-h", `${Math.max(SOLO_MIN_HEIGHT, Math.min(room, room2))}px`,
  );

  // จังหวะ 3 — **ด่านสุดท้าย: วัดผลลัพธ์จริง อย่าเชื่อการคำนวณ**
  //
  // ตัวเลขนำเข้าทุกตัวข้างบน (ตำแหน่งแผง · ความสูงของเหนือจอ · ความสามารถในการเลื่อน)
  // ยังขยับได้อีกหลายวินาทีระหว่างหน้ากำลังโหลดข้อมูลจากเซิร์ฟเวอร์ คิดเก่งแค่ไหน
  // ก็พลาดได้ถ้านำเข้าเพี้ยน — วัดก้นการ์ดจริงแล้วหดตามที่จมจริงจึงไม่มีทางพลาด
  // (ไล่บั๊กนี้มาแล้วสองรอบ: จมใต้ขอบล่าง 81 จุด แล้ว 24 จุด ทั้งที่คำนวณว่าพอดี)
  for (let pass = 0; pass < 3; pass += 1) {
    const over = Math.round(screen.card.getBoundingClientRect().bottom)
      - window.innerHeight + 8;
    if (over <= 0) break;
    const nowH = parseFloat(screensBox.style.getPropertyValue("--solo-h")) || room;
    const next = Math.max(SOLO_MIN_HEIGHT, Math.round(nowH - over));
    if (next >= nowH) break;
    screensBox.style.setProperty("--solo-h", `${next}px`);
    document.body.style.setProperty(
      "--phone-col", `${Math.ceil(Math.max(floorWidth, next * shape + edge().outside))}px`,
    );
  }
}

// ย่อ/ขยายหน้าต่างแล้วจอต้องโตตาม ไม่ใช่ค้างขนาดเดิมจนล้นออกนอกหน้าจอ
window.addEventListener("resize", sizeSolo);

// **คิดครั้งเดียวตอนเปิดหน้าไม่พอ — ของเหนือจอโตทีหลังได้อีกหลายวินาที**
//
// เจอจริง 26 ส.ค. 2569: คิดตอนเพิ่งโหลดได้ที่ว่าง 240 จุด (ค่าต่ำสุด) จอเลยยุบ
// เหลือ 108x240 แล้วค้างอยู่อย่างนั้น ทั้งที่พอหน้าจัดวางเสร็จมีที่ว่างจริง 646 จุด
// ของที่โตทีหลังคือ รายชื่อเครื่อง · ชิปแรม/เนื้อที่ · แถบเตือนเวอร์ชัน ซึ่งมาจาก
// การถามเซิร์ฟเวอร์ จึงมาถึงช้ากว่าเฟรมแรกของเบราว์เซอร์เสมอ
//
// `requestAnimationFrame` รอบเดียวแบบเดิมช่วยได้แค่เฟรมถัดไป ไม่ครอบคลุมของที่
// มาอีกสองวินาทีให้หลัง — ต้องเฝ้าไว้ตลอดแล้วคิดใหม่ทุกครั้งที่แผงเปลี่ยนความสูง
if (typeof ResizeObserver === "function") {
  let queued = false;
  const soon = () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; sizeSolo(); });
  };
  const watcher = new ResizeObserver(soon);
  const panel = screensBox.closest(".phone-panel") || screensBox.parentElement;
  if (panel) watcher.observe(panel);
  watcher.observe(screensBox);
}

// ------------------------------------------------- พับแถบมือถือทั้งแถบ
//
// **จำเป็นบนไอแพด** จอแคบกว่า 900 จุดหน้าเว็บจะเรียงเป็นคอลัมน์เดียว แถบมือถือ
// จึงไปกองอยู่ข้างบนทั้งหมด ต้องเลื่อนผ่านจอมือถือ + ปุ่มลัด + ช่องลิงก์ + ช่อง
// แคปชัน + Wi-Fi ก่อนจะถึงงานที่ตั้งใจจะมาทำจริง — พับเก็บได้จบเรื่อง
const FOLD_KEY = "phoneFold";
// ตรงกับจุดที่ styles.css สลับเป็นคอลัมน์เดียว ถ้าแก้ที่นั่นต้องแก้ที่นี่ด้วย
const NARROW_PX = 900;
const foldButton = $("#phoneFold");
const phonePanel = screensBox.closest(".phone-panel");

function applyFold(folded) {
  if (!phonePanel || !foldButton) return;
  phonePanel.classList.toggle("folded", folded);
  foldButton.setAttribute("aria-expanded", String(!folded));
  const hint = $("#phoneFoldHint");
  if (hint) hint.textContent = folded ? "แตะเพื่อกางออก" : "แตะเพื่อพับเก็บ";
  // กางออกแล้วต้องคิดความสูงจอใหม่ — ตอนพับอยู่วัดอะไรก็ได้ 0 ทั้งหมด
  if (!folded) sizeSolo();
}

if (foldButton && phonePanel) {
  let saved = null;
  try { saved = localStorage.getItem(FOLD_KEY); } catch { /* โหมดส่วนตัว */ }
  // ยังไม่เคยเลือกเอง: จอแคบพับไว้ก่อน (ไอแพด/มือถือ) จอกว้างกางไว้เหมือนเดิม
  applyFold(saved === null ? window.innerWidth <= NARROW_PX : saved === "1");
  foldButton.addEventListener("click", () => {
    const next = !phonePanel.classList.contains("folded");
    try { localStorage.setItem(FOLD_KEY, next ? "1" : "0"); } catch { /* ไม่เป็นไร */ }
    applyFold(next);
  });
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
deviceSelect.addEventListener("change", () => {
  focus(deviceSelect.value);
  // เลือกเครื่องจากช่องนี้ตอนกำลังดูจอเดียว ต้องสลับจอที่โชว์ตามไปด้วย
  // ไม่งั้นเลือกเครื่องหนึ่งแต่ตายังเห็นอีกเครื่อง แล้วกดปุ่มลัดผิดตัว
  if (viewMode !== "all" && screens.has(deviceSelect.value)) {
    setView(deviceSelect.value);
  }
});

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

// ---- กลับมาดูอีกครั้งแล้วภาพต้องมาเอง
//
// **ทำไมต้องมี** ฝั่งเซิร์ฟเวอร์ไล่ "ตัวถ่ายจอที่ไม่มีคนดู" ออกเป็นระยะ เพื่อไม่ให้
// สะสมจนกินแรมมือถือ (26 ส.ค. 2569 เคยค้าง 12 ตัวบนเครื่องเดียว กิน 596 MB)
// พอสลับแท็บไปทำอย่างอื่นนานๆ แล้วกลับมา ท่ออาจถูกตัดไปแล้ว ถ้าไม่ต่อคืนให้
// ผู้ใช้จะเห็นจอค้างนิ่งแล้วนึกว่าระบบพัง
//
// **ต่อคืนเฉพาะจอที่ยังเปิดค้างไว้** จอที่ผู้ใช้กด "หยุด" เองห้ามเปิดคืนเด็ดขาด
// (ยังกด "เริ่มดูจอ" เองได้ตามปกติ)
document.addEventListener("visibilitychange", () => {
  if (document.hidden) return;
  for (const screen of screens.values()) {
    if (!screen.live) continue;
    const open = screen.socket && screen.socket.readyState === WebSocket.OPEN;
    if (open) continue;
    screen.streamTries = 0;
    screen.say("กลับมาแล้ว — กำลังต่อภาพคืน…");
    if (supportsWebCodecs) screen.startStream();
    else screen.startPolling();
  }
});

// ---- ปลุกจอ (คนละเรื่องกับปุ่ม ⏻ ซึ่งเป็นปุ่มสลับ)
$("#phoneWake")?.addEventListener("click", async () => {
  const serial = deviceSelect.value;
  if (!serial) {
    phoneNote.textContent = "เลือกมือถือก่อน";
    return;
  }
  const button = $("#phoneWake");
  button.disabled = true;
  phoneNote.textContent = "กำลังปลุกจอ…";
  try {
    const result = await api("/api/phone/wake", {
      method: "POST",
      body: JSON.stringify({ serial }),
    });
    // บอกสถานะก่อน-หลังให้เห็น จะได้รู้ว่าจอดับอยู่จริงหรือติดอยู่แล้ว
    phoneNote.textContent = result.before === "Awake"
      ? "จอติดอยู่แล้ว — ปัดหน้าล็อกออกให้อีกที"
      : `ปลุกจอแล้ว (จาก ${result.before} → ${result.after})`;
  } catch (error) {
    phoneNote.textContent = error.message;
  } finally {
    button.disabled = false;
  }
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
