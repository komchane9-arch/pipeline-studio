/* งานฝั่งวิดีโอ: Input ① · GEMS · Release ③ · สตอรีบอร์ด 🎬 */

import { $, CLIP_API, api, config, hooks } from "./core.js";

// ============================================================ Input ①
export function fillInput() {
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
//
// **ตรวจของก่อนส่งไปทำคลิป** ตัวคัดอัตโนมัติเลือกรูป/จุดขายผิดได้เสมอ ของเดิม
// หน้านี้โชว์อย่างเดียวแก้ไม่ได้ ผู้ใช้จึงต้องยอมรับของที่ผิดไปทั้งดุ้น หรือทิ้ง
// แล้วดึงใหม่ (ซึ่งเสียเวลาครึ่งนาทีและโควตา AI ทุกครั้ง)
//
// ข้อมูลที่ต้องใช้มีครบอยู่แล้วตั้งแต่ตอนดึง — `picked` (รูปที่คัดมา) ·
// `candidates` (รูปทั้งหมดที่โหลดไว้) · `highlights` (จุดขาย 3 ข้อ) ·
// `features` (จุดขายเต็มรายการ ที่ตั้งใจเก็บไว้ให้สลับได้ตั้งแต่ 22 ส.ค. 2569
// แต่ยังไม่เคยมีหน้าจอให้สลับ) ตรงนี้คือหน้าจอนั้น
let shopeeData = null;
// ของที่กำลังแก้อยู่ แยกจาก `shopeeData` ที่เป็นของดิบตอนดึงมา
let pickedImages = [];      // รูปที่จะเอาไปใช้
let spareImages = [];       // รูปที่เขี่ยออก ยังดึงกลับได้
let liveHighlights = [];    // จุดขายที่จะเอาไปใช้
let spareFeatures = [];     // จุดขายที่ AI หามาได้แต่ยังไม่ได้ใช้
let canEditShopee = true;   // ตัดสินไปแล้ว = แก้ไม่ได้อีก

const shopeeImageSrc = (file) =>
  `/api/shopee/image?path=${encodeURIComponent(file)}`;

/** การ์ดรูปหนึ่งใบ — mode "spare" คือกองที่เขี่ยออกไว้ ปุ่มจะเป็น ＋ แทน ✕ */
function imageCard(image, index, mode) {
  const box = document.createElement("figure");
  box.className = `shopee-shot ${image.kind || ""}`;
  const img = document.createElement("img");
  // เสิร์ฟจากเครื่องเราเอง ไม่ดึงจาก Shopee ซ้ำตอนแสดงผล
  img.src = shopeeImageSrc(image.file);
  img.alt = image.label || `รูปที่ ${index + 1}`;
  img.loading = "lazy";
  const act = document.createElement("button");
  act.type = "button";
  act.className = "shot-act";
  act.textContent = mode === "spare" ? "＋" : "✕";
  act.title = mode === "spare" ? "เอารูปนี้กลับมาใช้" : "เอารูปนี้ออก";
  act.disabled = !canEditShopee;
  act.addEventListener("click", () => {
    if (mode === "spare") {
      spareImages = spareImages.filter((i) => i.file !== image.file);
      pickedImages = [...pickedImages, image];
    } else {
      pickedImages = pickedImages.filter((i) => i.file !== image.file);
      spareImages = [image, ...spareImages];
    }
    renderShopeeImages();
  });
  const caption = document.createElement("figcaption");
  caption.textContent =
    image.kind === "overview" ? "ภาพรวม" : (image.label || "ตัวเลือก");
  caption.title = caption.textContent;
  box.append(img, act, caption);
  return box;
}

function renderShopeeImages() {
  $("#shopeeGallery").replaceChildren(
    ...pickedImages.map((image, index) => imageCard(image, index, "picked")),
  );
  $("#shopeeSpare").replaceChildren(
    ...spareImages.map((image, index) => imageCard(image, index, "spare")),
  );
  const count = $("#shopeePickCount");
  count.textContent = `${pickedImages.length} ใบ`;
  // **เขี่ยรูปออกจนหมดแล้วทำคลิปไม่ได้** ต้องบอกตรงนี้ ไม่ใช่ปล่อยให้ไปล้ม
  // ตอนเจนซึ่งเสียเวลาเป็นนาทีและเสียเครดิตไปแล้ว
  count.classList.toggle("warn", pickedImages.length === 0);
  $("#shopeeSpareCount").textContent = `${spareImages.length} ใบ`;
  $("#shopeeSpareWrap").hidden = spareImages.length === 0;
}

function renderShopeeHighlights() {
  $("#shopeeHighlights").replaceChildren(
    ...liveHighlights.map((text, index) => {
      const row = document.createElement("li");
      const field = document.createElement("input");
      field.type = "text";
      field.value = text;
      field.placeholder = "พิมพ์จุดขาย";
      field.disabled = !canEditShopee;
      field.addEventListener("input", () => {
        liveHighlights[index] = field.value;
      });
      const drop = document.createElement("button");
      drop.type = "button";
      drop.className = "ghost tiny";
      drop.textContent = "−";
      drop.title = "เอาข้อนี้ออก (ไปกองเพิ่มเติม ดึงกลับได้)";
      drop.disabled = !canEditShopee;
      drop.addEventListener("click", () => {
        const [gone] = liveHighlights.splice(index, 1);
        if (gone && gone.trim()) spareFeatures = [gone, ...spareFeatures];
        renderShopeeHighlights();
        renderShopeeExtra();
      });
      row.append(field, drop);
      return row;
    }),
  );
  $("#shopeeHighlightCount").textContent = `${liveHighlights.length} ข้อ`;
}

function renderShopeeExtra() {
  $("#shopeeExtra").replaceChildren(
    ...spareFeatures.map((text, index) => {
      const row = document.createElement("li");
      const take = document.createElement("button");
      take.type = "button";
      take.className = "ghost tiny";
      take.textContent = "＋";
      take.title = "เอาข้อนี้ขึ้นไปใช้";
      take.disabled = !canEditShopee;
      take.addEventListener("click", () => {
        spareFeatures.splice(index, 1);
        liveHighlights = [...liveHighlights, text];
        renderShopeeHighlights();
        renderShopeeExtra();
      });
      const label = document.createElement("span");
      label.textContent = text;
      row.append(take, label);
      return row;
    }),
  );
  $("#shopeeExtraCount").textContent = `${spareFeatures.length} ข้อ`;
  $("#shopeeExtraWrap").hidden = spareFeatures.length === 0;
}

$("#shopeeAddHighlight")?.addEventListener("click", () => {
  liveHighlights = [...liveHighlights, ""];
  renderShopeeHighlights();
  $("#shopeeHighlights").querySelector("li:last-child input")?.focus();
});

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
    pickedImages = [...(payload.picked || [])];
    // รูปที่เหลือ = ที่โหลดมาทั้งหมด ลบที่ถูกคัดไว้แล้วออก
    const taken = new Set(pickedImages.map((image) => image.file));
    spareImages = (payload.candidates || []).filter((i) => !taken.has(i.file));
    liveHighlights = [...(payload.highlights || [])];
    // จุดขายเพิ่มเติม = รายการเต็มที่ AI หามาได้ ลบข้อที่ถูกเลือกไปแล้วออก
    const used = new Set(liveHighlights.map((text) => String(text).trim()));
    spareFeatures = (payload.features || [])
      .map((text) => String(text).trim())
      .filter((text) => text && !used.has(text));
    $("#shopeeName").value = payload.name || "";
    $("#shopeeDetail").value = payload.detail || "";
    $("#decideNote").textContent = "";
    // ดึงสินค้าชิ้นใหม่ = เริ่มแก้ได้ใหม่ ไม่ติดล็อกจากชิ้นก่อนที่ตัดสินไปแล้ว
    canEditShopee = true;
    $("#shopeeResult").classList.remove("locked");
    $("#shopeeName").disabled = false;
    $("#shopeeAddHighlight").disabled = false;
    renderShopeeImages();
    renderShopeeHighlights();
    renderShopeeExtra();
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
  // ตัดสินไปแล้วต้องแก้ไม่ได้ — ของเดิมยังพิมพ์ทับได้ทั้งที่กดอนุมัติไปแล้ว
  // ผู้ใช้จะนึกว่าที่แก้ถูกบันทึก ทั้งที่ขั้นถัดไปหยิบของตอนกดอนุมัติไปใช้แล้ว
  setShopeeEditable(entry.status === "pending");
  // อนุมัติจาก Telegram แล้วแก้ข้อความมาด้วย ต้องเอามาแสดงให้ตรงกัน
  if (entry.status === "approved" && Array.isArray(entry.highlights)) {
    shopeeData = { ...(shopeeData || {}), highlights: entry.highlights };
    liveHighlights = [...entry.highlights];
    renderShopeeHighlights();
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

/** ล็อกการแก้หลังตัดสินแล้ว — เรียกซ้ำได้ ปุ่มถูกสร้างใหม่ทุกครั้งที่วาด */
function setShopeeEditable(on) {
  canEditShopee = on;
  $("#shopeeResult").classList.toggle("locked", !on);
  $("#shopeeName").disabled = !on;
  $("#shopeeAddHighlight").disabled = !on;
  renderShopeeImages();
  renderShopeeHighlights();
  renderShopeeExtra();
}

async function decide(status) {
  if (!approvalId) return;
  const note = $("#decideNote");
  const product = $("#shopeeName").value.trim();
  const highlights = liveHighlights.map((t) => t.trim()).filter(Boolean);
  // **ด่านก่อนส่ง** ปล่อยของไม่ครบไปขั้นถัดไป = เสียเวลาเจนแล้วล้มกลางทาง
  if (status === "approved") {
    const missing = !product ? "ชื่อสินค้า"
      : !highlights.length ? "จุดขายอย่างน้อย 1 ข้อ"
        : !pickedImages.length ? "รูปอย่างน้อย 1 ใบ" : "";
    if (missing) {
      note.textContent = `ยังส่งไม่ได้ — ต้องมี${missing}ก่อน`;
      return;
    }
  }
  $("#approveWeb").disabled = true;
  $("#rejectWeb").disabled = true;
  note.textContent = status === "approved"
    ? "กำลังบันทึกที่แก้ แล้วส่งไปทำสตอรีบอร์ด…" : "กำลังยกเลิก…";
  try {
    const fresh = await api(`/api/approvals/${approvalId}`, {
      method: "POST",
      body: JSON.stringify({
        status,
        product,
        highlights,
        images: pickedImages.map((image) => image.file),
        features: spareFeatures,
      }),
    });
    // ขั้นถัดไปในหน้านี้ (ช่องสินค้าเดียว · ขั้น GEMS) ต้องได้ของที่แก้แล้ว
    shopeeData = {
      ...(shopeeData || {}),
      name: product,
      highlights,
      picked: pickedImages,
      saved_images: pickedImages.map((image) => image.file),
    };
    paintApproval(fresh);
    if (approvalTimer) window.clearInterval(approvalTimer);
    if (status === "approved") await sendToStoryboard(note);
    else note.textContent = "ยกเลิกแล้ว — รูปที่โหลดมายังอยู่ในเครื่องและบน Drive ไม่ได้ลบ";
  } catch (error) {
    note.textContent = error.message;
  } finally {
    $("#approveWeb").disabled = false;
    $("#rejectWeb").disabled = false;
  }
}

/** ส่งเข้าคิวสตอรีบอร์ดของสายคลิป (คนละเซิร์ฟเวอร์ พอร์ต 8877) */
async function sendToStoryboard(note) {
  const link = shopeeData?.url || "";
  if (!link) {
    note.textContent = "บันทึกแล้ว — แต่ไม่มีลิงก์สินค้าให้ส่งต่อ "
      + "สั่งเองได้ที่แท็บสตอรีบอร์ด";
    return;
  }
  try {
    const payload = await api(`${CLIP_API}/api/jobs`, {
      method: "POST",
      body: JSON.stringify({ links: link }),
    });
    note.textContent = "✅ อนุมัติแล้ว · ส่งเข้าคิวสตอรีบอร์ดแล้ว "
      + `(ค้างในคิวทั้งหมด ${payload.waiting} งาน)`;
  } catch (error) {
    // **ห้ามเงียบ** บันทึกสำเร็จแต่ส่งต่อไม่สำเร็จ ถ้าไม่บอกจะนั่งรอคลิปที่ไม่มีวันมา
    note.textContent = "อนุมัติและบันทึกแล้ว แต่ส่งเข้าคิวสตอรีบอร์ดไม่สำเร็จ: "
      + error.message;
  }
}

$("#approveWeb").addEventListener("click", () => decide("approved"));
$("#rejectWeb").addEventListener("click", () => decide("rejected"));

$("#shopeeUse").addEventListener("click", () => {
  if (!shopeeData) return;
  // ต้องหยิบ**ของที่ผู้ใช้แก้อยู่ตรงหน้า** ไม่ใช่ของดิบตอนดึงมา
  // ของเดิมหยิบ shopeeData.name เสมอ แก้ชื่อแล้วกดปุ่มนี้จะได้ชื่อเก่ากลับมา
  $("#singleName").value = $("#shopeeName").value.trim() || shopeeData.name || "";
  // ส่งจุดขายไปให้ขั้นเจน ไม่ใช่รายละเอียดดิบ 5 พันตัวอักษร
  // (prompt ที่ยาวเกินทำให้ Gemini หลุดประเด็นไปพูดเรื่องใบกำกับภาษี)
  const highlights = liveHighlights
    .map((text) => text.trim()).filter(Boolean).join("\n");
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
export function fillGems() {
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
    window.setTimeout(() => hooks.reloadConfig(), 20000);   // อยู่ใน boot.js — เรียกผ่าน hooks กัน import วงกลม
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

export function fillRelease() {
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

export async function loadClips() {
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
  /* ปุ่มพักไว้รอแก้ / เอากลับ (ผู้ใช้สั่ง 27 ส.ค. 2026)
   *
   * **ต่างจาก ✕ ยกเลิก ตรงที่กลับมาทำต่อได้** ยกเลิกคือทิ้ง ส่วนพักคือ
   * "ยังเอาอยู่ แต่ยังไม่พร้อม" — ก่อนหน้านี้มีแค่สองทางคือปล่อยค้างในกองเดิม
   * จนปนกับงานที่เดินได้จริง หรือยกเลิกทิ้งซึ่งแรงเกินไป
   *
   * งานที่เครื่องกำลังทำอยู่ (`running`) พักไม่ได้ — เบราว์เซอร์เปิดค้างอยู่
   * และอาจใช้เครดิตไปแล้ว ปุ่มจึงไม่โผล่เลย ดีกว่าโผล่แล้วกดไม่ได้ */
  if (job.parked) {
    tools.append(iconBtn("↩", "เอากลับเข้าขั้นเดิม", () =>
      act(() => jobPost(`${job.id}/unpark`))));
  } else if (job.open && !job.running) {
    tools.append(iconBtn("🅿", "พักไว้รอแก้ — เครื่องจะไม่แตะจนกว่าจะเอากลับ", () => {
      const why = window.prompt("พักไว้เพราะอะไร (เว้นว่างได้)") ?? null;
      if (why === null) return;              // กดยกเลิกในกล่อง = ไม่ต้องพัก
      act(() => jobPost(`${job.id}/park`, { why }));
    }));
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

/** บรรทัดบอกเพดาน "ทำทีละ 8 งาน" — สร้างจาก JS ไม่แตะ index.html
 *
 *  **เพดานที่มองไม่เห็น แยกไม่ออกจากระบบค้าง** 25 ส.ค. 2026 ผู้ใช้ส่งลิงก์ 33 ใบ
 *  แล้วเห็นขยับแค่ 8 ใบ ถ้าไม่บอกไว้ตรงนี้ จะโดนไล่บั๊กผิดทางทุกครั้งที่คิวยาว
 *
 *  ข้อความมาจากเซิร์ฟเวอร์ (`load_text`) ทั้งดุ้น **ห้ามประกอบเอง** ไม่งั้นวันที่
 *  เพดานเปลี่ยนจาก 8 เป็นเลขอื่น หน้าเว็บจะยังบอกเลขเก่าอยู่โดยไม่มีใครรู้
 */
function queueLoadNote() {
  let node = $("#storyLoadNote");
  if (!node) {
    node = el("p", { className: "note load-note", id: "storyLoadNote" });
    $("#storyQueueList")?.before(node);
  }
  return node;
}

/** กระดาน 6 ขั้น — งานไหนค้างอยู่ตรงไหน (ผู้ใช้สั่ง 26 ส.ค. 2026)
 *
 *  *"ตอนนี้ผมงงกับงานมากไม่รู้ว่าอันไหนอยู่ stage ไหนเท่าไรบ้าง"*
 *
 *  **ตัวเลขและการจัดกองมาจากเซิร์ฟเวอร์ทั้งหมด หน้าเว็บไม่คิดเอง**
 *  เพราะกอง Shopee/Facebook/TikTok ใช้กติกาเดียวกับด่านที่กั้นก่อนโพสต์จริง
 *  ถ้าหน้าเว็บคิดเอง วันหลังจะกลายเป็น "กระดานบอกว่าลงได้ แต่กดแล้วโดนปฏิเสธ"
 *
 *  **จำกองที่เลือกไว้** เพราะหน้านี้วาดใหม่เองทุก 6 วินาที ถ้าไม่จำ พอถึงรอบวาด
 *  ใหม่มันจะเด้งกลับกองแรกทุกครั้ง แล้วใช้งานไม่ได้เลย
 */
const BOARD_KEY = "clipBoardPick";
let boardPick = localStorage.getItem(BOARD_KEY) || "";
let boardData = null;

/** กล่องแถบ 6 ขั้น — **วางพาดเต็มความกว้างเหนือสองคอลัมน์** (ผู้ใช้สั่ง 26 ส.ค.)
 *
 *  ครั้งแรกผมวางไว้ในคอลัมน์คิวซึ่งกว้างราว 380 px เลยต้องจัดเป็นตาราง 2 แถว
 *  ผู้ใช้บอกว่า *"ไม่ใช่แบบนี้ เอาแต่ละหัวข้อเรียงกันเป็น flow ยาว ต่อกันด้านบนเลย"*
 *  — ตรงกับที่เขาวาดมา คือ 6 กล่องเรียงแถวเดียวพาดด้านบน แล้วรายการอยู่ข้างล่าง
 *
 *  จึงต้องแทรก**ก่อน `.story-layout`** ไม่ใช่ในคอลัมน์ เพื่อให้กินความกว้างเต็ม
 */
function boardBox() {
  let node = $("#clipBoard");
  if (!node) {
    node = el("div", { className: "clip-board", id: "clipBoard" });
    const layout = document.querySelector("#tab-story .story-layout");
    if (layout) layout.before(node);
    else $("#storyQueueList")?.before(node);
  }
  return node;
}

/** หัวเรื่อง "ของที่พักไว้รอแก้ในขั้นนี้" — คั่นระหว่างงานที่ยังเดินกับงานที่ถูกพัก
 *
 *  **ผู้ใช้สั่ง 27 ส.ค. 2569** — *"ตัวรอแก้ให้ใส่ในแต่ละใต้ stage แยกกันเลย
 *  ว่ารอแก้ stage ไหน"*
 *
 *  เดิมของรอแก้ถูกกองรวมเป็นกองที่ 7 แยกออกมาต่างหาก ทำให้ต้องสลับกองไปมา
 *  เพื่อดูว่าขั้นที่กำลังสนใจมีอะไรค้างบ้าง ตอนนี้อยู่ใต้ขั้นของตัวเองแล้ว
 *  เห็นพร้อมกันในที่เดียว
 */
function parkedHead(bucket) {
  return el("li", { className: "board-parked-head" },
    el("b", { textContent: `🅿️ รอแก้ในขั้นนี้ ${bucket.parked_count} ใบ` }),
    el("small", { textContent: "เครื่องไม่แตะ ของที่ทำไว้ยังอยู่ครบ · ดูในแชท /wait" }),
  );
}

/** หัวข้อย่อยตามชนิดของการแก้ — ชื่อ · จำนวน · **วิธีแก้** · ปุ่มเอากลับทั้งกลุ่ม
 *
 *  **`fix_hint` ต้องโชว์เสมอ ไม่ใช่โชว์แค่ชื่อ** — ชื่อบอกได้แค่ "ค้างตรงไหน"
 *  ส่วนวิธีแก้คือ "ต้องทำอะไรถึงจะผ่าน" ซึ่งเป็นเหตุผลทั้งหมดที่ผู้ใช้สั่งให้แยก
 *  (หารูปเพิ่ม · พิมพ์คอมเมนต์สั่งแก้ · แก้ข้อความเอง · สั่งเจนใหม่ที่เสียเครดิต Veo)
 *
 *  **ชื่อกับวิธีแก้มาจากเซิร์ฟเวอร์ทั้งคู่** (`fix_title` · `fix_hint`) ห้ามคิดเองฝั่งนี้
 *  และ **ห้ามเรียงใหม่** — เดินตามลำดับที่เซิร์ฟเวอร์ส่งมา แล้วขึ้นหัวข้อใหม่เมื่อ
 *  `fix_group` เปลี่ยนเท่านั้น ไม่งั้นวันหนึ่งหน้าเว็บกับแชท `/wait` จะจัดไม่ตรงกัน
 *  แล้วไม่มีใครรู้ว่าอันไหนถูก
 */
function fixGroupHead(items) {
  const first = items[0];
  const head = el("li", { className: "board-group" });
  head.append(el("b", { className: "board-group-name",
                        textContent: `${first.fix_title} · ${items.length} ใบ` }));

  // เอากลับทั้งกลุ่มด้วยการยิงทีละใบผ่านทางเดิม — ไม่ต้องรอที่อยู่ใหม่ฝั่งเซิร์ฟเวอร์
  // และถ้าใบไหนพลาดจะรู้ทันทีว่าใบไหน แทนที่จะล้มทั้งชุดโดยไม่รู้ว่าตกตรงไหน
  if (items.length > 1) {
    head.append(textBtn("↩ เอากลับทั้งกลุ่ม", "ghost board-group-back", async () => {
      const ids = items.map((job) => job.id);
      if (!window.confirm(`เอางาน ${ids.length} ใบในกลุ่ม "${first.fix_title}" `
        + "กลับไปทำต่อทั้งหมด?")) return;
      let done = 0;
      const failed = [];
      for (const id of ids) {
        try { await jobPost(`${id}/unpark`); done += 1; }
        catch (error) { failed.push(`${id} (${error.message})`); }
      }
      // **ต้องบอกว่าตกใบไหน** ถ้าบอกแค่ "ไม่สำเร็จ" ผู้ใช้ต้องไปไล่เปิดดูทีละใบเอง
      $("#storyNote").textContent = failed.length
        ? `เอากลับได้ ${done}/${ids.length} ใบ · ตกค้าง ${failed.length} ใบ — ${failed[0]}`
        : `เอากลับแล้ว ${done} ใบ จากกลุ่ม ${first.fix_title}`;
      await loadJobQueue();
    }));
  }

  head.append(el("small", { className: "board-group-hint",
                            textContent: first.fix_hint || "" }));
  return head;
}

/** แถวของใบที่ถูกพักไว้ — ต้องบอก **ขั้นที่ค้างตอนถูกพัก** ไม่ใช่สถานะตอนนี้
 *
 *  ใบที่ล้มก่อนถูกพักจะมี `stage: "failed"` ซึ่งแปลว่า "ล้มเหลว" — ไม่ได้บอกเลยว่า
 *  ต้องไปแก้ตรงไหน ต้องใช้ `from_label` ที่บอกว่าค้างขั้นไหนตอนถูกพัก
 */
function parkedRow(item) {
  const row = el("li", { className: "story-queue-item review board-parked-item" });
  if (item.id === openJobId) row.classList.add("active");
  const why = (item.why || "").trim();
  row.append(
    el("b", { textContent: item.name || item.id }),
    el("small", { textContent: `ค้างที่ ${item.from_label}${why ? ` · ${why}` : ""}` }),
  );
  const tools = el("span", { className: "story-queue-tools" });
  tools.append(iconBtn("↩", `เอากลับเข้าขั้น ${item.from_label}`,
    () => act(() => jobPost(`${item.id}/unpark`))));
  row.append(tools);
  row.addEventListener("click", (event) => {
    if (event.target.closest("button")) return;
    showJob(item.id);
  });
  return row;
}

function paintBoard() {
  const box = boardBox();
  const list = $("#storyQueueList");
  if (!boardData) { box.replaceChildren(); return; }
  const buckets = boardData.buckets || [];

  // ยังไม่เคยเลือก หรือกองที่เลือกไว้หายไป → ไปกองแรกที่มีงานค้าง
  if (!buckets.some((b) => b.key === boardPick)) {
    boardPick = (buckets.find((b) => b.count > 0) || buckets[0] || {}).key || "";
  }

  box.replaceChildren(...buckets.map((bucket) => {
    const button = el("button", {
      type: "button",
      className: "board-tab"
        + (bucket.key === boardPick ? " is-on" : "")
        + (bucket.count ? "" : " is-empty"),
    });
    button.title = bucket.hint;
    // สีประจำขั้นผูกกับ **รหัสกอง** ไม่ใช่ลำดับ — สลับลำดับวันหลังสีจะไม่เพี้ยนตาม
    button.dataset.key = bucket.key;
    button.append(
      el("span", { className: "board-name", textContent: bucket.title }),
      // "(2/10)" = ค้างอยู่ 2 จากสต๊อกที่อยากให้มี 10
      //
      // **กองที่ไม่มีเส้นวัดต้องโชว์ตัวเลขเดียว** กอง "รอแก้" ตั้ง target = 0
      // เพราะยิ่งน้อยยิ่งดี ไม่ใช่ของที่ต้องมีสำรอง ถ้าใช้รูปแบบเดียวกับกองอื่น
      // จะขึ้นว่า "(3/0)" ซึ่งอ่านแล้วเหมือน "3 จาก 0" — ไม่มีความหมาย
      // และขัดกับข้อความข้างล่างที่บอกว่ากองนี้ไม่มีเส้นวัด
      el("span", { className: "board-count",
                   textContent: (bucket.target ?? 10)
                     ? `(${bucket.count}/${bucket.target ?? 10})`
                     : `(${bucket.count})` }),
    );
    if (bucket.short) button.classList.add("is-short");
    button.addEventListener("click", () => {
      boardPick = bucket.key;
      try { localStorage.setItem(BOARD_KEY, boardPick); } catch { /* โหมดส่วนตัว */ }
      paintBoard();      // วาดจากของที่มีอยู่ก่อน กดแล้วต้องเปลี่ยนทันที ไม่หน่วง
      // รายการ "งานที่เก็บไว้" กรองตามหัวข้อเดียวกัน ต้องวาดใหม่ด้วย
      // ไม่งั้นกดสลับหัวข้อแล้วข้างบนเปลี่ยน ข้างล่างยังเป็นของหัวข้อเดิม
      loadStoryRuns();
      // **แล้วดึงของสดมาทับ** — ของที่พักไว้เปลี่ยนเฉพาะตอนคนกดปุ่ม 🅿 หรือ ↩
      // ซึ่งแปลว่าคนที่กดคือคนที่กำลังดูอยู่ ถ้าเขาพักใบหนึ่งแล้วสลับกองไปมา
      // ควรเห็นผลทันที ไม่ใช่รอรอบดึงถัดไปแล้วนึกว่าปุ่มไม่ทำงาน
      loadJobQueue();
    });
    return button;
  }));

  const picked = buckets.find((b) => b.key === boardPick);
  // บรรทัดบอกว่าขาดเท่าไรและ**ต้องทำอะไรถึงจะเติมได้** — ตัวเลขเฉยๆ ตอบไม่ได้
  // ว่าต้องทำอะไรต่อ และแต่ละขั้นเติมด้วยวิธีคนละอย่าง
  const short = $("#boardShort") || el("p", { className: "note", id: "boardShort" });
  /* กองรอแก้ไม่มีเส้นวัด — ยิ่งน้อยยิ่งดี ไม่ใช่ของที่ต้องมีสำรอง
   * ถ้าใช้ข้อความชุดเดียวกับกองอื่นจะขึ้นว่า "ขาดอีก 10 ใบ" ซึ่งกลับหัวกลับหาง
   * แล้วคนอ่านจะเข้าใจว่าต้องไปหางานพังมาเติม
   *
   * ผู้ใช้สั่ง 27 ส.ค. 2026: *"ให้ลิ้งไปที่คำสั่ง /wait ใน telegram เวลาเรียกดู"*
   * — หน้าเว็บกับแชทต้องเห็นรายการเดียวกัน ไม่ใช่คนละชุด
   *   ตอนนี้ลิงก์ไป /wait ย้ายไปอยู่ที่หัวเรื่อง "รอแก้ในขั้นนี้" ใต้แต่ละกองแทน
   *   เพราะกองรวม "รอแก้" ถูกยกเลิกไปแล้ว (ผู้ใช้สั่งใหม่ 27 ส.ค. เย็น) */
  if (picked?.short) {
    short.textContent = `⚠️ ขั้นนี้ค้างอยู่ ${picked.count} ใบ `
      + `— เส้นวัดคือ ${picked.target} ใบ ขาดอีก ${picked.short} · ${picked.refill || ""}`;
    short.hidden = false;
  } else {
    short.textContent = picked
      ? `✅ ขั้นนี้มีงานค้าง ${picked.count} ใบ ถึงเส้นวัด ${picked.target} แล้ว`
      : "";
    short.hidden = !picked;
  }
  if (!short.isConnected) box.after(short);

  // ใบงานบนกระดานเป็นข้อมูลย่อ ถ้ามีใบเต็มอยู่ในมือแล้วให้ใช้ใบเต็ม
  const draw = (jobs) => (jobs || []).map((row) =>
    jobRow(jobCards.find((j) => j.id === row.id) || row));

  const rows = draw(picked?.jobs);
  if (!rows.length) {
    rows.push(el("li", { className: "note",
      textContent: `ไม่มีงานค้างที่ขั้น "${picked?.title || "นี้"}"` }));
  }

  // ---- ของที่พักไว้รอแก้ในขั้นนี้ ----
  //
  // **ไม่มีของพัก = ไม่ต้องขึ้นอะไรเลย** ไม่ต้องมีหัวข้อ ไม่ต้องมีเส้นคั่น
  // หัวข้อเปล่าที่โผล่ทุกกองทำให้ต้องกวาดตาผ่านของที่ไม่มีอยู่จริงทุกครั้ง
  //
  // ทุกกองส่ง `parked` มาเสมอ (ว่างก็เป็นลิสต์เปล่า) จึงไม่ต้องเช็คว่ามีฟิลด์ไหม
  if (picked?.parked_count) {
    rows.push(parkedHead(picked));
    // ขึ้นหัวข้อย่อยใหม่เมื่อ `fix_group` เปลี่ยน — **เดินตามลำดับที่เซิร์ฟเวอร์
    // ส่งมาเท่านั้น ห้ามเรียงใหม่เอง** ไม่งั้นจะไม่ตรงกับที่แชท /wait แสดง
    //
    // **เคยมีฟิลด์ `groups` ที่จัดกลุ่มมาให้เสร็จ แต่เลน video ถอดออกไปแล้ว**
    // (เพราะข้อมูลชุดเดียวส่งสองรูปแล้ววันหลังจะเพี้ยนกันเงียบๆ) ชื่อกลุ่มกับ
    // วิธีแก้ยังมาจากเซิร์ฟเวอร์เหมือนเดิม ติดมากับแต่ละใบเป็น `fix_title`/`fix_hint`
    // — ฝั่งนี้แค่ตัดท่อนตามที่เขาเรียงมา ไม่ได้ตั้งชื่อหรือเรียงเอง
    let mark = null;
    let bunch = [];
    const flush = () => {
      if (!bunch.length) return;
      rows.push(fixGroupHead(bunch), ...bunch.map(parkedRow));
      bunch = [];
    };
    for (const item of picked.parked || []) {
      if (item.fix_group !== mark) { flush(); mark = item.fix_group; }
      bunch.push(item);
    }
    flush();
  }
  // **โชว์เฉพาะงานของหัวข้อที่เลือกเท่านั้น** (ผู้ใช้สั่ง 26 ส.ค. 2026)
  //
  // ตอนแรกผมเอางานที่ปิดไปแล้ว (ล้ม/ยกเลิก) มาต่อท้ายไว้ใต้เส้นแบ่งด้วย
  // ผู้ใช้บอกว่า *"โชว์แค่งานที่ค้างหัวข้อนั้นๆ ไม่เอามารวม"* — ถูกของเขา
  // เพราะจุดประสงค์ของกระดานคือ "กองนี้มีอะไรค้าง" การเอาของที่จบแล้วมาปน
  // ทำให้นับด้วยตาไม่ตรงกับตัวเลขในวงเล็บ ซึ่งทำลายประโยชน์ของตัวเลขไปเลย
  //
  // งานที่ปิดไปแล้วยังดูได้ที่รายการ "งานที่เก็บไว้" ข้างล่าง ไม่ได้หายไปไหน
  list.replaceChildren(...rows);
}

export async function loadJobQueue() {
  const list = $("#storyQueueList");
  if (!list) return;
  let payload;
  try {
    payload = await api(`${CLIP_API}/api/jobs`);
  } catch {
    $("#storyQueueCount").textContent = "ต่อไม่ติด";
    queueLoadNote().textContent = "";
    boardBox().replaceChildren();
    list.replaceChildren(el("li", {
      className: "note",
      textContent: `เปิดเซิร์ฟเวอร์สายคลิปก่อน — python clip_app.py`,
    }));
    return;
  }
  jobCards = payload.jobs || [];
  $("#storyFlowOn").checked = !!payload.flow_enabled;

  const open = jobCards.filter((job) => job.open);
  const load = payload.load || null;
  // ป้ายหัวคิวสั้นๆ ให้เห็นเพดานทันที ส่วนเหตุผลเต็มอยู่บรรทัดใต้ลงไป
  $("#storyQueueCount").textContent = load
    ? `${load.busy}/${load.limit}${load.queued ? ` · รอ ${load.queued}` : ""}`
    : (open.length ? `${open.length} งานค้าง` : "ว่าง");
  const note = queueLoadNote();
  note.textContent = payload.load_text || "";
  note.classList.toggle("warn", !!load?.full);

  // อ่านกระดานแยกอีกคำขอ — **ล้มแล้วต้องไม่ลากคิวตายตาม**
  // ถ้ากระดานอ่านไม่ได้ ยังต้องเห็นรายการงานแบบเดิมได้อยู่
  try {
    boardData = await api(`${CLIP_API}/api/board`);
  } catch (error) {
    boardData = null;
    // **ต้องบอกทางออกด้วย** ข้อความที่บอกแค่ว่าพังทำให้ผู้ใช้ได้แต่นั่งดู
    boardBox().replaceChildren(el("p", { className: "note",
      textContent: `โหลดกระดานไม่สำเร็จ: ${error.message}`
        + " — กด 🔄 โหลดใหม่ หรือดูใน Telegram ด้วย /wait" }));
    list.replaceChildren(...open.map(jobRow));
    return;
  }
  paintBoard();
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

/** เปิดดูรูปขนาดเต็ม — ผู้ใช้สั่งเพิ่ม 25 ส.ค. 2026
 *
 *  รูปย่อในคลังเล็กมากจนดูไม่ออกว่าใบไหนเป็นใบไหน โดยเฉพาะรูปที่เป็นภาพ
 *  รายละเอียดสินค้าซึ่งมีตัวหนังสือเต็มไปหมด ต้องกดดูเต็มก่อนถึงจะเลือกถูก
 *
 *  สร้าง <dialog> ต่อกับ body **ไม่แตะโครงหน้า** (body เป็น block ธรรมดา
 *  และ dialog แบบ modal อยู่นอกการไหลของหน้าอยู่แล้ว)
 */
function zoomImage(src, alt) {
  let box = document.getElementById("imgZoom");
  if (!box) {
    box = el("dialog", { id: "imgZoom", className: "img-zoom" });
    // กดที่ว่างรอบรูปเพื่อปิด — บนมือถือหาปุ่มกากบาทยากกว่าแตะข้างๆ
    box.addEventListener("click", (event) => {
      if (event.target === box) box.close();
    });
    document.body.append(box);
  }
  const close = textBtn("✕ ปิด", "ghost", () => box.close());
  const pic = el("img", { src, alt: alt || "", className: "img-zoom-pic" });

  /* กำหนดขนาดรูปเป็นตัวเลขจริงหลังรูปโหลดเสร็จ (แก้ 26 ส.ค. 2026)
   *
   *  **ทำไมต้องคำนวณเอง ไม่ปล่อยให้ CSS จัดการ** กล่องเป็น <dialog> ซึ่งคิดขนาด
   *  ตัวเองจากของข้างใน ตอนเปิดขึ้นมารูปยังโหลดไม่เสร็จ ขนาดจึงเป็นศูนย์ กล่องเลย
   *  หดไปเท่าความกว้างของแถบปุ่มด้านล่าง (วัดได้ 560px) พอรูปโหลดมาที่ 774px
   *  ก็ล้นออกนอกกล่อง ขอบขวาโดนตัด
   *
   *  ทางแก้แรกที่ลองคือบังคับกล่องเป็น 94% ของจอ ซึ่งแก้อาการล้นได้ **แต่เสียกว่าเดิม**
   *  บนจอกว้างรูปจัตุรัสจะลอยกลางพื้นขาวกว้างมาก และแถบปุ่มปิดถูกดันออกไปไกลจนกดไม่ถึง
   *
   *  แบบนี้: คิดขนาดที่พอดีจอเอง (ไม่เกิน 88% กว้าง · 78% สูง) แล้วใส่เป็น px จริง
   *  กล่องจึงหดพอดีรูปเป๊ะ ไม่มีพื้นที่ขาวเหลือ และปุ่มปิดอยู่ติดใต้รูปเสมอ
   *  **ห้ามขยายเกินขนาดไฟล์จริง** (ตัวคูณไม่เกิน 1) ไม่งั้นรูปเล็กจะถูกดึงจนแตก
   */
  const fitPic = () => {
    if (!pic.naturalWidth || !pic.naturalHeight) return;
    // **ต้องวัดด้วย clientWidth/clientHeight ไม่ใช่ innerWidth/innerHeight**
    // สองตัวนี้ต่างกันตรงความกว้างแถบเลื่อน (วัดได้ 397 กับ 380 = ต่างกัน 17px)
    // ส่วนหน่วย vw ที่ CSS ใช้อิงตัวหลัง ถ้าเราคิดจากตัวแรก ค่าที่ได้จะใหญ่กว่าที่ CSS
    // ยอม แล้ว max-width จะไปบีบความกว้างทีหลังโดยที่ความสูงไม่ถูกบีบตาม
    // → กรอบรูปบิดเบี้ยว (เจอจริงบนจอ 397: JS สั่ง 349x349 แต่ออกมาเป็น 330x349)
    const vw = document.documentElement.clientWidth;
    const vh = document.documentElement.clientHeight;
    const scale = Math.min(
      (vw * 0.88) / pic.naturalWidth,
      (vh * 0.78) / pic.naturalHeight,
      1,                                  // ห้ามขยายเกินขนาดไฟล์จริง เดี๋ยวภาพแตก
    );
    pic.style.width = `${Math.round(pic.naturalWidth * scale)}px`;
    pic.style.height = `${Math.round(pic.naturalHeight * scale)}px`;
  };
  pic.addEventListener("load", fitPic);
  if (pic.complete) fitPic();
  // ย่อ/ขยายหน้าต่างแล้วต้องคิดใหม่ ไม่งั้นกล่องล้นจอที่เล็กลง
  if (!box.dataset.fitBound) {
    box.dataset.fitBound = "1";
    window.addEventListener("resize", () => {
      if (box.open) box.__fit?.();
    });
  }
  box.__fit = fitPic;

  box.replaceChildren(
    pic,
    el("div", { className: "img-zoom-bar" },
      el("a", { href: src, target: "_blank", rel: "noreferrer",
                textContent: "เปิดไฟล์เต็มในแท็บใหม่" }),
      close),
  );
  box.showModal();
}

/** ปุ่มแว่นขยายบนรูปหนึ่งใบ — กดแล้วไม่ให้ไปโดนการกดของการ์ดที่ครอบอยู่ */
function zoomBtn(src, alt) {
  const button = iconBtn("🔍", "ดูรูปขนาดเต็ม", () => zoomImage(src, alt));
  button.addEventListener("click", (event) => event.stopPropagation());
  return button;
}

// ------------- ที่พักของที่กำลังแก้ (ผู้ใช้สั่งไว้ 23 ส.ค. 2026) ---------------
//
//   "ในการแก้จุดเด่นหรือแก้รูป มันจะมีแก้มากกว่า 1 จุดแน่ๆ ผมอยากให้มีการกดให้ครบก่อน
//    แล้วมีปุ่มส่งทีเดียว เช่น ผมลบจุดเด่น 3 เพิ่ม 6 7 8 เสร็จปุ๊บกดส่งครั้งเดียว"
//
// เดิมหน้าเว็บยิงบันทึกทุกครั้งที่กดแก้ทีละจุด ซึ่งต่างจากฝั่งแชทที่สะสมไว้ก่อน
// สองทางทำงานคนละแบบ แล้วกดพลาดทีเดียวก็บันทึกไปแล้ว ถอยไม่ได้
//
// **ห้ามสะสมในหน้าเว็บแล้วยิงทีละข้อรัวๆ ตอนกดยืนยัน** ถ้าขาดกลางคัน (เน็ตหลุด ·
// ปิดหน้า) จะเหลือครึ่งๆ ซึ่งแย่กว่าไม่ได้แก้เลย เพราะไม่มีใครรู้ว่าหยุดตรงไหน —
// ฝั่งเซิร์ฟเวอร์จึงมี `/images` กับ `/highlights` ที่เขียน**ทั้งชุดครั้งเดียวจบ**
const editDraft = {};

/** งานไหนกำลังรอ AI คิดจุดเด่นอยู่ (ผู้ใช้สั่ง 26 ส.ค. 2026)
 *
 *  "กด gen จุดเด่นผ่าน AI แล้วไม่รู้ว่าเสร็จหรือไม่เสร็จ ถ้ายังรอผลอยู่ให้ขึ้นตัววนๆ"
 *
 *  งานนี้ใช้เวลา 15–30 วินาที ซึ่งนานพอที่จะแยกไม่ออกว่า "กำลังทำ" กับ "กดไม่ติด"
 *  เก็บสถานะไว้นอกฟังก์ชันวาด เพราะหน้าจอวาดใหม่เองทุก 6 วินาที ถ้าเก็บไว้ข้างใน
 *  ตัวหมุนจะหายไปกลางทางแล้วกลับไปเหมือนไม่มีอะไรเกิดขึ้น
 */
const aiBusy = {};

/** งานไหน "เพิ่งกด AI แล้วล้ม" — เก็บเหตุผลไว้โชว์ตรงปุ่ม (ผู้ใช้สั่ง 26 ส.ค. 2026)
 *
 *  **ที่ต้องมีเพราะข้อความล้มไปโผล่ผิดที่** ของเดิมเขียนลง `#storyNote` ซึ่งอยู่
 *  **ใต้กรอบสองฝั่งทั้งหมด** (web/index.html บรรทัด 579) คนละที่กับปุ่มที่เพิ่งกด
 *  แถมสองฝั่งเลื่อนแยกกันตั้งแต่ 26 ส.ค. บรรทัดนั้นจึงอยู่นอกจอไปเลย
 *
 *  ผลที่เกิดจริง: 22:28 กดเจนจุดเด่นของทีวี 55 นิ้ว (26577901113) แล้ว Gemini
 *  ล้มสองรอบ (หมดเวลา 141 วิ · แล้ว 503 ทั้งสองโมเดล) ระบบเขียน error ไว้ครบ
 *  ใน log แต่ **บนหน้าจอไม่มีอะไรขึ้นเลย** ผู้ใช้เห็นแค่จุดเด่นไม่เพิ่ม
 *
 *  เก็บนอกฟังก์ชันวาดเหมือน `aiBusy` เพราะหน้าจอวาดใหม่เองทุก 6 วินาที
 *  **ไม่ล้างเองตามเวลา** — ล้างเมื่อกดใหม่หรือสำเร็จเท่านั้น ความล้มเหลวที่
 *  หายไปเองคือความล้มเหลวที่ไม่มีใครเห็น
 */
const aiError = {};

/** กล่องแดงบอกว่าล้มเพราะอะไร — วางไว้ติดปุ่มที่กด ไม่ใช่ท้ายหน้า */
function aiErrorBox(jobId) {
  const why = aiError[jobId];
  if (!why) return null;
  const box = el("div", { className: "ai-error" });
  box.append(
    el("p", { className: "ai-error-head", textContent: "❌ ให้ AI คิดจุดเด่นไม่สำเร็จ" }),
    el("p", { className: "ai-error-why", textContent: why }),
    el("p", { className: "note", textContent:
      "ส่วนใหญ่เป็นฝั่ง Google ขัดข้องชั่วคราว (503 = เครื่องเขาแน่น · "
      + "หมดเวลา = ตอบช้าเกิน) กดใหม่อีกครั้งได้เลย · "
      + "ถ้าขึ้นว่าโควตาหมด ต้องรอวันถัดไป" }),
  );
  box.append(el("div", { className: "inline-row" },
    textBtn("✕ ปิดข้อความนี้", "ghost", () => {
      delete aiError[jobId];
      box.remove();
    })));
  return box;
}

/** ที่แก้ค้างของงานนี้ — ผูกกับของฝั่งเซิร์ฟเวอร์ตอนเริ่มแก้
 *
 *  ถ้าของฝั่งเซิร์ฟเวอร์เปลี่ยนไประหว่างที่ยังแก้ค้าง (อีกคนกดในแชท) **ต้องทิ้ง
 *  ที่แก้แล้วเริ่มใหม่** ไม่ใช่เขียนทับของเขา — แต่ต้องบอกด้วยว่าทิ้งเพราะอะไร
 */
function draftFor(job, run) {
  const base = JSON.stringify([
    run.images || [], run.image_pool || [], run.highlights || [], run.features || [],
  ]);
  const kept = editDraft[job.id];
  if (kept && kept.base === base) return kept;
  const highlights = run.highlights || [];
  const fresh = {
    base,
    images: [...(run.images || [])],
    pool: [...(run.image_pool || [])],
    highlights: [...highlights],
    spare: (run.features || []).filter((text) => !highlights.includes(text)),
    // ทิ้งที่แก้ค้างเพราะของฝั่งโน้นเปลี่ยน — ต้องขึ้นเตือน ไม่ใช่หายไปเฉยๆ
    dropped: !!(kept && draftDirty(kept)),
  };
  editDraft[job.id] = fresh;
  return fresh;
}

function draftDirty(draft) {
  const [images, , highlights] = JSON.parse(draft.base);
  return JSON.stringify(draft.images) !== JSON.stringify(images)
      || JSON.stringify(draft.highlights) !== JSON.stringify(highlights);
}

function draftChanges(draft) {
  const [images, , highlights] = JSON.parse(draft.base);
  const hlAdded = draft.highlights.filter((t) => !highlights.includes(t)).length;
  const hlGone = highlights.filter((t) => !draft.highlights.includes(t)).length;
  return {
    imgOn: draft.images.some((name) => !images.includes(name)),
    imgOff: images.some((name) => !draft.images.includes(name)),
    hlOn: hlAdded > 0,
    hlOff: hlGone > 0,
    // **จุดเด่นนับด้วย max ไม่ใช่บวกกัน** (แก้ 26 ส.ค. 2026)
    //
    // ตั้งแต่พิมพ์ทับในกรอบได้ การแก้ข้อความหนึ่งข้อจะดูเหมือน "ข้อเก่าหายไป 1 +
    // ข้อใหม่โผล่มา 1" ถ้าบวกกันจะขึ้นว่าแก้ 2 จุด — วัดจริงแล้วพิมพ์แก้ 2 ข้อ
    // ขึ้นว่า "แก้ค้างไว้ 4 จุด" ซึ่งทำให้คนอ่านนึกว่าตัวเองเผลอไปแตะอะไรเพิ่ม
    //
    // ใช้ตัวที่มากกว่าแทน: แก้ข้อความ = 1 · เพิ่มข้อใหม่ = 1 · ลบทิ้ง = 1
    // (ส่วนรูปยังบวกกันเหมือนเดิม เพราะเป็นการเอาเข้า/เอาออกจริงๆ ไม่ใช่แก้ข้อความ)
    count: draft.images.filter((n) => !images.includes(n)).length
         + images.filter((n) => !draft.images.includes(n)).length
         + Math.max(hlAdded, hlGone),
  };
}

/** ส่งที่แก้ทั้งชุดขึ้นเซิร์ฟเวอร์ — ยิงเฉพาะส่วนที่แก้จริง ส่วนละครั้งเดียว
 *
 *  ยิงสองครั้ง (รูป · จุดเด่น) เพราะเป็นของคนละชุด แต่**แต่ละครั้งเขียนทั้งชุดจบ
 *  ในตัวเอง** ไม่ใช่ทยอยทีละข้อ ถ้าครั้งที่สองล้ม ต้องบอกให้ชัดว่าครั้งแรกผ่านแล้ว
 *  ไม่ใช่ขึ้นว่า "ไม่สำเร็จ" ลอยๆ แล้วผู้ใช้กดซ้ำจนของซ้อนกัน
 */
async function saveDraft(job, draft) {
  const changed = draftChanges(draft);
  const done = [];
  try {
    if (changed.imgOn || changed.imgOff) {
      const result = await jobPost(`${job.id}/images`, { images: draft.images });
      done.push(result.message || "บันทึกชุดรูปแล้ว");
    }
    if (changed.hlOn || changed.hlOff) {
      const result = await jobPost(`${job.id}/highlights`, { highlights: draft.highlights });
      done.push(result.message || "บันทึกจุดเด่นแล้ว");
    }
  } catch (error) {
    $("#storyNote").textContent = done.length
      ? `${done.join(" · ")} — แต่ส่วนที่เหลือไม่สำเร็จ: ${error.message}`
      : `บันทึกไม่สำเร็จ: ${error.message}`;
    delete editDraft[job.id];          // ดึงของจริงมาตั้งต้นใหม่ จะได้ไม่เดาว่าเหลืออะไร
    await loadJobQueue();
    await showJob(job.id, true);
    return false;
  }
  delete editDraft[job.id];
  $("#storyNote").textContent = done.join(" · ") || "ไม่มีอะไรเปลี่ยน";
  await loadJobQueue();
  await showJob(job.id, true);
  return true;
}

/** กล่องตรวจชุดรูป+จุดเด่น — วาดใหม่ในเครื่องทุกครั้งที่กด ไม่ยิงเซิร์ฟเวอร์
 *  จนกว่าจะกดบันทึก (นั่นคือทั้งหมดของ "แก้ให้ครบก่อนแล้วส่งทีเดียว") */
function imageReview(job, run, meta) {
  const draft = draftFor(job, run);
  const box = el("div", { className: "img-review" });
  const paint = () => box.replaceChildren(...imageReviewParts(job, meta, draft, paint));
  paint();
  return [box];
}

function imageReviewParts(job, meta, draft, paint) {
  const itemId = job.item_id || "";
  const images = draft.images;
  const pool = draft.pool;
  const highlights = draft.highlights;
  const out = [];

  if (draft.dropped) {
    // ทิ้งที่แก้ค้างเพราะอีกทาง (ปุ่มในแชท) แก้ของชิ้นเดียวกันไปแล้ว **ต้องบอก**
    // ถ้าหายไปเงียบๆ ผู้ใช้จะนึกว่ากดบันทึกไปแล้วทั้งที่ยังไม่ได้กด
    out.push(el("p", { className: "note warn", textContent:
      "⚠️ ข้อมูลถูกแก้จากอีกทาง (แชท) ระหว่างที่กำลังแก้อยู่ — ที่แก้ค้างถูกทิ้ง "
      + "หน้านี้ดึงของล่าสุดมาให้แล้ว เริ่มแก้ใหม่ได้เลย" }));
    draft.dropped = false;
  }

  // ── แถบบันทึก: แก้ให้ครบก่อน แล้วกดส่งทีเดียว (ผู้ใช้สั่ง 23 ส.ค. 2026) ──
  //
  // `refreshBar` มีไว้ให้ช่องพิมพ์จุดเด่นเรียกตอนพิมพ์ — **ห้ามเรียก paint()**
  // เพราะวาดใหม่ทั้งก้อนตอนกำลังพิมพ์จะทำให้เคอร์เซอร์เด้งไปท้ายช่องทุกตัวอักษร
  const bar = el("div", { className: "inline-row save-bar" });
  const refreshBar = () => {
    const now = draftChanges(draft);
    bar.className = `inline-row save-bar${now.count ? " on" : ""}`;
    if (!now.count) {
      bar.replaceChildren(el("small", { className: "note", textContent:
        "แก้ได้หลายจุดติดกัน — ยังไม่บันทึกจนกว่าจะกดปุ่มบันทึก" }));
      return;
    }
    bar.replaceChildren(
      el("b", { className: "save-count", textContent: `แก้ค้างไว้ ${now.count} จุด` }),
      textBtn("💾 บันทึกที่แก้ทั้งหมด", "primary", () => saveDraft(job, draft)),
      textBtn("↩️ ยกเลิกที่แก้", "ghost", () => {
        // คืนค่าจากของฝั่งเซิร์ฟเวอร์ที่ผูกไว้ตอนเริ่มแก้ ไม่ต้องยิงถามใหม่
        const [wasImages, wasPool, wasHighlights, features] = JSON.parse(draft.base);
        draft.images = [...wasImages];
        draft.pool = [...wasPool];
        draft.highlights = [...wasHighlights];
        draft.spare = features.filter((text) => !wasHighlights.includes(text));
        paint();
      }),
    );
  };
  refreshBar();
  out.push(bar);

  out.push(el("h4", { textContent: `🖼 ชุดรูปที่จะส่งเข้า GPT (${images.length} ใบ)` }));

  // ── ซ้าย: ชุดที่เลือกไว้ · ขวา: คลังสำรอง กดเลือกได้เลย ──────────────
  //
  // ผู้ใช้สั่ง 25 ส.ค. 2026 (วงกลมแดงในภาพ) — "ให้รูปในคลังขึ้นโชว์ตรงนี้เลย
  // แล้วผมกดเลือกเอง จุดเด่นด้วย" เดิมต้องกดปุ่ม 🔄 ทีละใบเพื่อสุ่มเปลี่ยน
  // ซึ่งไม่รู้ว่าจะได้ใบไหน และไม่เห็นว่าในคลังมีอะไรบ้าง
  //
  // ทั้งก้อนนี้อยู่ใน #storyDetail — เป็นเนื้อหาในกล่อง ไม่ใช่โครงหน้า
  const pair = el("div", { className: "bank-pair" });

  const picked = el("div", { className: "bank-side" });
  const grid = el("div", { className: "story-grid" });
  images.forEach((name, index) => {
    const tools = el("span", { className: "story-cell-tools" });
    tools.append(zoomBtn(clipFile(itemId, name), `รูปที่ ${index + 1}`));
    if (images.length > 1) {
      tools.append(iconBtn("🗑", "เอาใบนี้ออก (ย้ายไปคลัง)", () => {
        draft.images = images.filter((_, spot) => spot !== index);
        draft.pool = [name, ...pool];
        paint();
      }));
    }
    grid.append(el("figure", { className: "story-cell" },
      el("img", {
        className: "story-thumb", loading: "lazy", alt: `รูปที่ ${index + 1}`,
        src: clipFile(itemId, name),
      }), tools));
  });
  picked.append(grid);

  const bank = el("div", { className: "bank-side" });
  if (pool.length) {
    bank.append(el("p", { className: "bank-title",
                          textContent: `คลังสำรอง ${pool.length} ใบ — กดเพื่อใช้ใบนั้น` }));
    const bankGrid = el("div", { className: "story-grid bank-grid" });
    const full = images.length >= meta.max_images;
    pool.forEach((name, spot) => {
      const cell = el("figure", { className: `story-cell pick${full ? " off" : ""}` },
        el("img", {
          className: "story-thumb", loading: "lazy", alt: name,
          src: clipFile(itemId, name),
        }));
      cell.append(el("span", { className: "story-cell-tools" },
        zoomBtn(clipFile(itemId, name), name)));
      cell.title = full ? `ครบ ${meta.max_images} ใบแล้ว — เอาใบเดิมออกก่อน` : "กดเพื่อใช้ใบนี้";
      if (!full) {
        cell.addEventListener("click", () => {
          draft.images = [...images, name];
          draft.pool = pool.filter((_, at) => at !== spot);
          paint();
        });
      }
      bankGrid.append(cell);
    });
    bank.append(bankGrid);
  } else {
    bank.append(el("p", { className: "note", textContent: "คลังสำรองว่าง" }));
  }
  pair.append(picked, bank);
  out.push(pair);

  // **ปุ่มไปต่อเป็นสีเทาธรรมดาเมื่อยังไม่มีอะไรค้าง** (ผู้ใช้สั่ง 26 ส.ค. 2026)
  //
  // ของเดิมเป็นสีเข้มทึบ (`primary`) ตลอดเวลา ซึ่งในงานที่เพิ่งเปิดมาและยังไม่ได้
  // แตะอะไรเลย มันดูเหมือน **ปุ่มที่ถูกกดไปแล้ว** ทำให้ไม่รู้ว่าต้องกดหรือกดไปแล้ว
  // เปลี่ยนเป็น: เทาธรรมดาเมื่อยังไม่มีอะไรแก้ค้าง · เข้มขึ้นเมื่อมีของค้างรอบันทึก
  // สีจึงกลายเป็นข้อมูลว่า "มีอะไรรออยู่ไหม" แทนที่จะเป็นแค่การตกแต่ง
  out.push(el("div", { className: "inline-row" },
    textBtn("✅ ใช้ชุดรูปนี้ ไปต่อ", draftDirty(draft) ? "primary" : "ghost",
            () => commitDraft(job, draft, "img_ok"))));

  // ── จุดเด่น: ซ้ายคือที่เลือกไว้ · ขวาคือจุดขายทั้งหมดที่ AI ไล่ไว้ ─────
  out.push(el("h4", { textContent: `✨ จุดเด่นที่จะส่งเข้า GPT (${highlights.length} ข้อ)` }));

  const hlPair = el("div", { className: "bank-pair" });
  const hlPicked = el("div", { className: "bank-side" });
  // พิมพ์ทับในกรอบได้เลย (ผู้ใช้สั่ง 26 ส.ค. 2026 — "ให้เหมือนเดิมแบบคลิ๊กในกรอบแล้วแก้ได้เลย")
  //
  // ของเดิมต้องกดปุ่ม ✏️ แล้วเด้งกล่อง prompt ของเบราว์เซอร์ขึ้นมา ซึ่งแก้ทีละข้อ
  // และมองไม่เห็นข้ออื่นระหว่างแก้ ตอนนี้เป็นช่องพิมพ์ตรงๆ เหมือนกรอบบทพูด
  const [, , baseHighlights] = JSON.parse(draft.base);
  const list = el("ol", { className: "story-highlights hl-list" });
  highlights.forEach((text, index) => {
    const item = el("li", {});
    const area = el("textarea", { className: "hl-line", rows: 1, spellcheck: false });
    area.value = text;
    const was = baseHighlights[index];
    if (was !== undefined && text !== was) {
      area.classList.add("edited");
      area.title = `ของเดิม: ${was}`;
    }
    const fit = () => { area.style.height = "auto"; area.style.height = `${area.scrollHeight}px`; };
    area.addEventListener("input", () => {
      draft.highlights[index] = area.value;
      fit();
      area.classList.toggle("edited", area.value !== was);
      refreshBar();               // ขยับแค่แถบล่าง ไม่วาดใหม่ทั้งก้อน เคอร์เซอร์จะได้ไม่เด้ง
    });
    area.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || was === undefined) return;
      event.preventDefault();
      draft.highlights[index] = was;
      area.value = was;
      area.classList.remove("edited");
      fit();
      refreshBar();
    });
    item.append(area);
    if (highlights.length > 1) {
      item.append(iconBtn("🗑", "เอาข้อนี้ออก (ย้ายไปกองสำรอง)", () => {
        const gone = draft.highlights[index];
        draft.highlights = draft.highlights.filter((_, at) => at !== index);
        // เก็บเข้ากองสำรองเสมอ ไม่ใช่ทิ้ง — ข้อที่พิมพ์เองก็ต้องดึงกลับได้
        if (gone && !draft.spare.includes(gone)) draft.spare = [gone, ...draft.spare];
        paint();
      }));
    }
    list.append(item);
    window.requestAnimationFrame(fit);
  });
  hlPicked.append(list);

  const hlBank = el("div", { className: "bank-side" });
  const spare = draft.spare.filter((text) => !highlights.includes(text));
  if (spare.length) {
    const full = highlights.length >= meta.max_highlights;
    hlBank.append(el("p", { className: "bank-title",
      textContent: `จุดขายทั้งหมดที่ไล่ไว้ ${spare.length} ข้อ — กดเพื่อใช้ข้อนั้น` }));
    const ul = el("ul", { className: "bank-list" });
    spare.forEach((text) => {
      const row = el("li", { className: `bank-item${full ? " off" : ""}` },
        el("span", { textContent: text }));
      row.title = full ? `ครบ ${meta.max_highlights} ข้อแล้ว — เอาข้อเดิมออกก่อน` : "กดเพื่อใช้ข้อนี้";
      if (!full) {
        row.addEventListener("click", () => {
          draft.highlights = [...highlights, text];
          draft.spare = draft.spare.filter((old) => old !== text);
          paint();
        });
      }
      ul.append(row);
    });
    hlBank.append(ul);
  } else {
    hlBank.append(el("p", { className: "note",
      textContent: "ยังไม่มีจุดขายสำรอง — เพิ่มเองได้ด้วยปุ่มข้างล่าง" }));
  }
  hlPair.append(hlPicked, hlBank);
  out.push(hlPair);

  const hlTools = el("div", { className: "inline-row" });
  if (highlights.length < meta.max_highlights) {
    hlTools.append(textBtn("➕ เพิ่มจุดเด่นเอง", "ghost", () => {
      const next = window.prompt("จุดเด่นข้อใหม่");
      if (next && next.trim() && !highlights.includes(next.trim())) {
        draft.highlights = [...highlights, next.trim()];
        paint();
      }
    }));
  }
  if (aiBusy[job.id]) {
    // กำลังรอ AI — ปุ่มกดไม่ได้ และมีตัวหมุนบอกว่ายังไม่เสร็จ
    const wait = el("span", { className: "ai-wait" },
      el("span", { className: "spinner" }),
      el("span", { textContent: `กำลังให้ AI ดูรูป ${images.length} ใบ… (ราว 15–30 วินาที)` }));
    hlTools.append(wait);
  } else {
    hlTools.append(textBtn(
      `✨ ให้ AI ดูรูปแล้วเขียนจุดเด่นใหม่ (${Math.min(images.length, meta.max_highlights)} ข้อ)`,
      "ghost", () => regenHighlights(job, draft, meta.max_highlights, paint)));
    hlTools.append(modelPicker(meta.highlight_models));
  }
  out.push(framingPicker(job, meta));
  hlTools.append(textBtn("✅ ใช้จุดเด่นชุดนี้ ไปต่อ",
                         draftDirty(draft) ? "primary" : "ghost",
                         () => commitDraft(job, draft, "hl_ok")));
  out.push(hlTools);
  // กล่องแดงบอกว่า AI ล้มเพราะอะไร — อยู่ติดปุ่มที่กด ไม่ใช่ท้ายหน้า
  const oops = aiErrorBox(job.id);
  if (oops) out.push(oops);
  // บอกจำนวนที่จะได้จริง ไม่ใช่จำนวนรูป — ถ้าเลือกรูปเกินเพดานจุดเด่น
  // ต้องเห็นตั้งแต่ก่อนกด ไม่ใช่ไปงงตอนได้ผลมาไม่ครบตามจำนวนรูป
  const willGet = Math.min(images.length, meta.max_highlights);
  out.push(el("p", { className: "note", textContent:
    `ปุ่ม ✨ จะส่งรูป ${images.length} ใบที่เลือกไว้ข้างบนเข้า Gemini `
    + `แล้วให้เขียนจุดเด่นใบละ 1 ข้อ รวม ${willGet} ข้อ จากสิ่งที่เห็นในรูปใบนั้น`
    + (images.length > meta.max_highlights
        ? ` (เก็บจุดเด่นได้สูงสุด ${meta.max_highlights} ข้อ จึงได้ไม่ครบทุกใบ)`
        : "")
    + " — ของเดิมจะถูกแทนที่" }));
  return out;
}

/** ช่องติ๊ก "เห็นสินค้าเต็มทุกฉาก" (ผู้ใช้สั่ง 26 ส.ค. 2026)
 *
 *  "ทำเป็นช่องให้ติ๊กเพิ่มตอนส่งไปสร้าง storyboard ว่าเห็นสินค้าเต็มทุกฉาก
 *   **เป็นการซูมแต่ต้องเห็นสินค้าเต็มทุกฉาก**"
 *
 *  ประโยคหลังสำคัญ — ไม่ใช่ห้ามซูม กล้องยังขยับเข้าหาสินค้าได้ ที่ห้ามคือซูมเข้าไป
 *  ในส่วนใดส่วนหนึ่งจนตัวสินค้าถูกตัดขอบ
 *
 *  **บันทึกทันทีที่ติ๊ก ไม่รอปุ่มบันทึกรวม** ต่างจากรูป/จุดเด่นโดยตั้งใจ —
 *  ค่านี้ถูกจำไว้เป็นค่าตั้งต้นของงานถัดไปด้วย ถ้าค้างไว้ไม่บันทึกแล้วเผลอปิดหน้า
 *  งานถัดไปจะได้ค่าเก่าโดยที่ผู้ใช้คิดว่าเปลี่ยนไปแล้ว
 */
function framingPicker(job, meta) {
  const mode = (meta.framing_menu || [])[0];
  const box = el("div", { className: "framing-box" });
  if (!mode) return box;

  let on = !!meta.framing;
  const own = !!meta.framing_own;

  const paint = () => {
    const btn = textBtn(`${on ? "☑" : "☐"} ${mode.label}`, on ? "primary" : "ghost",
      () => toggle(!on));
    btn.title = mode.hint;
    box.replaceChildren(
      el("div", { className: "inline-row framing-row" }, btn),
      el("p", { className: "note", textContent: on
        ? mode.hint + (own ? "" : " · (ค่าที่จำไว้จากงานก่อน — กดเปลี่ยนได้)")
        : "ไม่ติ๊ก = ปล่อยให้ GPT จัดมุมกล้องเอง (จะได้ฉากระยะใกล้เป็นส่วนใหญ่)" }),
    );
  };

  async function toggle(next) {
    const was = on;
    on = next;
    paint();
    try {
      const result = await jobPost(`${job.id}/framing`, { framing: next });
      $("#storyNote").textContent = result.message;
    } catch (error) {
      on = was;                          // ยิงไม่ผ่าน ต้องเด้งกลับ ไม่ใช่โชว์ว่าเปลี่ยนแล้ว
      paint();
      $("#storyNote").textContent = `ตั้งค่าไม่สำเร็จ: ${error.message}`;
    }
  }

  paint();
  return box;
}

/** ให้ AI ดูรูปที่เลือกไว้แล้วคิดจุดเด่นใหม่ (ผู้ใช้สั่ง 26 ส.ค. 2026)
 *
 *  ส่ง **รูปชุดที่กำลังโชว์อยู่บนจอ** ไป ไม่ใช่ให้เซิร์ฟเวอร์ไปอ่านของที่บันทึกไว้
 *  เพราะถ้ายังสลับรูปค้างไว้ไม่ได้กดบันทึก สองฝั่งจะเห็นคนละชุด แล้วผู้ใช้จะงงว่า
 *  ทำไมจุดเด่นไม่ตรงกับรูปที่เห็นตรงหน้า
 *
 *  ยิงหนึ่งครั้ง = เสียโควตา Gemini หนึ่งครั้ง จึงต้องถามยืนยันก่อนเสมอ และต้อง
 *  บอกให้ชัดว่าของเดิมจะหายไป ไม่ใช่เพิ่มต่อท้าย
 */
/* ---------------------------------------- เลือกโมเดลที่จะให้ดูรูป
 *
 * ผู้ใช้สั่ง 27 ส.ค. 2026: "ด้านข้างในทำ drop down เลือกเปลี่ยน model ได้"
 *
 * **ที่มา** วันนั้นกดปุ่ม ✨ แล้วล้มทุกครั้ง เพราะโมเดลทั้งสองตัวในสายพานตายพร้อมกัน
 * — 3.5-flash โควตาหมด (ชั้นฟรีให้ 20 ครั้ง/วัน **แยกถังรายโมเดล**) ส่วน 3.7-flash
 * ฝั่ง Google แน่นเอง (503) ทั้งที่ยังมีโมเดลอื่นที่ยิงจริงแล้วตอบได้อีก 5 ตัว
 *
 * เพราะโควตาแยกถังรายโมเดล การเลือกเองจึงไม่ใช่แค่ทางหนีตอนล่ม แต่คือการเพิ่ม
 * จำนวนครั้งที่กดได้ต่อวันด้วย
 *
 * **จำที่เลือกไว้ในเครื่อง** ไม่ใช่ผูกกับใบงาน — เป็นความชอบของคนใช้ ไม่ใช่
 * คุณสมบัติของสินค้า เลือกครั้งเดียวแล้วใช้ยาวกับทุกใบ
 */
const HL_MODEL_KEY = "clipHighlightModel";
let hlModel = localStorage.getItem(HL_MODEL_KEY) || "";

/* โควตาที่ใช้ไปวันนี้ **แยกรายโมเดล** (ผู้ใช้สั่ง 27 ส.ค. 2026 "ให้โชว์โควต้าแต่ละตัว")
 *
 * **ทำไมถึงสำคัญพอที่จะโชว์** โควตาชั้นฟรีของ Google คือ 20 ครั้ง/วัน **ต่อโมเดล
 * แยกถังกัน** ไม่ใช่ถังรวม — ตัวหนึ่งหมดไม่ได้แปลว่าตัวอื่นหมด
 * ถ้าไม่โชว์ คนเลือกจะเดาไม่ออกเลยว่าทำไมกดแล้วล้ม แล้วจะกดซ้ำที่ตัวเดิมเรื่อยๆ
 *
 * **เพดานรู้ได้ทางเดียวคือโดนปฏิเสธมาแล้ว** Google ไม่มีที่ให้ถามว่าเหลือเท่าไร
 * โมเดลที่ยังไม่เคยหมดจึงบอกได้แค่ "ยิงไปกี่ครั้ง" — **ห้ามเดาเลขที่เหลือให้**
 * เพราะคนจะวางแผนตามเลขที่เดา แล้วผิดแผนโดยไม่รู้ตัว
 */
let hlQuota = null;              // {model: {calls, left, limit, dry}}

async function loadHlQuota() {
  try {
    const data = await api("/api/gemini-quota");
    const map = {};
    (data.rows || []).forEach((row) => { map[row.model] = row; });
    hlQuota = map;
  } catch {
    hlQuota = null;              // ถามไม่ได้ = ไม่โชว์ ดีกว่าโชว์เลขมั่ว
  }
}

/** ป้ายโควตาต่อท้ายชื่อโมเดล — คืนค่าว่างถ้ายังไม่รู้ */
function quotaTag(id) {
  if (!id || !hlQuota) return "";
  const row = hlQuota[id];
  if (!row) return " · ยังไม่ได้ใช้วันนี้";
  if (row.dry) return " · ⛔ หมดโควตาแล้ววันนี้";
  if (row.left !== null && row.left !== undefined) return ` · เหลือ ${row.left}/${row.limit}`;
  return ` · ใช้ไป ${row.calls} ครั้ง`;
}

function modelPicker(menu) {
  const rows = Array.isArray(menu) && menu.length ? menu : null;
  if (!rows) return null;               // เซิร์ฟเวอร์รุ่นเก่ายังไม่ส่งเมนูมา
  // ที่เลือกไว้หายจากเมนู (เราถอดโมเดลนั้นออก) = ถอยไปอัตโนมัติ ไม่ใช่ยิงชื่อที่ตายแล้ว
  if (hlModel && !rows.some((row) => row.id === hlModel)) hlModel = "";

  const box = el("label", { className: "model-pick" },
    el("span", { className: "model-pick-tag", textContent: "โมเดล" }));
  const select = el("select", { className: "model-pick-sel" });
  rows.forEach((row) => {
    const option = el("option", { value: row.id, textContent: row.label + quotaTag(row.id) });
    option.title = row.note || "";
    if (row.id === hlModel) option.selected = true;
    select.append(option);
  });
  const note = el("span", { className: "model-pick-note" });
  const paintNote = () => {
    const row = rows.find((item) => item.id === select.value);
    note.textContent = row ? row.note || "" : "";
  };
  paintNote();
  select.addEventListener("change", () => {
    hlModel = select.value;
    try { localStorage.setItem(HL_MODEL_KEY, hlModel); } catch { /* โหมดส่วนตัว */ }
    paintNote();
  });
  box.append(select, note);

  // ถามโควตาครั้งแรกแล้ววาดป้ายใหม่ — ไม่หน่วงการวาดรอบแรกให้ช้าลง
  if (hlQuota === null) {
    loadHlQuota().then(() => {
      if (!hlQuota) return;
      [...select.options].forEach((option) => {
        const row = rows.find((item) => item.id === option.value);
        if (row) option.textContent = row.label + quotaTag(row.id);
      });
    });
  }
  return box;
}

async function regenHighlights(job, draft, maxHighlights, paint = null) {
  const images = [...draft.images];
  if (!images.length) {
    $("#storyNote").textContent = "เลือกรูปอย่างน้อย 1 ใบก่อน แล้วค่อยให้ AI ดู";
    return;
  }
  const willGet = Math.min(images.length, maxHighlights);

  /* **ต้องบันทึกชุดรูปก่อนเจน** (แก้ 26 ส.ค. 2026 — ผู้ใช้แจ้งว่ารูปที่เลือกหายหมด)
   *
   *  ของเดิมส่งรูปไปให้ AI ดูเฉยๆ แล้วทิ้งที่พักการแก้ พอวาดใหม่จากฝั่งเซิร์ฟเวอร์
   *  ก็ได้ชุดรูป**เก่า**กลับมา เพราะไม่เคยมีใครสั่งบันทึกชุดใหม่
   *
   *  ที่ร้ายกว่ารูปหาย: จุดเด่นที่ได้คิดมาจากรูปที่ผู้ใช้เลือก แต่รูปที่โชว์เป็นชุดเก่า
   *  = จุดเด่นพูดถึงของที่ไม่มีในรูป โดยไม่มีอะไรฟ้องเลย
   *
   *  รากของปัญหาคือผมมองการเลือกรูปเป็น "ข้อมูลป้อน AI" แต่ผู้ใช้มองว่าเป็น
   *  "นี่คือรูปที่ฉันจะใช้" — กดปุ่มนี้แปลว่ายืนยันชุดรูปนี้แล้ว ต้องบันทึกให้
   */
  const changed = draftChanges(draft);
  const needSave = changed.imgOn || changed.imgOff;
  const hlDirty = changed.hlOn || changed.hlOff;

  if (!window.confirm(
    `ส่งรูป ${images.length} ใบที่เลือกไว้เข้า Gemini แล้วให้เขียนจุดเด่นใบละ 1 ข้อไหม\n\n`
    + `· จะได้จุดเด่น ${willGet} ข้อ`
    + (images.length > maxHighlights
        ? ` (เลือกรูป ${images.length} ใบ แต่เก็บจุดเด่นได้สูงสุด ${maxHighlights} ข้อ)\n`
        : " ตามจำนวนรูป\n")
    + (needSave ? "· ชุดรูปที่เพิ่งเลือกจะถูก **บันทึกให้ก่อน** แล้วค่อยส่งเข้า AI\n" : "")
    + `· จุดเด่นชุดเดิม ${draft.highlights.length} ข้อ กับคลังจุดขายเดิม จะถูกแทนที่ทั้งหมด\n`
    + (hlDirty ? "· จุดเด่นที่แก้ค้างไว้จะถูกแทนที่ด้วย เพราะกำลังขอชุดใหม่ทั้งชุด\n" : "")
    + "· ใช้โควตา Gemini 1 ครั้ง และรอราว 15–30 วินาที")) return;

  const done = [];
  aiBusy[job.id] = true;
  delete aiError[job.id];       // เริ่มรอบใหม่ = ล้างคำบ่นรอบเก่า
  paint?.();                    // เปลี่ยนปุ่มเป็นตัวหมุนทันที ไม่ต้องรอวาดรอบถัดไป
  try {
    if (needSave) {
      $("#storyNote").textContent = `💾 บันทึกชุดรูป ${images.length} ใบก่อน…`;
      const saved = await jobPost(`${job.id}/images`, { images });
      done.push(saved.message || "บันทึกชุดรูปแล้ว");
    }
    $("#storyNote").textContent =
      (done.length ? `${done.join(" · ")} · ` : "")
      + `🔎 กำลังให้ AI ดูรูป ${images.length} ใบแล้วเขียนจุดเด่น ${willGet} ข้อ… `
      + "(ราว 15–30 วินาที อย่าเพิ่งปิดหน้า)";
    const result = await jobPost(`${job.id}/features`, { images, model: hlModel });
    // ทิ้งที่พักได้แล้ว — ทั้งชุดรูปและจุดเด่นถูกเขียนลงฝั่งเซิร์ฟเวอร์เรียบร้อย
    delete editDraft[job.id];
    done.push(result.message);
    $("#storyNote").textContent =
      `${done.join(" · ")} · จุดเด่นเดิมคือ: ${result.before.join(" / ") || "—"}`;
  } catch (error) {
    // บอกให้ชัดว่าขั้นไหนผ่านไปแล้ว ไม่ใช่ "ไม่สำเร็จ" ลอยๆ แล้วผู้ใช้กดซ้ำจนรูปซ้อน
    delete editDraft[job.id];
    const why = done.length
      ? `${done.join(" · ")} — แต่ขั้นถัดไปไม่สำเร็จ: ${error.message}`
      : error.message;
    // เขียนสองที่: บรรทัดล่างเหมือนเดิม **และกล่องแดงติดปุ่ม** ซึ่งเป็นที่ที่
    // ผู้ใช้มองอยู่จริง (บรรทัดล่างอยู่นอกกรอบที่เลื่อนอยู่ จึงพลาดได้ง่าย)
    aiError[job.id] = why;
    $("#storyNote").textContent = `คิดจุดเด่นจากรูปไม่สำเร็จ: ${why}`;
  } finally {
    // **ต้องปลดใน finally** ไม่งั้นถ้าล้มกลางทาง ตัวหมุนจะค้างตลอดกาล
    // แล้วปุ่มจะกดไม่ได้อีกเลยจนกว่าจะโหลดหน้าใหม่
    delete aiBusy[job.id];
  }
  await loadJobQueue();
  await showJob(job.id, true);
}

/** กด "ใช้ชุดนี้ ไปต่อ" — บันทึกที่แก้ค้างให้ก่อนเสมอ แล้วค่อยส่งไปขั้นถัดไป
 *
 *  ถ้าปล่อยให้กดไปต่อทั้งที่ยังไม่บันทึก ขั้นถัดไปจะหยิบของเก่าไปใช้ แล้วผู้ใช้
 *  จะเห็นคลิปที่ทำจากรูป/จุดเด่นชุดที่ตัวเองเพิ่งเปลี่ยนทิ้งไป โดยไม่มีอะไรฟ้อง
 */
async function commitDraft(job, draft, action) {
  if (draftDirty(draft) && !(await saveDraft(job, draft))) return;
  await act(() => jobPost(`${job.id}/action`, { action }));
}

/** นับคำในบทพูด — **ต้องได้เลขเดียวกับฝั่งเซิร์ฟเวอร์** (ผู้ใช้สั่ง 26 ส.ค. 2026)
 *
 *  **ห้ามนับตามช่องว่าง** ภาษาไทยไม่เว้นวรรคระหว่างคำ ช่องว่างที่เห็นคือการคั่นวลี
 *  วัดของจริงมาแล้ว: บทพูดที่มี ~40 คำ นับตามช่องว่างได้แค่ 15 → ขึ้นว่า "สั้นไป"
 *  ทั้งที่ยาวเกินเกณฑ์ ถ้าเชื่อเลขนั้นจะไปแก้บทให้ยาวขึ้นอีก
 *
 *  สูตร: อักษรไทยหารด้วยจำนวนอักษรต่อคำ + คำอังกฤษ/ตัวเลขนับตรงๆ
 *  ตัวหาร (`perWord`) **รับมาจากเซิร์ฟเวอร์** ไม่ตั้งเองในหน้าเว็บ — วันหนึ่งเกณฑ์
 *  ฝั่งโน้นเปลี่ยน หน้านี้จะตามเอง ไม่ต้องมาไล่แก้สองที่ให้ตรงกัน
 *
 *  เป็นค่าประมาณ ไม่ใช่ตัวตัดคำจริง — สิ่งที่ต้องรู้คือ "ยาวเกินคลิป 10 วินาทีไหม"
 *  ความละเอียดระดับนี้พอ
 */
const THAI_RE = /[\u0E00-\u0E7F]/g;
const LATIN_WORD_RE = /[A-Za-z0-9][A-Za-z0-9'\u2019-]*/g;

function countWords(text, perWord) {
  const body = Array.isArray(text) ? text.join(" ") : String(text || "");
  const thai = (body.match(THAI_RE) || []).length;
  const latin = (body.match(LATIN_WORD_RE) || []).length;
  return Math.round(thai / (perWord || 5.5)) + latin;
}

/** กล่องพับเก็บได้ (ผู้ใช้สั่ง 26 ส.ค. 2026 — "ทำให้จอตั้งแต่โชว์รุ่นสินค้าจนถึง prompt พับเก็บได้")
 *
 *  หน้าตรวจงานหนึ่งใบยาวมาก — สตอรีบอร์ด 5 ภาพเต็มจอ + บทพูด + คำสั่ง Flow
 *  กว่าจะเลื่อนถึงของที่อยากดูก็ผ่านของที่ไม่ได้ใช้ไปหลายจอ
 *
 *  **ต้องจำว่าพับอะไรไว้** เพราะหน้านี้วาดใหม่เองทุก 6 วินาที ถ้าไม่จำ พอถึงรอบ
 *  วาดใหม่ทุกอย่างจะกางกลับหมด แล้วที่เลื่อนดูอยู่ก็กระโดด — น่ารำคาญกว่าไม่มีปุ่มพับ
 *
 *  จำแยกรายงาน (`${job.id}:${key}`) เพราะคนละสินค้าคนละเรื่อง พับของใบหนึ่งไว้
 *  แล้วอีกใบพับตามด้วยไม่สมเหตุสมผล
 */
const foldOpen = {};

function fold(job, key, title, parts, openDefault = true) {
  const id = `${job.id}:${key}`;
  const box = el("details", { className: "story-fold" },
    el("summary", { className: "story-fold-head", textContent: title }), ...parts);
  box.open = foldOpen[id] ?? openDefault;
  box.addEventListener("toggle", () => { foldOpen[id] = box.open; });
  return box;
}

/** ปุ่มลบภาพสตอรีบอร์ดที่ไม่เอา (ผู้ใช้สั่ง 26 ส.ค. 2026)
 *
 *  **ทำไมถึงมีภาพเกินมา** — ChatGPT สุ่มเอากล่องทดลองของ OpenAI มาแทรก
 *  ("Which image do you like more? / Image 1 is better") แล้ววาดสองแบบมาให้
 *  เทียบกัน ทั้งสองใบเป็นสตอรีบอร์ดเต็มคนละแบบ ไม่ใช่ใบเก่ากับใบใหม่
 *  ตัวโหลดของเราเห็นเป็น "รูปในคำตอบล่าสุด" เหมือนกันทั้งคู่ จึงเก็บมาทั้งคู่
 *  (วัดแล้ว: เกิด 1 ใน 27 งาน · หลักฐานอยู่ใน gpt-storyboard.md ของงานนั้น)
 *
 *  **ปุ่มโผล่เฉพาะตอนมีเกิน 1 ใบ** เหมือนกริดรูปสินค้า — เหลือใบเดียวแล้วลบอีก
 *  จะได้ขั้นตรวจที่ว่างเปล่า ซึ่งแก้อะไรไม่ได้เลย ต้องไปสั่งวาดใหม่แทน
 *  ด่านจริงอยู่ฝั่งเซิร์ฟเวอร์อีกชั้น เผื่อมีคนยิงตรงเข้ามา
 */
function storyboardReview(job, run, meta = {}) {
  const frames = run.storyboard || [];
  const script = run.script || [];
  const shots = frames.map((name, index) => {
    const tools = el("span", { className: "story-cell-tools" });
    tools.append(zoomBtn(clipFile(run.item_id, name), `สตอรีบอร์ดใบที่ ${index + 1}`));
    if (frames.length > 1) {
      tools.append(iconBtn("🗑", "ลบใบนี้ทิ้ง (ย้ายลงถังขยะ กู้ได้)", () => {
        if (!confirm(`ลบสตอรีบอร์ดใบที่ ${index + 1} ทิ้ง?\n\n`
                     + "ไฟล์ย้ายลงถังขยะ กู้คืนได้ที่ storyboard/_trash")) return;
        act(() => jobPost(`${job.id}/storyboard`, { drop: name }));
      }));
    }
    return el("figure", { className: "story-shot" },
      el("img", {
        className: "story-frame", loading: "lazy",
        alt: `สตอรีบอร์ดใบที่ ${index + 1}`,
        src: clipFile(run.item_id, name),
      }), tools);
  });
  if (frames.length > 1) {
    shots.unshift(el("p", { className: "note warn-note", textContent:
      `⚠️ ได้มา ${frames.length} ใบ — ChatGPT แอบวาดสองแบบมาให้เลือก `
      + "ไม่ใช่เราสั่ง เลือกใบที่จะใช้แล้วกด 🗑 ลบใบที่เหลือทิ้ง "
      + "(คำสั่ง Flow กับบทพูดอ้างอิงใบล่างสุดใบเดียว)" }));
  }
  const out = [
    fold(job, "storyboard", `🖼 สตอรีบอร์ด (${frames.length} ภาพ)`, shots),
    approveBlock(job, "storyboard", job.storyboard_ok),
    fold(job, "script", `🗣 บทพูด (${script.length} ฉาก)`, [scriptEditor(job, script, meta)]),
    approveBlock(job, "script", job.script_ok),
  ];
  return out;
}

/** พิมพ์แก้บทพูดได้ทีละฉาก แล้วกดบันทึกทีเดียว (ผู้ใช้สั่ง 26 ส.ค. 2026)
 *
 *  **ไม่บันทึกทุกครั้งที่พิมพ์** ตามที่ผู้ใช้วางไว้ตั้งแต่ฝั่งแชท — แก้ให้ครบก่อน
 *  แล้วกดส่งครั้งเดียว ยิงขึ้นเซิร์ฟเวอร์ทั้งชุดจบในตัวเอง ไม่ทยอยทีละฉาก
 *
 *  **เพิ่ม/ลบฉากไม่ได้** เพราะบทพูดฉากที่ N ผูกกับภาพสตอรีบอร์ดใบที่ N —
 *  ถ้าจำนวนเพี้ยน ฉากจะเลื่อนกันทั้งแถบแล้วคลิปจะพูดคนละเรื่องกับภาพ
 *  ที่นี่จึงมีแต่ช่องพิมพ์ ไม่มีปุ่มเพิ่ม/ลบ และด่านจริงอยู่ฝั่งเซิร์ฟเวอร์อีกชั้น
 */
function scriptEditor(job, original, meta = {}) {
  const box = el("div", { className: "script-edit" });
  const bar = el("div", { className: "inline-row script-bar" });
  let draft = [...original];

  const countChanged = () =>
    draft.reduce((n, text, i) => n + (text !== original[i] ? 1 : 0), 0);

  /* ป้ายนับคำ — เกณฑ์มาจากเซิร์ฟเวอร์ ไม่ได้ตั้งเลขเองในหน้าเว็บ
   *
   *  เกณฑ์คือ **จำนวนคำรวมทั้งคลิป** ไม่ใช่ต่อฉาก เพราะคลิปยาว 10 วินาที
   *  พูดได้เท่านี้ — ยาวกว่านี้เสียงจะล้นคลิป (เป็นเกณฑ์เดียวกับที่สั่ง GPT ตอนเขียน)
   */
  function wordTag() {
    const min = meta.script_min_words;
    const max = meta.script_max_words;
    const total = countWords(draft, meta.thai_chars_per_word);
    if (!min || !max) {
      return el("span", { className: "note", textContent: `รวม ~${total} คำ` });
    }
    const over = total > max;
    const under = total < min;
    const mark = over ? "⚠️" : under ? "⚠️" : "✅";
    const why = over ? `เกินไป ${total - max} คำ — เสียงจะล้นคลิป 10 วินาที`
              : under ? `ยังขาดอีก ${min - total} คำ`
              : "อยู่ในเกณฑ์";
    return el("span", {
      className: `word-tag${over ? " over" : under ? " under" : " ok"}`,
      title: `เกณฑ์ ${min}–${max} คำต่อคลิป (คลิปยาว 10 วินาที) · นับแบบไทยไม่เว้นวรรค`,
      textContent: `${mark} รวม ~${total} คำ / เกณฑ์ ${min}–${max} คำ · ${why}`,
    });
  }

  function paintBar() {
    const now = countChanged();
    const bits = [wordTag()];
    if (!now) {
      bits.push(el("span", { className: "note", textContent:
        "พิมพ์ทับในช่องได้เลย · แก้ครบทุกฉากแล้วค่อยกดบันทึก · กด Esc คืนฉากนั้นเป็นของเดิม" }));
    } else {
      bits.push(
        el("span", { className: "note", textContent: `แก้ไป ${now} ฉาก ยังไม่ได้บันทึก` }),
        textBtn("💾 บันทึกบทพูด", "primary", saveScript),
        textBtn("↩ ทิ้งที่แก้", "ghost", () => { draft = [...original]; paintAll(); }),
      );
    }
    bar.replaceChildren(...bits);
  }

  async function saveScript() {
    if (draft.some((text) => !text.trim())) {
      $("#storyNote").textContent = "มีฉากที่ยังว่างอยู่ — เติมข้อความให้ครบก่อนบันทึก";
      return;
    }
    try {
      const result = await jobPost(`${job.id}/script`, { script: draft });
      $("#storyNote").textContent = result.message;
      await loadJobQueue();
      await showJob(job.id, true);
    } catch (error) {
      $("#storyNote").textContent = `บันทึกบทพูดไม่สำเร็จ: ${error.message}`;
    }
  }

  function paintAll() {
    const rows = el("ol", { className: "story-highlights script-list" });
    draft.forEach((text, index) => {
      const area = el("textarea", {
        className: `script-line${text !== original[index] ? " edited" : ""}`,
        rows: 1, spellcheck: false,
      });
      area.value = text;
      area.title = text !== original[index] ? `ของเดิม: ${original[index]}` : "พิมพ์ทับได้เลย";
      // ยืดช่องให้พอดีข้อความ จะได้เห็นทั้งฉากโดยไม่ต้องเลื่อนอ่าน
      const fit = () => { area.style.height = "auto"; area.style.height = `${area.scrollHeight}px`; };
      area.addEventListener("input", () => {
        draft[index] = area.value;
        fit();
        area.classList.toggle("edited", area.value !== original[index]);
        // ขยับแค่แถบล่าง ไม่วาดใหม่ทั้งก้อน — วาดใหม่ตอนพิมพ์จะทำให้เคอร์เซอร์เด้งไปท้ายช่อง
        paintBar();
      });
      area.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;
        event.preventDefault();
        draft[index] = original[index];
        area.value = original[index];
        area.classList.remove("edited");
        fit();
        paintBar();
      });
      // นับรายฉากด้วย — เกณฑ์เป็นของทั้งคลิป แต่ตอนแก้ทีละฉากต้องรู้ว่าฉากนี้กินไปเท่าไร
      const per = el("small", { className: "word-per" });
      const showPer = () => {
        per.textContent = `~${countWords(draft[index], meta.thai_chars_per_word)} คำ`;
      };
      showPer();
      area.addEventListener("input", showPer);
      area.addEventListener("keydown", (event) => {
        if (event.key === "Escape") window.requestAnimationFrame(showPer);
      });
      rows.append(el("li", {}, area, per));
      window.requestAnimationFrame(fit);
    });
    box.replaceChildren(rows, bar);
    paintBar();
  }

  paintAll();
  return box;
}

/** ผลตรวจคลิป 3 ข้อ — ชัดถึง 1080p ไหม · มีเสียงพูดไหม · ตัวอักษรอ่านออกไหม
 *
 *  **ต้องโชว์คู่กับคลิปเสมอ** ผู้ใช้กดอนุมัติคลิปจากหน้านี้ ถ้าไม่เห็นผลตรวจก็จะ
 *  อนุมัติคลิปที่ตัวอักษรเพี้ยนโดยไม่รู้ตัว แล้วต้องเจนใหม่ = เสียเครดิต Flow 15 หน่วย
 *
 *  ป้ายทั้งหมดมาจากเซิร์ฟเวอร์ (`clip_check.chips()`) ตัวเดียวกับที่ส่งเข้าแชท
 *  **ห้ามตีความผลเองที่นี่** ไม่งั้นแชทกับหน้าเว็บจะบอกผลไม่ตรงกันแล้วไม่รู้ว่าอันไหนจริง
 */
function checkBlock(view) {
  if (!view) return [];
  const out = [];
  // "ยังไม่ได้ตรวจ" กับ "ผลเก่าไม่ตรงกับไฟล์แล้ว" ต้องดังกว่าตัวป้าย เพราะสองอย่างนี้
  // แปลว่ายังไม่มีใครดูคลิปนี้จริง ซึ่งอันตรายกว่าตรวจแล้วไม่ผ่าน
  if (view.note) out.push(el("p", { className: "note warn", textContent: `⚠️ ${view.note}` }));
  if (!view.chips?.length) return out;

  const row = el("div", { className: "check-row" });
  view.chips.forEach((chip) => row.append(
    el("span", { className: `check-chip ${chip.state}`, textContent: chip.text }),
  ));
  out.push(el("p", { className: "bank-title", textContent: "🔍 ผลตรวจคลิป" }), row);
  view.chips.filter((chip) => chip.detail).forEach((chip) => out.push(
    el("p", { className: "note", textContent: `${chip.text} — ${chip.detail}` }),
  ));
  return out;
}

/** เลือกมือถือก่อนลงจริง — **ห้ามเดาว่าจะใช้เครื่องไหน** (กติกา CLAUDE.md ข้อ 8)
 *
 *  "โพสต์ลงบัญชีผิด" กู้คืนไม่ได้ ส่วน "ต้องกดเลือกเครื่องเพิ่มอีกที" เสียแค่เวลา
 *  หนึ่งคลิก จอนี้จึงเป็นจุดยืนยันก่อนลงของจริงไปในตัว
 */
async function askPhoneThenPost(row, itemId) {
  let phones = [];
  try {
    const payload = await api("/api/devices");
    phones = (payload.devices || []).filter(
      (device) => device.enabled && (device.lanes || []).includes("post"));
  } catch (error) {
    $("#storyNote").textContent = `อ่านทะเบียนมือถือไม่ได้: ${error.message}`;
    return;
  }
  if (!phones.length) {
    $("#storyNote").textContent =
      "ยังไม่มีมือถือที่เปิดใช้ในสายโพสต์ — เปิดเครื่องในแท็บมือถือก่อน";
    return;
  }

  let box = document.getElementById("pubPick");
  if (!box) {
    box = el("dialog", { id: "pubPick", className: "img-zoom" });
    box.addEventListener("click", (event) => { if (event.target === box) box.close(); });
    document.body.append(box);
  }
  const rows = phones.map((phone) => {
    const button = textBtn(
      `${phone.ready ? "📱" : "⚠️"} ${phone.label}` + (phone.ready ? "" : " (ไม่ได้เสียบอยู่)"),
      phone.ready ? "primary" : "ghost",
      () => { box.close(); runPublish(row, itemId, phone); },
    );
    return el("div", { className: "pub-pick-row" }, button,
      el("small", { className: "note", textContent: phone.account || "ยังไม่ได้ผูกบัญชี" }));
  });
  box.replaceChildren(
    el("h4", { textContent: `จะลง ${row.name} ด้วยมือถือเครื่องไหน` }),
    el("p", { className: "note warn", textContent:
      "กดแล้วระบบจะแตะจอเครื่องนั้นเองจนโพสต์ขึ้นจริง — ถอนคืนไม่ได้ ต้องไปลบเองในแอป" }),
    ...rows,
    el("div", { className: "img-zoom-bar" }, textBtn("✕ ยกเลิก", "ghost", () => box.close())),
  );
  box.showModal();
}

async function runPublish(row, itemId, phone) {
  $("#storyNote").textContent =
    `กำลังลง ${row.name} บน ${phone.label} — กินเวลาหลายนาที ห้ามแตะจอเครื่องนั้นระหว่างนี้`;
  try {
    const result = await api("/api/publish/flow/run", {
      method: "POST",
      body: JSON.stringify({ serial: phone.serial, target: row.target, item_id: itemId }),
    });
    $("#storyNote").textContent = result.ok
      ? `✅ ลง ${row.name} แล้ว — เดินผังครบ ${result.done}/${result.total} ขั้น`
      : `❌ เดินผังไม่จบ หยุดที่ขั้น ${result.done}/${result.total} — ดูสาเหตุใน Log`;
  } catch (error) {
    // ด่านลำดับปฏิเสธก็มาทางนี้ (409) ต้องโชว์เหตุผลของด่านตรงๆ ไม่ใช่ "ลงไม่สำเร็จ" ลอยๆ
    $("#storyNote").textContent = `ลง ${row.name} ไม่ได้: ${error.message}`;
  }
  await loadJobQueue();
  if (openJobId) await showJob(openJobId, true);
}

/** ลำดับการลง 3 ที่ — Shopee Video → Facebook Reels → TikTok เว้นอย่างน้อย 1 วันปฏิทิน
 *
 *  **หน้าเว็บห้ามคิดกติกาเอง** ทุกแถวมาจาก `publish_order.rows()` ฝั่งเซิร์ฟเวอร์
 *  ซึ่งเป็นตัวเดียวกับด่านที่กั้นก่อนโพสต์จริง ถ้าเขียนแยกกันสองชุด วันหลังจะกลายเป็น
 *  หน้าเว็บบอกว่ากดได้ แต่พอกดจริงด่านปฏิเสธ แล้วไม่มีใครรู้ว่าฝั่งไหนถูก
 */
function publishBlock(rows, itemId) {
  // งานที่ยังไม่มีข้อมูลสินค้า (เพิ่งเข้าคิว) ยังไม่มีอะไรให้ลง — โชว์ไปก็สับสนเปล่า
  if (!rows?.length || !itemId) return [];
  const out = [el("h4", { textContent: "📤 ลำดับการลง" })];
  const list = el("ol", { className: "pub-order" });
  rows.forEach((row) => {
    const line = el("li", { className: `pub-row ${row.status}` });
    line.append(
      el("b", { textContent: row.name }),
      el("small", { className: "pub-mark", textContent: row.mark }),
    );
    if (row.url) {
      line.append(el("a", {
        href: row.url, target: "_blank", rel: "noreferrer", textContent: "เปิดโพสต์ที่ลงไว้",
      }));
    }
    if (row.status !== "posted") {
      // TikTok ยังลงด้วยการเปิดหน้าเว็บบนคอม ไม่ได้กดบนจอมือถือ (ขัดกติกาข้อ 2.7
      // ที่ยังแก้ไม่เสร็จ) จึงยังสั่งจากปุ่มนี้ไม่ได้ — บอกตรงๆ ดีกว่าซ่อนปุ่มไว้
      const noPhone = row.target === "tiktok";
      const button = textBtn(
        "⬆️ ลงเลย", row.can_post && !noPhone ? "primary" : "ghost",
        () => askPhoneThenPost(row, itemId),
      );
      button.disabled = !row.can_post || noPhone;
      button.title = noPhone
        ? "TikTok ยังลงผ่านเบราว์เซอร์บนคอม สั่งจากแชทแทน"
        : (row.can_post ? `ลง ${row.name} เดี๋ยวนี้` : row.why);
      line.append(button);
      if (noPhone) {
        line.append(el("small", { className: "note",
          textContent: "TikTok ยังลงผ่านเบราว์เซอร์บนคอม — สั่งจากแชท" }));
      }
    }
    // **ห้ามซ่อนเหตุผล** ปุ่มจางที่ไม่บอกว่าทำไม แยกไม่ออกจากระบบพัง
    if (!row.can_post) line.append(el("small", { className: "note", textContent: row.why }));
    list.append(line);
  });
  out.push(list);
  return out;
}

/** เครื่องเล่นคลิปของงานนั้น — ใช้ทั้งตอนรอตรวจและตอนเปิดดูย้อนหลัง
 *  เขียนที่เดียวเพื่อให้สองที่นั้นแสดงเหมือนกันเสมอ */
function videoBlock(run, heading = "🎬 คลิปที่เจนได้", view = null) {
  const names = run?.videos || [];
  if (!names.length) return [];
  const out = [el("h4", { textContent: `${heading} (${names.length} ไฟล์)` })];
  names.forEach((name) => {
    const src = clipFile(run.item_id, name);
    out.push(el("video", {
      className: "story-video", controls: true, preload: "metadata", src,
    }));
    // เผื่อ codec ที่เบราว์เซอร์เล่นไม่ได้ ต้องยังเปิด/เซฟไฟล์ตรงๆ ได้
    out.push(el("a", {
      className: "story-video-link", href: src, target: "_blank",
      rel: "noreferrer", textContent: `⬇️ ${name.split("/").pop()}`,
    }));
  });
  out.push(...checkBlock(view));
  return out;
}

function videoReview(job, run, view) {
  const out = videoBlock(run, "🎬 คลิปที่เจนได้", view);
  if (!out.length) out.push(el("h4", { textContent: "🎬 ยังไม่พบไฟล์คลิป" }));
  out.push(el("div", { className: "inline-row" },
    textBtn("✅ อนุมัติคลิป", "primary",
      () => act(() => jobPost(`${job.id}/action`, { action: "vid_ok" })))));
  out.push(regenBox(job));
  return out;
}

/** ลบแล้วเจนใหม่ พร้อมช่องบอกว่าต้องแก้อะไร (ผู้ใช้สั่ง 26 ส.ค. 2026)
 *
 *  "ตรงฟังก์ชั่นลบแล้วเจนใหม่ ให้มีช่องใส่คอมเมนต์ที่ต้องแก้ด้วย
 *   แล้วให้ทำคอมเมนต์นั้นไปปรับแก้"
 *  ลำดับที่ต้องการ: AI ดูคลิป → ดูคอมเมนต์ → ปรับคำสั่ง → เจนใหม่
 *
 *  **ทำไมต้องมี** ปุ่มเดิมลบคลิปแล้วเจนซ้ำด้วยคำสั่งชุดเดิมเป๊ะ ซึ่งได้ของหน้าตา
 *  เดิมกลับมาและเสียเครดิต Flow ฟรี — ขัดกติกาข้อ 3 ของโปรเจกต์ที่ว่า
 *  "retry ต้องเปลี่ยนอะไรบางอย่าง ไม่ใช่ยิงของเดิมซ้ำ"
 *
 *  งานนี้กินเวลาหลายนาที (อัปคลิปขึ้น Gemini + ให้มันดูจนจบ + แก้คำสั่ง)
 *  จึงต้องมีตัวหมุนบอก ไม่งั้นแยกไม่ออกจาก "กดไม่ติด"
 */
function regenBox(job) {
  const box = el("div", { className: "regen-box" });

  const paint = () => {
    if (aiBusy[job.id]) {
      box.replaceChildren(
        el("h4", { textContent: "🔄 ลบแล้วเจนใหม่" }),
        el("span", { className: "ai-wait" },
          el("span", { className: "spinner" }),
          el("span", { textContent: "AI กำลังดูคลิปแล้วแก้คำสั่ง… "
            + "(อัปคลิปขึ้นไปให้ดูใช้เวลาหลายนาที อย่าเพิ่งปิดหน้า)" })),
      );
      return;
    }
    const note = el("textarea", {
      className: "regen-note", rows: 2, spellcheck: false,
      placeholder: "บอกว่าต้องแก้อะไร เช่น “ฉาก 3 ทีวีถูกตัดขอบ” "
                 + "หรือ “ทั้งคลิปมืดไป ให้สว่างขึ้น” (เว้นว่างได้ = เจนซ้ำของเดิม)",
    });
    box.replaceChildren(
      el("h4", { textContent: "🔄 ลบแล้วเจนใหม่" }),
      note,
      el("div", { className: "inline-row" },
        textBtn("🔄 แก้ตามคอมเมนต์แล้วเจนใหม่", "ghost", () => run(note.value))),
      el("p", { className: "note", textContent:
        "AI จะดูคลิปที่ได้จริงก่อน แล้วเอาคอมเมนต์ไปแก้คำสั่งเจนภาพ "
        + "จากนั้นค่อยลบคลิปเดิมแล้วเข้าคิวเจนใหม่ "
        + "— ถ้าแก้คำสั่งไม่สำเร็จจะไม่ลบอะไรเลย" }),
    );
  };

  async function run(note) {
    const text = (note || "").trim();
    if (!text && !window.confirm(
      "ไม่ได้ใส่คอมเมนต์ — จะเจนใหม่ด้วยคำสั่งชุดเดิม\n\n"
      + "คลิปที่ได้จะหน้าตาใกล้เคียงของเดิม และเสียเครดิต Flow อีกรอบ\n"
      + "แน่ใจไหม")) return;

    aiBusy[job.id] = true;
    paint();
    $("#storyNote").textContent = text
      ? "🎬 AI กำลังดูคลิปแล้วแก้คำสั่งตามคอมเมนต์…"
      : "🔄 กำลังลบคลิปเดิมแล้วเข้าคิวเจนใหม่…";
    try {
      const result = await jobPost(`${job.id}/regen`, { note: text });
      const lines = [result.message];
      if (result.why) lines.push(`เหตุผล: ${result.why}`);
      if ((result.problems || []).length) {
        lines.push("AI เห็นปัญหาในคลิป: " + result.problems.join(" · "));
      }
      $("#storyNote").textContent = lines.join(" · ");
    } catch (error) {
      $("#storyNote").textContent = `เจนใหม่ไม่สำเร็จ: ${error.message}`;
    } finally {
      // **ต้องปลดใน finally** ไม่งั้นล้มแล้วตัวหมุนค้างตลอดกาล กดปุ่มไม่ได้อีก
      delete aiBusy[job.id];
    }
    await loadJobQueue();
    await showJob(job.id, true);
  }

  paint();
  return box;
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
  const view = payload.video_check_view || null;
  // ไม่วาดใหม่ถ้าไม่มีอะไรเปลี่ยน — วาดทุก 6 วิจะทำให้ที่เลื่อนดูอยู่กระโดดกลับ
  //
  // ต้องมี `publish_next` กับผลตรวจอยู่ในกุญแจด้วย เพราะสองอย่างนี้เขียนลง run.json
  // ไม่ได้แตะ `updated_at` ของงาน — ลงโพสต์เสร็จแล้วแถวลำดับจะค้างของเก่าถ้าไม่นับ
  const key = [job.id, job.stage, job.updated_at, job.storyboard_ok, job.script_ok,
               payload.publish_next || "", view?.checked, view?.ok, view?.stale].join("|");
  if (!force && key === detailKey) return;
  detailKey = key;

  // ทุกอย่างตั้งแต่ชื่อรุ่นสินค้าลงไปอยู่ในกล่องพับใบเดียว (ผู้ใช้สั่ง 26 ส.ค. 2026)
  // กดที่ชื่อสินค้า = พับเก็บทั้งใบ เหลือแค่บรรทัดเดียว แล้วเลื่อนไปดูงานอื่นได้เร็ว
  // ส่วน "ลำดับการลง 3 ที่" อยู่นอกกล่อง เพราะเป็นแผงที่ต้องกดจริงและสั้นอยู่แล้ว
  const parts = [];
  if (job.error) parts.push(el("p", { className: "note fail", textContent: `❌ ${job.error}` }));

  if (job.stage === "image_review") parts.push(...imageReview(job, run, payload));
  else if (job.stage === "storyboard_review" || job.stage === "script_review") {
    parts.push(...storyboardReview(job, run, payload));
  } else if (job.stage === "video_review") parts.push(...videoReview(job, run, view));
  else if (job.stage === "tiktok_post_review") {
    parts.push(el("p", { className: "note", textContent: "ขั้นยืนยันก่อนโพสต์ TikTok ยังต้องกดในแชท" }));
  } else if (job.open) {
    parts.push(el("p", { className: "note", textContent: "ยังไม่ถึงจุดที่ต้องตัดสินใจ — รอระบบทำต่อ" }));
  }

  parts.push(...runExtras(run, job.stage === "video_review", view, job));

  const head = job.name || job.link || job.id;
  const whole = fold(job, "whole",
    `${head}  —  ${job.stage_label}${job.note ? ` · ${job.note}` : ""}`, parts);

  // **แผงลงโพสต์อยู่บนสุด ไม่ใช่ล่างสุด** (แก้ 26 ส.ค. 2026)
  //
  // ของเดิมอยู่ท้ายสุด ซึ่งเคยพอใช้ได้ตอนทั้งหน้าเลื่อนเป็นก้อนเดียว แต่พอแยกให้
  // แต่ละฝั่งเลื่อนเอง แถบเลื่อนของทั้งหน้าก็หายไป — วัดแล้วปุ่ม "ลงเลย" ตกไปอยู่ที่
  // ระดับ 3,534 พิกเซล ในช่องที่สูงแค่ 900 ผู้ใช้จึงเห็นเป็น "ปุ่มโพสต์ด้านล่างหาย"
  //
  // เอาไว้บนสุดแล้วเห็นทันทีที่เปิดงาน ไม่ต้องเลื่อนผ่านสตอรีบอร์ด 5 ภาพกับคำสั่ง
  // Flow 6 ชุดก่อน และยังพับเก็บได้ถ้าอยากได้ที่ว่างไปดูของอื่น (สูง 310px = 39%
  // ของช่องที่เห็น ใหญ่เกินกว่าจะตรึงค้างไว้ตลอด)
  const pub = publishBlock(payload.publish_order, run.item_id);
  const pubFold = pub.length
    ? [fold(job, "publish", "📤 ลำดับการลง 3 ที่ — กดลงได้จากตรงนี้", pub.slice(1))]
    : [];
  box.replaceChildren(...pubFold, whole);
}

let storyRuns = [];

function storyMarks(run) {
  const marks = [];
  marks.push(run.storyboard_count ? `🖼 ${run.storyboard_count}` : "🖼 —");
  marks.push(run.flow_prompt_count ? `🎥 ${run.flow_prompt_count}` : "🎥 —");
  // มีคลิปแล้วหรือยัง — เห็นจากรายการได้เลยว่าอันไหนกดเข้าไปดูคลิปได้
  if (run.videos?.length) marks.push(`▶️ ${run.videos.length}`);
  if (run.refused) marks.push("⚠️ โดนปฏิเสธ");
  return marks.join(" · ");
}

export async function loadStoryRuns() {
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
    // **กรองตามหัวข้อที่เลือกอยู่** (ผู้ใช้สั่ง 26 ส.ค. 2026)
    //
    // ป้ายขั้นมาจากเซิร์ฟเวอร์ (`run.bucket`) ตัวเดียวกับที่จัดกระดาน
    // ถ้าหน้าเว็บมาเดาเองจากข้อมูลใน run จะกลายเป็นสองสูตรที่วันหลังไม่ตรงกัน
    //
    // งานที่ลงครบสามที่แล้วจะได้ `bucket` เป็นค่าว่าง = ไม่เข้ากองไหน
    // ยังดูได้โดยกดหัวข้อไหนก็ได้แล้วเลื่อนหา — ไม่ได้หายไป แค่ไม่ปนกับของที่ค้าง
    const mine = boardPick
      ? storyRuns.filter((run) => (run.bucket || "") === boardPick)
      : storyRuns;
    const done = storyRuns.length - mine.length;
    $("#storyNote").textContent = boardPick
      ? `${mine.length} ชิ้นในขั้นนี้` + (done ? ` · อีก ${done} ชิ้นอยู่ขั้นอื่น` : "")
      : `${storyRuns.length} ชิ้น`;
    list.replaceChildren(
      ...mine.map((run) => {
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
  parts.push(...runExtras(run, false, run.video_check_view));
  parts.push(...publishBlock(run.publish_order, run.item_id));
  box.replaceChildren(...parts);
}

/** ของที่ดูได้เสมอไม่ว่างานอยู่ขั้นไหน — ลิงก์ แชท GPT และคำสั่ง Flow
 *  ใช้ร่วมกันระหว่างหน้ารายละเอียดของคิว กับรายการงานที่เก็บไว้ */
function runExtras(run, skipVideos = false, view = null, job = null) {
  if (!run || !run.item_id) return [];
  const parts = [];
  // คลิปขึ้นก่อนของอื่น — เป็นผลลัพธ์ที่คนอยากดูที่สุด
  // ข้ามเมื่องานอยู่ขั้นรอตรวจคลิป เพราะตรงนั้นแสดงไปแล้วพร้อมปุ่มอนุมัติ
  if (!skipVideos) parts.push(...videoBlock(run, "▶️ คลิปที่เจนไว้", view));
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
  const promptParts = [];
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
    promptParts.push(el("div", { className: "story-prompt" },
      el("pre", { textContent: prompt }), copy));
  });
  if (promptParts.length && job) {
    parts.push(fold(job, "prompts",
      `⌨ คำสั่งสำหรับ Google Flow (${prompts.length} ชุด)`, promptParts));
  } else if (promptParts.length) {
    parts.push(...promptParts);
  }

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
    // บอกเพดานตั้งแต่ตอนรับลิงก์ — วาง 33 ใบแล้วเห็นขยับ 8 ใบโดยไม่มีคำอธิบาย
    // แยกไม่ออกจาก "ระบบค้าง" (กติกา CLAUDE.md ข้อ 2.7.1)
    $("#storyAddNote").textContent =
      `เข้าคิวแล้ว ${payload.count} งาน · ค้างในคิวทั้งหมด ${payload.waiting} งาน`
      + (payload.load_text ? `\n${payload.load_text}` : "");
    $("#storyAddNote").classList.toggle("warn", !!payload.load?.full);
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

// ============================================ หลักฐานตอนพัง (กติกาข้อ 2.6.1)
//
// ทุกครั้งที่มีอะไรพัง ระบบแคปหน้าจอ + เก็บผังหน้า + บริบทไว้ให้เอง (`evidence.py`)
// **หลักฐานที่เรียกดูยาก เท่ากับไม่ได้เก็บ** — 25 ส.ค. 2026 สายเจนคลิปล้มรวด 13 ใบ
// เดาได้ว่าโดน Shopee บล็อก แต่ไม่มีภาพสักใบ จึงตอบไม่ได้ว่าหน้านั้นเขียนว่าอะไร
// มีปุ่มให้กดไหม บอกให้รอกี่นาที
//
// สร้างทั้งก้อนจาก JS ต่อท้าย #tab-story — **ไม่แตะ index.html** ซึ่งเป็นไฟล์ส่วนกลาง
// (.tab-area เป็น flex column ลูกใหม่จึงไปต่อท้ายเฉยๆ ไม่กระทบผังที่มีอยู่)
let evidenceTag = "";
let evidenceParts = null;

function evidenceBlock() {
  if (evidenceParts) return evidenceParts;
  const tab = $("#tab-story");
  if (!tab) return null;
  const filter = el("div", { className: "inline-row ev-filter" });
  const note = el("p", { className: "note" });
  const list = el("div", { className: "ev-list" });
  const box = el("details", { className: "block ev-block" },
    el("summary", { textContent: "🧾 หลักฐานตอนพัง — ภาพหน้าจอ + บริบท" }),
    el("div", {}, filter, note, list));
  // โหลดตอนกางเท่านั้น — แท็บนี้ถูกวาดใหม่ทุก 6 วินาที ยิงทุกครั้งคือเปลืองเปล่า
  box.addEventListener("toggle", () => { if (box.open) loadEvidence(); });
  tab.append(box);
  evidenceParts = { box, filter, note, list };
  return evidenceParts;
}

function paintEvidenceFilter(tags) {
  const parts = evidenceParts;
  if (!parts) return;
  const buttons = ["", ...tags].map((tag) => {
    const button = textBtn(tag || "ทั้งหมด", "ghost tiny", () => {
      evidenceTag = tag;
      loadEvidence();
    });
    if (tag === evidenceTag) button.classList.add("on");
    return button;
  });
  parts.filter.replaceChildren(...buttons);
}

function evidenceRow(event) {
  const base = `${CLIP_API}/api/evidence/${encodeURIComponent(event.stem)}`;
  const body = el("div", { className: "ev-body" });
  const row = el("details", { className: "ev-item" },
    el("summary", {},
      el("b", { textContent: event.why || event.stem }),
      el("small", { textContent: ` · ${event.when}${event.tag ? ` · ${event.tag}` : ""}` })),
    body);

  row.addEventListener("toggle", () => {
    if (!row.open || row.dataset.loaded) return;
    row.dataset.loaded = "1";        // โหลดครั้งเดียว กางปิดกางอีกไม่ยิงซ้ำ
    if (event.has_shot) {
      // **ไม่ใส่ loading="lazy"** ตรงนี้ — รูปถูกสร้างตอนกดกางรายการนั้นอยู่แล้ว
      // จึงไม่มีอะไรให้ประหยัด แต่กลับเพิ่มโอกาสที่รูปไม่ยอมโหลดเพราะเบราว์เซอร์
      // ตัดสินว่า "ยังไม่ถึงตา" (เจอจริงตอนทดสอบ: ยิงไฟล์ตรงๆ ได้ 200 แต่ <img>
      // ไม่เริ่มโหลดเลย) — หลักฐานที่กดแล้วไม่ขึ้นรูป เท่ากับไม่ได้เก็บ
      const shot = el("img", {
        className: "ev-shot", src: `${base}/png`,
        alt: event.why || "ภาพหน้าจอตอนพัง", title: "กดเพื่อดูเต็มจอ",
      });
      shot.addEventListener("click", () => zoomImage(`${base}/png`, event.why));
      body.append(shot);
    }
    // โชว์เฉพาะไฟล์ที่มีจริง (เซิร์ฟเวอร์บอกมาใน `kinds`) — ลิงก์ที่กดแล้วไม่มีไฟล์
    // ทำให้เข้าใจผิดว่าหลักฐานหาย ทั้งที่ตอนนั้นแคปได้แค่บางอย่าง
    const links = el("div", { className: "inline-row" });
    const label = {
      txt: "📄 บริบท", txt2: "🔤 ข้อความที่อยู่บนจอตอนนั้น",
      html: "🧩 ผังหน้าเว็บ", xml: "📱 ผังหน้าจอมือถือ",
    };
    (event.kinds || []).forEach((kind) => {
      if (!label[kind]) return;
      links.append(el("a", {
        href: `${base}/${kind}`, target: "_blank", rel: "noreferrer",
        textContent: label[kind],
      }));
    });
    if (links.children.length) body.append(links);

    // บริบทเป็นไฟล์ตัวหนังสือสั้นๆ กางให้อ่านตรงนี้เลย ดีกว่าบังคับเปิดแท็บใหม่
    // (ใช้ fetch ตรงๆ ไม่ผ่าน api() เพราะ api() แกะเป็น JSON แต่นี่เป็นข้อความเปล่า)
    if ((event.kinds || []).includes("txt")) {
      fetch(`${base}/txt`)
        .then((response) => (response.ok ? response.text() : ""))
        .then((text) => {
          if (text) body.append(el("pre", { className: "story-raw", textContent: text }));
        })
        .catch(() => { /* อ่านบริบทไม่ได้ไม่ควรทำให้ทั้งรายการพัง */ });
    }
  });
  return row;
}

async function loadEvidence() {
  const parts = evidenceBlock();
  if (!parts || !parts.box.open) return;
  parts.note.textContent = "กำลังโหลด…";
  let payload;
  try {
    payload = await api(`${CLIP_API}/api/evidence?limit=40`
      + (evidenceTag ? `&tag=${encodeURIComponent(evidenceTag)}` : ""));
  } catch (error) {
    parts.note.textContent = `โหลดหลักฐานไม่ได้: ${error.message}`;
    parts.list.replaceChildren();
    return;
  }
  paintEvidenceFilter(payload.tags || []);
  const events = payload.events || [];
  parts.note.textContent = events.length
    ? `ทั้งหมด ${payload.total} เหตุการณ์ · แสดง ${events.length} รายการล่าสุด`
    : "ยังไม่มีหลักฐานในหมวดนี้";
  parts.list.replaceChildren(...events.map(evidenceRow));
}

// เฝ้าคิวเฉพาะตอนเปิดแท็บนี้อยู่ — งานสายคลิปกินเวลาเป็นนาที ไม่ต้องถามถี่
window.setInterval(() => {
  if ($("#tab-story")?.hidden) return;
  loadJobQueue();
  if (openJobId) showJob(openJobId);
}, 6000);

// สร้างกล่องหลักฐานไว้รอตั้งแต่โหลดหน้า (ยังไม่ยิงข้อมูลจนกว่าจะกดกาง)
evidenceBlock();
