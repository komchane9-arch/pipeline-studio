/* งานฝั่งวิดีโอ: Input ① · GEMS · Release ③ · สตอรีบอร์ด 🎬 */

import { $, CLIP_API, api, config, hooks } from "./core.js";
import { syncLinkLibrary } from "./link-library.js";

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

/* โหมดทำเอง — เจ้าของอัปสตอรีบอร์ดกับคลิปเอง แทนที่จะให้ระบบเจน
 * (สายคลิปส่งสเปคมา 19 ก.ย. 2569 · เจ้าของสั่งเอง)
 *
 * **ทำไมต้องมีที่เก็บแยก แทนที่จะอ่านจากใบงานตรงๆ** — สถานะนี้มีอยู่ที่เดียว
 * คือแถวใน `/api/clips` ส่วน `/api/clips/<id>` ที่การ์ดใบงานใช้เปิด **ไม่มี
 * ฟิลด์ manual เลยสักตัว** (วัดแล้ว 0 จาก 9) และ `/api/board` ก็ไม่มีแถวรายใบ
 * ขอให้สายคลิปเติมไปแล้ว พอเติมมาตัวนี้จะอ่านจากใบงานตรงๆ ได้เลย
 *
 * ค่า `undefined` = **ยังไม่รู้** ซึ่งต้องหน้าตาต่างจาก "รู้แล้วว่ายังไม่ติ๊ก"
 * (ข้อ 2.3.1 ข้อ 4) ไม่งั้นวันที่อ่านไม่ได้ ใบที่ติ๊กไว้จะขึ้นเป็นยังไม่ติ๊ก
 * แล้วเจ้าของกดซ้ำกลายเป็นปิดโหมดทิ้งโดยไม่รู้ตัว */
const manualTick = new Map();
// ข้อความผลล่าสุดต่อใบ — ต้องค้างให้อ่านทัน ไม่ใช่เด้งแล้วหาย
// (บทเรียนฝั่งโพสต์วันนี้: เหตุผลที่เริ่มงานไม่ได้ถูกส่งเป็นข้อความเด้ง
//  ของปุ่ม เจ้าของเลยไม่เห็น แล้วนึกว่าบอทค้าง)
const manualSaid = new Map();
let manualTickAsked = false;

/** สถานะติ๊กของใบนี้ — true/false = รู้แล้ว · undefined = ยังไม่รู้ */
function manualTickOf(run, itemId) {
  // ใบงานมีฟิลด์มาเองเมื่อไร ใช้ของใบงานก่อนเสมอ (สดกว่าที่เราจำไว้)
  if (run && typeof run.manual_ticked === "boolean") return run.manual_ticked;
  return manualTick.get(String(itemId));
}

function rememberManualTicks(rows) {
  (rows || []).forEach((row) => {
    if (row && row.item_id && typeof row.manual_ticked === "boolean") {
      manualTick.set(String(row.item_id), row.manual_ticked);
    }
  });
}

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

/** บรรทัดบอกสถานะคลิปในแถวกระดาน — คืน null ถ้าแถวนั้นยังไม่มีคลิป
 *
 *  **สเปคจากสายคลิป 30 ส.ค. 2569 · เจ้าของสั่งเอง** (กติกาข้อ 7.1.1)
 *  *"เจนเสร็จเอาคลิปทุกคลิปไปใส่ในใบงานด้วยนะ"* — เดิมแถวบอกแค่ชื่อกับขั้น
 *  มองไม่ออกว่าใบไหนมีคลิปแล้ว ต้องเปิดทีละการ์ดจาก **247 ใบ**
 *
 *  ⚠️ **`video_ok = null` ต้องแสดงต่างจาก `false`** (กติกาข้อ 2.3.1)
 *  null = ยังไม่ได้ตรวจ · false = ตรวจแล้วไม่ผ่าน — วาดเหมือนกันเมื่อไร
 *  คลิปที่ยังไม่ได้ตรวจจะดูเหมือนคลิปเสีย (เกิดจริงวันนี้ตอนเครดิต Gemini หมด
 *  ผลตรวจออกมาว่างเปล่าทั้งชุด)
 */
function videoLine(job) {
  const count = job.video_count || 0;
  if (!count && job.clip_state === "generation") {
    return el("small", {
      className: "row-video unknown",
      textContent: "⏳ ของพร้อมแล้ว · รอเจนคลิป",
    });
  }
  if (!count) return null;
  const ok = job.video_ok;
  const mark = ok === true ? "✅" : (ok === false ? "❌" : "⏳");
  const bits = [`🎬 ${count} ไฟล์`];
  if (job.resolution) bits.push(job.resolution);
  bits.push(ok === null || ok === undefined ? `${mark} ยังไม่ได้ตรวจ` : mark);
  const line = el("small", {
    className: `row-video ${ok === false ? "bad" : (ok === true ? "ok" : "unknown")}`,
    textContent: bits.join(" · "),
  });
  // ข้อความจากเซิร์ฟเวอร์เป็นภาษาไทยพร้อมแสดงแล้ว วางได้เลยไม่ต้องแปลง
  if (ok === false && job.video_note) {
    line.append(el("span", { className: "row-video-why", textContent: ` ${job.video_note}` }));
  }
  return line;
}

/** ด่านให้เจ้าของยืนยันว่าสินค้าที่ระบบผูกไว้ตรงกับใบงานจริงไหม
 *
 *  **เจ้าของสั่ง 14 ก.ย. 2569** — *"ขั้นตอนการอ่านและจับคู่ ให้ทำปกติจนเสร็จ
 *  เพิ่มเข้าไปในโชว์เคส แล้วเพิ่มขั้นตอนให้ผมคอนเฟิร์ม โดยใบงาน และหน้าสินค้า
 *  ใน tiktok มาแนบ"*
 *
 *  **เหตุการณ์ที่ทำให้ต้องมี** — 14 ก.ย. TikTok ตีธงใบ 52807075353 ว่าผิด
 *  นโยบาย "โปรโมตสินค้าที่ไม่ตรงกับสินค้าจริง" (ลดการมองเห็น + ลบสินค้าออกจาก
 *  วิดีโอ) เพราะตัวดูรูปตัดสินว่าตรงจาก "เคสกากเพชรลายคิตตี้เหมือนกัน"
 *  ทั้งที่คนละร้าน และชื่อที่อ่านได้คือ "x300 ultra x3oo pro x300 x3oo"
 *  ซึ่งไม่ใช่ชื่อสินค้าด้วยซ้ำ
 *
 *  วางรูปสองฝั่งคู่กันเพราะ **คนจับผิดจากรูปได้เร็วกว่าอ่านชื่อ** และเน้นชื่อ
 *  ทั้งสองฝั่งไว้ให้เทียบง่าย
 */
