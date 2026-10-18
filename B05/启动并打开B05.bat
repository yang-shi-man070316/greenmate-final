@echo off
rem GreenMate 一键启动：自动判断服务是否在运行，然后打开 B05 页面
cd /d "E:\GreenMate\greenmate-final"

netstat -ano | findstr ":8000" | findstr "LISTENING" >nul
if %errorlevel%==0 (
    echo [GreenMate] 服务已在运行，直接打开 B05 页面
) else (
    echo [GreenMate] 服务未运行，正在启动（新窗口保持开启，Ctrl+C 可停止服务）
    start "GreenMate Server" cmd /k ".venv\Scripts\python.exe B05\run.py"
    timeout /t 4 /nobreak >nul
)

start "" "http://127.0.0.1:8000/B05/"
