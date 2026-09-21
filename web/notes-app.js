/* หน้าโน้ตเดี่ยวสำหรับมือถือ (/notes) — ติดตั้งเป็นแอปบนจอโฮมได้
 *
 * เจ้าของสั่ง 21 ก.ย. 2569 — "เขียนแอพแอนดรอยที่ซิ้งข้อมูลในโน้ตขึ้นบนเว็บ
 * ให้หน่อย แล้วถ้าวางข้อมูลบนเว็ปให้สามารถเปิดดูในมือถือได้ด้วย"
 *
 * **ไม่มีการซิงก์สองทางให้ต้องมาแก้ชนกัน** ข้อมูลอยู่ที่เซิร์ฟเวอร์ที่เดียว
 * ทั้งคอมและมือถืออ่านเขียนกองเดียวกัน พิมพ์ฝั่งไหนอีกฝั่งก็เห็น
 *
 * **ไม่ import core.js โดยตั้งใจ** ไฟล์นั้น 50 KB และมีตัวดึงสถานะที่วิ่งเป็น
 * ระยะ ซึ่งหน้านี้ไม่ได้ใช้เลย — เปลืองเน็ตกับแบตมือถือเปล่าๆ
 */
import { mountNotes } from "./notes-ui.js";

/** ตัวยิง API แบบย่อ — รูปแบบผลลัพธ์/ข้อผิดพลาดเหมือน core.js เป๊ะ
 *  เพื่อให้ notes-ui.js ใช้ได้โดยไม่ต้องรู้ว่าถูกเรียกจากหน้าไหน */
async function api(path, options = {}) {
  const answer = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  let data = null;
  try {
    data = await answer.json();
  } catch {
    data = null;
  }
  if (!answer.ok) {
    // ข้อความไทยมาจากเซิร์ฟเวอร์ครบแล้ว เอามาแสดงตรงๆ
    throw new Error(data?.detail || `เซิร์ฟเวอร์ตอบ ${answer.status}`);
  }
  return data;
}

const root = document.querySelector("#notesRoot");
const ui = mountNotes(root, api);

async function refresh() {
  try {
    await ui.load();
    if (!ui.count) ui.tellState("ยังไม่มีโน้ต กด ＋ เพื่อเริ่มใบแรก");
  } catch (error) {
    ui.tellState(`โหลดโน้ตไม่ได้: ${error.message}`, true);
  }
}

refresh();

/* กลับเข้าแอปเมื่อไรให้ดึงของใหม่ — คนพิมพ์บนคอมไว้ พอหยิบมือถือขึ้นมาต้องเห็น
 *
 * **ไม่ใช้การดึงซ้ำทุกกี่วินาที** เพราะหน้านี้อยู่บนมือถือ การยิงถามทั้งวัน
 * กินแบตและเน็ตเปล่า ในขณะที่คนเปิดดูจริงแค่ตอนหยิบเครื่องขึ้นมา
 *
 * ตัว flush ของ notes-ui ทำงานตอนหน้าถูกซ่อนอยู่แล้ว จึงไม่มีทางที่การดึงใหม่
 * ตอนกลับมาจะไปทับข้อความที่ยังไม่ได้บันทึก
 */
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") refresh();
});

/* ตัวช่วยให้เปิดได้ตอนเน็ตสะดุด — เก็บหน้ากับไฟล์หน้าตาไว้
 * ตัวข้อมูลโน้ต (/api/) ไม่แคช เพราะต้องได้ของสดเสมอ */
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw-notes.js").catch(() => {
    // จดทะเบียนไม่ได้ก็ยังใช้งานได้ปกติ แค่ไม่มีตัวช่วยตอนเน็ตหลุด
  });
}
