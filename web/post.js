/* งานฝั่งโพสต์: ผังโพสต์วิดีโอ (Shopee Video / Facebook Reels) · โพสต์ลงกลุ่ม Facebook */

import { $, api } from "./core.js";
import { deviceSelect, touchIntercept } from "./phone.js";

// ============================================================ Publish 💰
const ACTIONS = [
  ["train", "เทรนตำแหน่ง"],
  ["shopee", "พิมพ์ link Shopee"],
  ["lazada", "พิมพ์ link Lazada"],
  ["hashtags", "พิมพ์ # แฮชแท็ก"],
];
export let queue = [];
// boot.js เป็นคนโหลด config แล้วเทค่าเริ่มต้นเข้ามา — ESM เขียนทับตัวแปรที่ import มาไม่ได้
export function setQueue(items) { queue = items; }
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

export function renderQueue() {
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
    touchIntercept.fn = null;
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
  touchIntercept.fn = async (point) => {
    touchIntercept.fn = null;
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
  // ขั้นที่กำลังรันอยู่ (เลขขั้น หรือ "all") — ตัวนี้คือสิ่งเดียวที่ทำให้ผู้ใช้เห็นว่า
  // กดปุ่มติดแล้ว ระหว่างรอ API ซึ่งใช้เวลาจริง 6–15 วินาทีต่อขั้น
  let pfRunning = null;

  const pfNote = (text) => { $("#pfNote").textContent = text; };

  /** เขียนข้อความสถานะ **แล้วเลื่อนให้เห็นด้วย**
   *
   * `#pfNote` อยู่ **ใต้รายการ 28 ขั้น** ใน index.html กดปุ่มของขั้นต้นๆ แล้วข้อความ
   * ไปโผล่นอกจอ ผู้ใช้จึงเห็นว่า "กดแล้วไม่มีอะไรเกิดขึ้น" ทั้งที่ระบบทำงานอยู่
   *
   * 18 ส.ค. 2026 ผู้ใช้แจ้งว่าปุ่ม ▶ ไม่ทำงาน — ตรวจแล้วปุ่มยิง API ได้ HTTP 200
   * และมือถือขยับจริง (ขั้น 1 ใช้ 6.2 วิ · ขั้น 2 ใช้ 12.4 วิ) ปัญหาคือไม่มีอะไร
   * ตอบสนองตรงที่สายตาอยู่ ไม่ใช่ปุ่มเสีย
   */
  const pfNoteSeen = (text) => {
    pfNote(text);
    try {
      $("#pfNote").scrollIntoView({ block: "nearest", behavior: "smooth" });
    } catch (error) { /* เบราว์เซอร์เก่าไม่รองรับ ไม่ใช่เรื่องคอขาดบาดตาย */ }
  };

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

  /** กล่องที่เลื่อนจริงของ element นี้ — ไล่ขึ้นไปหาตัวแรกที่เลื่อนได้
   *
   *  **ห้ามเดาชื่อไว้ล่วงหน้า** เพราะตัวที่เลื่อนไม่ตายตัว — `.process-panel`
   *  มี `overflow-y: auto` เฉพาะในเงื่อนไขขนาดจอ จอกว้างจึงเลื่อนที่แผงนั้น
   *  ส่วนจอแคบเลื่อนทั้งหน้า จำค่าจากตัวผิดแล้วคืนก็เหมือนไม่ได้แก้อะไรเลย
   */
  function scrollBoxOf(node) {
    let box = node?.parentElement;
    while (box && box !== document.body) {
      const how = getComputedStyle(box).overflowY;
      if (/(auto|scroll)/.test(how) && box.scrollHeight > box.clientHeight) return box;
      box = box.parentElement;
    }
    return document.scrollingElement || document.documentElement;
  }

  /** วาดผังใหม่ทั้งก้อน — **แต่ต้องไม่ทำให้หน้ากระโดด**
   *
   *  **เจ้าของสั่ง 30 ส.ค. 2569** — *"ตอนกดเทรนเสร็จ หน้าฝั่งขวามันชอบเด้ง
   *  เลื่อนลง แก้ด้วย มันเวียนหัว ให้มันอยู่แบบเดิมเฉยๆ"*
   *
   *  `replaceChildren` ลบแถวเดิมทิ้งแล้วสร้างใหม่หมด เบราว์เซอร์จึงเสียตำแหน่ง
   *  ที่เลื่อนค้างไว้ ผังยาว 23 ขั้นและต้องเทรนทีละจุดหลายจุดติดกัน จึงเจอทุกครั้ง
   *
   *  คืนตำแหน่งใน `requestAnimationFrame` เท่านั้น — คืนทันทีหลังวาดจะไม่ติด
   *  เพราะตอนนั้นเบราว์เซอร์ยังไม่ได้จัดวางแถวใหม่ ความสูงยังเป็นของเก่าอยู่
   */
  function pfRender() {
    const list = $("#pfList");
    const box = scrollBoxOf(list);
    const keep = box ? box.scrollTop : 0;
    list.replaceChildren(
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

        // กำลังรันอยู่ = ล็อกปุ่มทุกอันในผัง เพราะเซิร์ฟเวอร์รับได้ทีละงาน
        // (กดซ้ำได้แต่จะโดนตอบ 409 ซึ่งดูเหมือนพัง ทั้งที่ระบบทำงานถูกแล้ว)
        if (pfRunning !== null) {
          tools.querySelectorAll("button").forEach((button) => {
            button.disabled = true;
          });
        }

        row.append(head, meta, tools);

        // สถานะต้องขึ้น **ในแถวที่กด** ไม่ใช่ท้ายรายการ — ผู้ใช้มองอยู่ตรงนี้
        if (pfRunning !== null && pfRunning === step.order) {
          row.classList.add("running");
          const busy = document.createElement("small");
          busy.className = "note";
          busy.textContent =
            "⏳ กำลังสั่งมือถือทำขั้นนี้… (บางขั้นใช้เวลาถึง 15 วินาที)";
          row.append(busy);
        } else if (step.result) {
          const result = document.createElement("small");
          result.className = "note";
          result.textContent =
            (step.result.ok ? "✓ " : "✗ ") + step.result.message;
          row.append(result);
        }
        return row;
      }),
    );
    // คืนตำแหน่งเลื่อนเดิม — ต้องรอให้เบราว์เซอร์วางแถวใหม่เสร็จก่อน
    if (box && keep) requestAnimationFrame(() => { box.scrollTop = keep; });
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
      pfArmed = null; touchIntercept.fn = null; pfRender();
      pfNote("ยกเลิกการเทรนแล้ว");
      return;
    }
    if (!deviceSelect.value) { pfNote("เลือกมือถือแล้วเริ่มดูจอก่อน"); return; }
    pfArmed = step.id;
    armedStep = null;               // กันชนกับตัวเทรนแบบเดิมที่ใช้ตัวดักตัวเดียวกัน
    pfRender();
    pfNote(`กำลังเทรน "${step.name}" — คลิกจุดบนจอมือถือ`);
    touchIntercept.fn = async (point) => {
      touchIntercept.fn = null;
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
    // ข้อความเตือนพวกนี้ต้อง **เลื่อนให้เห็น** ไม่งั้นกดแล้วเงียบสนิท
    // เหมือนปุ่มเสีย ทั้งที่ระบบแค่บอกว่ายังไม่ได้เลือกมือถือ
    if (!deviceSelect.value) { pfNoteSeen("เลือกมือถือก่อน"); return; }
    if (pfRunning !== null) { pfNoteSeen("กำลังรันอยู่ รอให้ขั้นก่อนหน้าจบก่อน"); return; }
    // รันทั้งผังจบที่ "กดโพสต์" ซึ่งเรียกคืนไม่ได้ — ต้องให้คนยืนยันก่อนเสมอ
    if (!only && !window.confirm(
      "รันทั้งผังบนมือถือจริง — ขั้นสุดท้ายคือกดโพสต์ ยืนยันไหม?",
    )) return;

    // ตั้งสถานะ **แล้ววาดใหม่ทันที** ก่อนจะไปรอ API — ตรงนี้คือสิ่งที่หายไป
    // ทำให้ผู้ใช้เห็นว่ากดไม่ติด ทั้งที่ระบบกำลังสั่งมือถืออยู่
    pfRunning = only || "all";
    pfRender();
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
      const tags = (data.tags || []).map((tag) =>
        `#${tag.tag} ${tag.count === null ? "อ่านยอดไม่ได้" : tag.count.toLocaleString()}` +
        (tag.used ? " ✓" : " ✗")).join(" · ");
      const ads = (data.ads_closed || []).length;
      pfNoteSeen(
        `${data.ok ? "สำเร็จ" : "หยุดกลางทาง"} — ทำได้ ${data.done}/${data.total} ขั้น` +
        (ads ? ` · ปิดโฆษณาที่เด้งแทรก ${ads} ครั้ง` : "") +
        (tags ? ` · แท็ก: ${tags}` : ""),
      );
    } catch (error) { pfNoteSeen(error.message); }
    finally {
      // ต้องอยู่ใน finally — ล้มกลางทางแล้วปุ่มค้าง disabled ทั้งผังคือพังหนักกว่าเดิม
      pfRunning = null;
      pfRender();
    }
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
let gfpDevices = [];

