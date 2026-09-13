/* จุดเริ่มทำงาน — ไฟล์เดียวที่ index.html โหลด ที่เหลือถูก import ต่อกันเป็นทอดๆ */

import { api, config, hooks, pollHealth, pollLogs, setConfig, setSystem, system } from "./core.js";
import { loadDevices, loadTargets } from "./phone.js";
import { loadFbGroups, loadFbJobs, renderQueue, setQueue } from "./post.js";
import { loadGroupHealth } from "./groups.js";
import { loadPrompts, openPrompts } from "./prompts.js";
import { loadBoard } from "./board.js";
import { loadFbControl, watchFbControl } from "./fbcontrol.js";
import { loadEngage, wireEngage } from "./engage.js";
import { fillGems, fillInput, fillRelease, loadClips, loadJobQueue, loadStoryRuns } from "./video.js";

// เวอร์ชันที่หน้านี้ "ควรคู่กับ" เซิร์ฟเวอร์ = อ่านจาก ?v= ของตัวเองอัตโนมัติ
// เดิมอ่านจาก <script src> ของ app.js — ตอนนี้เป็นโมดูล ใช้ import.meta.url ตรงกว่า
// ห้าม hardcode เลขที่นี่เด็ดขาด (เคยชนกัน 3 รอบใน 1 วันตอนหลายแชทแก้พร้อมกัน)
const EXPECTED_SERVER_VERSION = new URL(import.meta.url).searchParams.get("v") || "";

// ============================================================== เริ่มต้น
async function reloadConfig() {
  setConfig(await api("/api/config"));
  fillInput();
  fillGems();
  fillRelease();
  setQueue(config.publish_queue.map((step) => ({ ...step })));
  renderQueue();
}

// GEMS (video.js) ต้องสั่งโหลด config ใหม่ได้ แต่ boot โหลดทีหลัง import ย้อนไม่ได้
hooks.reloadConfig = () => reloadConfig();

(async () => {
  try {
    setSystem(await api("/api/system"));
    if (EXPECTED_SERVER_VERSION && system.app_version !== EXPECTED_SERVER_VERSION) {
      document.body.insertAdjacentHTML(
        "afterbegin",
        `<p style="color:#cf7a68;padding:8px 16px;border-bottom:1px solid #cf7a68">` +
          `หน้าเว็บกับเซิร์ฟเวอร์เป็นคนละรุ่น (หน้า ${EXPECTED_SERVER_VERSION} / ` +
          `เซิร์ฟเวอร์ ${system.app_version}) — ปิดเซิร์ฟเวอร์แล้วเปิดใหม่ หรือกด Ctrl+F5</p>`,
      );
    }
    // ที่เก็บงานโพสต์ถอยไปใช้โฟลเดอร์เปล่า = ทั้งสายโพสต์ตาบอด ต้องเห็นทันที
    // ที่เปิดหน้า ไม่ใช่ไปเจอเอาตอนสั่งโพสต์แล้วขึ้นว่า "ไม่มีกลุ่ม" (31 ส.ค. 2569)
    if (system.post_dir_ready === false) {
      document.body.insertAdjacentHTML(
        "afterbegin",
        `<p style="color:#f8a0a0;background:#3a1f22;padding:10px 16px;` +
          `border-bottom:2px solid #a2545c;line-height:1.6">` +
          `<b>⚠️ ที่เก็บงานโพสต์ใช้ไม่ได้ — ทะเบียนกลุ่มและใบงานจะขึ้นว่าว่างทั้งที่ของจริงยังอยู่ครบ</b>` +
          `<br>${system.post_dir_why || "ปิดเซิร์ฟเวอร์แล้วเปิดใหม่เมื่อ Google Drive พร้อม"}</p>`,
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
    // แท็บสถานะกลุ่ม — อ่านฐานข้อมูลโพสต์ 1.7 GB จึงโหลดครั้งเดียวตอนเปิด
    // แล้วให้กดปุ่มโหลดใหม่เอง ไม่ตั้งให้ดึงซ้ำอัตโนมัติ (เปลืองเปล่า
    // เพราะบอทเก็บโพสต์รอบละหลายนาที ตัวเลขไม่ได้ขยับทุกวินาที)
    await loadGroupHealth();
    document.querySelector("#ghReload")?.addEventListener("click", loadGroupHealth);
    // หน้าคำสั่ง AI — ยังไม่โหลดจนกว่าจะกดเฟือง (ข้อความยาวรวมหลายพันตัว
    // และเปิดดูนานๆ ครั้ง ดึงตอนเปิดหน้าทุกครั้งคือเสียเปล่า)
    document.querySelector("#ppOpen")?.addEventListener("click", openPrompts);
    document.querySelector("#ppReload")?.addEventListener("click", loadPrompts);
    // กระดานกลุ่มที่บอทสำรวจ — 1,588 กลุ่ม จึงโหลดทีเดียวตอนเปิดแล้วจบ
    // ส่วนกอง "ไม่ดี" ขอเป็นรายกองตอนกดเปิด (ดู board.js)
    await loadBoard();
    document.querySelector("#bdReload")?.addEventListener("click", loadBoard);
    // แผงคุมบอทสายโพสต์ — ดูสดทุก 5 วิเฉพาะตอนแท็บเปิดอยู่ (ดู fbcontrol.js)
    await loadFbControl();
    watchFbControl();
    // ตอบคอมเมนต์ — อ่านจากฐานข้อมูลที่บอทเก็บไว้ ไม่ได้แตะ Facebook
    // จึงดึงครั้งเดียวตอนเปิดหน้าพอ เปลี่ยนเฉพาะตอนบอทเก็บรอบใหม่หรือคนกดโหลด
    wireEngage();
    await loadEngage();
    document.querySelector("#fcReload")?.addEventListener("click", loadFbControl);
    await pollLogs();
    // ไว้ท้ายสุด — อ่านจำนวนมือถือจาก dropdown ที่ loadDevices เติมไว้แล้ว
    await pollHealth();
  } catch (error) {
    document.body.insertAdjacentHTML(
      "afterbegin",
      `<p style="color:#f8a0a0;padding:8px 16px">โหลดไม่สำเร็จ: ${error.message}</p>`,
    );
  }
})();
