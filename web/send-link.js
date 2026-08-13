/* หน้าส่งลิงก์จากมือถือเข้าคอม — เปิดผ่าน adb reverse ที่ localhost:8866 */

(() => {
  const $ = (selector) => document.querySelector(selector);
  const note = $("#sendNote");

  function setNote(message, bad = false) {
    note.textContent = message;
    note.style.color = bad ? "var(--danger)" : "";
  }

  async function api(url, options = {}) {
    const response = await fetch(url, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "ส่งไม่สำเร็จ");
    return payload;
  }

  async function refresh() {
    try {
      const payload = await api("/api/links");
      $("#sentList").replaceChildren(
        ...payload.items.slice(0, 20).map((item) => {
          const row = document.createElement("li");
          const tag = document.createElement("span");
          tag.className = "tag";
          tag.textContent = item.platform;
          row.append(tag, document.createTextNode(item.url));
          return row;
        }),
      );
    } catch { /* อ่านรายการไม่ได้ไม่ต้องขัดจังหวะการส่ง */ }
  }

  $("#sendButton").addEventListener("click", async () => {
    const text = $("#linkText").value.trim();
    if (!text) {
      setNote("วางลิงก์ก่อน", true);
      return;
    }
    $("#sendButton").disabled = true;
    try {
      const payload = await api("/api/links", {
        method: "POST",
        body: JSON.stringify({ text }),
      });
      $("#linkText").value = "";
      setNote(
        payload.added
          ? `ส่งเข้าคอมแล้ว ${payload.added} ลิงก์` +
            (payload.skipped ? ` (ซ้ำ ${payload.skipped})` : "")
          : "ลิงก์นี้ส่งไปแล้ว",
      );
      await refresh();
    } catch (error) {
      setNote(error.message, true);
    } finally {
      $("#sendButton").disabled = false;
    }
  });

  // navigator.clipboard.readText ใช้ได้เฉพาะหน้าที่มาจาก https หรือ localhost
  // หน้านี้เปิดผ่าน adb reverse ที่ localhost จึงเข้าเงื่อนไข
  $("#pasteButton").addEventListener("click", async () => {
    if (!navigator.clipboard?.readText) {
      setNote("เบราว์เซอร์นี้อ่านคลิปบอร์ดไม่ได้ — กดวางเองในช่องแทน", true);
      return;
    }
    try {
      $("#linkText").value = await navigator.clipboard.readText();
      setNote("วางจากคลิปบอร์ดแล้ว — กดส่งได้เลย");
    } catch {
      setNote("มือถือไม่อนุญาตให้อ่านคลิปบอร์ด — กดวางเองในช่องแทน", true);
    }
  });

  $("#clearButton").addEventListener("click", async () => {
    if (!window.confirm("ล้างรายการลิงก์ทั้งหมดไหม")) return;
    await api("/api/links", { method: "DELETE" });
    await refresh();
    setNote("ล้างรายการแล้ว");
  });

  refresh();
})();
