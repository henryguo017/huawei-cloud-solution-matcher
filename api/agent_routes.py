"""
Agent 对话端点 — POST /api/agent/chat (SSE, require_login)

将 app/agent SolutionAgent 的 ReAct 循环事件（step / thought / tool_start /
tool_end / final / final_answer / clarify）桥接为 SSE 流式推送，供前端 Agent
视图消费。

设计要点：
- 鉴权 require_login（get_current_user）：满足"Agent 与经典作用于同一账号"。
- 引擎事件经 asyncio.Queue 桥接为 SSE，避免回调内直接 yield 的协程冲突。
- 收尾 event:result 带 {answer, steps, elapsed, tool_calls, success} 供前端定稿。
- 客户端断开（前端 abort / 切换守卫中断）→ generator CancelledError → 取消
  Agent 任务，后端自然停止，配合前端 TaskGuard 中断形成完整反向链路。

2026-08-26 路由收拢：/agent/match、/agent/match/stream、/agent/clarify 三个路由
从 api/routes.py 迁入本文件（经典与 Agent 代码物理隔离）。共享辅助：
- _sse_json_default → api/sse_utils（两模式共用）
- _build_client_context_block → 仍留在 api/routes.py（依赖经典侧 4 个内部 helper），
  本文件单向 import（routes 不 import agent_routes，无循环）。
"""
import json
import os
import asyncio
import logging
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.auth_dependencies import get_current_user, require_login
from api.dependencies import get_usage_logger, get_achievement_service_dep
from api.models import MatchRequest, MatchResponse, ClarifyRequest, SourceDocument
from api.sse_utils import sse_json_default as _sse_json_default
from api.routes import _build_client_context_block
from app.agent import get_agent
from app.config import SSE_HEARTBEAT_ENABLED, SSE_HEARTBEAT_INTERVAL, SSE_TIMEOUT, MATCH_LLM_MODEL
from app.services.knowledge_base import set_kb_user_context

logger = logging.getLogger(__name__)

router = APIRouter()

# 本地工具名缓存（首次枚举后复用，避免每次请求重建 ToolRegistry）
_LOCAL_TOOL_NAMES = None


def _local_tool_names():
    global _LOCAL_TOOL_NAMES
    if _LOCAL_TOOL_NAMES is None:
        try:
            from app.agent.tools import create_default_tools
            _LOCAL_TOOL_NAMES = create_default_tools().get_tool_names()
        except Exception as e:  # pragma: no cover - 防御性
            logger.warning("[agent/tools] 本地工具枚举失败（已忽略）: %s", e)
            _LOCAL_TOOL_NAMES = []
    return _LOCAL_TOOL_NAMES


class AgentChatRequest(BaseModel):
    message: str
    session_id: str = ""
    client_id: Optional[int] = None  # 方案 B：客户上下文透传（前端选择器选定；后端暂透传，语义注入随 Plan A 推进）
    model: Optional[str] = None      # Agent 用户临时切换的模型（Pro/Flash），None 走 config 默认
    thinking: Optional[str] = None   # "enabled" 启用深度思考 / "disabled" 关闭；None 走 config 默认
    rerun_plan_index: Optional[int] = None  # P2-D5：Plan 单步重跑（后端从 _step_results 取原参数重跑该步并重新汇总）
    tool_permissions: Optional[dict] = None  # #3 工具权限策略 {tool: "allow"|"ask"|"deny"}，None 走 harness 默认
    disable_web_search: bool = False         # #6 联网搜索开关：True 时 Agent 不调用 web_search


