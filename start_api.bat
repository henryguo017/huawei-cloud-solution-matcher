@echo off
chcp 65001
echo ========================================
echo 华为云解决方案匹配系统 API 服务
echo ========================================
echo.

cd /d "%~dp0"

if not exist "venv" (
    echo [错误] 虚拟环境不存在，请先运行 install.bat
    pause
    exit /b 1
)

echo [启动] 正在启动 API 服务...
echo [地址] http://localhost:8000
echo [文档] http://localhost:8000/docs
echo.

call venv\Scripts\activate.bat
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

pause