function tiktokConfirmBox(job) {
  const key = job.item_id || job.id;
  const box = el("div", { className: "tkc" });
  const answered = job.tiktok_confirm_answer;

  const head = el("div", { className: "tkc-head" });
  head.append(el("b", {
    textContent: answered === "ok" ? "✅ ยืนยันแล้วว่าตรง"
      : answered === "no" ? "❌ ตอบว่าไม่ตรง — จะไม่ลงใบนี้"
      : "🔎 ยืนยันก่อนลง TikTok",
  }));
  if (job.tiktok_confirm_at) {
    head.append(el("small", { textContent: `ตอบเมื่อ ${job.tiktok_confirm_at}` }));
  }
  box.append(head);

  // ---- สองฝั่งคู่กัน: ของในใบงาน กับ ของที่เจอใน TikTok ----
  const pair = el("div", { className: "tkc-pair" });
  const side = (title, shot, name, warn) => {
    const col = el("div", { className: "tkc-side" });
    col.append(el("small", { className: "tkc-title", textContent: title }));
    if (shot) {
      const img = document.createElement("img");
      img.alt = title;
      img.src = clipFile(key, shot);
      img.title = "กดเพื่อเปิดรูปเต็ม";
      // ขนาดในกล่องดูได้แค่คร่าวๆ — ตอนจะตัดสินจริงต้องซูมดูฉลากกับรายละเอียด
      img.addEventListener("click", (event) => {
        event.stopPropagation();        // ห้ามทะลุไปเลือกแถวในรายการ
        window.open(img.src, "_blank", "noreferrer");
      });
      col.append(img);
    } else {
      col.append(el("p", { className: "tkc-noshot", textContent: "ไม่มีภาพ" }));
    }
    col.append(el("p", {
      className: "tkc-name" + (warn ? " is-warn" : ""),
      textContent: name || "(อ่านชื่อไม่ได้)",
    }));
    return col;
  };
  pair.append(side("ใบงานของเรา", job.tiktok_link_reference, job.name, false));
  // ใบเก่าที่ผูกไว้ก่อนมีด่านนี้ไม่มีภาพหน้าสินค้า — ถอยไปใช้ภาพผลค้นหา 4 อันดับ
  pair.append(side("สินค้าใน TikTok",
    job.tiktok_product_page_shot || job.tiktok_link_shot,
    job.tiktok_product_name, !job.tiktok_product_name));
  box.append(pair);

  // **อ่านชื่อไม่ได้ = ใบที่เคยโดนตีธงเป็นแบบนี้พอดี** ต้องเตือนให้ชัด
  if (!job.tiktok_product_name) {
    box.append(el("p", { className: "tkc-warn",
      textContent: "⚠️ อ่านชื่อสินค้าจากหน้า TikTok ไม่ได้ — ควรตอบว่าไม่ตรงไว้ก่อน" }));
  }

  const note = el("p", { className: "tkc-note" });
  const bar = el("div", { className: "tkc-buttons" });
  const send = async (body, button, saying) => {
    [...bar.children].forEach((b) => { b.disabled = true; });
    note.textContent = saying;
    note.className = "tkc-note";
    try {
      const out = await api(
        `${CLIP_API}/api/clips/${encodeURIComponent(key)}/tiktok-link/owner-confirm`,
        { method: "POST", body: JSON.stringify(body) });
      note.textContent = out.message || "บันทึกคำตอบแล้ว";
      loadJobQueue();               // ให้กระดานกับรายการอัปเดตตามทันที
    } catch (error) {
      // ตอบไม่สำเร็จต้องบอก **ห้ามทำเหมือนสำเร็จ** ไม่งั้นจะนึกว่ายืนยันไปแล้ว
      note.textContent = `บันทึกไม่ได้ — ${error.message}`;
      note.className = "tkc-note is-bad";
      [...bar.children].forEach((b) => { b.disabled = false; });
    }
  };
  const add = (text, cls, body, saying) => {
    const button = el("button", { type: "button", className: `tkc-btn ${cls}`,
      textContent: text });
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      send(body, button, saying);
    });
    bar.append(button);
  };
  if (answered !== "ok") add("✅ ตรง ลงได้", "is-ok", { ok: true }, "กำลังบันทึกว่าตรง…");
  if (answered !== "no") add("❌ ไม่ตรง", "is-no", { ok: false }, "กำลังบันทึกว่าไม่ตรง…");
  if (answered) add("↩ ยกเลิกคำตอบ", "is-undo", { ok: null }, "กำลังล้างคำตอบ…");
  box.append(bar, note);
  return box;
}

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
  const clip = videoLine(job);
  if (clip) row.append(clip);
  if (job.tiktok_link_status) {
    const pending = job.tiktok_link_status === "pending_review";
    const failed = job.tiktok_link_status === "error";
    const running = job.tiktok_link_status === "running";
    const added = job.tiktok_link_status === "showcase_added";
    const mark = pending ? "⏳" : failed ? "❌" : running ? "🔄" : "✅";
    const label = pending ? "สินค้า TikTok · รอตรวจ (ยังไม่เพิ่มโชว์เคส)"
      : failed ? "เพิ่มสินค้าเข้าโชว์เคส TikTok ไม่สำเร็จ"
      : running ? "กำลังตรวจสินค้า TikTok"
      : added ? `เพิ่มเข้าโชว์เคสแล้ว · อันดับ ${job.tiktok_link_rank || "?"}`
      : `ผลสินค้า TikTok เดิม · อันดับ ${job.tiktok_link_rank || "?"}`;
    row.append(el("small", {
      className: `row-video ${failed ? "bad" : pending || running ? "unknown" : "ok"}`,
      textContent: `${mark} ${label}`,
      title: [job.tiktok_product_name, job.tiktok_link_reason].filter(Boolean).join(" · ") || label,
    }));
  }
  // ---- ด่านให้เจ้าของยืนยันสินค้า TikTok ก่อนลงคลิป -------------------
  if (job.tiktok_confirm_pending || job.tiktok_confirm_answer) {
    row.append(tiktokConfirmBox(job));
  }

  if (job.publish_auto_skip && job.publish_note) {
    row.append(el("small", {
      className: "row-video unknown",
      textContent: `⏭ ${job.publish_note}`,
      title: "ใบงานยังอยู่ในกองนี้ แต่ระบบอัตโนมัติจะข้ามไปทำใบถัดไป",
    }));
  }

  /* **แถวที่ไม่มีรหัสใบงาน — ห้ามโชว์ปุ่มจัดการคิวสักปุ่ม**
   *
   * ตั้งแต่กระดานนับจากไฟล์งานด้วย (ไม่ใช่แค่ใบงานในคิว) จะมีแถวที่ `id` เป็น
   * ค่าว่าง เพราะงานเจนคลิปจบแล้วและใบงานออกจากคิวไป แต่คลิปยังรอลงอยู่
   *
   * ปุ่มจัดการคิวทุกตัวยิงด้วย `id` ทั้งหมด แถวพวกนี้จึงกดแล้วยิงไปที่
   * `/api/jobs//retry` ซึ่งไม่มีทางสำเร็จ — วัดจริง 27 ส.ค. 2569:
   * **19 จาก 23 แถวในกอง Shopee Video โชว์ปุ่ม ↻ กับ 🗑 ที่กดไม่ขึ้นเลย**
   * และ 🗑 อ่านว่า "ลบ" ซึ่งน่ากลัวกว่าที่มันทำได้จริงเสียอีก
   *
   * ปุ่มที่กดไม่ขึ้นแย่กว่าไม่มีปุ่ม — คนกดแล้วไม่เกิดอะไรจะคิดว่าระบบพัง */
  /** รหัสที่ยิงคำสั่งได้เสมอ
   *
   *  **`item_id` มีทุกแถว ส่วน `id` ไม่มี** — ตั้งแต่กระดานนับจากไฟล์งานด้วย
   *  แถวที่งานเจนจบไปแล้วจะไม่มีใบงานในคิวเหลืออยู่ วัดจริง 27 ส.ค. 2569:
   *  **19 จาก 23 แถวในกอง Shopee Video ไม่มี `id`** ซึ่งเป็นกองที่มีของมากที่สุด
   *
   *  ที่อยู่ฝั่งเซิร์ฟเวอร์รับได้ทั้งสองรหัสแล้ว (หาในคิวก่อน ไม่เจอค่อยหาไฟล์งาน)
   *  จึงยิงด้วย `item_id` ได้ตลอด ไม่ต้องแยกปุ่มสองแบบ
   */
  const key = job.item_id || job.id;
  const tools = el("span", { className: "story-queue-tools" });

  /* ---- ปุ่มลงแต่ละปลายทาง ----
   *
   * **รายการมาจาก `can_publish` ของเซิร์ฟเวอร์ ห้ามคิดกติกาลำดับเองฝั่งนี้**
   * เป็นตัวเดียวกับด่านที่กั้นก่อนโพสต์จริง ถ้าเขียนแยกกันสองชุด วันหลังจะกลายเป็น
   * หน้าเว็บบอกว่ากดได้ แต่พอกดจริงด่านปฏิเสธ แล้วไม่มีใครรู้ว่าฝั่งไหนถูก
   *
   * **ปลายทางที่ยังลงไม่ได้ต้องโชว์ด้วย แบบจาง ไม่ใช่ซ่อน** ปุ่มที่หายไปเฉยๆ
   * แยกไม่ออกจาก "ระบบพัง" ส่วนปุ่มจางที่บอกเหตุผลได้ ตอบได้ว่าต้องรออะไร
   * (เหตุผลที่เจอบ่อยคือกติกาเว้น 1 วันระหว่างปลายทาง)
   */
  for (const spot of job.can_publish || []) {
    const mark = String(spot.label || "📤").split(" ")[0];
    if (spot.ok) {
      tools.append(iconBtn(mark, `ลง ${spot.label} — ต้องเลือกเครื่องก่อน`,
        () => askPhoneThenPost({ name: spot.label, target: spot.target }, key)));
    } else {
      // กดแล้วบอกเหตุผล ดีกว่ากดแล้วเงียบ — คนที่กดคือคนที่อยากรู้ว่าทำไมยังไม่ได้
      const blocked = iconBtn(mark, `ยังลง ${spot.label} ไม่ได้ — ${spot.why}`,
        () => { $("#storyNote").textContent = `ยังลง ${spot.label} ไม่ได้ — ${spot.why}`; });
      blocked.classList.add("is-blocked");
      tools.append(blocked);
    }
  }

  if (job.id && job.stage === "queued") {
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
  //
  // **พัก/เอากลับใช้ได้ทุกแถว** ไม่ต้องมีใบงานในคิว เพราะที่อยู่รับรหัสสินค้าแล้ว
  // ของเดิมผูกกับ `job.open` ซึ่งแถวที่มาจากไฟล์งานไม่มีฟิลด์นี้เลย ปุ่มจึงไม่เคยโผล่
  if (job.parked) {
    tools.append(iconBtn("↩", "เอากลับเข้าขั้นเดิม", () =>
      act(() => jobPost(`${key}/unpark`))));
  } else if (!job.running) {
    tools.append(iconBtn("🅿", "พักไว้รอแก้ — เครื่องจะไม่แตะจนกว่าจะเอากลับ", () => {
      const why = window.prompt("พักไว้เพราะอะไร (เว้นว่างได้)") ?? null;
      if (why === null) return;              // กดยกเลิกในกล่อง = ไม่ต้องพัก
      act(() => jobPost(`${key}/park`, { why }));
    }));
  }
  // ยกเลิก/ทำใหม่/ลบ แตะ **ใบงานในคิว** โดยตรง แถวที่ไม่มีใบงานจึงทำไม่ได้
  if (job.id && job.open && !job.running) {
    tools.append(iconBtn("✕", "ยกเลิกงานนี้", () => act(() => jobPost(`${job.id}/cancel`))));
  }
  if (job.id && !job.open) {
    tools.append(
      iconBtn("↻", "สั่งทำใหม่", () => act(() => jobPost(`${job.id}/retry`))),
      iconBtn("🗑", "ลบแถวออกจากคิว (ไฟล์งานไม่หาย)", () => act(() =>
        api(`${CLIP_API}/api/jobs/${encodeURIComponent(job.id)}`, { method: "DELETE" }))),
    );
  }
  row.append(tools);

  row.addEventListener("click", (event) => {
    if (event.target.closest("button")) return;   // กดปุ่มในแถวไม่ใช่กดเลือกแถว
    // **ไม่มีใบงาน = ไม่มีอะไรให้เปิด** เปิดไปจะได้หน้าเปล่าแล้วคนจะคิดว่าพัง
    if (!job.id) {
      $("#storyNote").textContent =
        "คลิปใบนี้เจนจบแล้ว ไม่มีใบงานในคิวให้เปิดดู — กดปุ่มลงหรือปุ่มพักได้เลย";
      return;
    }
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
const PUBLISH_BOARD_KEYS = new Set(["shopee_video", "facebook_reels", "tiktok"]);
let boardPublishProgress = [];
let boardPublishProgressOnline = true;

/** หาชื่อใบงานจาก progress ก่อน แล้วค่อยถอยไปหาในกองทั้งหก
 *
 * งานที่เพิ่งจบอาจถูกย้ายไปกองถัดไปแล้ว จึงห้ามหาเฉพาะกองของปลายทางเดิม.
 */
function publishProgressName(clip) {
  if (clip?.name) return clip.name;
  const id = String(clip?.item_id || "");
  for (const bucket of boardData?.buckets || []) {
    const found = (bucket.jobs || []).find((job) => String(job.item_id || job.id || "") === id);
    if (found?.name) return found.name;
  }
  return "";
}

async function runPublishResume(clip, buttons) {
  const warning = `ให้ใบงาน ${clip.item_id} ทำต่อจากขั้นที่ค้างใช่ไหม?`
    + "\n\nระบบจะตรวจสถานะเดิมก่อน และอาจโพสต์ขึ้นจริงเมื่อเดินถึงขั้นสุดท้าย";
  if (!window.confirm(warning)) return;

  buttons.forEach((button) => { button.disabled = true; });
  $("#storyNote").textContent = `Resume ใบงาน ${clip.item_id} — ห้ามแตะมือถือระหว่างนี้`;
  try {
    const result = await api("/api/publish/flow/run", {
      method: "POST",
      body: JSON.stringify({
        serial: clip.serial,
        target: clip.target,
        item_id: clip.item_id,
        resume: true,
      }),
    });
    $("#storyNote").textContent = result.awaiting_post_approval
      ? `✅ กู้ใบงาน ${clip.item_id} แล้ว — หยุดรอก่อนโพสต์ตามที่ตั้งไว้`
      : (result.ok
        ? `✅ Resume ใบงาน ${clip.item_id} สำเร็จ`
        : `❌ ใบงาน ${clip.item_id} หยุดอีกครั้งที่ ${result.done}/${result.total}`);
  } catch (error) {
    $("#storyNote").textContent = `Resume ใบงาน ${clip.item_id} ไม่ได้: ${error.message}`;
  } finally {
    await loadJobQueue();
    if (openJobId) await showJob(openJobId, true);
  }
}


async function resetPublishStatus(clip, target, buttons) {
  if (!window.confirm(
    `ล้างสถานะ ${target} ให้กลับเป็น “ตอนนี้ว่าง” ใช่ไหม?\n\n`
    + "คำสั่งนี้ไม่เริ่มใบงาน ไม่แตะมือถือ และไม่เปลี่ยนคิวจริง",
  )) return;

  buttons.forEach((button) => { button.disabled = true; });
  $("#storyNote").textContent = `กำลังล้างสถานะ ${target}…`;
  try {
    const result = await api("/api/publish/progress/reset", {
      method: "POST",
      body: JSON.stringify({ target, item_id: clip?.item_id || "" }),
    });
    $("#storyNote").textContent = `✅ ${result.message}`;
  } catch (error) {
    $("#storyNote").textContent = `Reset สถานะไม่ได้: ${error.message}`;
  } finally {
    await loadJobQueue();
    if (openJobId) await showJob(openJobId, true);
  }
}


async function runPublishStop(target, clip, button) {
  // Stop เป็นคำสั่งปลอดภัยและ idempotent: กดตอนว่างก็ต้องปิด auto ได้ จึงไม่ถามซ้ำ
  // และไม่ disable ปุ่มระหว่าง request — ผู้ใช้ต้องกดได้ตลอดตามข้อกำหนด.
  button.setAttribute("aria-busy", "true");
  const item = clip?.item_id ? ` ใบงาน ${clip.item_id}` : "";
  $("#storyNote").textContent = `กำลังสั่ง Stop ${target}${item}…`;
  try {
    const result = await api("/api/publish/stop", {
      method: "POST",
      body: JSON.stringify({ target }),
    });
    $("#storyNote").textContent = `${result.ok ? "⏹" : "⚠️"} ${result.message}`;
  } catch (error) {
    $("#storyNote").textContent = `Stop ไม่สำเร็จ: ${error.message}`;
  } finally {
    button.removeAttribute("aria-busy");
    await loadJobQueue();
    if (openJobId) await showJob(openJobId, true);
  }
}


/** ปุ่มควบคุมอยู่ทุกกล่อง แต่เปิดให้กดเฉพาะงานล่าสุดที่ล้มจริง
 *  ด่านฝั่งเซิร์ฟเวอร์เป็นผู้ตัดสินซ้ำอีกชั้น โดยเฉพาะกรณีแตะ Post ไปแล้ว. */
function appendPublishControls(box, clip, target) {
  const controls = clip?.controls || {};
  const resume = el("button", {
    type: "button", className: "board-live-control is-resume",
    // ป้ายไทยสั้นกว่าและตรงกติกาข้อ 5.2 — "Resume" 8 ตัวอักษรไม่พอในช่อง
    // กว้าง 35px ตอนกระดานมี 7 กอง (วัดจริง 13 ก.ย. 2569 ตกขอบทุกความกว้าง)
    textContent: "▶ ทำต่อ", disabled: !controls.can_resume,
    title: controls.can_resume ? "ทำต่อจากขั้นที่หยุด" : (controls.reason || "ยังไม่มีงานที่ทำต่อได้"),
  });
  const reset = el("button", {
    type: "button", className: "board-live-control is-reset",
    textContent: "↺ รีเซ็ต", disabled: !controls.can_reset,
    title: controls.can_reset
      ? "ล้างสถานะกล่องนี้ให้กลับเป็น ตอนนี้ว่าง — ไม่เริ่มงานและไม่แตะมือถือ"
      : (controls.reason || "ยังไม่มีสถานะที่ล้างได้"),
  });
  const stop = el("button", {
    type: "button", className: "board-live-control is-stop",
    textContent: "■ หยุด", disabled: false,
    title: "หยุดการทำงาน ปิดอัตโนมัติ และคืนใบที่ค้างเป็นคิวที่ 1",
  });
  const buttons = [resume, reset];
  resume.addEventListener("click", (event) => {
    event.stopPropagation();
    runPublishResume(clip, buttons);
  });
  reset.addEventListener("click", (event) => {
    event.stopPropagation();
    resetPublishStatus(clip, target, buttons);
  });
  stop.addEventListener("click", (event) => {
    event.stopPropagation();
    runPublishStop(target, clip, stop);
  });
  if (clip?.status === "failed" && (!controls.can_resume || !controls.can_reset)) {
    box.append(el("small", {
      className: "board-live-control-reason",
      textContent: controls.reason || "จุดนี้ยังทำต่ออัตโนมัติไม่ได้",
    }));
  }
  box.append(el("div", { className: "board-live-actions" }, resume, reset, stop));
}

/** กล่องสดใต้กองโพสต์ — แยก running ออกจากผลล่าสุดให้ชัดเจน
 *
 * แถวแรกของ API คือรายการใหม่สุด แต่ให้ running มาก่อนเสมอ เผื่อรายการที่
 * เพิ่งจบอีกปลายทางมี timestamp ใหม่กว่า จะได้ไม่บังงานที่กำลังแตะมือถือจริง.
 */
function publishLiveBox(bucket) {
  const rows = boardPublishProgress.filter((clip) => clip.target === bucket.key);
  const clip = rows.find((row) => row.status === "running") || rows[0] || null;
  const box = el("div", { className: "board-live" });
  box.dataset.target = bucket.key;
  box.setAttribute("aria-live", "polite");

  if (!boardPublishProgressOnline) {
    box.classList.add("is-error");
    box.append(
      el("b", { className: "board-live-state", textContent: "⚠️ อ่านสถานะไม่ได้" }),
      el("small", { textContent: "งานโพสต์ยังทำต่อได้ตามปกติ" }),
    );
    appendPublishControls(box, null, bucket.key);
    return box;
  }

  if (!clip) {
    box.classList.add("is-idle");
    box.append(
      el("b", { className: "board-live-state", textContent: "⏸ ตอนนี้ว่าง" }),
      el("small", { textContent: "ไม่มีใบงานกำลังทำ" }),
    );
    appendPublishControls(box, null, bucket.key);
    return box;
  }

  const total = Number(clip.total || 0);
  const step = Number(clip.step || 0);
  const running = clip.status === "running";
  const failed = clip.status === "failed";
  const stopped = clip.status === "stopped";
  box.classList.add(running ? "is-running" : ((failed || stopped) ? "is-failed" : "is-done"));
  const state = running ? "🔄 กำลังทำ"
    : (stopped ? "⏹ หยุดแล้ว" : (failed ? "❌ ล่าสุดหยุด" : "✅ ล่าสุดเสร็จ"));
  box.append(
    el("b", { className: "board-live-state",
      textContent: `${state}${total ? ` · ขั้น ${step}/${total}` : ""}` }),
    el("span", { className: "board-live-now", textContent: clip.now || "กำลังเริ่ม…" }),
    el("small", { className: "board-live-id", textContent: `ใบงาน ${clip.item_id || "—"}` }),
  );
  const name = publishProgressName(clip);
  if (name) {
    const item = el("small", { className: "board-live-name", textContent: name });
    item.title = name;
    box.append(item);
  }
  const clock = running ? clip.started : clip.ended;
  if (clock) box.append(el("small", { className: "board-live-time",
    textContent: running ? `เริ่ม ${clock}` : `จบ ${clock}` }));
  appendPublishControls(box, clip, bucket.key);
  return box;
}

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
      const ids = items.map((job) => job.item_id || job.id);
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
  /* **ด่านยืนยันสินค้า TikTok ต้องโผล่ในถังพักด้วย**
   *
   * เจอจริง 14 ก.ย. 2569: เซิร์ฟเวอร์บอกว่ามีใบรอยืนยัน 8 ใบ แต่หน้าเว็บ
   * ขึ้นกล่องให้กดแค่ 4 ใบ — อีก 4 ใบอยู่ในถังพักไว้รอแก้ ซึ่งแถวในถังพัก
   * วาดแค่ชื่อกับปุ่มเอาออกจากพัก **ไม่เคยวาดกล่องยืนยันเลย**
   *
   * ผลคือใบพวกนั้นค้างรอเจ้าของตัดสินโดยที่เจ้าของไม่มีทางกดได้ และมองไม่เห็น
   * ด้วยว่ามีอะไรค้างอยู่ (กติกาข้อ 2.3.1 — ของที่รอคนแต่คนไม่เห็น = รอตลอดไป)
   */
  if (item.tiktok_confirm_pending || item.tiktok_confirm_answer) {
    row.classList.add("has-confirm");
    row.append(tiktokConfirmBox(item));
    row.append(el("small", {
      className: "row-video unknown",
      textContent: "ℹ ตอบได้เลย แต่ใบนี้ยังลงไม่ได้จนกว่าจะเอาออกจากถังพักก่อน",
    }));
  }

  const tools = el("span", { className: "story-queue-tools" });
  // **ต้องใช้ `item_id`** ใบที่งานเจนจบไปแล้วไม่มี `id` — ยิงด้วย `id` จะได้
  // `/api/jobs//unpark` ซึ่งกดแล้วเงียบ (เจอจริงตอนทดสอบ 27 ส.ค. 2569)
  tools.append(iconBtn("↩", `เอากลับเข้าขั้น ${item.from_label}`,
    () => act(() => jobPost(`${item.item_id || item.id}/unpark`))));
  row.append(tools);
  row.addEventListener("click", (event) => {
    if (event.target.closest("button")) return;
    showJob(item.id);
  });
  return row;
}

/** ปุ่มติ๊ก "อนุมัติอัตโนมัติ" เหนือกล่องขั้นตอน
 *
 *  **เจ้าของสั่ง 28 ส.ค. 2569** — *"สร้างปุ่ม bypass ข้างบนแต่ละขั้น … เป็นปุ่ม
 *  ให้ติ้กกด และให้มีสัญลักษณ์บอกว่ากดเปิดหรือปิดอยู่ … approve ไฟล์งานที่รออยู่
 *  ทั้งหมด รวมที่มารอก่อนหน้าด้วย ยกเว้นงานที่กดไว้ว่าพักไว้รอแก้"*
 *
 *  **ทำไมเป็นปุ่มพี่น้องของกล่อง ไม่ใช่ลูกในกล่อง** ปุ่มซ้อนในปุ่มไม่ถูกต้อง
 *  และคลิกจะทะลุไปโดนกล่อง ทำให้กองที่เลือกอยู่เปลี่ยนตามทุกครั้งที่กดสวิตช์
 *
 *  **แยกออกด้วยตาโดยไม่ต้องอ่าน** ใช้สัญลักษณ์ ☑/☐ คู่กับสี ไม่ใช่สีอย่างเดียว
 */
function autoToggle(bucket) {
  const auto = bucket.auto;
  const button = el("button", {
    type: "button",
    className: "board-auto" + (auto.on ? " is-on" : ""),
  });
  button.setAttribute("role", "switch");
  button.setAttribute("aria-checked", auto.on ? "true" : "false");
  /* เลข "พัก" ต้องโผล่ทุกขั้นที่มีของค้าง ไม่ใช่เฉพาะขั้นที่โพสต์ขึ้นจริง
   *
   * ของเดิมใช้ `auto.risk` เป็นตัวตัดสินว่าจะโชว์เลขพักไหม แต่ `risk` แปลว่า
   * "กดแล้วของขึ้นจริง ถอนคืนไม่ได้" ไม่ได้เกี่ยวกับการพักเลย เอาสองเรื่องที่
   * ไม่เกี่ยวกันมาผูกกัน ผลจึงออกมากลับหัว
   *
   * วัดจริง 11 ก.ย. 2569: ขั้นสตอรีบอร์ดพักไว้ **40 ใบ ซึ่งเยอะที่สุดในระบบ**
   * กลับเป็นขั้นที่ตัวเลขไม่โผล่บนจอ ต้องเอาเมาส์ไปชี้ค้างถึงจะเห็น ส่วนขั้นที่
   * พักน้อยกว่ากลับเห็น — และ 40 ใบนั้นคือใบที่ **รอเจ้าของตัดสินใจอยู่**
   * (คลิป 20 วินาทีต้องเจน 2 รอบ เครดิตเป็น 2 เท่า ยังไม่ได้ตัดสินว่าจะทำไหม)
   * ของค้างที่รอคนตัดสินแต่คนไม่เห็น = รอไปเรื่อยๆ โดยไม่มีใครรู้ (กติกาข้อ 2.3.1)
   *
   * คำยังต่างกันตามเดิม เพราะสองขั้นนี้รอคนละเรื่อง
   *   ขั้นที่โพสต์ขึ้นจริง  "พร้อม N"  = พร้อมโพสต์ขึ้นจริงแล้ว
   *   ขั้นอื่น              "รอ N"     = รอกดอนุมัติ
   */
  const paint = (on, waiting, parked = 0) => {
    button.classList.toggle("is-on", on);
    button.setAttribute("aria-checked", on ? "true" : "false");
    const ready = auto.risk
      ? ` · พร้อม ${waiting || 0}`
      : (!on && waiting ? ` · รอ ${waiting}` : "");
    const held = parked ? ` · พัก ${parked}` : "";
    button.textContent = `${on ? "☑" : "☐"} อัตโนมัติ${ready}${held}`;
  };
  paint(auto.on, auto.waiting, auto.parked_skipped);
  button.title = auto.on
    ? `เปิดอยู่ — พร้อมทำ ${auto.waiting || 0} ใบ${auto.parked_skipped ? ` · พักไว้ ${auto.parked_skipped} ใบ` : ""}`
    : `ปิดอยู่ — พร้อมทำ ${auto.waiting || 0} ใบ${auto.parked_skipped ? ` · พักไว้ ${auto.parked_skipped} ใบ` : ""}`;

  button.addEventListener("click", async (event) => {
    // ห้ามทะลุไปโดนกล่อง — ไม่งั้นกดสวิตช์แล้วกองที่เลือกอยู่เปลี่ยนตาม
    event.stopPropagation();
    const next = !button.classList.contains("is-on");
    // เปิดของที่โพสต์จริงต้องถามก่อน ถอนคืนไม่ได้ · ปิดไม่ต้องถาม
    // กองที่มี `risk` = กดแล้ว **โพสต์ขึ้นจริงเอง** ไม่ใช่แค่กดผ่านขั้นตอน
    // (TikTok · Shopee Video · Facebook Reels) ถอนคืนไม่ได้ จึงต้องถามก่อนเปิด
    if (next && auto.risk
        && !window.confirm(`${auto.risk}

เปิดอนุมัติอัตโนมัติของ "${auto.label}" ใช่ไหม?`)) {
      return;
    }
    button.disabled = true;
    paint(next, auto.waiting, auto.parked_skipped); // ขยับให้เห็นทันที แล้วค่อยยืนยันกับเซิร์ฟเวอร์
    try {
      const out = await api(`${CLIP_API}/api/auto-approve`, {
        method: "POST",
        body: JSON.stringify({ step: auto.key, on: next }),
      });
      $("#storyNote").textContent = out.message
        || (next ? `เปิดอนุมัติอัตโนมัติของ "${auto.label}" แล้ว`
                 : `ปิดอนุมัติอัตโนมัติของ "${auto.label}" แล้ว`);
      loadJobQueue();
    } catch (error) {
      // **ดีดกลับ** ห้ามให้ดูเหมือนเปิดแล้วทั้งที่ไม่ได้เปิด (CLAUDE.md ข้อ 2.3)
      paint(!next, auto.waiting, auto.parked_skipped);
      $("#storyNote").textContent = `สั่งไม่สำเร็จ — ${error.message}`;
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

/** ปุ่ม Chrome ใต้กอง — **สองแบบ ไม่ใช่แบบเดียว**
 *
 *  กอง Clip  สวิตช์กาง/หุบแถบเครดิต เพราะบานที่เจนคลิปอยู่ในแถบนั้นอยู่แล้ว
 *  กองอื่น   ปุ่มเปิดตรงๆ เพราะ **ไม่ได้อยู่ในแถบเครดิตเลย**
 *
 *  เจ้าของสั่ง 13 ก.ย. 2569: *"ทำเป็นฟังก์ชั่นเด้งขึ้นมา พอกดดู chrome ค่อยเด้ง
 *  แถบ chrome ขึ้นมา ไม่ต้องโชว์ตลอด"* — ตอนแรกผมเปลี่ยนปุ่มนี้เป็นสวิตช์**ทุกกอง**
 *  ซึ่งทำให้เปิด Chrome ของ Shopee กับ ChatGPT ไม่ได้อีกเลย
 *
 *  ยืนยันจากของจริง 13 ก.ย.: แถบเครดิตมีแต่บัญชี Flow 7 ใบ (komchan*9)
 *  ส่วนสองบานนั้นเป็นคนละโปรไฟล์ ไม่อยู่ในแถบ
 *      ดึง Link (Shopee)     flow_browser_profile3
 *      Storyboard (ChatGPT)  flow_browser_profile
 *  และสองบานนี้แหละคือบานที่ต้องให้คนเข้าไปดูบ่อยที่สุด — Shopee ขึ้นจิ๊กซอว์
 *  ให้เลื่อนซึ่งระบบทำแทนไม่ได้ · ChatGPT หลุดล็อกอินหรือโควตารูปหมด
 *
 *  **ปุ่มชื่อเดียวกันที่ทำคนละอย่างในหน้าเดียวคือกับดัก** จึงตั้งชื่อต่างกันด้วย
 */
function browserViewButton(browser, key, twins = []) {
  // กองนี้เคยชื่อ "clip" — สายคลิปแยกเป็น gen_clip (เจน) กับ check_clip (ตรวจ)
  // เมื่อ 19 ก.ย. 2569 และ **ลบชื่อเดิมทิ้งถาวร** แถบเครดิต Flow เป็นของขั้นเจน
  if (key === "gen_clip") {
    const toggle = el("button", {
      type: "button",
      className: "board-browser" + (chromeOpen ? " is-on" : ""),
      textContent: chromeOpen ? "👁 ซ่อน Chrome" : "👁 ดู Chrome",
      title: chromeOpen
        ? "หุบแถบ Chrome ของสายเจนคลิป"
        : "กางแถบ Chrome ของสายเจนคลิป — ดูเครดิตและเปิดทีละบัญชี",
    });
    toggle.addEventListener("click", (event) => {
      event.stopPropagation();     // ห้ามทะลุไปโดนกล่อง ไม่งั้นกองที่เลือกเปลี่ยนตาม
      setChromeOpen(!chromeOpen);
    });
    return toggle;
  }

  /* **ป้ายต้องบอกว่าเปิดหน้าต่างไหน ไม่ใช่บอกว่า "เปิด Chrome" เฉยๆ**
   *
   * เจอจริง 14 ก.ย. 2569 ตอนสายคลิปเพิ่มกอง Picture: กอง "ดึง Link" กับ
   * "Picture" มีปุ่ม Chrome คนละปุ่ม **แต่เปิดหน้าต่างเดียวกัน** (รูปสินค้า
   * โหลดจาก Shopee ด้วยหน้าต่างเดียวกับตอนดึงลิงก์) ถ้าทั้งคู่เขียนว่า
   * "เปิด Chrome" เหมือนกัน คนกดจะนึกว่ามีสองหน้าต่างให้เลือก แล้วกดสลับ
   * ไปมาโดยไม่รู้ว่าได้ของเดิม
   *
   * เอาชื่อจริงจากเซิร์ฟเวอร์มาใช้ (ตัดคำว่า "Chrome" ออก เพราะมีไอคอนบอกแล้ว
   * และช่องกว้างแค่ 139px) แล้วบอกตรงๆ ในคำอธิบายว่ากองไหนใช้หน้าต่างร่วมกัน
   */
  const short = (browser.label || "").replace(/^Chrome\s*/i, "").trim();
  const shared = twins.filter((name) => name && name !== browser.label);
  const button = el("button", {
    type: "button",
    className: "board-browser",
    textContent: `🖥 ${short || "เปิด Chrome"}`,
    title: `เปิดหรือยก ${browser.label} ขึ้นมาบนจอ`
      + (shared.length ? ` — หน้าต่างเดียวกับ ${shared.join(" · ")}` : ""),
  });
  button.addEventListener("click", async (event) => {
    event.stopPropagation();
    button.disabled = true;
    try {
      const out = await api(`${CLIP_API}/api/browser/show`, {
        method: "POST",
        body: JSON.stringify({ stage: browser.stage }),
      });
      $("#storyNote").textContent = out.message;
    } catch (error) {
      $("#storyNote").textContent = `เปิด ${browser.label} ไม่สำเร็จ — ${error.message}`;
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

/* ====================== 🖥 Chrome ของสายเจนคลิป — เปิดทีละบัญชี + เครดิต
 *
 * เจ้าของสั่ง 11 ก.ย. 2569: *"โชว์ chrome ทุก chrome แล้วผมสามารถกดเข้าได้
 * แต่ละหน้า แต่ละ log in รวมดึงอัพเดตเครดิตไว้ มีปุ่มรีเฟรชคอยอัพเดตเครดิตให้ด้วย"*
 * สเปคมาจากสายคลิป (ฝั่งงาน commit fcbb7a6) ตามขั้นตอนข้อ 7.1.1
 *
 * ## ที่อยู่ที่ใช้ (พอร์ตสายคลิป)
 *   GET  {CLIP_API}/api/flow/chromes            รายชื่อบาน + เครดิต + ใครเปิดอยู่
 *   POST {CLIP_API}/api/browser/show            {profile} → ยกบานนั้นขึ้นหน้าจอ
 *   POST {CLIP_API}/api/flow/credits/refresh    {} ทุกบาน · {profile} บานเดียว
 *
 * ## สามข้อที่ห้ามทำพลาด
 *
 * 1. **เครดิตเป็น `null` ได้ และ `null` ไม่ใช่ 0** — แปลว่า "ยังอ่านไม่ได้"
 *    ถ้าวาดเป็น 0 เจ้าของจะนึกว่าบัญชีนั้นเครดิตหมดแล้วสลับหนีทั้งที่ยังเต็ม
 *    (กติกาข้อ 2.3.1 ข้อ 4 — "ยังไม่ได้ตรวจ" ต้องหน้าตาต่างจาก "ตรวจแล้วได้ศูนย์")
 *
 * 2. **ชื่อโฟลเดอร์กับชื่อบัญชีไม่ตรงกัน** เช่นโฟลเดอร์ komchanc9 เป็นบัญชี
 *    komchand9@gmail.com (ผลจากการซ่อมตอนล็อกอินสลับหน้าต่าง 10 ก.ย.)
 *    **โชว์อีเมลเป็นหลัก** เพราะเป็นสิ่งที่เจ้าของเข้าใจ ส่วนชื่อโฟลเดอร์ใช้ส่งกลับ
 *
 * 3. **ไม่ตั้งตัวดึงเป็นรอบ** เครดิตเปลี่ยนเฉพาะตอนกดปุ่มหรือปิดโครมเท่านั้น
 *    ดึงตอนเปิดแท็บครั้งเดียว แล้วดึงใหม่หลังกดปุ่มก็พอ
 */
let chromeData = null;        // null = ยังไม่เคยดึง (ต่างจาก [] ที่แปลว่าไม่มีบาน)
let chromeBusy = false;       // กำลังอ่านเครดิตอยู่ — กันกดซ้ำ

// กาง/หุบ — ตั้งต้นเป็น "หุบ" ตามที่เจ้าของสั่ง แล้วจำค่าที่เลือกไว้ในเครื่อง
const CHROME_OPEN_KEY = "clipChromeOpen";
let chromeOpen = false;
try { chromeOpen = localStorage.getItem(CHROME_OPEN_KEY) === "1"; } catch { /* โหมดส่วนตัว */ }

function setChromeOpen(open) {
  chromeOpen = Boolean(open);
  try { localStorage.setItem(CHROME_OPEN_KEY, chromeOpen ? "1" : "0"); } catch { /* โหมดส่วนตัว */ }
  // **ดึงข้อมูลตอนกางเท่านั้น** และดึงใหม่ทุกครั้งที่กาง เพราะระหว่างที่หุบอยู่
  // เครดิตหรือบานที่เปิดค้างอาจเปลี่ยนไปแล้ว ของที่ค้างในมือถือเป็นของเก่า
  if (chromeOpen) loadChromes();
  else paintChromes();
  paintBoard();                    // ป้ายบนปุ่มต้องเปลี่ยนตามทันที
}

function chromeBox() {
  let node = $("#clipChromes");
  if (!node) {
    node = el("div", { className: "clip-chromes", id: "clipChromes" });
    boardBox().after(node);
  }
  return node;
}

function chromeCard(row) {
  const card = el("div", {
    className: "cb-card" + (row.running ? " is-on" : ""),
  });
  const open = el("button", { type: "button", className: "cb-open" });
  // อีเมลขึ้นก่อน เพราะเป็นสิ่งที่เจ้าของจำได้ ส่วนชื่อโฟลเดอร์เป็นเรื่องของเครื่อง
  open.append(el("span", { className: "cb-acct",
    textContent: (row.running ? "🟢 " : "") + (row.account || row.label || row.profile) }));

  // **แยก "ยังไม่เคยวัด" ออกจาก "วัดแล้วได้ศูนย์"** สองอย่างนี้ห้ามหน้าตาเหมือนกัน
  const known = typeof row.credits === "number";
  const credit = el("span", {
    className: "cb-credit" + (known ? "" : " is-unknown"),
    textContent: known
      ? `${row.credits} หน่วย${row.stale ? " (เลขเก่า)" : ""}`
      : "ยังไม่เคยวัด",
  });
  open.append(credit);
  if (known) {
    open.append(el("span", { className: "cb-left",
      textContent: `เจนได้อีก ${row.clips_left ?? 0} คลิป` }));
  }
  // เหตุผลที่อ่านเครดิตไม่ได้ — เช่น "บัญชีถูกลงชื่อออกจากโปรไฟล์นี้ ต้องล็อกอิน
  // ใหม่ครั้งเดียว" ซึ่งบอกได้เลยว่าต้องทำอะไร ต่างจากเลขเปล่าๆ ที่บอกแค่ว่าผิด
  //
  // ⚠️ ตรวจแล้ว 13 ก.ย. 2569: `/api/flow/chromes` **ยังไม่ส่ง `note` มา**
  // (flow_credits.rows() ไม่มีคีย์นี้ — `why` มีเฉพาะตอนกดรีเฟรช) เขียนรับไว้
  // ล่วงหน้าให้ ถ้าฝั่งงานใส่มาเมื่อไรก็ขึ้นเอง ไม่มีก็ไม่มีอะไรงอก
  if (row.note) open.append(el("span", { className: "cb-why", textContent: row.note }));
  open.title = `เปิด Chrome ของ ${row.account || row.profile}`
    + (row.note ? ` · ${row.note}` : "")
    + (row.checked_at ? ` · อ่านเครดิตล่าสุด ${row.checked_at}` : "");

  open.addEventListener("click", async () => {
    open.disabled = true;
    const was = open.title;
    try {
      const out = await api(`${CLIP_API}/api/browser/show`, {
        method: "POST",
        body: JSON.stringify({ profile: row.profile }),
      });
      $("#storyNote").textContent = out.message;
      await loadChromes();          // เปิดแล้วสถานะ "กำลังเปิดอยู่" เปลี่ยน ต้องวาดใหม่
    } catch (error) {
      $("#storyNote").textContent = `เปิด Chrome ไม่สำเร็จ — ${error.message}`;
    } finally {
      open.disabled = false;
      open.title = was;
    }
  });

  // ปุ่มอ่านเครดิตเฉพาะบานนี้ — เร็วกว่าไล่ทุกบานหลายเท่า (30-40 วิ เทียบ 2-4 นาที)
  const one = el("button", { type: "button", className: "cb-one",
    textContent: "🔄", title: "อ่านเครดิตเฉพาะบัญชีนี้ (ราว 30-40 วินาที)" });
  one.addEventListener("click", () => refreshCredits(row.profile, one));

  card.append(open, one);
  return card;
}

async function refreshCredits(profile, button) {
  if (chromeBusy) return;         // ยิงซ้อนกันแล้วโครมจะแย่งกันเปิด
  chromeBusy = true;
  const note = $("#storyNote");
  if (note) {
    note.textContent = profile
      ? `กำลังเปิด Chrome อ่านเครดิตของ ${profile}… อาจใช้เวลา 30-40 วินาที`
      : "กำลังเปิด Chrome อ่านเครดิตทีละบาน… อาจใช้เวลา 2-4 นาที";
  }
  chromeBox().classList.add("is-busy");
  if (button) button.disabled = true;
  try {
    const out = await api(`${CLIP_API}/api/flow/credits/refresh`, {
      method: "POST",
      body: JSON.stringify(profile ? { profile } : {}),
    });
    // คำตอบมีชุดใหม่มาแล้ว วาดทับได้เลย ไม่ต้องยิง GET ซ้ำ
    if (out.chromes) chromeData = out;
    if (note) note.textContent = out.message || "อ่านเครดิตเสร็จแล้ว";
  } catch (error) {
    // **ห้ามเขียนให้เข้าใจว่าบัญชีมีปัญหา** อ่านเครดิตไม่ได้ ไม่ได้แปลว่าใช้งานไม่ได้
    if (note) note.textContent = `ดูเครดิตไม่ได้ตอนนี้ — ยังใช้งานบัญชีได้ตามปกติ (${error.message})`;
  } finally {
    chromeBusy = false;
    chromeBox().classList.remove("is-busy");
    if (button) button.disabled = false;
    paintChromes();
  }
}

function paintChromes() {
  const box = chromeBox();
  // หุบอยู่ = ไม่วาดอะไรเลย ไม่ใช่วาดแล้วซ่อนด้วย CSS — ของที่ไม่มีใครดู
  // ไม่ควรอยู่ในหน้า และรูปในนั้นจะได้ไม่ถูกโหลดทิ้ง
  if (!chromeOpen || chromeData === null) { box.replaceChildren(); return; }
  const rows = chromeData.chromes || [];

  const head = el("div", { className: "cb-head" });
  head.append(el("b", { textContent: "Chrome ของสายเจนคลิป" }));
  // รวมเครดิตทั้งหมด — ตัวที่เจ้าของใช้ตัดสินว่าเจนต่อได้อีกกี่ใบ จึงต้องเด่นสุด
  const per = chromeData.credits_per_clip || 0;
  const total = chromeData.credits_total;
  if (typeof total === "number") {
    head.append(el("span", { className: "cb-total",
      textContent: `รวม ${total} หน่วย` + (per ? ` · เจนได้อีกราว ${Math.floor(total / per)} คลิป` : "") }));
  }
  const all = el("button", { type: "button", className: "cb-all",
    textContent: chromeBusy ? "กำลังอ่าน…" : "🔄 อัปเดตเครดิตทุกบัญชี",
    title: "เปิด Chrome ทีละบานเพื่ออ่านเครดิตจริง — ใช้เวลาราว 2-4 นาที" });
  all.disabled = chromeBusy;
  all.addEventListener("click", () => refreshCredits("", all));
  head.append(all);

  const list = el("div", { className: "cb-list" });
  if (!rows.length) {
    list.append(el("p", { className: "cb-empty",
      textContent: "ยังไม่มีโปรไฟล์ Chrome ของสายเจนคลิป" }));
  } else {
    rows.forEach((row) => list.append(chromeCard(row)));
  }

  const parts = [head, list];
  if (chromeData.note) {
    parts.push(el("p", { className: "cb-note", textContent: chromeData.note }));
  }
  box.replaceChildren(...parts);
}

async function loadChromes() {
  try {
    chromeData = await api(`${CLIP_API}/api/flow/chromes`);
  } catch (error) {
    // อ่านรายชื่อไม่ได้ ≠ บัญชีมีปัญหา — เขียนให้ชัดว่าคนละเรื่อง
    chromeData = { chromes: [], note: `ดูเครดิตไม่ได้ตอนนี้ — ยังใช้งานบัญชีได้ตามปกติ (${error.message})` };
  }
  paintChromes();
}

/* ====================== 🎵 Chrome ของ TikTok 7 ช่อง — ซ่อนไว้ กดแล้วค่อยเด้ง
 *
 * เจ้าของสั่ง 13 ก.ย. 2569: *"ตรง tiktok ก็ทำเหมือนกัน เพิ่มตรงดู chrome
 * พอกดดู chrome ค่อยให้มี chrome เด้งขึ้นมา"* — สเปคจากสายคลิป
 * `SPEC-ช่อง-chrome-tiktok.md` (ea2d511) ตามขั้นตอนข้อ 7.1.1
 *
 *   GET  {CLIP_API}/api/tiktok/chromes             ทั้ง 7 ช่อง
 *   POST {CLIP_API}/api/tiktok/chromes/open        {slot} เปิดช่องนั้นไปล็อกอิน
 *   POST {CLIP_API}/api/tiktok/chromes/refresh     {slot} ช่องเดียว · {} ทุกช่อง (76 วิ)
 *
 * ## สี่ข้อที่พลาดง่ายมาก
 *
 * 1. **"ยังไม่ได้ล็อกอิน" ไม่ใช่ความผิดพลาด** เป็นสถานะตั้งต้นปกติของทุกช่อง
 *    ตอนนี้ทั้ง 7 ช่องยังไม่ได้ล็อกอิน ถ้าขึ้นแดงหมดทั้งแผง มันจะกลายเป็น
 *    แถบที่ไม่มีใครสนใจภายในไม่กี่วัน แล้ววันที่พังจริงก็จะไม่มีใครเห็น
 *
 * 2. **"ยังไม่เคยตรวจ" กับ "ตรวจแล้วไม่ผ่าน" ห้ามหน้าตาเหมือนกัน**
 *    (กติกาข้อ 2.3.1 ข้อ 4) — อย่างแรก `checked_at` ว่าง อย่างหลัง `stale` จริง
 *    สองอย่างนี้แก้คนละทาง ถ้าแสดงเหมือนกันจะไล่ผิดทาง
 *
 * 3. **ห้ามทำช่องให้พิมพ์ไอดีเอง** ไอดีต้องมาจากการอ่านหน้า TikTok จริงเท่านั้น
 *    พิมพ์เองได้เมื่อไร วันหนึ่งโปรไฟล์กับไอดีจะไม่ตรงกัน แล้วคลิปขึ้นผิดช่อง
 *    ซึ่ง**ถอนคืนไม่ได้**
 *
 * 4. **ไม่ดึงตอนแถบหุบ** และดึงซ้ำทุก 5 วินาที**เฉพาะตอนมีช่องเปิดค้างอยู่**
 *    เพราะการรู้ว่าหน้าต่างเปิดไหมต้องไล่ดูโปรเซสทั้งเครื่อง
 */
const TIKTOK_OPEN_KEY = "tiktokChromeOpen";
let ttData = null;            // null = ยังไม่เคยดึง · {} ว่าง = ดึงแล้วไม่มีช่อง
let ttBusy = false;
let ttTimer = null;
let ttOpen = false;
try { ttOpen = localStorage.getItem(TIKTOK_OPEN_KEY) === "1"; } catch { /* โหมดส่วนตัว */ }

function ttBox() {
  let node = $("#tiktokChromes");
  if (!node) {
    node = el("div", { className: "clip-chromes", id: "tiktokChromes" });
    chromeBox().after(node);
  }
  return node;
}

function setTiktokOpen(open) {
  ttOpen = Boolean(open);
  try { localStorage.setItem(TIKTOK_OPEN_KEY, ttOpen ? "1" : "0"); } catch { /* โหมดส่วนตัว */ }
  if (ttOpen) loadTiktok();
  else { stopTiktokWatch(); paintTiktok(); }
  paintBoard();
}

/** ปุ่ม "👁 ดู Chrome" ใต้กอง TikTok — กองนี้ไม่มี browser จาก API จึงต้องวางเอง */
function tiktokViewButton() {
  const button = el("button", {
    type: "button",
    className: "board-browser" + (ttOpen ? " is-on" : ""),
    textContent: ttOpen ? "👁 ซ่อน Chrome" : "👁 ดู Chrome",
    title: ttOpen ? "หุบแถบช่อง TikTok" : "กางแถบช่อง TikTok ทั้ง 7 ช่อง",
  });
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    setTiktokOpen(!ttOpen);
  });
  return button;
}

/** ดึงซ้ำเฉพาะตอนมีหน้าต่างเปิดค้าง — เจ้าของปิดหน้าต่างเองได้ตลอดเวลา
 *  ส่วนไอดีเปลี่ยนเฉพาะตอนกดปุ่ม จึงไม่ต้องถามซ้ำถ้าไม่มีอะไรเปิดอยู่ */
function tuneTiktokWatch() {
  const anyOpen = (ttData?.chromes || []).some((row) => row.running);
  if (ttOpen && anyOpen) {
    if (!ttTimer) ttTimer = window.setInterval(loadTiktok, 5000);
  } else {
    stopTiktokWatch();
  }
}

function stopTiktokWatch() {
  if (ttTimer) { window.clearInterval(ttTimer); ttTimer = null; }
}

async function ttSend(path, body, button, saying) {
  if (ttBusy) return;
  ttBusy = true;
  const note = $("#storyNote");
  if (note && saying) note.textContent = saying;
  if (button) button.disabled = true;
  try {
    const out = await api(`${CLIP_API}/api/tiktok/chromes/${path}`, {
      method: "POST", body: JSON.stringify(body || {}),
    });
    // **เอา message มาแสดงตรงๆ ห้ามย่อ** มันบอกวิธีทำงานทั้งรอบให้เจ้าของ
    if (note && out.message) note.textContent = out.message;
    if (out.chromes) ttData = out;
  } catch (error) {
    if (note) note.textContent = error.message;
  } finally {
    ttBusy = false;
    if (button) button.disabled = false;
    await loadTiktok();
  }
}

function ttCard(row) {
  const card = el("div", { className: "cb-card tt-card" + (row.running ? " is-on" : "") });
  const main = el("button", { type: "button", className: "cb-open" });
  main.append(el("span", { className: "cb-acct",
    textContent: `ช่อง ${row.slot}` + (row.running ? " · เปิดอยู่" : "") }));

  // สี่สถานะ แยกกันชัดเจนตามตารางในสเปค — **ห้ามยุบรวม**
  if (row.handle) {
    main.append(el("span", { className: "cb-credit", textContent: row.handle }));
    if (row.stale) {
      main.append(el("span", { className: "cb-why",
        textContent: `ตรวจรอบล่าสุดไม่ผ่าน — ${row.note || "ไม่ทราบสาเหตุ"}` }));
    } else if (row.checked_at) {
      main.append(el("span", { className: "cb-left", textContent: `ตรวจล่าสุด ${row.checked_at}` }));
    }
  } else if (!row.checked_at) {
    // ยังไม่เคยไปอ่านเลย — คนละเรื่องกับอ่านแล้วไม่เจอ
    main.append(el("span", { className: "cb-credit is-unknown", textContent: "— ยังไม่ได้ล็อกอิน —" }));
  } else {
    main.append(el("span", { className: "cb-credit is-unknown", textContent: "ยังอ่านไอดีไม่ได้" }));
    if (row.note) main.append(el("span", { className: "cb-why", textContent: row.note }));
  }

  main.title = row.running
    ? `ยกหน้าต่างช่อง ${row.slot} ขึ้นมา`
    : `เปิด Chrome ช่อง ${row.slot} เพื่อล็อกอิน TikTok`;
  main.addEventListener("click", () => ttSend("open", { slot: row.slot }, main,
    row.running ? `กำลังยกหน้าต่างช่อง ${row.slot} ขึ้นมา…` : `กำลังเปิด Chrome ช่อง ${row.slot}…`));

  const one = el("button", { type: "button", className: "cb-one",
    textContent: "🔄", title: `อ่านไอดีของช่อง ${row.slot} ใหม่` });
  one.addEventListener("click", () => ttSend("refresh", { slot: row.slot }, one,
    `กำลังอ่านไอดีช่อง ${row.slot}…`));

  card.append(main, one);
  return card;
}

function paintTiktok() {
  const box = ttBox();
  if (!ttOpen || ttData === null) { box.replaceChildren(); return; }

  // ยิงไม่ถึงเซิร์ฟเวอร์ — **ห้ามขึ้นว่า 0 ช่อง** เพราะ 7 ช่องยังอยู่ครบ
  // แค่เราอ่านไม่ได้ (กติกาข้อ 2.3.1 — "ตรวจไม่ได้" ไม่ใช่ "ตรวจแล้วว่าง")
  if (ttData.unreachable) {
    box.replaceChildren(el("p", { className: "cb-note",
      textContent: `ยังอ่านสถานะช่อง Chrome ไม่ได้ — ${ttData.unreachable}` }));
    return;
  }

  const rows = ttData.chromes || [];
  const head = el("div", { className: "cb-head" });
  head.append(el("b", { textContent: "ช่อง TikTok" }));
  const ready = rows.filter((r) => r.ready).length;
  head.append(el("span", { className: ready ? "cb-total" : "cb-total is-none",
    textContent: `ล็อกอินแล้ว ${ready} จาก ${rows.length || 7} ช่อง` }));
  const all = el("button", { type: "button", className: "cb-all",
    textContent: ttBusy ? "กำลังอ่าน…" : "🔄 อ่านไอดีทุกช่อง",
    title: "เปิดทีละช่องเพื่ออ่านไอดีจริง — ใช้เวลาราว 76 วินาที" });
  all.disabled = ttBusy;
  all.addEventListener("click", () => ttSend("refresh", {}, all,
    "กำลังไล่อ่านไอดีทีละช่อง… ใช้เวลาราว 76 วินาที"));
  head.append(all);

  const list = el("div", { className: "cb-list" });
  if (!rows.length) list.append(el("p", { className: "cb-empty", textContent: "ยังไม่มีช่อง TikTok ในระบบ" }));
  else rows.forEach((row) => list.append(ttCard(row)));

  const parts = [head, list];
  if (ttData.note) parts.push(el("p", { className: "cb-note", textContent: ttData.note }));
  box.replaceChildren(...parts);
}

async function loadTiktok() {
  try {
    ttData = await api(`${CLIP_API}/api/tiktok/chromes`);
  } catch (error) {
    ttData = { unreachable: error.message };
  }
  paintTiktok();
  tuneTiktokWatch();
}

/** โควตาโพสต์ใต้กล่อง — "โพสต์วันนี้ 1/70"
 *
 *  ⚠️ **ต้องมีคำว่า "โพสต์วันนี้" กำกับเสมอ** เพราะตัวเลขในวงเล็บบนกล่อง
 *  `(1/10)` แปลว่า "งานค้าง 1 จากสต๊อกที่อยากมี 10" ซึ่ง**คนละเรื่องกันสิ้นเชิง**
 *  วางเลขลอยๆ สองชุดติดกันคือเชิญให้อ่านสลับกัน
 */
function quotaLine(bucket) {
  const quota = bucket.quota;
  const node = el("span", {
    className: "board-quota" + (quota.full ? " is-full" : ""),
    textContent: `โพสต์วันนี้ ${quota.text || `${quota.used}/${quota.limit}`}`,
  });
  node.title = quota.full
    ? `ครบโควตาวันนี้แล้ว (${quota.limit}) — ลงเพิ่มไม่ได้จนกว่าจะขึ้นวันใหม่`
    : `ลงได้อีก ${quota.left} คลิปวันนี้`;
  return node;
}

function paintBoard() {
  const box = boardBox();
  const list = $("#storyQueueList");
  if (!boardData) { box.replaceChildren(); return; }

  /* **ไม่ดึงรายชื่อ Chrome ทุกรอบที่นี่** — paintBoard ถูกเรียกทุก 6 วินาที
   * และแถบตั้งต้นเป็นหุบ ดึงเฉพาะตอนคนกดกาง (ดู setChromeOpen)
   *
   * แต่ต้องดึง **หนึ่งครั้ง** ถ้าคราวก่อนปิดหน้าไปตอนแถบกางค้างอยู่
   *
   * เจอจริงตอนเทส 13 ก.ย. 2569: กางแถบไว้แล้วรีเฟรชหน้า → ปุ่มขึ้นว่า
   * "ซ่อน Chrome" (อ่านค่าที่จำไว้ถูก) **แต่แถบว่างเปล่า** เพราะไม่มีใคร
   * สั่งวาด — ป้ายบอกสถานะขัดกับของจริงบนจอ ซึ่งผิดกติกาข้อ 2.3.1
   */
  if (chromeOpen && chromeData === null) loadChromes();
  if (ttOpen && ttData === null) loadTiktok();
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
      // เดิมกอง "clip" กองเดียวโชว์สองตัวเลข "(n เจน/n ตรวจ)" เพราะสองขั้นอยู่
      // รวมกัน ตอนนี้แยกเป็นคนละกองแล้ว แต่ละกองจึงนับของตัวเองตามปกติ
      el("span", { className: "board-count",
                   textContent: (bucket.target ?? 10)
                     ? `(${bucket.count}/${bucket.target ?? 10})`
                     : `(${bucket.count})` }),
    );
    if (bucket.short) button.classList.add("is-short");
    // ห่อเป็นช่องเดียวกัน: สวิตช์อยู่บน · กล่องอยู่กลาง · โควตาอยู่ล่าง
    //
    // **วาดตามที่ API ส่งมา ไม่ตัดสินจากชื่อกอง** — `auto: null` = กองนั้นยังไม่มี
    // ขั้นอนุมัติอัตโนมัติ · `quota: null` = ไม่มีโควตา ห้ามวาด x/70
    //
    // ⚠️ **อย่าฝังรายชื่อกองไว้ในโค้ดนี้** ตอนแรกสเปคบอกว่า Shopee Video กับ
    // Facebook Reels "ไม่มีขั้นอนุมัติ" แล้วเจ้าของสั่งกลับในวันเดียวกันว่า
    // *"shopee กับ facebook reels ทำโพสต์อัตโนมัติด้วยนะ"* — ถ้าตอนนั้นเขียน
    // ชื่อกองไว้ตายตัว จะต้องมาไล่แก้หน้าเว็บอีกรอบ
    // เขียนแบบอ่านจาก API ตั้งแต่แรก พอเซิร์ฟเวอร์ใส่ `auto` ให้ ปุ่มก็ขึ้นเอง
    const cell = el("div", { className: "board-cell" });
    if (bucket.auto) cell.append(autoToggle(bucket));
    cell.append(button);
    if (bucket.browser) {
      // กองอื่นที่เปิดหน้าต่างเดียวกัน — เอาไปบอกในคำอธิบายของปุ่ม
      const twins = buckets
        .filter((other) => other.browser
          && other.key !== bucket.key
          && other.browser.stage === bucket.browser.stage)
        .map((other) => other.browser.label);
      cell.append(browserViewButton(bucket.browser, bucket.key, twins));
    }
    // กอง TikTok ไม่มี browser มาจาก API (เป็นคนละชุดโปรไฟล์กับสายเจนคลิป)
    // จึงต้องวางปุ่มเอง — ผูกกับรหัสกอง ไม่ใช่ลำดับ สลับลำดับแล้วยังถูก
    if (bucket.key === "tiktok") cell.append(tiktokViewButton());
    if (bucket.quota) cell.append(quotaLine(bucket));
    if (PUBLISH_BOARD_KEYS.has(bucket.key)) cell.append(publishLiveBox(bucket));
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
    return cell;
  }));

  syncLinkLibrary(box, boardPick === "link", () => loadJobQueue());
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
  // เดิมมีข้อความพิเศษของกอง "clip" ที่กางสองตัวเลขให้ดู — ไม่ต้องแล้ว
  // เพราะแยกเป็นกอง gen_clip กับ check_clip ซึ่งใช้ข้อความมาตรฐานได้ตรงกว่า
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

  /** วาดแถว — **ต้องรวมสองแหล่ง ไม่ใช่เลือกอันใดอันหนึ่ง**
   *
   *  ใบงานในคิว (`/api/jobs`) มี `open` · `running` · `error` ที่กระดานไม่มี
   *  ส่วนแถวบนกระดาน (`/api/board`) มี `can_publish` · `item_id` ที่คิวไม่มี
   *
   *  ของเดิมเขียนว่า "ถ้ามีใบเต็มให้ใช้ใบเต็ม" ซึ่ง **ทิ้ง `can_publish` ทั้งก้อน**
   *  วัดจริง 27 ส.ค. 2569: กอง Shopee Video 23 แถว — 19 แถวที่ไม่มีใบงานในคิว
   *  ได้ปุ่มลงครบ ส่วน **4 แถวที่มีใบงานกลับไม่ได้ปุ่มเลยสักปุ่ม**
   *  ซึ่งกลับหัวกลับหางจากที่ควรเป็น (แถวที่ข้อมูลครบกว่าได้ปุ่มน้อยกว่า)
   *
   *  ให้ค่าจากกระดานทับ เพราะกระดานคือแหล่งของกติกาลำดับการลง
   */
  const draw = (jobs) => (jobs || []).map((row) => {
    const full = row.id ? jobCards.find((j) => j.id === row.id) : null;
    return jobRow(full ? { ...full, ...row } : row);
  });

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

/* **รอบเก่ายังไม่กลับ ห้ามยิงรอบใหม่** (19 ก.ย. 2569)
 *
 * ตัวจับเวลาข้างล่างเรียกทุก 6 วินาที ส่วนตัวนี้ยิง `/api/board` ซึ่งวัดจริง
 * แล้วใช้ **22 วินาที** ต่อรอบแม้ตอนไม่มีใครกวน คำขอจึงกองทับกันเรื่อยๆ
 * แล้วยิ่งกองยิ่งช้า กลายเป็นวงจรที่ซ้ำเติมตัวเอง
 *
 * วัดจริงบนเซิร์ฟเวอร์สายคลิปตัวเดียวกัน
 *
 *     ขณะหน้าเว็บยิงทุก 6 วิ     หลังหยุดยิง
 *     /api/board   เกิน 120 วิ       22.0 วิ
 *     /api/jobs         64.3 วิ        5.6 วิ
 *     /api/clips         9.3 วิ        1.6 วิ
 *
 * ช้าขึ้น 6–11 เท่าเพราะการทับกันล้วนๆ **ตัวที่อยู่ช้า 22 วินาทีเป็นคนละเรื่อง
 * และยังต้องแก้ที่ฝั่งสายคลิป** — ตัวกันนี้แค่ทำให้ของช้าไม่ขยายตัวเอง
 * ไม่ได้ทำให้มันเร็วขึ้น อย่าเข้าใจผิดว่าแก้จบแล้ว
 */
let queueBusy = false;

export async function loadJobQueue() {
  const list = $("#storyQueueList");
  if (!list) return;
  if (queueBusy) return;          // รอบก่อนยังไม่กลับ — ข้ามรอบนี้ไปเลย
  queueBusy = true;
  try {
    return await loadJobQueueOnce(list);
  } finally {
    queueBusy = false;
  }
}

async function loadJobQueueOnce(list) {
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
  const [boardResult, progressResult] = await Promise.allSettled([
    api(`${CLIP_API}/api/board`),
    api("/api/publish/progress"),
  ]);
  if (boardResult.status === "rejected") {
    const error = boardResult.reason;
    boardData = null;
    // **ต้องบอกทางออกด้วย** ข้อความที่บอกแค่ว่าพังทำให้ผู้ใช้ได้แต่นั่งดู
    boardBox().replaceChildren(el("p", { className: "note",
      textContent: `โหลดกระดานไม่สำเร็จ: ${error.message}`
        + " — กด 🔄 โหลดใหม่ หรือดูใน Telegram ด้วย /wait" }));
    list.replaceChildren(...open.map(jobRow));
    return;
  }
  boardData = boardResult.value;
  if (progressResult.status === "fulfilled") {
    boardPublishProgress = progressResult.value.clips || [];
    boardPublishProgressOnline = true;
  } else {
    boardPublishProgress = [];
    boardPublishProgressOnline = false;
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
/** ปุ่มติ๊ก "ทำเอง" — วางคู่ปุ่ม "ใช้ชุดรูปนี้ ไปต่อ" เพราะเป็นจุดตัดสินใจเดียวกัน
 *  จะให้เครื่องทำต่อ หรือจะอัปสตอรีบอร์ดกับคลิปเอง
 *
 *  **ต้องกดได้ตั้งแต่ใบงานมีรูปแล้ว ไม่ต้องรออนุมัติรูปก่อน** เจ้าของสั่งไว้ชัด
 *  (*"ตอนดึงรูปเสร็จแล้วขึ้นเป็นใบงานโชว์รูปและรายละเอียดสินค้า
 *  ยังไม่ต้องมีการอนุมัติ"*) การ์ดนี้โผล่ตั้งแต่ขั้น image_review อยู่แล้ว
 *  จึงวางตรงนี้ได้พอดี
 */
function manualTickButton(itemId, paint, run = null) {
  const state = manualTickOf(run, itemId);
  const box = el("label", { className: "manual-tick" });
  const tick = el("input", { type: "checkbox" });
  tick.checked = state === true;
  // ยังไม่รู้สถานะ = ห้ามให้หน้าตาเหมือน "รู้แล้วว่ายังไม่ติ๊ก"
  tick.indeterminate = state === undefined;
  tick.disabled = state === undefined;
  const word = el("span", { textContent: state === undefined
    ? "ทำเอง — กำลังอ่านสถานะ…"
    : "ทำเอง (อัปสตอรีบอร์ด + คลิปเอง)" });
  box.append(tick, word);
  if (state === undefined) {
    box.classList.add("is-unknown");
    // ดึงรายการ**ครั้งเดียว**ต่อการโหลดหน้า แล้ววาดใหม่ — รายการหนัก 8 MB
    // ยิงซ้ำทุกการ์ดจะกลายเป็นถล่มเซิร์ฟเวอร์สายคลิปเอง
    if (!manualTickAsked) {
      manualTickAsked = true;
      loadStoryRuns().then(paint).catch(() => { manualTickAsked = false; });
    }
    return box;
  }
  tick.addEventListener("change", async () => {
    const want = tick.checked;
    tick.disabled = true;
    word.textContent = want ? "กำลังเข้าโหมดทำเอง…" : "กำลังออกจากโหมดทำเอง…";
    try {
      const reply = await api(`${CLIP_API}/api/clips/${encodeURIComponent(itemId)}/manual`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ on: want }),
      });
      // อ่าน `on` จากผลตอบตรงๆ ไม่คิดสถานะอื่นเอง — ค่าที่ต้องคำนวณ
      // (พร้อมกดเสร็จไหม · ค้างตรงไหน) ปล่อยให้รอบโหลดรายการเอามาให้
      const on = reply?.manual?.on === true;
      manualTick.set(String(itemId), on);
      manualSaid.set(String(itemId), { text: reply?.message || "", bad: false });
    } catch (error) {
      // ข้อความไทยมาจากเซิร์ฟเวอร์อยู่แล้ว แสดงตรงๆ ไม่ต้องแปลเอง
      manualSaid.set(String(itemId), {
        text: `ติ๊กไม่สำเร็จ: ${error.message}`, bad: true });
    }
    paint();
  });
  return box;
}

function imageReview(job, run, meta) {
  const draft = draftFor(job, run);
  const box = el("div", { className: "img-review" });
  const paint = () => box.replaceChildren(...imageReviewParts(job, meta, draft, paint, run));
  paint();
  return [box];
}

function imageReviewParts(job, meta, draft, paint, run = null) {
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
            () => commitDraft(job, draft, "img_ok")),
    manualTickButton(itemId, paint, run)));
  const said = manualSaid.get(String(itemId));
  if (said?.text) {
    out.push(el("p", { className: `note${said.bad ? " fail" : ""}`,
                       textContent: said.text }));
  }

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

/** สตอรีบอร์ดที่เก็บไว้ของงานซึ่งออกจากขั้นตรวจแล้ว — แสดงอย่างเดียว
 *
 * งานที่ Flow ปิดจะจบคิวเป็น `done` ทั้งที่ยังรอเจนคลิปอยู่ หน้าเดิมวาดภาพ
 * เฉพาะ `storyboard_review`/`script_review` จึงดูเหมือนไม่มี Storyboard ทั้งที่
 * ไฟล์อยู่ครบ ห้ามใช้ `storyboardReview()` ตรงนี้เพราะจะพาปุ่มอนุมัติ/ลบภาพ
 * กลับมาในงานที่ผ่านขั้นนั้นแล้ว.
 */
function storedStoryboard(job, run) {
  const frames = run.storyboard || [];
  if (!frames.length) return null;
  const shots = frames.map((name, index) => el("figure", { className: "story-shot" },
    el("img", {
      className: "story-frame", loading: "lazy",
      alt: `สตอรีบอร์ดใบที่ ${index + 1}`,
      src: clipFile(run.item_id, name),
    }),
    el("span", { className: "story-cell-tools" },
      zoomBtn(clipFile(run.item_id, name), `สตอรีบอร์ดใบที่ ${index + 1}`)),
  ));
  return fold(job, "stored-storyboard", `🖼 สตอรีบอร์ดที่ใช้เจน (${frames.length} ภาพ)`, shots);
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

  /* ---- ประโยคปกติสำหรับให้คนอ่าน (สเปคสายคลิป 9 ก.ย. 2569) --------------
   *
   * เจ้าของสั่ง: "หน้าที่โชว์ผมให้เขียนมาเป็นประโยคปกติ" — ขีดคั่นพยางค์
   * มีไว้ให้ตัวอ่านเสียงของ Veo อ่านคำไทยถูก **ไม่ได้มีไว้ให้คนอ่าน**
   *
   *     ส่ง Flow  ฝน-หนัก ก็-เปิด-ไฟ-ได้-นะ
   *     โชว์      ฝนหนัก ก็เปิดไฟได้นะ
   *
   * **ช่องพิมพ์ยังเป็นแบบมีขีดเหมือนเดิม ห้ามเปลี่ยน** เพราะที่อยู่บันทึก
   * ยังรับเฉพาะแบบมีขีด ถ้าส่งประโยคปกติเข้าไป เสียงจะอ่านคำไทยผิด
   * (เคยเจอ 11 ใบ — "ทำงาน" อ่านเป็น "ทวาร") สายคลิปกำลังทำฝั่งรับค่า
   * ประโยคปกติแล้วให้ ChatGPT ใส่ขีดกลับให้ เสร็จแล้วค่อยสลับช่องพิมพ์
   *
   * `script_show` อยู่ **ชั้นบนสุด** ของคำตอบ ไม่ได้อยู่ใน `run`
   */
  const plainAll = Array.isArray(meta.script_show) ? meta.script_show : [];
  // จำนวนฉากต้องเท่ากันเป๊ะ ไม่งั้นบรรทัดจะเลื่อนกันแล้วอ่านผิดฉาก
  // — ไม่เท่ากันให้ทิ้งไปเลย ดีกว่าโชว์ของที่จับคู่ผิด (กติกาข้อ 2.3.1)
  const plainOk = plainAll.length === original.length;
  const plainMismatch = plainAll.length > 0 && !plainOk;

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
      // ประโยคปกติวางไว้ **บนช่องพิมพ์** เพราะเป็นตัวที่คนอ่านตรวจ
      // ส่วนช่องพิมพ์แบบมีขีดคือของที่ส่งเข้า Flow — ให้เห็นคู่กันไปเลย
      // จะได้รู้ว่าแก้ตรงไหนแล้วมีผลกับอะไร
      const cell = [];
      if (plainOk && plainAll[index] && plainAll[index] !== text) {
        cell.push(el("p", {
          className: "script-plain",
          textContent: plainAll[index],
          title: "ประโยคปกติ — ไว้อ่านตรวจ ไม่ใช่ตัวที่ส่งเข้า Flow",
        }));
      }
      cell.push(area, per);
      rows.append(el("li", {}, ...cell));
      window.requestAnimationFrame(fit);
    });
    const head = [];
    if (plainOk) {
      head.push(el("p", { className: "note script-hint", textContent:
        "บรรทัดบน = ประโยคปกติไว้อ่านตรวจ · ช่องล่าง = แบบคำอ่านที่ส่งเข้า Flow "
        + "(ขีดคั่นมีไว้ให้เสียงอ่านคำไทยถูก) — แก้ที่ช่องล่างเท่านั้น" }));
    } else if (plainMismatch) {
      // เกิดไม่ได้ในทางปฏิบัติ แต่ถ้าเกิดต้องดัง ไม่ใช่เงียบแล้วโชว์ผิดฉาก
      head.push(el("p", { className: "note warn-note", textContent:
        `⚠️ บทพูดสองแบบไม่ตรงกัน (ประโยคปกติ ${plainAll.length} ฉาก · `
        + `แบบคำอ่าน ${original.length} ฉาก) — แจ้งสายคลิป` }));
    }
    box.replaceChildren(...head, rows, bar);
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
    window.__lastDevices = payload.devices || [];   // ไว้แยกข้อความเคสว่างข้างล่าง
    // **คัดด้วยสายคลิป + ต้องเทรนปลายทางนี้แล้ว** (แก้ 28 ส.ค. 2569 ตามสเปค
    // SPEC-เลือกมือถือก่อนลงคลิป.md ที่สายคลิปส่งมา เจ้าของคอนเฟิร์มแล้ว)
    //
    // ของเดิมคัดด้วย lanes.includes("post") ซึ่งอ่านผิดความหมาย — ในทะเบียน
    // "post" แปลว่า *งานสายโพสต์กลุ่ม Facebook เป็นเจ้าของเครื่องนี้* ไม่ได้แปลว่า
    // *เครื่องนี้โพสต์คลิปได้* เครื่องที่ใช้ลงคลิปจริงตั้งสายงานเป็น "clip"
    // จึงถูกคัดทิ้ง แล้วกล่องขึ้นเครื่องที่ลงไม่ได้มาให้เลือกแทน
    //
    // ที่ไล่ไม่เจอเพราะ **กล่องยังขึ้นเครื่องมาให้เลือก 2 เครื่อง ดูปกติทุกอย่าง**
    // ไม่ล้ม ไม่มี error — ตรงกับ CLAUDE.md ข้อ 2.3 ที่ว่าตัวตรวจที่บอกว่าผ่าน
    // ทั้งที่ยังไม่ผ่าน อันตรายกว่าไม่มีตัวตรวจ
    //
    // วัดจากทะเบียนจริงวันนั้น
    //   Xiaomi 11T pro    สาย post          Shopee 16 จุด  → ขึ้น (ไม่ควร)
    //   REDMI 15C สำรอง   สาย post,engage   Shopee 0 จุด   → ขึ้น (ไม่ควร)
    //   REDMI 15C วิดีโอ  สาย clip          Shopee 20 จุด  → หายไป (ต้องขึ้น)
    //
    // ⚠️ ใช้ `trained` เท่านั้น **ห้ามใช้ `steps`** — steps มีให้ทุกเครื่องตั้งแต่แรก
    // เพราะเป็นแบบร่างกลาง ดู steps จะเห็นทุกเครื่องพร้อมหมด ทั้งที่กดจริงแล้ว
    // ล้มตั้งแต่ขั้นแรก ส่วน points คือจุดที่เจ้าของเทรนเองบนเครื่องนั้น
    //
    // `flows` ไม่มีคีย์ tiktok (ลงผ่านเบราว์เซอร์บนคอม) จึงต้องทนกับ undefined
    phones = (payload.devices || []).filter((device) =>
      device.enabled
      && (device.lanes || []).includes("clip")
      && ((device.flows || {})[row.target] || {}).trained);
  } catch (error) {
    $("#storyNote").textContent = `อ่านทะเบียนมือถือไม่ได้: ${error.message}`;
    return;
  }
  if (!phones.length) {
    // แยกสองเคส — ข้อความเดิมชี้ไปที่ "สายโพสต์" ซึ่งพาไปแก้ผิดที่
    const clipPhones = (window.__lastDevices || []).filter(
      (device) => device.enabled && (device.lanes || []).includes("clip"));
    $("#storyNote").textContent = clipPhones.length
      ? `เครื่องสายคลิปยังไม่ได้เทรนวิธีลง ${row.name || "ปลายทางนี้"} `
        + "— ไปเทรนในแท็บมือถือก่อน"
      : "ยังไม่ได้ตั้งเครื่องไหนเป็นสายคลิป — ไปที่แท็บมือถือ เลือกเครื่อง "
        + 'แล้วติ๊ก "คลิป"';
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

// ================================================ กล่อง "กำลังทำอะไรอยู่"
//
// **สเปคจากสายคลิป 29 ส.ค. 2569** (กติกาข้อ 7.1.1 — เจ้าของคอนเฟิร์มแล้ว)
//
// เจ้าของสั่ง: *"ในแต่ละคลิปโชว์ log ที่ด้านข้างหน่อยว่ากำลังทำขั้นตอนไหน"*
//
// ทำไมจำเป็น — โพสต์หนึ่งใบใช้ 8–10 นาที มี 22 ขั้น ระหว่างนั้นหน้าเว็บเงียบสนิท
// เจ้าของแยกไม่ออกว่า "กำลังทำ" กับ "ค้าง" ต่างกันตรงไหน **วันนี้ถามมา 4 ครั้ง
// ว่าทำไมค้าง ทั้งที่ทุกครั้งระบบทำงานปกติ** (เป็นจังหวะที่มันอ่านหน้าจอมือถือ
// ไม่ได้ ซึ่งกิน 36 วินาทีต่อครั้งเมื่อหน้ามีวิดีโอเล่นอยู่)

const PROGRESS_GAP = 4000;        // ดึงทุก 4 วิ — ขั้นหนึ่งใช้ราว 15 วิ ถี่กว่านี้ไม่ได้อะไรเพิ่ม
const PROGRESS_STUCK = 90;        // ขั้นเดิมนิ่งเกินกี่วินาทีถึงบอกว่ากำลังอ่านจอ
// จำว่าแต่ละใบเปลี่ยนขั้นล่าสุดเมื่อไร — ใช้ตัดสินว่า "นิ่ง" หรือ "เดินอยู่"
const progressSeen = new Map();   // itemId -> {step, at}

/** แปลงเวลาแบบ "15:28:05" เป็นวินาทีที่ผ่านมาแล้ว
 *
 *  เซิร์ฟเวอร์ส่งมาเป็นเวลาอย่างเดียวไม่มีวันที่ — งานที่เริ่มก่อนเที่ยงคืนแล้ว
 *  ดูตอนตีหนึ่งจะได้ค่าติดลบ ถ้าไม่ดักไว้จะขึ้นว่า "ผ่านไป -1400 นาที"
 */
function secondsSince(clock) {
  if (!clock) return null;
  const bits = String(clock).split(":").map(Number);
  if (bits.length < 2 || bits.some(Number.isNaN)) return null;
  const now = new Date();
  const then = new Date(now);
  then.setHours(bits[0], bits[1], bits[2] || 0, 0);
  let gap = (now - then) / 1000;
  if (gap < -60) gap += 86400;          // ข้ามเที่ยงคืนมาแล้ว
  return Math.max(0, Math.round(gap));
}

function humanGap(seconds) {
  if (seconds === null) return "";
  if (seconds < 60) return `${seconds} วินาที`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return s ? `${m}:${String(s).padStart(2, "0")} นาที` : `${m} นาที`;
}

function progressLine(row) {
  const line = el("li", { className: `prog-line ${row.ok === false ? "bad" : ""}` });
  line.append(
    el("span", { className: "prog-at", textContent: row.at || "" }),
    el("span", { className: "prog-no", textContent: row.no ? `${row.no}` : "" }),
    // ขั้นที่ล้มคือสิ่งเดียวที่คนจะย้อนมาอ่าน — ต้องเห็นชัดด้วยไอคอน ไม่ใช่แค่สี
    el("span", { className: "prog-tick", textContent: row.ok === false ? "✗" : "✓" }),
    el("span", { className: "prog-name", textContent: row.name || "" }),
  );
  if (row.message) line.append(el("small", { className: "prog-msg", textContent: row.message }));
  return line;
}

function paintProgress(box, clip) {
  box.replaceChildren();
  if (!clip) {
    box.append(el("p", { className: "note", textContent: "ยังไม่ได้เริ่มลงคลิปนี้" }));
    return;
  }
  const total = clip.total || 0;
  const step = clip.step || 0;
  const running = clip.status === "running";
  const failed = clip.status === "failed";

  const head = el("div", { className: "prog-head" });
  const icon = failed ? "❌" : (running ? "🔄" : "✅");
  head.append(
    el("b", { className: "prog-now", textContent: `${icon} ${clip.now || "—"}` }),
    el("span", { className: "prog-step", textContent: total ? `ขั้น ${step}/${total}` : "" }),
  );
  box.append(head);

  if (total) {
    const bar = el("div", { className: "prog-bar" });
    bar.append(el("i", { style: `width:${Math.min(100, Math.round(step / total * 100))}%` }));
    box.append(bar);
  }
  if (clip.device) {
    box.append(el("small", { className: "prog-dev", textContent: `บนเครื่อง ${clip.device}` }));
  }

  // **"ผ่านไปกี่นาทีแล้ว" ตอบคำถาม "ค้างหรือเปล่า" ได้ตรงที่สุด** (สเปคข้อ 3)
  const ran = secondsSince(clip.started);
  const when = [];
  if (clip.started) when.push(`เริ่ม ${clip.started}`);
  if (running && ran !== null) when.push(`ผ่านไป ${humanGap(ran)}`);
  if (clip.status === "done" && ran !== null) when.push(`ใช้เวลา ${humanGap(ran)}`);
  if (when.length) box.append(el("small", { className: "prog-when", textContent: when.join(" · ") }));

  if (failed) {
    box.append(el("p", { className: "note warn",
      textContent: `❌ หยุดที่ขั้น ${step}/${total} — ${clip.now || ""}` }));
  }

  // **หัวใจของงานนี้** — ขั้นเดิมนิ่งนานไม่ได้แปลว่าค้าง (สเปคข้อ 4)
  // อาการ "ดูเหมือนค้าง" ทั้งหมดของวันนี้มาจากจังหวะอ่านหน้าจอที่มีวิดีโอเล่นอยู่
  // ซึ่งกิน 36 วินาทีต่อครั้ง ไม่มีอะไรบนจอบอก เจ้าของเลยถามซ้ำ 4 รอบ
  if (running) {
    const key = clip.item_id;
    const seen = progressSeen.get(key);
    if (!seen || seen.step !== step) {
      progressSeen.set(key, { step, at: Date.now() });
    } else if ((Date.now() - seen.at) / 1000 > PROGRESS_STUCK) {
      box.append(el("p", { className: "note",
        textContent: "กำลังอ่านหน้าจอมือถือ — หน้าที่มีวิดีโอเล่นอยู่ใช้เวลานานกว่าปกติ" }));
    }
  }

  const lines = [...(clip.lines || [])].reverse();   // ใหม่สุดอยู่บน (สเปคข้อ 1)
  if (lines.length) {
    const list = el("ul", { className: "prog-list" });
    lines.forEach((row) => list.append(progressLine(row)));
    box.append(list);
  }
}

/** ดึงความคืบหน้าเป็นระยะ — หยุดเองเมื่อกล่องหลุดจากหน้า
 *
 *  ผูกการหยุดไว้กับ `isConnected` แทนที่จะไปแก้ทางที่ปิดการ์ด เพราะการ์ดถูกวาดใหม่
 *  หลายทาง (เปลี่ยนงาน · refresh รอบ 6 วิ · กดพับ) ถ้าต้องไปไล่ปิดทีละทาง
 *  จะมีทางที่ลืมแล้วเหลือตัวดึงค้างวิ่งเปล่าตลอดกาล
 */
async function watchProgress(itemId, box) {
  let first = true;
  while (true) {
    await new Promise((done) => setTimeout(done, first ? 300 : PROGRESS_GAP));
    first = false;
    if (!box.isConnected) return;         // การ์ดปิดไปแล้ว — เลิกดึง
    let clip = null;
    try {
      const payload = await api(`/api/publish/progress?item_id=${encodeURIComponent(itemId)}`);
      clip = (payload.clips || [])[0] || null;
    } catch {
      // **ดึงไม่ได้ ≠ งานล้ม** (สเปคข้อ 5) งานโพสต์เดินอยู่คนละทางกับหน้าเว็บ
      // ห้ามขึ้นข้อความที่ทำให้เข้าใจว่าคลิปพัง
      if (!box.isConnected) return;
      box.replaceChildren(el("p", { className: "note",
        textContent: "ดูความคืบหน้าไม่ได้ตอนนี้ — งานยังทำอยู่ตามปกติ" }));
      continue;
    }
    if (!box.isConnected) return;
    paintProgress(box, clip);
    // จบแล้วไม่ต้องดึงต่อ แต่ค้างผลไว้ให้อ่าน (สเปคข้อ 5 ของหัวข้อการวาด)
    if (clip && clip.status !== "running") return;
  }
}

function progressBox(itemId) {
  const box = el("div", { className: "pub-progress" });
  box.append(el("p", { className: "note", textContent: "กำลังอ่านความคืบหน้า…" }));
  watchProgress(itemId, box);
  return box;
}

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
      const button = textBtn(
        "⬆️ ลงเลย", row.can_post ? "primary" : "ghost",
        () => askPhoneThenPost(row, itemId),
      );
      button.disabled = !row.can_post;
      button.title = row.can_post ? `ลง ${row.name} เดี๋ยวนี้` : row.why;
      line.append(button);
    }
    // **ห้ามซ่อนเหตุผล** ปุ่มจางที่ไม่บอกว่าทำไม แยกไม่ออกจากระบบพัง
    if (!row.can_post) line.append(el("small", { className: "note", textContent: row.why }));
    list.append(line);
  });
  // กล่อง "กำลังทำอะไรอยู่" อยู่ข้างลำดับการลง ตามที่เจ้าของสั่ง
  const wrap = el("div", { className: "pub-split" }, list, progressBox(itemId));
  out.push(wrap);
  return out;
}

