@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ===== ADB MCP server =====
echo เปิด server ที่ 127.0.0.1:8765 ...
start "adb-mcp-server" cmd /k python adb_mcp_server.py
timeout /t 3 >nul
echo.
echo เปิด Cloudflare tunnel ...
echo เมื่อขึ้น URL https://xxxx.trycloudflare.com ให้ต่อเส้นทาง /^<รหัส^>/mcp ต่อท้าย
echo (รหัสอยู่ในหน้าต่าง server) แล้วเอา URL เต็มไปใส่เป็น custom connector ที่ claude.ai
echo.
cloudflared tunnel --url http://127.0.0.1:8765