@router.get("/agent/tools", tags=["Agent 工具发现"])
async def agent_tools(user: dict = Depends(get_current_user)):
    """P1-C 工具发现/调试只读端点（需登录）：返回本地工具数与已注册远端工具名。

    不暴露任何密钥（webhook/secret 等）；远端工具仅在 AGENT_MCP_CLIENT=1 且配置后才有列表。
    """
    remote = []
    try:
        from app.agent import mcp_client
        remote = mcp_client.get_registered_names()
    except Exception as e:  # pragma: no cover - 防御性
        logger.warning("[agent/tools] 远端工具枚举失败（已忽略）: %s", e)
    return {
        "local_tool_count": len(_local_tool_names()),
        "local_tool_names": _local_tool_names(),
        "remote_tool_names": remote,
        "mcp_enabled": (os.getenv("AGENT_MCP_CLIENT", "0") or "0").strip() == "1",
    }


@router.post("/agent/chat", tags=["Agent 对话"])
async def agent_chat(
    request: Request,
    body: AgentChatRequest,
    user: dict = Depends(get_current_user),
):
    user_id = user.get("id") or user.get("user_id") or "anon"
    session_id = body.session_id or f"agent_{user_id}"
    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message 不能为空")

    event_queue: "asyncio.Queue" = asyncio.Queue()

    async def emit(event: dict) -> None:
        await event_queue.put(event)

    async def run_agent() -> None:
        try:
            # 设置用户上下文：Agent 文件工具（list_dir/read_customer_file）依赖
            # get_kb_user_context()（ContextVar）判断登录态与用户目录
            if isinstance(user_id, int) and user_id > 0:
                from app.services.knowledge_base import set_kb_user_context
                set_kb_user_context(user_id)
            # 工具栏选择的模型/思考开关：透传到 harness（None 时走 config 默认）
            model_override = body.model if body.model else None
            thinking_override = body.thinking if body.thinking in ("enabled", "disabled") else None
            result = await get_agent().run(
                message,
                session_id=session_id,
                event_callback=emit,
                user_id=user_id,
                user_info=user,
                model=model_override,
                thinking=thinking_override,
                rerun_plan_index=body.rerun_plan_index,
                tool_permissions=body.tool_permissions,
                disable_web_search=body.disable_web_search,
            )
            await event_queue.put({
                "type": "result",
                "answer": result.get("answer", ""),
                "steps": result.get("steps"),
                "elapsed": result.get("elapsed"),
                "tool_calls": result.get("tool_calls", []),
                "success": result.get("success", False),
                "plan": result.get("plan") or [],           # P0：执行计划（前端 Plan 面板用）
                "format_mode": result.get("format_mode", "solution"),  # P0：导出时决定 report_type
                "plan_status": result.get("plan_status") or [],       # P1-1：plan 每步终态（result 后保留面板点亮）
                "reflexion_used": result.get("reflexion_used", False),     # P1-3：是否触发过反思
                "reflexion_success": result.get("reflexion_success", False),  # P1-3：反思是否成功注入
            })

            # P1 飞书/钉钉群机器人通知（按用户推送，默认关；仅 success 时触发；失败吞掉，不阻塞主链路）
            if result.get("success"):
                try:
                    from app.services.notify import notify_for_user
                    notify_for_user(
                        user_id,
                        demand=message,
                        share_payload={
                            "kind": "agent",
                            "title": (message or "Agent 方案")[:60],
                            "demand": message,
                            "solution": result.get("answer", ""),
                            "industry": "",
                            "sources": [],
                            "created_at": datetime.now().isoformat(),
                        },
                    )
                except Exception as _nerr:
                    logger.warning("[agent/chat] 通知发送失败（已忽略）: %s", _nerr)
        except Exception as e:
            logger.exception("[agent/chat] 运行失败 session=%s", session_id)
            await event_queue.put({"type": "error", "message": str(e)})
        finally:
            await event_queue.put(None)  # 结束哨兵

    async def generate():
        task = asyncio.create_task(run_agent())
        try:
            while True:
                event = await event_queue.get()
                if event is None:
                    break
                yield (
                    f"event: {event.get('type', 'message')}\n"
                    f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                )
        except asyncio.CancelledError:
            # 客户端断开（前端 abort / 切换守卫中断）→ 取消 Agent 任务，后端自然停止
            task.cancel()
            raise
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
# ========== Agent 智能匹配（单 Agent + Tool Calling） ==========

