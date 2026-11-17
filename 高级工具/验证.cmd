@echo off
chcp 65001 >nul
cd /d "%~dp0.."
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" (
  echo 请先运行 安装.cmd。
  pause
  exit /b 2
)
".venv\Scripts\python.exe" -m buaa_booking selfcheck
".venv\Scripts\python.exe" -m buaa_booking demo
".venv\Scripts\python.exe" -m buaa_booking network-check
echo 下一步：运行 登录并查场.cmd，在本机输入账号。以上步骤没有创建真实订单。
pause