const FB_STATUS_TEXT = {
  waiting_caption: "รอแคปชัน",
  waiting_image: "รอรูป",
  ready: "พร้อมโพสต์",
  running: "กำลังโพสต์…",
  done: "เสร็จแล้ว",
  failed: "ล้มเหลว",
  stopped: "หยุดไว้",
  cancelled: "ยกเลิก",
};

// แผง gfpFlow ถูกยุบไปรวมกับแผงบอทบนสุด (web/fbcontrol.js) เมื่อ 11 ก.ย. 2569
// ตามที่เจ้าของสั่ง — หน้าเดียวมีสองแผงบอกเรื่องเดียวกันคนละหน้าตา
// ปุ่มทำต่อ/รีเซ็ต/หยุด กับผลรายกลุ่มย้ายไปอยู่ในใบโพสต์ของแผงนั้นแล้ว

function fbMessage(text) {
  if ($("#fbNote")) $("#fbNote").textContent = text;
  if ($("#gfpNote")) $("#gfpNote").textContent = text;
}

function gfpSelectedGroups() {
  return [...document.querySelectorAll("#gfpGroupChoices input:checked")].map((box) => box.value);
}

function renderGfpDevice() {
  const select = $("#gfpPostDevice");
  const option = select?.selectedOptions?.[0];
  if ($("#gfpDevice")) {
    $("#gfpDevice").textContent = option
      ? `เลือกแล้ว: ${option.textContent}`
      : "ยังไม่มีมือถือสายโพสต์ที่ผูกบัญชีและเชื่อมต่ออยู่";
  }
}