/** ป้ายความละเอียดของคลิป — **สามสถานะ ไม่ใช่สอง**
 *
 *  สเปคจากสายคลิป 29 ส.ค. 2569 หลัง Google Flow อัปเป็น 1.1 แล้วแอบเจนคลิป
 *  ออกมาเป็น 360p ติดกัน 8 ใบโดยไม่มีอะไรฟ้อง — งานเดินจนจบเหมือนปกติทุกอย่าง
 *
 *  **`video_is_1080p` เป็น null ได้ และ null ไม่ได้แปลว่าไม่ผ่าน** แปลว่า
 *  *ยังวัดไม่ได้* — ไม่มี ffprobe บนเครื่อง หรือเป็นใบเก่าที่บันทึกไว้ก่อน
 *  วันที่เริ่มวัด
 *
 *  วัดของจริงตอนเขียน: ผ่าน 7 ใบ · ต่ำกว่า 2 ใบ · **ยังไม่ได้วัด 109 จาก 118**
 *  เอา null ไปวาดแดงเมื่อไร หน้าจะแดง 92% ทั้งที่ไม่มีอะไรเสีย แล้วเจ้าของจะสั่ง
 *  เจนใหม่ทิ้งเครดิตเปล่าใบละ 15 หน่วย — กติกาข้อ 2.3.1 ข้อ 4 บอกไว้ตรงๆ ว่า
 *  ต้องแยก "ยังไม่ได้ตรวจ" ออกจาก "ตรวจแล้วผ่าน" เสมอ
 */
