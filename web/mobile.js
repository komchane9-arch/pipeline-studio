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
    const btnQuickApprove = $("#btnQuickApprove");
    const approved = payload.status === "approved";
    tools.hidden = !approved;

    if (btnQuickApprove) {
      btnQuickApprove.hidden = approved || !payload.can_approve;
      btnQuickApprove.onclick = async () => {
        btnQuickApprove.disabled = true;
        btnQuickApprove.textContent = "กำลังอนุมัติ…";
        try {
          const res = await fetch("/api/access/quick-approve", {
            method: "POST",
            headers: headers()
          });
          const data = await res.json();
          if (data.ok) {
            checkStatus();
            const params = new URLSearchParams(location.search);
            if (params.get("redirect")) {
              window.location.href = params.get("redirect");
            }
          } else {
            alert(data.detail || "อนุมัติไม่สำเร็จ");
            btnQuickApprove.disabled = false;
            btnQuickApprove.textContent = "✅ อนุมัติอุปกรณ์นี้ทันที (ผ่าน Tailscale)";
          }
        } catch (e) {
          alert("เกิดข้อผิดพลาด: " + e.message);
          btnQuickApprove.disabled = false;
          btnQuickApprove.textContent = "✅ อนุมัติอุปกรณ์นี้ทันที (ผ่าน Tailscale)";
        }
      };
    }

    if (approved) {
      gate.querySelector(".big").textContent = "✅";
      $("#gateTitle").textContent = "ใช้งานได้แล้ว";
      $("#gateText").textContent =
        payload.role === "admin" ? "เครื่องหลัก" : `อนุญาตแล้ว · ${payload.device || ""}`;
      const params = new URLSearchParams(location.search);
      if (params.get("redirect")) {
        window.location.href = params.get("redirect");
      }
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
      $("#gateText").textContent = "เช็คว่าคอมเปิดโปรแกรมอยู่และต่อเน็ตวงเดียวกันหรือ Tailscale";
      return;
    }
    gate.querySelector(".big").textContent = "⏳";
    $("#gateTitle").textContent = "รอเครื่องหลักอนุญาต";
    $("#gateText").textContent = payload.can_approve
      ? "เชื่อมต่อผ่านเส้นทาง Tailscale — กดปุ่มด้านล่างเพื่ออนุมัติเครื่องนี้ได้ทันที"
      : `เปิด Pipeline Studio บนคอม → ⚙ ตั้งค่า → อุปกรณ์ที่ขอเข้าใช้ → กดอนุญาต (${payload.device || "อุปกรณ์นี้"})`;
  }

  checkStatus();
  // เช็คถี่ๆ ระหว่างรออนุมัติ จะได้เด้งเป็นใช้งานได้เองทันทีที่กดอนุญาตบนคอม
  window.setInterval(checkStatus, 3000);
})();