@router.delete("/agent/memory", tags=["Agent 记忆"])
async def clear_agent_memory(user: dict = Depends(get_current_user)):
    """P2-2：清空当前用户的长程情景记忆（agent_episodes）。"""
    try:
        from app.agent.memory_profiles import clear_episodes, count_episodes
        uid = user.get("id") or user.get("user_id") or 0
        before = count_episodes(uid)
        removed = clear_episodes(uid)
        return {"ok": True, "removed": removed, "before": before}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"清空记忆失败: {e}")


@router.get("/agent/memory/stats", tags=["Agent 记忆"])
async def agent_memory_stats(user: dict = Depends(get_current_user)):
    """P2-2：查询当前用户长程情景记忆条数（设置页展示用）。"""
    try:
        from app.agent.memory_profiles import count_episodes
        uid = user.get("id") or user.get("user_id") or 0
        return {"ok": True, "episodes": count_episodes(uid)}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"查询记忆失败: {e}")


# ========== Agent 工具栏能力（上下文用量 / 提示词优化 / 工具权限确认） ==========

@router.get("/agent/context-usage", tags=["Agent 上下文"])
async def agent_context_usage(session_id: str = "", user: dict = Depends(get_current_user)):
    """#1 上下文用量预估：返回 system/tools/memory/conversation 各桶 token 估算与总占用百分比。"""
    try:
        from app.agent import get_agent
        uid = user.get("id") or user.get("user_id") or 0
        sid = session_id or f"agent_{uid}"
        agent = get_agent()
        if uid and isinstance(uid, int):
            try:
                from app.services.knowledge_base import set_kb_user_context
                set_kb_user_context(uid)
            except Exception:
                pass
            agent._user_id = uid
        data = agent.harness.estimate_context_usage(sid)
        return {"ok": True, **data}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"上下文用量统计失败: {e}")


class EnhancePromptRequest(BaseModel):
    prompt: str
    session_id: str = ""


@router.post("/agent/enhance-prompt", tags=["Agent 提示词"])
async def agent_enhance_prompt(
    body: EnhancePromptRequest,
    user: dict = Depends(get_current_user),
):
    """#2 提示词优化：把用户原始诉求改写为更清晰、结构化、可执行的指令，便于 Agent 检索与生成。"""
    raw = (body.prompt or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="prompt 不能为空")
    if len(raw) > 2000:
        raw = raw[:2000]
    optimizer_prompt = (
        "你是华为云售前方案助手的「提示词优化器」。请把用户的原始诉求改写为更清晰、结构化、可执行的指令，"
        "让方案 Agent 能更精准地检索知识库、匹配竞品并生成落地方案。\n"
        "改写要求：\n"
        "1. 若原话缺失行业/场景/规模/目标，基于常识合理补全，并用 [假设: ...] 标注你的推断；\n"
        "2. 用一句话明确「希望得到什么产出」（如方案书/竞品对比/架构建议）；\n"
        "3. 保留用户原意，不擅自扩大范围，不添加无关要求；\n"
        "4. 输出语言与用户输入一致（中文需求用中文输出）；\n"
        "5. 只输出优化后的提示词本身，不要任何解释、不要代码围栏、不要前缀。\n\n"
        f"原始提示词：\n\"\"\"\n{raw}\n\"\"\"\n\n优化后提示词："
    )
    try:
        from app.models.llm import get_llm_response
        enhanced = await get_llm_response(optimizer_prompt, model=MATCH_LLM_MODEL)
        enhanced = (enhanced or "").strip()
        # 去除可能的代码围栏（模型偶有违规包裹）
        if enhanced.startswith("```"):
            enhanced = enhanced.strip("`")
            if enhanced.startswith("json") or enhanced.startswith("markdown") or enhanced.startswith("text"):
                enhanced = enhanced.split("\n", 1)[-1] if "\n" in enhanced else enhanced
            enhanced = enhanced.strip("`").strip()
        if not enhanced:
            return {"ok": True, "enhanced": raw, "unchanged": True}
        return {"ok": True, "enhanced": enhanced, "unchanged": False}
    except Exception as e:
        logger.warning("[agent/enhance-prompt] 优化失败: %s", e)
        # 优化失败不阻断用户：原样返回，前端按原 prompt 发送
        return {"ok": True, "enhanced": raw, "unchanged": True, "error": str(e)}