function sizeChip(run) {
  const pass = run?.video_is_1080p;
  const low = run?.video_min_height;
  const heights = run?.video_heights || [];
  // หลายไฟล์ที่ความละเอียดไม่เท่ากัน ต้องบอกให้ครบ ไม่งั้นเห็นแค่ตัวเตี้ยสุด
  const spread = heights.length > 1 && new Set(heights).size > 1
    ? ` (${heights.map((h) => (h ? `${h}p` : "?")).join(" · ")})` : "";
  if (pass === true) {
    return el("span", { className: "check-chip ok", textContent: `✅ ชัด ${low}p${spread}` });
  }
  if (pass === false) {
    return el("span", { className: "check-chip fail",
      textContent: `❌ ได้แค่ ${low}p${spread} — ต่ำกว่า 1080p` });
  }
  return el("span", { className: "check-chip unknown", textContent: "⚪ ยังไม่ได้วัดความละเอียด" });
}

/** สั่งเจนคลิปใหม่ให้สินค้าที่ไม่มีใบงานในคิวแล้ว
 *
 *  **ลบคลิปเดิมทิ้งและเสียเครดิต Flow 15 หน่วยต่อครั้ง** จึงต้องถามก่อนเสมอ
 *  (สายคลิปขอมาเองพร้อมสเปค 29 ส.ค. 2569)
 *
 *  ข้อความผิดพลาดของฝั่งเซิร์ฟเวอร์เป็นภาษาคนอยู่แล้ว ปล่อยให้ `act()` โชว์ตามจริง
 *  ห้ามแปลงเป็นคำของตัวเอง — สองที่พูดคนละอย่างแล้วจะไม่รู้ว่าอันไหนจริง
 */
