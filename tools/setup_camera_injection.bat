@echo off
REM เปิดระบบ Camera Injection (Iriun Webcam + LDPlayer 14 + ADB)
chcp 65001 >nul
cd /d "%~dp0\.."
C:\Python311\python.exe tools\setup_camera_injection.py %*
echo.
pause
