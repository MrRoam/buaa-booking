@echo off
chcp 65001 >nul
cd /d "%~dp0.."
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" (
  echo 请先运行 安装.cmd。
  pause
  exit /b 2
)
".venv\Scripts\python.exe" -m buaa_booking login
if errorlevel 1 goto done
".venv\Scripts\python.exe" -m buaa_booking check
:done
echo 本次只登录和查场，不会创建订单。
pause