async function regenClip(run) {
  const itemId = run?.item_id;
  if (!itemId) return;
  const now = run?.video_min_height;
  const files = (run?.videos || []).length;
  if (!window.confirm(
    "เจนคลิปนี้ใหม่ไหม\n\n"
    + (now ? `· คลิปตอนนี้ได้ ${now}p\n` : "")
    + `· คลิปเดิม ${files} ไฟล์ จะถูกลบทิ้ง เอากลับไม่ได้\n`
    + "· ใช้เครดิต Flow 15 หน่วย\n"
    + "· ใช้คำสั่งเดิมที่เก็บไว้ ไม่ทำสตอรีบอร์ดใหม่ ไม่ถาม Shopee ซ้ำ")) return;
  await act(() => api(`${CLIP_API}/api/clips/${encodeURIComponent(itemId)}/regen`,
    { method: "POST", body: "{}" }));
}

/** เครื่องเล่นคลิปของงานนั้น — ใช้ทั้งตอนรอตรวจและตอนเปิดดูย้อนหลัง
 *  เขียนที่เดียวเพื่อให้สองที่นั้นแสดงเหมือนกันเสมอ */
function videoBlock(run, heading = "🎬 คลิปที่เจนได้", view = null) {
  const names = run?.videos || [];
  if (!names.length) return [];
  const out = [el("h4", { textContent: `${heading} (${names.length} ไฟล์)` })];
  out.push(el("div", { className: "check-row" }, sizeChip(run),
    textBtn("♻️ เจนใหม่", "mini-btn", () => regenClip(run))));
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
               payload.publish_next || "", view?.checked, view?.ok, view?.stale,
               run?.tiktok_product_link?.updated_at || ""].join("|");
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

  // ใบ `done` ในกอง Clip คือของที่อนุมัติ Storyboard/บทพูดแล้ว แต่ตอนนั้น Flow
  // ปิดอยู่ จึงยังไม่มีวิดีโอ ต้องเห็นภาพต้นทางก่อนตัดสินใจว่าจะส่งไปเจนหรือไม่.
  if (job.stage === "done") {
    const savedStoryboard = storedStoryboard(job, run);
    if (savedStoryboard) parts.push(savedStoryboard);
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
    // หุบไว้เป็นค่าตั้งต้น (เจ้าของสั่ง 28 ส.ค. 2569) — แผงนี้ยาวและไม่ได้ใช้ทุกครั้ง
    // กางค้างไว้แล้วดันของที่ต้องดูจริงตกจอ · กดครั้งเดียวแล้วระบบจำให้เอง
    ? [fold(job, "publish", "📤 ลำดับการลง 3 ที่ — กดลงได้จากตรงนี้", pub.slice(1), false)]
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
    // แถวพวกนี้เป็น**ที่เดียว**ที่มีสถานะโหมดทำเอง เก็บไว้ให้การ์ดใบงานใช้
    rememberManualTicks(storyRuns);
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
  const tiktokLink = run.tiktok_product_link || {};
  if (tiktokLink.status || tiktokLink.url) {
    const pending = tiktokLink.status === "pending_review";
    const added = tiktokLink.status === "showcase_added";
    const failed = tiktokLink.status === "error";
    const running = tiktokLink.status === "running";
    const heading = added ? "✅ เพิ่มสินค้าเข้าโชว์เคส TikTok แล้ว"
      : pending ? "⏳ สินค้า TikTok — รอตรวจ"
      : failed ? "❌ เพิ่มสินค้าเข้าโชว์เคส TikTok ไม่สำเร็จ"
      : running ? "🔄 กำลังตรวจสินค้า TikTok"
      : "✅ ผลสินค้า TikTok เดิม";
    parts.push(el("p", { className: `note ${pending ? "warn" : ""}` },
      el("b", { textContent: heading }),
      document.createTextNode(tiktokLink.selected_rank
        ? ` · อันดับ ${tiktokLink.selected_rank}` : ""),
      tiktokLink.url ? document.createTextNode(" · ลิงก์เดิม: ") : document.createTextNode(""),
      tiktokLink.url ? el("a", {
        href: tiktokLink.url, target: "_blank", rel: "noreferrer",
        textContent: tiktokLink.url,
      }) : document.createTextNode(""),
      tiktokLink.tiktok_product_name
        ? document.createTextNode(` · ชื่อที่คัดลอก: ${tiktokLink.tiktok_product_name}`)
        : document.createTextNode(""),
      tiktokLink.reason
        ? document.createTextNode(` · ${tiktokLink.reason}`) : document.createTextNode("")));
  }
  const skippedPublish = Object.values(run.publish || {}).find(
    (state) => state && state.auto_skip);
  if (skippedPublish?.error) {
    parts.push(el("p", { className: "note warn",
      textContent: `⏭ ${skippedPublish.error}` }));
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
