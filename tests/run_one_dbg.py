import asyncio, sys, os, re, time
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 测试专用：让 embedding 在主线程执行，规避 Windows+Python3.13 下
# sentence-transformers 在 worker 线程推理的段错误（不影响生产 Linux 环境）。
import asyncio as _a
async def _sync_to_thread(fn, *args, **kwargs):
    return fn(*args, **kwargs)
_a.to_thread = _sync_to_thread

from app.agent import get_agent

async def main():
    agent = get_agent(max_steps=8, timeout=120.0)
    q = "某中型装备制造企业，200台数控设备，常因非计划停机损失大，想上预测性维护平台，减少停机并降本"
    print("START", flush=True)
    res = await agent.run(q, session_id="dbg3")
    ans = res.get("answer", "")
    print("SUCCESS:", res.get("success"), "STEPS:", res.get("steps"), "ALEN:", len(ans), flush=True)
    print("SOURCES:", re.findall(r'《([^》]+)》', ans)[:5], flush=True)
    print("HEAD:", ans[:300], flush=True)

asyncio.run(main())
print("DONE", flush=True)
