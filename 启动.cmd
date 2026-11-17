@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo 请先双击 安装.cmd，完成后再双击 启动.cmd。
  pause
  exit /b 2
)
start "" ".venv\Scripts\pythonw.exe" -m buaa_booking.launcher_ui
