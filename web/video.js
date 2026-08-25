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

export async function loadJobQueue() {
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

/** เครื่องเล่นคลิปของงานนั้น — ใช้ทั้งตอนรอตรวจและตอนเปิดดูย้อนหลัง
 *  เขียนที่เดียวเพื่อให้สองที่นั้นแสดงเหมือนกันเสมอ */
function videoBlock(run, heading = "🎬 คลิปที่เจนได้") {
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
  return out;
}

function videoReview(job, run) {
  const out = videoBlock(run, "🎬 คลิปที่เจนได้");
  if (!out.length) out.push(el("h4", { textContent: "🎬 ยังไม่พบไฟล์คลิป" }));
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

  parts.push(...runExtras(run, job.stage === "video_review"));
  box.replaceChildren(...parts);
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
function runExtras(run, skipVideos = false) {
  if (!run || !run.item_id) return [];
  const parts = [];
  // คลิปขึ้นก่อนของอื่น — เป็นผลลัพธ์ที่คนอยากดูที่สุด
  // ข้ามเมื่องานอยู่ขั้นรอตรวจคลิป เพราะตรงนั้นแสดงไปแล้วพร้อมปุ่มอนุมัติ
  if (!skipVideos) parts.push(...videoBlock(run, "▶️ คลิปที่เจนไว้"));
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