class PermissionDecisionRequest(BaseModel):
    decision: str  # "allow" | "deny"


@router.post("/agent/permission/{request_id}", tags=["Agent 权限"])
async def agent_permission_resolve(request_id: str, body: PermissionDecisionRequest):
    """#3 工具权限确认：前端用户点击「允许/拒绝」后回传决策，唤醒 Agent 阻塞的 Future。"""
    try:
        from app.agent.permission_gate import resolve_permission
        hit = resolve_permission(request_id, body.decision or "deny")
        return {"ok": True, "hit": hit}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"权限确认失败: {e}")


def _resolve_agent_session_id(user: dict, client_id: Optional[int]) -> str:
    """Agent 记忆的 session_id：提供 client_id 时按 用户:客户 维度隔离，避免多客户串味；否则沿用全局（按用户）。"""
    if client_id:
        return f"{user['id']}:{client_id}"
    return str(user['id'])


async def _process_and_emit_agent_result(queue, result: dict, user: dict, original_demand: str, is_quick_demo: bool, group_id=None, client_id=None, client_context_meta: Optional[dict] = None):
    """
    Agent 流式结束后统一处理：保存历史（含版本化）、成就检测、提取来源文档、推送 result 事件。
    供 /agent/match/stream 与 /agent/clarify 共用，单一事实来源避免逻辑分叉。

    - 澄清暂停（result.paused=True）：不保存历史、不触发成就，直接下发 result（前端据此保留提问卡等待作答）；
    - 正常完成：保存历史并回填版本元信息(group_id/version/is_final/title)到 result。
    """
    # 澄清暂停或会话过期：不落库、不触发成就，直接下发 result 事件
    if result.get("paused") or result.get("expired"):
        result["newly_unlocked"] = []
        result["history_id"] = None
        result["source_documents"] = []
        await queue.put({"type": "result", "data": result})
        return

    history_id = None
    if user and user.get('id'):
        try:
            usage_logger = get_usage_logger()
            usage_logger.log_match(original_demand or "", user_id=user['id'], mode="agent")
            # 提取行业信息
            industry_hint = ""
            for tc in result.get("tool_calls", []):
                if tc.get("tool") in ("search_kb", "search_competitor") and tc.get("result"):
                    try:
                        rd = json.loads(tc["result"]) if isinstance(tc["result"], str) else tc["result"]
                        for doc in rd.get("results", []):
                            ind = doc.get("industry", "")
                            if ind:
                                industry_hint = ind
                                break
                    except Exception:
                        pass
                if industry_hint:
                    break
            history_id = usage_logger.save_match_history(
                demand_text=original_demand or "",
                solution=result.get("answer", ""),
                industry=industry_hint,
                sources=[],
                user_id=user['id'],
                group_id=group_id,
                client_id=client_id,
            )
            # 回填版本元信息
            meta = usage_logger.get_match_history_meta(history_id, user_id=user['id'])
            if meta:
                result["group_id"] = meta["group_id"]
                result["version"] = meta["version"]
                result["is_final"] = meta["is_final"]
                result["title"] = meta["title"]
        except Exception as log_err:
            logger.warning(f"[Agent SSE] 保存历史失败: {log_err}")

    # ── 成就检测 ──
    newly_unlocked = []
    if user and user.get('id') and not is_quick_demo:
        try:
            achievement_svc = get_achievement_service_dep()
            industry_hint = ""
            for tc in result.get("tool_calls", []):
                if tc.get("tool") in ("search_kb", "search_competitor") and tc.get("result"):
                    try:
                        rd = json.loads(tc["result"]) if isinstance(tc["result"], str) else tc["result"]
                        for doc in rd.get("results", []):
                            ind = doc.get("industry", "")
                            if ind:
                                industry_hint = ind
                                break
                    except Exception:
                        pass
                if industry_hint:
                    break
            newly_unlocked = achievement_svc.check_after_match(
                user_id=user['id'],
                demand_text=original_demand,
                mode="agent",
                industry=industry_hint,
            )
        except Exception as ach_err:
            logger.warning(f"[Agent SSE] 成就检测失败: {ach_err}")

    result["newly_unlocked"] = newly_unlocked
    result["history_id"] = history_id
    result["client_context_used"] = client_context_meta

    # 从 tool_calls 中提取 source_documents（与非流式 /agent/match 保持一致）
    _sdocs = []
    for _tc in result.get("tool_calls", []):
        if _tc.get("tool") in ("search_kb", "search_competitor") and _tc.get("result"):
            try:
                _rd = json.loads(_tc["result"]) if isinstance(_tc["result"], str) else _tc["result"]
                for _d in _rd.get("results", []):
                    _sdocs.append(SourceDocument(
                        page_content=_d.get("content", ""),
                        metadata={
                            "source": _d.get("source", ""),
                            "industry": _d.get("industry", ""),
                        }
                    ).model_dump())
            except (json.JSONDecodeError, TypeError):
                pass
    result["source_documents"] = _sdocs

    await queue.put({"type": "result", "data": result})


