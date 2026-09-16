# -*- coding: utf-8 -*-
"""FC 灰度门禁 · A8 错误自愈率验证（≥6 例错误注入，2026-09-15）

指标定义（docs/agent-architecture-fc-2026-09-11.md §6）：
    A8 错误自愈率 = 工具报错后模型自行修正并成功的比例，达标线 ≥60%。
S4 现状：FC 臂仅 1/1 例自然触发（样本不足）→ 本脚本用确定性故障注入补足样本。

做法：把指定工具包一层 FlakyTool（前 N 次调用返回真实形态的错误 JSON，
之后放行真实执行），跑完整 FC 运行时，判定模型是否自愈：
  - 瞬时/参数/限流类：任务完成 + 该工具最终至少成功一次 + 终稿非空；
  - 持续失败类：任务完成 +（换工具拿到同等信息 或 终稿如实说明缺口不编造）。

运行条件：DEEPSEEK_API_KEY（读 .env）；KB 可用（search_kb 真实执行）。
用法：
    python tests/verify_fc_a8_error_injection.py            # 全部用例
    python tests/verify_fc_a8_error_injection.py --only 2   # 单跑用例 2
输出：逐例 PASS/FAIL + JSON 证据摘要；A8≥0.6 退出码 0，否则 1。
"""
import argparse
import asyncio
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(ROOT, '.env'))

if not os.getenv("DEEPSEEK_API_KEY"):
    print("缺少 DEEPSEEK_API_KEY（.env）——本脚本是真 API E2E，无法桩掉模型行为。")
    sys.exit(2)

from app.agent.harness import AgentHarness  # noqa: E402
from app.agent.intent import classify_intent  # noqa: E402
from app.agent.memory import ConversationMemory  # noqa: E402
from app.agent.tools import Tool, ToolRegistry, create_default_tools  # noqa: E402

# 无权限弹窗：脚本内全部放行（生产由前端弹窗决策，与本验证无关）
PERMS = {"generate_doc": "allow", "web_search": "allow",
         "web_extract": "allow", "run_python": "allow"}


class FlakyTool:
    """故障注入包装：前 fail_n 次 execute 返回错误 JSON，之后透传真实工具。

    错误文本对齐真实工具形态（{"status":"error"} 会被 _is_error_obs 与
    连败计数器一致识别），错误信息可指定"参数不正确"类（引导改参数）或
    "服务繁忙/超时"类（引导重试或换路）。
    """

    def __init__(self, inner: Tool, fail_n: int, error_text: str,
                 always_fail: bool = False):
        self._inner = inner
        self._fail_n = fail_n
        self._error_text = error_text
        self._always_fail = always_fail
        self.calls = 0        # 真实放行的调用次数
        self.failed_calls = 0  # 注入失败的次数

    def __getattr__(self, item):
        return getattr(self._inner, item)

    async def execute(self, **kwargs) -> str:
        if self._always_fail or self.calls + self.failed_calls < self._fail_n:
            self.failed_calls += 1
            return json.dumps({"status": "error", "message": self._error_text},
                              ensure_ascii=False)
        self.calls += 1
        return await self._inner.execute(**kwargs)


def wrap_tool(registry: ToolRegistry, name: str, **kw) -> FlakyTool:
    inner = registry.get(name)
    if inner is None:
        raise KeyError(f"工具不存在: {name}（可用: "
                       f"{[t.name for t in registry.list_tools()]}）")
    flaky = FlakyTool(inner, **kw)
    registry.register(flaky)  # register 按 name 覆盖，FlakyTool.name 透传 inner
    return flaky


def make_harness() -> AgentHarness:
    return AgentHarness(create_default_tools(), ConversationMemory(), verbose=False)


def _honest_gap(answer: str) -> bool:
    """持续失败例：终稿是否如实说明缺口（而非编造成功）"""
    keys = ("未能", "无法", "没有找到", "未找到", "暂时无法", "检索失败",
            "不可用", "知识库暂时", "暂时不可用", "存在缺口", "信息缺口",
            "受限", "失败")
    return any(k in (answer or "") for k in keys)