async function loadGfpDevices() {
  const select = $("#gfpPostDevice");
  if (!select) return;
  try {
    const payload = await api("/api/devices");
    gfpDevices = (payload.devices || []).filter((row) =>
      row.enabled && (row.lanes || []).includes("post"));
    const usable = gfpDevices.filter((row) => row.ready && row.account);
    select.replaceChildren(...(gfpDevices.length ? gfpDevices.map((row) => {
      const option = new Option(
        `${row.label} · ${row.account || "ยังไม่ได้ผูกบัญชี"}` + (row.ready ? "" : " · ไม่ได้เสียบ"),
        row.serial,
      );
      option.disabled = !row.ready || !row.account;
      return option;
    }) : [new Option("— ยังไม่มีมือถือสายโพสต์ —", "")]));
    const focused = usable.find((row) => row.serial === deviceSelect.value);
    select.value = (focused || usable[0] || {}).serial || "";
    renderGfpDevice();
  } catch (error) {
    select.replaceChildren(new Option("อ่านรายการมือถือไม่ได้", ""));
    fbMessage(error.message);
    renderGfpDevice();
  }
}

function updateGfpSteps() {
  const caption = $("#gfpCaption").value.trim();
  const postFiles = $("#gfpPostImages").files.length;
  const comments = [$("#gfpComment1").value.trim(), $("#gfpComment2").value.trim()];
  const commentFiles = [$("#gfpCommentImage1").files.length, $("#gfpCommentImage2").files.length];
  const states = {
    caption: Boolean(caption),
    "post-image": postFiles > 0 && postFiles <= 3,
    comment: comments.some(Boolean),
    "comment-image": commentFiles.some(Boolean),
    groups: gfpSelectedGroups().length > 0 && gfpSelectedGroups().length <= 6,
  };
  document.querySelectorAll("#gfpDraftSteps [data-part]").forEach((step) => {
    step.classList.toggle("done", Boolean(states[step.dataset.part]));
    step.classList.toggle("optional", ["comment", "comment-image"].includes(step.dataset.part));
  });
  $("#gfpCaptionCount").textContent = `${$("#gfpCaption").value.length.toLocaleString("th-TH")} ตัวอักษร`;
  $("#gfpGroupCount").textContent = `${gfpSelectedGroups().length}/6`;
  renderGfpDevice();
}

