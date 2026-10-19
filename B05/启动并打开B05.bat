@echo off
rem GreenMate 一键启动：检测服务是否运行；未运行则启动并等待就绪，再打开 B05 页面
cd /d "E:\GreenMate\greenmate-final"

netstat -ano | findstr ":8000" | findstr "LISTENING" >nul
if %errorlevel%==0 goto open

echo [GreenMate] 服务未运行，正在启动（新窗口保持开启，Ctrl+C 可停止服务）
start "GreenMate Server" cmd /k ".venv\Scripts\python.exe B06\run.py"

set tries=0
:wait
timeout /t 2 /nobreak >nul
netstat -ano | findstr ":8000" | findstr "LISTENING" >nul
if %errorlevel%==0 goto open
set /a tries+=1
if %tries% lss 15 goto wait
echo [警告] 等待 30 秒后服务仍未就绪，请查看服务窗口里的报错信息

:open
start "" "http://127.0.0.1:8000/B05/"
