@echo off
chcp 65001 >nul
rem GreenMate 一键启动 v4：自动记录启动日志，失败时直接显示日志内容
cd /d "E:\GreenMate\greenmate-final"

curl -s -o NUL --max-time 2 http://127.0.0.1:8000/ >nul 2>&1
if %errorlevel%==0 goto open

echo [GreenMate] 服务未运行，正在启动（启动日志写入 greenmate_start.log）
start "GreenMate Server" cmd /k ".venv\Scripts\python.exe B06\run.py > greenmate_start.log 2>&1"

set tries=0
:wait
timeout /t 2 /nobreak >nul
curl -s -o NUL --max-time 2 http://127.0.0.1:8000/ >nul 2>&1
if %errorlevel%==0 goto open
set /a tries+=1
if %tries% lss 20 goto wait

echo.
echo [失败] 等待 40 秒服务仍未就绪。启动日志如下（可截图发给 Claude 分析）：
echo ----------------------------------------
type greenmate_start.log
echo ----------------------------------------
pause
exit /b 1

:open
start "" "http://127.0.0.1:8000/B04/"
