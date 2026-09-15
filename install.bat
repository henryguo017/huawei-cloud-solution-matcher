@echo off
chcp 65001
echo ========================================
echo 华为云解决方案匹配系统 - 依赖安装
echo ========================================
echo.

cd /d "%~dp0"

echo [步骤1] 创建虚拟环境...
if not exist "venv" (
    python -m venv venv
    echo [完成] 虚拟环境创建成功
) else (
    echo [跳过] 虚拟环境已存在
)

echo.
echo [步骤2] 激活虚拟环境...
call venv\Scripts\activate.bat

echo.
echo [步骤3] 升级 pip...
python -m pip install --upgrade pip

echo.
echo [步骤4] 安装项目依赖...
pip install -r requirements.txt

echo.
echo ========================================
echo [完成] 依赖安装完成！
echo ========================================
echo.
echo 下一步：
echo 1. 复制 .env.example 为 .env 并填写配置
echo 2. 运行 start_api.bat 启动 API 服务
echo.

pause
