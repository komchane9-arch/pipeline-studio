@echo off
chcp 65001 >nul
rem ตัวเรียกโปรแกรมทำคลิปให้เป็น 1080p — ลากไฟล์มาวางบนไอคอนได้เลย
set PYTHONIOENCODING=utf-8
python "%~dp0clip_up1080_tool.py" %*