function previewFiles(input, wrap) {
  const images = [...input.files].map((file) => {
    const image = document.createElement("img");
    const url = URL.createObjectURL(file);
    image.src = url;
    image.alt = file.name;
    image.title = `${file.name} · ${(file.size / 1024 / 1024).toFixed(1)} MB`;
    image.addEventListener("load", () => URL.revokeObjectURL(url), { once: true });
    return image;
  });
  wrap.replaceChildren(...images);
  updateGfpSteps();
}

function renderGfpGroups() {
  const wrap = $("#gfpGroupChoices");
  if (!wrap) return;
  wrap.replaceChildren(...fbGroups.map((group) => {
    const label = document.createElement("label");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.value = group.group_id;
    box.checked = group.enabled !== false;
    box.addEventListener("change", () => {
      if (gfpSelectedGroups().length > 6) {
        box.checked = false;
        fbMessage("เลือกได้ไม่เกิน 6 กลุ่มต่อโพสต์");
      }
      updateGfpSteps();
    });
    const name = document.createElement("span");
    name.textContent = group.name || group.group_id;
    name.title = group.group_id;
    label.append(box, name);
    return label;
  }));
  if (!fbGroups.length) wrap.textContent = "ยังไม่มีกลุ่มในทะเบียน";
  updateGfpSteps();
}

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

export async function loadFbGroups() {
  try {
    await loadGfpDevices();
    const payload = await api("/api/fb/groups");
    fbGroups = payload.groups;
    $("#fbGapMin").value = payload.gap_min;
    $("#fbGapMax").value = payload.gap_max;
    $("#fbAutoStart").checked = payload.auto_start;
    $("#fbAutoFollowup").checked = payload.auto_followup !== false;
    // ไม่มีค่าส่งมา = ถือว่าเปิด — ค่าตั้งต้นของฟีเจอร์นี้คือเปิด ถ้าเขียนเป็น
    // `!!payload.phone_clean` เฉยๆ เซิร์ฟเวอร์รุ่นเก่าที่ยังไม่ส่งค่านี้มาจะทำให้
    // ปุ่มโชว์ว่าปิด แล้วผู้ใช้กดบันทึกทีเดียวคือปิดฟีเจอร์จริงโดยไม่ตั้งใจ
    $("#fbPhoneClean").checked = payload.phone_clean !== false;
    $("#fbScreenSaver").checked = payload.screen_saver !== false;
    // เตือนให้เห็นชัด — ไม่งั้นส่งงานเข้าบอทแล้วเงียบโดยไม่รู้สาเหตุ
    $("#fbNote").textContent = payload.bot_ready
      ? ""
      : "⚠️ บอทหลักยังไม่ได้ตั้งโทเคน — งานที่ส่งเข้า Telegram จะไม่เข้าระบบ " +
        "(ตั้งที่ ⚙ ตั้งค่า → อนุมัติทาง Telegram)";
    renderFbGroups();
    renderGfpGroups();
  } catch (error) {
    $("#fbNote").textContent = error.message;
  }
}

function jobMedia(job, kind, index, alt) {
  const image = document.createElement("img");
  image.src = `/api/fb/jobs/${job.id}/media/${kind}/${index}`;
  image.alt = alt;
  image.title = "คลิกเพื่อเปิดรูปเต็ม";
  image.addEventListener("click", () => window.open(image.src, "_blank", "noopener"));
  return image;
}

