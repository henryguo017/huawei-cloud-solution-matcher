# -*- coding: utf-8 -*-
"""L4-P2 Agent Runtime · 主循环（runner.py）

**model-in-the-loop 的心脏**：模型通过原生 tool_calls 自选工具、自决终止；
宿主只做四件事 —— 喂 schema、拦权限、执行、把 observation 回填。

判据落地对照：
  C1 控制流在模型 → 无工具白名单、无步序约束；终止条件 = 模型不再请求工具
  C2 工具接口结构化 → schema.build_tool_schemas + tool_calls（无文本解析）
  C3 失败恢复在模型 → 工具错误结构化回填，模型自行调整；宿主只做预算熔断
  C4 计划所有权   → todo.update_plan 由模型调用，宿主不据此约束执行

宿主边界（不越界）：
  - 权限闸门复用 harness._gate_tool（human-in-the-loop）
  - 上下文压缩走 context.compact_messages（窗口保护）
  - 不可委托计算不在此层：金额仍由程序化成本表产出
  - 交付质量门与终稿组装在 harness._run_fc_runtime

thinking 按轮分档（实测依据见 config 注释）：
  - 决策轮 → AGENT_THINKING_DECISION（enabled），拿 reasoning_content 上屏
  - 模型已用 update_plan 把全部步骤标记 done → 下一次调用按 AGENT_THINKING_FINAL（disabled），
    **这是模型自己给出的"要收口了"信号**，不是宿主猜测
  - 宿主主动索要终稿（预算收口 / 完成态自纠）→ AGENT_THINKING_FINAL
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from app.config import (
    AGENT_MAX_TURNS, AGENT_TOKEN_BUDGET, AGENT_WALL_BUDGET, AGENT_ADVISORY_AT,
    AGENT_THINKING_DECISION, AGENT_THINKING_FINAL, AGENT_PARALLEL_READONLY,
    AGENT_COMPACT_AT, AGENT_COMPACT_KEEP_TURNS, MAX_PARALLEL, AGENT_CONTEXT_WINDOW,
)
from app.agent.runtime import events as ev
from app.agent.runtime import verify as vf
from app.agent.runtime.context import compose_system_prompt, messages_tokens, compact_messages
from app.agent.runtime.guards import RunGuards
from app.agent.runtime.schema import (
    build_tool_schemas, is_readonly, parse_tool_arguments, sanitize_messages,
    to_assistant_message, to_tool_message,
)
from app.agent.runtime.todo import TODO_TOOL_NAME, TODO_TOOL_SCHEMA, handle_update_plan, normalize_items

logger = logging.getLogger(__name__)

# 熔断收口提示（宿主主动索要终稿）
_CLOSE_INSTRUCTION = (
    "【宿主预算提示】本次任务的预算已到上限，现在必须收口。"
    "请立即基于你已经获得的信息输出最终答案，不要再调用任何工具；"
    "若某些信息确实缺失，请在答案中如实说明缺口。"
)


def _collect_facts(tool_calls_log: List[Dict[str, Any]], pending_export: Optional[str] = None) -> List[Dict[str, str]]:
    """收集「宿主核验事实」：在真实写操作之外，把宿主**已受理的导出**也计为事实。

    generate_doc 在本运行时是**延迟执行**（终稿产出后才落文件），因此工具调用记录里
    不会有它的成功条目；但宿主已受理即等同承诺完成。若不计入，完成态核验会把模型
    「已为你生成 Word 文档」误判为幻觉，触发一次无谓的自纠回合。
    """
    facts = vf.collect_write_facts(tool_calls_log)
    if pending_export:
        facts.append({
            "tool": "generate_doc",
            "kind": vf.FACT_KIND_BY_TOOL.get("generate_doc", "doc_export"),
            "summary": f"宿主已受理导出请求（格式 {pending_export}），将在终稿产出后生成文件",
        })
    return facts


class _TurnRecord:
    """单轮轨迹（供 trace / 评估指标 A7/A8/A9 统计）。"""
    __slots__ = ("index", "reasoning_chars", "content_chars", "tool_calls", "tokens", "thinking")

    def __init__(self, index: int, thinking: str):
        self.index = index
        self.thinking = thinking
        self.reasoning_chars = 0
        self.content_chars = 0
        self.tool_calls: List[str] = []
        self.tokens = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "turn": self.index,
            "thinking": self.thinking,
            "reasoning_chars": self.reasoning_chars,
            "content_chars": self.content_chars,
            "tools": list(self.tool_calls),
            "tokens": self.tokens,
        }


async def run_loop(
    harness,
    user_input: str,
    session_id: str,
    event_callback,
    tool_calls_log: list,
    extra_blocks: Optional[List[str]] = None,
    model: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """执行 model-in-the-loop 主循环。

    返回：成功 → {"final", "turns", "guards", "trace", "pending_export"}；
          无法产出终稿（LLM 异常等）→ None，由上层回退 legacy 管线。
    """
    from app.models.llm import get_llm_with_tools

    t0 = time.time()
    guards = RunGuards(
        turns_max=AGENT_MAX_TURNS,
        token_budget=AGENT_TOKEN_BUDGET,
        wall_budget=AGENT_WALL_BUDGET,
        advisory_at=AGENT_ADVISORY_AT,
        start_time=t0,
    )

    blocks = list(extra_blocks or [])
    blocks.append(vf.build_fact_block([]))          # 初始事实块：明确"尚无写操作"
    system_prompt = compose_system_prompt(blocks)
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]

    trace: Dict[str, Any] = {"turns": [], "compactions": 0, "stopped_by": ""}
    draft = ""
    active_step = -1
    pending_export: Optional[str] = None
    plan_all_done = False
    closed_by = "model"        # model=模型自主终止 / turns|tokens|wall=宿主熔断

    for _ in range(guards.turns_max):
        state, advisory = guards.check()
        if state == "stop":
            closed_by = guards.stopped_by or "budget"
            break
        if advisory:
            messages.append({"role": "system", "content": advisory})

        # ── 窗口保护：超阈值先压缩早期轮次 ──
        if messages_tokens(messages) >= int(AGENT_CONTEXT_WINDOW * AGENT_COMPACT_AT):
            messages, did = await compact_messages(
                messages, AGENT_COMPACT_KEEP_TURNS, summarize=harness._call_llm,
            )
            if did:
                trace["compactions"] += 1

        # ── 每轮重建 schema：本步注册的 dyn_* 下一步即可见（与 T1.2 对齐）──
        schemas = build_tool_schemas(harness.tools, extra=[TODO_TOOL_SCHEMA])

        # ── thinking 分档：模型已把所有步骤标 done → 这一轮很可能在写终稿 ──
        thinking = AGENT_THINKING_FINAL if plan_all_done else AGENT_THINKING_DECISION
        turn = guards.tick_turn()
        rec = _TurnRecord(turn, thinking)

        try:
            resp = await get_llm_with_tools(
                sanitize_messages(messages), schemas, model=model, thinking=thinking,
            )
        except Exception as e:  # noqa: BLE001
            harness._log("error", f"[FC] 第{turn}轮 LLM 调用失败，运行时放弃: {e}")
            trace["stopped_by"] = "llm_error"
            return None

        guards.add_usage(resp.get("usage"))
        try:
            rec.tokens = int((resp.get("usage") or {}).get("total_tokens") or 0)
        except (TypeError, ValueError):
            rec.tokens = 0

        reasoning = (resp.get("reasoning_content") or "").strip()
        content = (resp.get("content") or "").strip()
        calls = resp.get("tool_calls") or []
        rec.reasoning_chars = len(reasoning)
        rec.content_chars = len(content)
        rec.tool_calls = [(c.get("function") or {}).get("name", "") for c in calls]
        trace["turns"].append(rec.as_dict())

        # 真实推理上屏（思考面板不再是"模型写的台词"，而是模型自己的推理）
        if reasoning:
            await ev.emit_thought(harness, event_callback, reasoning, step=turn)

        # ── 终止条件：模型不再请求工具 → 这条消息就是终稿 ──
        if not calls:
            draft = content
            closed_by = "model"
            harness._log("system", f"[FC] 模型自主终止于第 {turn} 轮（终稿 {len(content)} 字）")
            break

        if content:
            await ev.emit_thought(harness, event_callback, content, step=turn)
        messages.append(to_assistant_message(content, calls))
        plan_all_done = False   # 只要还在调工具，就不算收口

        # ── 执行工具 ──
        results, active_step, pend, plan_done, wrote = await _execute_calls(
            harness, calls, event_callback, session_id, tool_calls_log, active_step,
        )
        if pend:
            pending_export = pend
        plan_all_done = plan_done
        for call_id, obs in results:
            messages.append(to_tool_message(call_id, obs))
        # 写操作发生后刷新事实块，避免模型基于过时认知做完成态表述
        if wrote:
            messages.append({
                "role": "system",
                "content": vf.build_fact_block(_collect_facts(tool_calls_log, pending_export)),
            })
    else:
        # for 正常跑满（未 break）→ 视为熔断
        closed_by = closed_by if closed_by != "model" else "turns"
        guards.stopped_by = guards.stopped_by or "turns"

    # ── 熔断收口：给模型一次产出终稿的机会（宿主索要终稿 → thinking 关闭）──
    if not draft:
        try:
            close_msgs = messages + [{"role": "system", "content": _CLOSE_INSTRUCTION}]
            resp = await get_llm_with_tools(
                sanitize_messages(close_msgs), [], model=model, thinking=AGENT_THINKING_FINAL,
            )
            guards.add_usage(resp.get("usage"))
            draft = (resp.get("content") or "").strip()
            if draft:
                harness._log("system", f"[FC] 宿主收口产出终稿（{len(draft)} 字）")
        except Exception as e:  # noqa: BLE001
            harness._log("warn", f"[FC] 收口失败: {e}")

    if not draft:
        harness._log("system", "[FC] 运行时未产出终稿 → 交回上层回退")
        return None

    # ── 完成态核验：不符时把修正权交回模型（一次）──
    facts = _collect_facts(tool_calls_log, pending_export)
    missing = vf.scan_false_write_claims(draft, facts)
    if missing:
        harness._log("system", f"[FC] 完成态核验未通过（缺失：{missing}），交回模型自纠")
        try:
            fix_msgs = messages + [
                {"role": "assistant", "content": draft},
                {"role": "system", "content": vf.build_correction_instruction(missing, facts)},
            ]
            resp = await get_llm_with_tools(
                sanitize_messages(fix_msgs), [], model=model, thinking=AGENT_THINKING_FINAL,
            )
            guards.add_usage(resp.get("usage"))
            fixed = (resp.get("content") or "").strip()
            if fixed:
                draft = fixed
        except Exception as e:  # noqa: BLE001
            harness._log("warn", f"[FC] 完成态自纠失败（保留原稿并告警）: {e}")

    trace["stopped_by"] = closed_by
    snap = guards.snapshot()
    snap["stopped_by"] = closed_by
    harness._log(
        "system",
        f"[FC] 运行结束 轮次={snap['turns']} tokens={snap['tokens']} "
        f"耗时={snap['elapsed']}s 终止={closed_by} 压缩={trace['compactions']}",
    )
    return {
        "final": draft,
        "turns": snap["turns"],
        "guards": snap,
        "trace": trace,
        "pending_export": pending_export,
    }


# ───────────────────────── 工具执行 ─────────────────────────

async def _exec_one(
    harness, name: str, args: Dict[str, Any], call_id: str,
    event_callback, session_id: str, tool_calls_log: list, plan_index: int,
) -> str:
    """执行单个工具调用（统一的事件/记忆/轨迹/摘要处理）。

    与 legacy `_exec_one_action` 语义对齐，但**不再受步级工具集限制**（C1）。
    """
    harness._step_count += 1
    step = harness._step_count
    await ev.emit_tool_start(harness, event_callback, name, step, plan_index)
    harness.memory.add_action(session_id, name, str(args))
    try:
        observation = await harness._execute_tool(name, args, event_callback)
    except Exception as e:  # noqa: BLE001 - 工具层异常也回填为 observation（C3）
        observation = f"工具 '{name}' 执行异常：{e}"
    harness.memory.add_observation(session_id, observation)
    tool_calls_log.append({
        "step": step, "tool": name, "input": args, "result": observation,
    })
    if "Error:" in observation:
        harness._consecutive_tool_failures += 1
    else:
        harness._consecutive_tool_failures = 0
    harness._record_trajectory("", name, observation)
    summary = harness._summarize_tool_result(name, observation)
    await ev.emit_tool_end(harness, event_callback, name, step, summary, plan_index)
    return observation


async def _execute_calls(
    harness, calls: List[Dict[str, Any]], event_callback, session_id: str,
    tool_calls_log: list, active_step: int,
) -> Tuple[List[Tuple[str, str]], int, Optional[str], bool, bool]:
    """按模型给出的 tool_calls 逐个/并发执行。

    返回 (results, active_step, pending_export, plan_all_done, wrote)：
      results        → [(call_id, observation), ...]，供回填 messages（顺序与 calls 一致）
      active_step    → update_plan 声明的"进行中"步索引（供 Plan 面板点亮）
      pending_export → 待终稿产出后执行的导出格式（None 表示无）
      plan_all_done  → 模型是否已把所有步骤标记为 done（收口信号）
      wrote          → 本轮是否发生写操作（触发事实块刷新）
    """
    results: List[Tuple[str, str]] = []
    pending_export: Optional[str] = None
    plan_all_done = False
    wrote = False

    # ① update_plan 优先处理：它决定本轮 tool 事件的 plan_index
    deferred: List[Dict[str, Any]] = []
    for tc in calls:
        fn = tc.get("function") or {}
        if fn.get("name") == TODO_TOOL_NAME:
            args, err = parse_tool_arguments(fn.get("arguments"))
            if err:
                results.append((tc.get("id"), f"错误：{err}"))
                continue
            obs, idx = await handle_update_plan(harness, event_callback, args)
            _, statuses, _ = normalize_items(args)
            plan_all_done = bool(statuses) and all(s == "done" for s in statuses)
            if idx >= 0:
                active_step = idx
            results.append((tc.get("id"), obs))
        else:
            deferred.append(tc)

    # ② generate_doc：先过权限闸门，实际落文件推迟到终稿产出之后
    normal: List[Dict[str, Any]] = []
    for tc in deferred:
        fn = tc.get("function") or {}
        if fn.get("name") == "generate_doc":
            args, err = parse_tool_arguments(fn.get("arguments"))
            if err:
                results.append((tc.get("id"), f"错误：{err}"))
                continue
            gate = await harness._gate_tool("generate_doc", args, event_callback)
            if gate is not None:
                results.append((tc.get("id"), gate))
                continue
            fmt = str((args or {}).get("format") or (args or {}).get("fmt") or "word").lower()
            if fmt not in ("word", "pdf", "pptx"):
                fmt = "word"
            pending_export = fmt
            results.append((
                tc.get("id"),
                f"导出请求已受理（格式 {fmt}）：宿主会在终稿产出后生成文件并给出下载链接。",
            ))
        else:
            # 参数解析失败也要回填结构化错误（不让模型拿到空参数静默失败）
            args, err = parse_tool_arguments(fn.get("arguments"))
            if err:
                results.append((tc.get("id"), f"错误：工具 {fn.get('name')} {err}"))
                continue
            normal.append({"tc": tc, "name": fn.get("name"), "args": args})

    # ③ 并行分流：全部只读且开关开启 → gather；否则串行（高风险工具逐个走权限弹窗）
    can_parallel = (
        (AGENT_PARALLEL_READONLY or "1").strip() == "1"
        and len(normal) >= 2
        and len(normal) <= MAX_PARALLEL
        and all(is_readonly(item["name"]) for item in normal)
    )
    if can_parallel:
        harness._log("system", f"[FC] 并发执行 {len(normal)} 个只读工具")
        obs_list = await asyncio.gather(*[
            _exec_one(harness, item["name"], item["args"], item["tc"].get("id"),
                      event_callback, session_id, tool_calls_log, active_step)
            for item in normal
        ])
        for item, obs in zip(normal, obs_list):
            results.append((item["tc"].get("id"), obs))
    else:
        for item in normal:
            obs = await _exec_one(
                harness, item["name"], item["args"], item["tc"].get("id"),
                event_callback, session_id, tool_calls_log, active_step,
            )
            results.append((item["tc"].get("id"), obs))

    wrote = any(item["name"] in vf.FACT_KIND_BY_TOOL for item in normal)
    return results, active_step, pending_export, plan_all_done, wrote
