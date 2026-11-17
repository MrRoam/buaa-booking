@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo 请先运行 安装.cmd。
  pause
  exit /b 2
)
start "" ".venv\Scripts\pythonw.exe" -m buaa_booking.availability_ui