function renderFbJobsInto(wrap, jobs, running, detailed = false) {
  if (!wrap) return;
  wrap.replaceChildren(
    ...jobs.slice(0, detailed ? 6 : 3).map((job) => {
      const card = document.createElement("div");
      card.className = "fb-job";

      if (job.has_image && !detailed) {
        const image = document.createElement("img");
        image.src = `/api/fb/jobs/${job.id}/image`;
        image.alt = "รูปที่จะโพสต์";
        card.append(image);
      }

      const body = document.createElement("div");
      body.className = "fb-job-body";

      const head = document.createElement("strong");
      head.textContent = `${job.id} · ${FB_STATUS_TEXT[job.status] || job.status}`;
      if (detailed) {
        const source = document.createElement("span");
        source.className = "gfp-job-source";
        source.textContent = job.source === "web" ? "หน้าเว็บ" : "Telegram";
        head.append(source);
      }
      body.append(head);

      const caption = document.createElement("p");
      caption.className = detailed ? "gfp-content-block" : "fb-caption";
      caption.textContent = job.caption || "(ยังไม่มีแคปชัน)";
      if (detailed) {
        const label = document.createElement("strong");
        label.textContent = "แคปชัน";
        caption.prepend(label);
      }
      body.append(caption);

      if (detailed && (job.images || []).length) {
        const media = document.createElement("div");
        media.className = "gfp-media";
        (job.images || []).forEach((_path, index) => {
          media.append(jobMedia(job, "post", index, `รูปโพสต์ใบที่ ${index + 1}`));
        });
        body.append(media);
      }

      if (detailed) {
        const comments = (job.comments?.length ? job.comments : (job.comment ? [job.comment] : []));
        const commentImages = job.comment_images || [];
        if (!comments.length) {
          const none = document.createElement("p");
          none.className = "note";
          none.textContent = "คอมเมนต์: ไม่มี";
          body.append(none);
        }
        comments.forEach((text, index) => {
          const comment = document.createElement("div");
          comment.className = "gfp-content-block";
          const label = document.createElement("strong");
          label.textContent = `คอมเมนต์ช่อง ${index + 1}`;
          comment.append(label, document.createTextNode(text));
          if (commentImages[index]) {
            const media = document.createElement("div");
            media.className = "gfp-media";
            media.append(jobMedia(job, "comment", index, `รูปคอมเมนต์ช่อง ${index + 1}`));
            comment.append(media);
          }
          body.append(comment);
        });
      }

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
            fbMessage(payload.message);
            startFbPolling();
          } catch (error) {
            fbMessage(error.message);
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
            fbMessage(payload.message);
            loadFbJobs();
          } catch (error) {
            fbMessage(error.message);
          }
        });
        actions.append(cancel);
      }
      body.append(actions);

      if (detailed) {
        const timeline = document.createElement("details");
        timeline.className = "gfp-timeline";
        timeline.open = job.status === "running";
        const summary = document.createElement("summary");
        const logs = job.log || [];
        summary.textContent = logs.length
          ? `ขั้นตอนที่ทำแล้ว ${logs.length} รายการ`
          : "ยังไม่ได้เริ่มทำบนมือถือ";
        timeline.append(summary);
        if (logs.length) {
          const list = document.createElement("ol");
          logs.slice(-30).forEach((text) => {
            const line = document.createElement("li");
            line.textContent = text;
            list.append(line);
          });
          timeline.append(list);
        }
        body.append(timeline);
      }
      card.append(body);
      return card;
    }),
  );
  if (!jobs.length) {
    wrap.textContent = detailed
      ? "ยังไม่มีงาน — สร้างจากฟอร์มด้านบน หรือส่งผ่าน Telegram ได้"
      : "ยังไม่มีงาน — ส่งรูปพร้อมแคปชันเข้าบอทใน Telegram";
  }
}

function renderFbJobs(jobs, running) {
  renderFbJobsInto($("#fbJobs"), jobs, running, false);
}

