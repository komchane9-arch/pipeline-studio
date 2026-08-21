@echo off
REM รีสตาร์ต 8866 แบบตรวจก่อนว่าปลอดภัยไหม (ตัวจริงอยู่ใน restart_studio.py)
REM
REM ตรรกะทั้งหมดอยู่ใน Python ไม่ใช่ในไฟล์นี้ เพราะ .bat/.ps1 กับข้อความภาษาไทย
REM เพี้ยนง่ายมากบน Windows PowerShell 5.1 (อ่านไฟล์ที่ไม่มี BOM เป็น ANSI)
REM ส่วน Python อ่านเขียน UTF-8 ตรงไปตรงมา และเรียก fb_backup ได้ทันที
chcp 65001 >nul
cd /d "%~dp0"
C:\Python311\python.exe "%~dp0restart_studio.py" %*
echo.
pause
