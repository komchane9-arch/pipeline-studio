/* หน้าแรกบนมือถือ — ถามสถานะสิทธิ์แล้วรอเครื่องหลักอนุมัติ */

(() => {
  const $ = (selector) => document.querySelector(selector);
  const TOKEN_KEY = "pipelineStudioToken";

  // บางเบราว์เซอร์บนมือถือทิ้งคุกกี้ จึงเก็บโทเคนไว้เองแล้วแนบไปทางเฮดเดอร์ด้วย
  // ถ้าไม่มีทางสำรอง ทุกครั้งที่ถามสถานะจะกลายเป็นเครื่องใหม่และไม่มีวันได้รับอนุมัติ
  function headers() {
    const token = localStorage.getItem(TOKEN_KEY);
    return token ? { "x-device-token": token } : {};
  }

  async function checkStatus() {
    try {
      const response = await fetch("/api/access/status", { headers: headers() });
      const payload = await response.json();
      if (payload.token) localStorage.setItem(TOKEN_KEY, payload.token);
      render(payload);
    } catch {
      render({ status: "offline" });
    }
  }

  function render(payload) {
    const gate = $("#gate");
    const tools = $("#tools");
    const approved = payload.status === "approved";
    tools.hidden = !approved;

    if (approved) {
      gate.querySelector(".big").textContent = "✅";
      $("#gateTitle").textContent = "ใช้งานได้แล้ว";
      $("#gateText").textContent =
        payload.role === "admin" ? "เครื่องหลัก" : `อนุญาตแล้ว · ${payload.device || ""}`;
      return;
    }
    if (payload.status === "revoked") {
      gate.querySelector(".big").textContent = "⛔";
      $("#gateTitle").textContent = "สิทธิ์ถูกยกเลิก";
      $("#gateText").textContent = "ขออนุญาตใหม่ที่คอมเครื่องหลัก";
      return;
    }
    if (payload.status === "offline") {
      gate.querySelector(".big").textContent = "📴";
      $("#gateTitle").textContent = "ต่อเซิร์ฟเวอร์ไม่ได้";
      $("#gateText").textContent = "เช็คว่าคอมเปิดโปรแกรมอยู่และอยู่ Wi-Fi วงเดียวกัน";
      return;
    }
    gate.querySelector(".big").textContent = "⏳";
    $("#gateTitle").textContent = "รอเครื่องหลักอนุญาต";
    $("#gateText").textContent =
      `เปิด Pipeline Studio บนคอม → ⚙ ตั้งค่า → อุปกรณ์ที่ขอเข้าใช้ → กดอนุญาต (${payload.device || "อุปกรณ์นี้"})`;
  }

  checkStatus();
  // เช็คถี่ๆ ระหว่างรออนุมัติ จะได้เด้งเป็นใช้งานได้เองทันทีที่กดอนุญาตบนคอม
  window.setInterval(checkStatus, 3000);
})();
