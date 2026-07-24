@echo off
:: Agent 测试启动脚本 - 使用正确的 Python 3.12
set PYTHON=C:\Users\33245\AppData\Local\Programs\Python\Python312\python.exe
echo Using Python: %PYTHON%
%PYTHON% tests/test_agent.py %*
