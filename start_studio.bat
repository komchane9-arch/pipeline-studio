@echo off
REM Pipeline Studio launcher - detached, with crash logs.
REM Starting the servers from here (instead of ad-hoc from a tool shell)
REM keeps them alive after the parent shell exits, and always leaves a log.
cd /d "%~dp0"
if not exist "data" mkdir "data"
start "" /b C:\Python311\python.exe app.py >> "data\server.log" 2>&1
echo Pipeline Studio starting on 8866 (clip server 8877 follows) - log: data\server.log