export async function loadFbJobs() {
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

function resetGfpForm() {
  $("#gfpCaption").value = "";
  $("#gfpPostImages").value = "";
  $("#gfpComment1").value = "";
  $("#gfpComment2").value = "";
  $("#gfpCommentImage1").value = "";
  $("#gfpCommentImage2").value = "";
  $("#gfpPostPreview").replaceChildren();
  $("#gfpCommentPreview1").replaceChildren();
  $("#gfpCommentPreview2").replaceChildren();
  updateGfpSteps();
}

async function submitGfp(runNow) {
  const caption = $("#gfpCaption").value.trim();
  const files = [...$("#gfpPostImages").files];
  const groups = gfpSelectedGroups();
  const serial = $("#gfpPostDevice").value;
  if (!serial) { fbMessage("เลือกมือถือสายโพสต์ที่ผูกบัญชีก่อน"); return; }
  if (!caption) { fbMessage("ใส่แคปชันก่อน"); return; }
  if (!files.length) { fbMessage("เลือกรูปโพสต์อย่างน้อย 1 ใบ"); return; }
  if (files.length > 3) { fbMessage("รูปโพสต์เลือกได้สูงสุด 3 ใบ"); return; }
  if (!groups.length || groups.length > 6) { fbMessage("เลือกกลุ่ม 1–6 กลุ่ม"); return; }
  for (const index of [1, 2]) {
    if ($(`#gfpCommentImage${index}`).files.length && !$(`#gfpComment${index}`).value.trim()) {
      fbMessage(`รูปคอมเมนต์ช่อง ${index} ต้องมีข้อความคอมเมนต์ด้วย`);
      return;
    }
  }

  const form = new FormData();
  form.append("serial", serial);
  form.append("caption", caption);
  form.append("groups", JSON.stringify(groups));
  form.append("comment_1", $("#gfpComment1").value);
  form.append("comment_2", $("#gfpComment2").value);
  form.append("run_now", String(runNow));
  files.forEach((file) => form.append("post_images", file));
  for (const index of [1, 2]) {
    const file = $(`#gfpCommentImage${index}`).files[0];
    if (file) form.append(`comment_image_${index}`, file);
  }

  $("#gfpSave").disabled = true;
  $("#gfpSend").disabled = true;
  fbMessage(runNow ? "กำลังสร้างงานและเริ่มโพสต์…" : "กำลังบันทึกงาน…");
  try {
    const payload = await api("/api/fb/jobs", { method: "POST", body: form });
    fbMessage(payload.message);
    resetGfpForm();
    await loadFbJobs();
    if (payload.started) startFbPolling();
  } catch (error) {
    fbMessage(error.message);
  } finally {
    $("#gfpSave").disabled = false;
    $("#gfpSend").disabled = false;
  }
}

$("#gfpCaption").addEventListener("input", updateGfpSteps);
$("#gfpComment1").addEventListener("input", updateGfpSteps);
$("#gfpComment2").addEventListener("input", updateGfpSteps);
$("#gfpPostImages").addEventListener("change", (event) => {
  if (event.target.files.length > 3) {
    event.target.value = "";
    $("#gfpPostPreview").replaceChildren();
    fbMessage("รูปโพสต์เลือกได้สูงสุด 3 ใบ");
    updateGfpSteps();
    return;
  }
  previewFiles(event.target, $("#gfpPostPreview"));
});
$("#gfpCommentImage1").addEventListener("change", (event) =>
  previewFiles(event.target, $("#gfpCommentPreview1")));
$("#gfpCommentImage2").addEventListener("change", (event) =>
  previewFiles(event.target, $("#gfpCommentPreview2")));
$("#gfpSave").addEventListener("click", () => submitGfp(false));
$("#gfpSend").addEventListener("click", () => submitGfp(true));
$("#gfpPostDevice").addEventListener("change", renderGfpDevice);
deviceSelect.addEventListener("change", () => {
  const matching = gfpDevices.find((row) =>
    row.serial === deviceSelect.value && row.ready && row.account);
  if (matching) $("#gfpPostDevice").value = matching.serial;
  renderGfpDevice();
});

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
        auto_followup: $("#fbAutoFollowup").checked,
        phone_clean: $("#fbPhoneClean").checked,
        screen_saver: $("#fbScreenSaver").checked,
      }),
    });
    $("#fbGapMin").value = payload.gap_min;
    $("#fbGapMax").value = payload.gap_max;
    $("#fbAutoFollowup").checked = payload.auto_followup !== false;
    $("#fbPhoneClean").checked = payload.phone_clean !== false;
    $("#fbScreenSaver").checked = payload.screen_saver !== false;
    $("#fbNote").textContent = "บันทึกค่าแล้ว";
  } catch (error) {
    $("#fbNote").textContent = error.message;
  }
});