CASES = [
    dict(no=1, name="瞬时超时×1（search_kb）",
         task="帮我检索知识库里关于华为云OEE和工业物联网方案的资料，简要总结要点。",
         inject=[("search_kb", dict(fail_n=1,
                  error_text="Error: KB 服务超时（upstream timeout），请稍后重试"))],
         mode="eventual_success"),
    dict(no=2, name="参数漂移×2（search_kb）",
         task="查一下制造业设备上云和预测性维护相关的知识库内容，列出关键实践。",
         inject=[("search_kb", dict(fail_n=2,
                  error_text="参数不正确：industry 取值非法，仅支持 manufacturing/health/gov；"
                             "query 不能为空。请修正参数后重试"))],
         mode="eventual_success"),
    dict(no=3, name="限流×2（search_kb）",
         task="从知识库找华为云政务云和数据安全方案的要求，做个要点清单。",
         inject=[("search_kb", dict(fail_n=2,
                  error_text='"status": "error" KB 服务繁忙（rate limit），请降低频率重试'))],
         mode="eventual_success"),
    dict(no=4, name="持续失败→换路或如实说明（search_kb 全程挂）",
         task="检索知识库中医疗行业影像云方案的核心要点并总结。",
         inject=[("search_kb", dict(fail_n=0, always_fail=True,
                  error_text="Error: KB 索引损坏（corrupt index），该工具当前不可用"))],
         mode="honest_or_detour"),
    dict(no=5, name="联网限流×2（web_search）",
         task="联网搜索华为云最近的工业互联网新闻动态，给我 3 条要点。",
         inject=[("web_search", dict(fail_n=2,
                  error_text="Error: 搜索服务限流（429 Too Many Requests），请稍后重试"))],
         mode="eventual_success", optional_tool="web_search"),
    dict(no=6, name="文件列目录瞬时失败×1（list_dir）",
         task="列一下我上传的资料文件夹里有哪些文件，并简单说明它们可能的用途。",
         inject=[("list_dir", dict(fail_n=1,
                  error_text="Error: 文件系统暂时不可用（EBUSY resource busy），请稍后重试"))],
         mode="eventual_success", optional_tool="list_dir"),
]


async def run_case(case: dict) -> dict:
    h = make_harness()
    wrappers = []
    for name, kw in case["inject"]:
        if case.get("optional_tool") == name and h.tools.get(name) is None:
            return dict(skip=True, why=f"工具 {name} 未注册")
        wrappers.append(wrap_tool(h.tools, name, **kw))

    t0 = asyncio.get_event_loop().time()
    result = await h.run(
        case["task"], session_id=f"a8_case{case['no']}",
        runtime="fc", autonomy="high", tool_permissions=PERMS,
        user_id=0,
    )
    wall = asyncio.get_event_loop().time() - t0
    answer = result.get("answer") or ""
    completed = bool(result.get("success")) and len(answer) >= 80

    detail = dict(no=case["no"], name=case["name"], wall=round(wall, 1),
                  completed=completed, answer_len=len(answer))
    if case["mode"] == "eventual_success":
        healed = completed and any(w.calls >= 1 for w in wrappers)
        detail["tool_success_calls"] = {w.name: w.calls for w in wrappers}
        detail["criterion"] = "completed + 该工具最终成功≥1次"
    else:  # honest_or_detour
        # 换路证据：search_kb 之外有工具成功调用（tool_calls_log）
        other_ok = any(
            (c.get("tool") != "search_kb") and not c.get("error")
            for c in (result.get("tool_calls_log") or []))
        healed = completed and (other_ok or _honest_gap(answer))
        detail["other_tool_ok"] = other_ok
        detail["honest_gap"] = _honest_gap(answer)
        detail["criterion"] = "completed + 换工具成功 或 终稿如实说明缺口"
    detail["healed"] = healed
    detail["answer_head"] = answer[:120].replace("\n", " ")
    return detail


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, help="只跑指定编号的用例")
    args = ap.parse_args()

    cases = [c for c in CASES if args.only in (None, c["no"])]
    results, skipped = [], 0
    for case in cases:
        print(f"\n▶ 用例 {case['no']}: {case['name']}")
        try:
            d = await asyncio.wait_for(run_case(case), timeout=600)
        except asyncio.TimeoutError:
            d = dict(no=case["no"], name=case["name"], healed=False,
                     why="600s 超时")
        if d.get("skip"):
            skipped += 1
            print(f"  SKIP（{d['why']}）——不计入分母")
            continue
        results.append(d)
        print(f"  {'PASS' if d.get('healed') else 'FAIL'} | {d.get('criterion', '')}"
              f" | wall={d.get('wall')}s | answer_len={d.get('answer_len')}")
        if d.get("tool_success_calls") is not None:
            print(f"  工具成功调用: {d['tool_success_calls']}")
        print(f"  终稿开头: {d.get('answer_head', d.get('why', ''))}")

    if not results:
        print("\n全部用例被跳过，无有效样本。")
        return 2
    healed = sum(1 for d in results if d.get("healed"))
    a8 = healed / len(results)
    ok = a8 >= 0.6
    print("\n" + "=" * 64)
    print(f"A8 错误自愈率 = {healed}/{len(results)} = {a8:.2f}"
          f"（达标线 ≥0.60）→ {'PASS' if ok else 'FAIL'}"
          + (f"，跳过 {skipped} 例" if skipped else ""))
    print("=" * 64)
    print("证据 JSON:", json.dumps(
        dict(metric="A8", healed=healed, total=len(results), rate=round(a8, 2),
             cases=[{k: v for k, v in d.items() if k != "answer_head"}
                    for d in results], date="2026-09-15"),
        ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