@router.post("/agent/match", response_model=MatchResponse, tags=["解决方案匹配"])
async def agent_match_solution(
    request: MatchRequest,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    user: dict = Depends(require_login)
):
    """
    Agent 智能匹配接口（ReAct + Tool Calling）

    先分析意图，再检索知识库，最后生成方案——适合模糊输入场景。
    """
    try:
        # 设置用户上下文，Agent 工具可使用用户独立知识库
        user_id = user['id']
        set_kb_user_context(user_id)

        # 保存原始 demand（用于成就检测，不被默认 prompt 覆盖）
        original_demand = request.demand

        # 空输入处理
        if not request.demand or not request.demand.strip():
            request.demand = "（用户未输入需求，请介绍华为云的核心解决方案和产品体系）"
            logger.info("[Agent] 检测到空输入，使用默认 prompt")

        agent = get_agent()
        session_id = _resolve_agent_session_id(user, request.client_id)

        # 方案 A：关联客户时构造『背景 + 历史方案』上下文
        client_block, client_meta = "", None
        if request.client_id and user_id > 0:
            client_block, client_meta = await _build_client_context_block(
                request.client_id, user_id, request.demand
            )

        # 阶段1：把上传的客户文件路径注入 Agent，引导其用 read_customer_file 读取
        extra_context = ""
        if request.customer_files:
            file_list = "\n".join(f"- {p}" for p in request.customer_files)
            extra_context = (
                "\n\n[用户上传了以下客户资料文件，请务必先用 read_customer_file 工具逐一读取并提取需求要点，"
                "再综合生成方案]\n" + file_list
            )
            logger.info(f"[Agent] 注入 {len(request.customer_files)} 个客户资料文件路径")

        # 方案 A：把客户背景上下文拼进 Agent 提示词（不与文件注入冲突）
        if client_block:
            extra_context = (extra_context + "\n\n" if extra_context else "") + client_block

        result = await agent.run(
            user_input=request.demand,
            session_id=str(session_id),
            extra_context=extra_context,
            user_id=user.get('id') if user else None,
            user_info=user,
        )

        # 阶段2：后台异步更新用户画像（best-effort，不阻断主响应）
        background_tasks.add_task(agent.update_user_profile, user['id'], str(session_id))

        answer = result.get("answer", "Agent 未能生成有效方案")
        tool_calls = result.get("tool_calls", [])
        steps = result.get("steps", 0)

        # 从工具调用中提取 source_documents
        source_docs = []
        for tc in tool_calls:
            if tc.get("tool") in ("search_kb", "search_competitor") and tc.get("result"):
                try:
                    result_data = json.loads(tc["result"]) if isinstance(tc["result"], str) else tc["result"]
                    for doc in result_data.get("results", []):
                        source_docs.append(SourceDocument(
                            page_content=doc.get("content", ""),
                            metadata={
                                "source": doc.get("source", ""),
                                "industry": doc.get("industry", ""),
                            }
                        ))
                except (json.JSONDecodeError, TypeError):
                    pass  # 无法解析的跳过

        logger.info(f"[Agent] 匹配完成: {steps} 步, {len(tool_calls)} 次工具调用")

        # 记录使用日志
        history_id = None
        if user and user.get('id'):
            try:
                usage_logger = get_usage_logger()
                usage_logger.log_match(original_demand or "", user_id=user['id'], mode="agent")
                industry_hint = ""
                for doc in source_docs:
                    ind = doc.metadata.get("industry", "")
                    if ind:
                        industry_hint = ind
                        break
                history_id = usage_logger.save_match_history(
                    demand_text=original_demand or "",
                    solution=answer,
                    industry=industry_hint,
                    sources=[{"source": d.metadata.get("source", ""), "industry": d.metadata.get("industry", "")} for d in source_docs],
                    user_id=user['id'],
                    client_id=request.client_id,
                )
            except Exception as log_err:
                logger.warning(f"[Agent] 保存历史失败: {log_err}")

        # 成就检测（Agent 模式）
        achievement_result = []
        if user and user.get('id') and not request.is_quick_demo:
            try:
                achievement_svc = get_achievement_service_dep()
                industry_hint = ""
                for doc in source_docs:
                    ind = doc.metadata.get("industry", "")
                    if ind:
                        industry_hint = ind
                        break
                achievement_result = achievement_svc.check_after_match(
                    user_id=user['id'],
                    demand_text=original_demand,
                    mode="agent",
                    industry=industry_hint,
                )
            except Exception as ach_err:
                logger.warning(f"[Agent] 成就检测失败: {ach_err}")

        return MatchResponse(
            answer=answer,
            source_documents=source_docs,
            solution_json=result.get("solution_json"),
            history_id=history_id,
            newly_unlocked=achievement_result if user and user.get('id') else None,
            client_context_used=client_meta,
        )
    except Exception as e:
        logger.error(f"[Agent] 智能匹配失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent 匹配失败: {str(e)}"
        )


