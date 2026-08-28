"""
Agent 本地测试脚本

用法:
    test_agent.bat                      # 用默认问题测试（自动使用正确的 Python）
    或
    python tests/test_agent.py "你的自定义问题"

首次运行会加载 embedding 模型，需要 60-90 秒，后续会更快。
"""

import sys, os, asyncio

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ".")

# 检查 Python 版本
if sys.version_info < (3, 10):
    print(f"\n[WARN] Python {sys.version_info.major}.{sys.version_info.minor} 版本过低，需要 >= 3.10")
    print(f"[INFO] 请使用: test_agent.bat 或指定 Python 3.12 路径")
    sys.exit(1)

print(f"[INFO] Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} @ {sys.executable}")

# 检查关键依赖
for pkg in ["dotenv", "langchain_community", "chromadb"]:
    try:
        __import__(pkg)
    except ImportError:
        print(f"\n[ERROR] 缺少依赖: {pkg}")
        print(f"[FIX] 请使用 test_agent.bat 启动，确保使用系统 Python 3.12")
        sys.exit(1)

from dotenv import load_dotenv
load_dotenv()

print(f"[INFO] 加载完成，启动 Agent...\n")
from app.agent.agent import SolutionAgent


async def test(question: str):
    agent = SolutionAgent(max_steps=5, timeout=300)

    print(f"{'='*60}")
    print(f"用户: {question}")
    print(f"{'='*60}\n")

    result = await agent.run(question, session_id="test")

    print(f"\n{'='*60}")
    success_label = "成功" if result["success"] else "降级完成"
    print(f"耗时: {result['elapsed']}s | 步数: {result['steps']} | 状态: {success_label}")
    if result["tool_calls"]:
        print("工具调用:")
        for tc in result["tool_calls"]:
            print(f"  Step {tc['step']}: {tc['tool']}({tc['input']})")
    print(f"\n{'─'*60}")
    print(result["answer"])
    print(f"{'─'*60}\n")


if __name__ == "__main__":
    default = "我想让工厂更智能一点"
    q = sys.argv[1] if len(sys.argv) > 1 else default
    asyncio.run(test(q))