# ========== Agent SSE 流式匹配（实时进度推送） ==========

@router.post("/agent/match/stream", tags=["解决方案匹配"])
async def agent_match_stream(
    request: MatchRequest,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    user: dict = Depends(require_login)
):
    """
    Agent 智能匹配 SSE 流式接口

    通过 Server-Sent Events 实时推送 ReAct 循环的每一步进度：
    - event: step     → 新步骤开始
    - event: tool_start → 开始执行工具
    - event: tool_end   → 工具执行完成
    - event: final      → Agent 完成
    - event: result     → 最终结果（answer, steps, elapsed, tool_calls）
    """
    session_id = _resolve_agent_session_id(user, request.client_id)

    async def generate():
        queue: asyncio.Queue = asyncio.Queue()

        async def event_callback(event):
            await queue.put(event)

        async def run_agent():
            try:
                # 设置用户上下文，Agent 工具可使用用户独立知识库
                set_kb_user_context(user['id'])

                # 保存原始 demand（用于成就检测，不被默认 prompt 覆盖）
                original_demand = request.demand

                # 空输入处理
                if not request.demand or not request.demand.strip():
                    request.demand = "（用户未输入需求，请介绍华为云的核心解决方案和产品体系）"

                agent = get_agent()

                # 方案 A：关联客户时构造『背景 + 历史方案』上下文
                client_block, client_meta = "", None
                if request.client_id and user.get('id'):
                    client_block, client_meta = await _build_client_context_block(
                        request.client_id, user['id'], request.demand
                    )

                # 阶段1：注入客户文件路径，引导 Agent 用 read_customer_file 读取
                extra_context = ""
                if request.customer_files:
                    file_list = "\n".join(f"- {p}" for p in request.customer_files)
                    extra_context = (
                        "\n\n[用户上传了以下客户资料文件，请务必先用 read_customer_file 工具逐一读取并提取需求要点，"
                        "再综合生成方案]\n" + file_list
                    )

                # 方案 A：把客户背景上下文拼进 Agent 提示词
                if client_block:
                    extra_context = (extra_context + "\n\n" if extra_context else "") + client_block

                result = await agent.run(
                    user_input=request.demand,
                    session_id=session_id,
                    extra_context=extra_context,
                    event_callback=event_callback,
                    user_id=user.get('id') if user else None,
                    user_info=user,
                )

                # 阶段2：后台异步更新用户画像（best-effort，不阻断流式响应）
                if user and user.get('id'):
                    background_tasks.add_task(agent.update_user_profile, user['id'], session_id)

                # ── 统一后处理：保存历史（含版本化）+ 成就检测 + 来源文档 + 下发 result ──
                await _process_and_emit_agent_result(
                    queue, result, user, original_demand, request.is_quick_demo,
                    group_id=request.group_id,
                    client_id=request.client_id,
                    client_context_meta=client_meta,
                )
            except Exception as e:
                logger.error(f"[Agent SSE] 执行失败: {e}")
                await queue.put({"type": "error", "message": str(e)})
            finally:
                try:
                    await queue.put(None)  # 结束信号
                except Exception:
                    pass

        task = asyncio.ensure_future(run_agent())

        start_time = time.time()
        try:
            while True:
                if SSE_HEARTBEAT_ENABLED:
                    # 受控路径：心跳保活 + 超时主动结束（防止悬挂连接拖垮 worker）
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_INTERVAL)
                    except asyncio.TimeoutError:
                        if time.time() - start_time > SSE_TIMEOUT:
                            logger.info("[Agent SSE] 流式超过超时上限,主动结束")
                            break
                        yield ": ping\n\n"  # SSE 注释行,客户端忽略,仅保活
                        continue
                else:
                    # 默认路径：与原行为完全一致
                    event = await queue.get()
                if event is None:
                    break
                event_type = event.get("type", "message")
                yield f"event: {event_type}\ndata: {json.dumps(event, ensure_ascii=False, default=_sse_json_default)}\n\n"
        except asyncio.CancelledError:
            logger.info("[Agent SSE] 客户端断开连接")
            task.cancel()
        except Exception as gen_err:
            logger.error(f"[Agent SSE] 生成器异常(连接将中断): {gen_err}")
            try:
                yield f"event: error\ndata: {json.dumps({'type':'error','message':f'内部错误: {gen_err}'}, ensure_ascii=False)}\n\n"
            except Exception:
                pass
        finally:
            await task

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        background=background_tasks,
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        },
    )


@router.post("/agent/clarify", tags=["解决方案匹配"])
async def agent_clarify(
    request: ClarifyRequest,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    user: dict = Depends(require_login)
):
    """
    Agent 交互式澄清续跑接口（阶段 2.5）

    用户回答完 Agent 暂停时提出的问题后，带上 clarify_id 与答案调此接口，
    后端恢复到暂停时的 ReAct 循环状态，把答案作为 Observation 接回并继续生成方案（不是重头再来）。
    """
    session_id = _resolve_agent_session_id(user, request.client_id)

    async def generate():
        queue: asyncio.Queue = asyncio.Queue()

        async def event_callback(event):
            await queue.put(event)

        async def run_agent():
            result_emitted = False
            try:
                from app.agent.clarify_store import ClarifySessionStore
                set_kb_user_context(user['id'])
                agent = get_agent()

                # 恢复原始需求（用于历史落库与成就检测）
                state = ClarifySessionStore.get(request.clarify_id)
                original_demand = state.get("user_input", "") if state else ""

                logger.info(f"[Agent Clarify] 续跑开始 clarify_id={request.clarify_id} answers_count={len(request.answers or [])}")

                result = await agent.run(
                    user_input="",
                    session_id=session_id,
                    event_callback=event_callback,
                    clarify_id=request.clarify_id,
                    answers=request.answers,
                    user_id=user.get('id') if user else None,
                    user_info=user,
                )

                logger.info(f"[Agent Clarify] agent.run 返回 success={result.get('success')} paused={result.get('paused')} expired={result.get('expired')}")

                if user and user.get('id'):
                    background_tasks.add_task(agent.update_user_profile, user['id'], session_id)

                # 安全包装：即使落库/成就检测失败，也保证发出 result 事件
                try:
                    await _process_and_emit_agent_result(
                        queue, result, user, original_demand, is_quick_demo=False, group_id=None,
                        client_id=request.client_id,
                    )
                    result_emitted = True
                except Exception as proc_err:
                    logger.warning(f"[Agent Clarify] 落库处理失败（仍下发结果）: {proc_err}")
                    result["newly_unlocked"] = []
                    result["history_id"] = None
                    result["source_documents"] = []
                    await queue.put({"type": "result", "data": result})
                    result_emitted = True

            except asyncio.CancelledError:
                logger.warning("[Agent Clarify] 任务被取消")
                await queue.put({"type": "error", "message": "请求被取消"})
                result_emitted = True
            except Exception as e:
                logger.error(f"[Agent Clarify] 执行失败: {e}", exc_info=True)
                await queue.put({"type": "error", "message": str(e)})
                result_emitted = True
            finally:
                if not result_emitted:
                    logger.error("[Agent Clarify] 未发出任何结果事件！发送兜底错误")
                    try:
                        await queue.put({"type": "error", "message": "内部异常：未生成结果"})
                    except Exception:
                        pass
                try:
                    await queue.put(None)
                except Exception:
                    pass

        task = asyncio.ensure_future(run_agent())

        start_time = time.time()
        try:
            while True:
                if SSE_HEARTBEAT_ENABLED:
                    # 受控路径：心跳保活 + 超时主动结束（防止悬挂连接拖垮 worker）
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_INTERVAL)
                    except asyncio.TimeoutError:
                        if time.time() - start_time > SSE_TIMEOUT:
                            logger.info("[Agent Clarify] 流式超过超时上限,主动结束")
                            break
                        yield ": ping\n\n"  # SSE 注释行,客户端忽略,仅保活
                        continue
                else:
                    # 默认路径：与原行为完全一致
                    event = await queue.get()
                if event is None:
                    break
                event_type = event.get("type", "message")
                yield f"event: {event_type}\ndata: {json.dumps(event, ensure_ascii=False, default=_sse_json_default)}\n\n"
        except asyncio.CancelledError:
            logger.info("[Agent Clarify] 客户端断开连接")
            task.cancel()
        except Exception as gen_err:
            logger.error(f"[Agent Clarify] 生成器异常: {gen_err}")
            try:
                yield f"event: error\ndata: {json.dumps({'type':'error','message':f'内部错误: {gen_err}'}, ensure_ascii=False)}\n\n"
            except Exception:
                pass
        finally:
            await task

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        background=background_tasks,
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )