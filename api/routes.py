from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from fastapi import UploadFile, File
from api.models import (
    MatchRequest, MatchResponse,
    AnalyzeRequest, AnalyzeResponse,
    KnowledgeStatsResponse, RebuildResponse, ClearResponse,
    HealthResponse, SourceDocument,
    DashboardStatsResponse,
    MatchHistoryListResponse, MatchHistoryItem, MatchHistoryDetail, CompareRequest, CompareResponse,
    CompareSummaryRequest, CompareSummaryResponse,
    RefineSolutionRequest, RefineSolutionResponse,
    UpdateSolutionRequest, UpdateSolutionResponse,
    RefineCompetitorRequest, RefineCompetitorResponse,
    CompetitorHistoryListResponse, CompetitorHistoryItem, CompetitorHistoryDetail,
    KBDocumentListResponse, KBDocumentContentResponse,
    KBDocumentCreateRequest, KBDocumentCreateResponse,
    KBDocumentUpdateRequest, KBDocumentUpdateResponse,
    KBDocumentDeleteResponse, KBDocumentReindexResponse,
)
from api.dependencies import (
    get_solution_matcher,
    get_competitor_analyzer,
    get_knowledge_base,
    get_usage_logger,
    get_achievement_service_dep,
    get_user_knowledge_base,
    get_solution_matcher_for_user,
    get_competitor_analyzer_for_user,
)
from app.models.llm import get_llm_response
from app.services.solution_matcher import SolutionMatcherService
from app.services.competitor_analyzer import CompetitorAnalyzerService
from app.services.knowledge_base import KnowledgeBaseService, set_kb_user_context
from app.services.usage_logger import UsageLoggerService
from app.config import APP_NAME, APP_VERSION, USER_DOCS_BASE_DIR
from app.agent.parsers.read_file import ALLOWED_EXT
from typing import Optional
import os
import json
import asyncio
import logging

from api.auth_dependencies import get_current_user, get_current_user_optional

# Agent 模块导入
from app.agent import SolutionAgent, get_agent

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/health", response_model=HealthResponse, tags=["系统"])
async def health_check():
    """
    健康检查接口
    """
    try:
        kb_service = get_knowledge_base()
        kb_stats = kb_service.get_stats()
        
        return HealthResponse(
            status="healthy",
            version=APP_VERSION,
            services={
                "knowledge_base": True,
                "solution_matcher": True,
                "competitor_analyzer": True,
                "vector_db": kb_stats["total_documents"] > 0
            }
        )
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        return HealthResponse(
            status="unhealthy",
            version=APP_VERSION,
            services={
                "knowledge_base": False,
                "solution_matcher": False,
                "competitor_analyzer": False,
                "vector_db": False
            }
        )

@router.post("/match", response_model=MatchResponse, tags=["解决方案匹配"])
async def match_solution(
    request: MatchRequest,
    user: Optional[dict] = Depends(get_current_user_optional)
):
    """
    解决方案智能匹配接口
    
    - **demand**: 客户需求描述（1-5000字符）
    
    即使知识库为空，AI也会基于华为云产品体系给出建议
    """
    try:
        # 使用用户独立知识库（登录用户）；匿名用户使用全局知识库
        user_id = user.get('id') if user else 0
        matcher = get_solution_matcher_for_user(user_id) if user_id > 0 else get_solution_matcher()

        # 保存原始 demand（用于成就检测，不被默认 prompt 覆盖）
        original_demand = request.demand

        # 空输入处理：用于"无声胜有声"隐藏成就，给 LLM 一个默认 prompt
        if not request.demand or not request.demand.strip():
            request.demand = "（用户未输入需求，请介绍华为云的核心解决方案和产品体系）"
            logger.info("检测到空输入，使用默认 prompt")

        # 阶段1：把上传的客户资料文本并入需求（标准/向导模式直接消费，不丢失文件内容）
        enriched_demand = request.demand
        if request.customer_files:
            file_text = _read_customer_files_text(user_id, request.customer_files)
            if file_text:
                enriched_demand = (
                    f"[用户上传的客户资料]\n{file_text}\n[/用户上传的客户资料]\n\n"
                    f"{request.demand}"
                )
                logger.info(f"[匹配] 已并入 {len(request.customer_files)} 个客户资料文件")

        result = await matcher.match(enriched_demand)
        
        source_docs = [
            SourceDocument(
                page_content=doc.page_content,
                metadata=doc.metadata
            )
            for doc in result.get("source_documents", [])
        ]
        
        logger.info("解决方案匹配成功")
        
        # 保存到历史记录 + 记录使用日志（仅登录用户）
        history_id = None
        if user and user.get('id'):
            try:
                usage_logger = get_usage_logger()
                # 使用原始 demand 记录（空输入不会被默认 prompt 覆盖）
                usage_logger.log_match(original_demand or "", user_id=user['id'], mode=request.mode)
            except Exception as log_err:
                logger.warning(f"记录使用日志失败: {log_err}")

            try:
                usage_logger = get_usage_logger()
                industry_hint = ""
                try:
                    for doc in result.get("source_documents", []):
                        if hasattr(doc, "metadata") and doc.metadata:
                            ind = doc.metadata.get("industry", "")
                            if ind:
                                industry_hint = ind
                                break
                except:
                    pass
                history_id = usage_logger.save_match_history(
                    demand_text=original_demand or "",
                    solution=result["answer"],
                    industry=industry_hint,
                    sources=[{"source": d.metadata.get("source", ""), "industry": d.metadata.get("industry", "")} for d in result.get("source_documents", [])],
                    user_id=user['id']
                )
            except Exception as hist_err:
                logger.warning(f"保存匹配历史记录失败: {hist_err}")

        # 成就检测
        achievement_result = []
        if user and user.get('id') and not request.is_quick_demo:
            try:
                achievement_svc = get_achievement_service_dep()
                industry_hint = ""
                try:
                    for doc in result.get("source_documents", []):
                        if hasattr(doc, "metadata") and doc.metadata:
                            ind = doc.metadata.get("industry", "")
                            if ind:
                                industry_hint = ind
                                break
                except:
                    pass
                achievement_result = achievement_svc.check_after_match(
                    user_id=user['id'],
                    demand_text=original_demand,
                    mode=request.mode if hasattr(request, 'mode') else "standard",
                    industry=industry_hint,
                )
            except Exception as ach_err:
                logger.warning(f"成就检测失败: {ach_err}")

        return MatchResponse(
            answer=result["answer"],
            source_documents=source_docs,
            solution_json=result.get("solution_json"),
            history_id=history_id,
            newly_unlocked=achievement_result if user and user.get('id') else None
        )
    except Exception as e:
        logger.error(f"解决方案匹配失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"匹配失败: {str(e)}"
        )
    
# ========== 客户资料文件上传（阶段1） ==========

@router.post("/upload/customer-file", tags=["文件交互"])
async def upload_customer_file(
    file: UploadFile = File(...),
    user: Optional[dict] = Depends(get_current_user),
):
    """
    上传客户资料文件到用户白名单目录 data/user_docs/{user_id}/customer_uploads/。

    校验：扩展名白名单 + 单文件 ≤100MB。返回相对路径供匹配接口使用。
    最多同时上传 10 个由前端控制；并发安全（每次独立写）。
    """
    try:
        user_id = user.get('id') if user else None
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录后再上传")

        # 扩展名白名单校验
        ext = os.path.splitext(file.filename or "")[1].lower()
        if ext not in ALLOWED_EXT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"不支持的文件格式: {ext}（仅支持 {', '.join(sorted(ALLOWED_EXT))}）"
            )

        # 读取内容并校验大小（单文件 ≤100MB）
        data = await file.read()
        max_bytes = 100 * 1024 * 1024
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"文件超过 100MB 上限（当前 {len(data) // (1024 * 1024)}MB）"
            )

        # 安全落盘（仅限用户白名单目录）
        from app.agent.file_security import safe_upload_path, ensure_user_dirs
        ensure_user_dirs(user_id)
        save_path = safe_upload_path(user_id, file.filename)
        with open(save_path, "wb") as f:
            f.write(data)

        rel = os.path.relpath(save_path, os.path.join(USER_DOCS_BASE_DIR, str(user_id)))
        logger.info(f"[Upload] 用户 {user_id} 上传文件: {rel} ({len(data)} bytes)")
        return {
            "success": True,
            "filename": os.path.basename(save_path),
            "path": rel,
            "size": len(data),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Upload] 上传失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"上传失败: {str(e)}"
        )


# ========== 客户文件辅助（阶段1） ==========

def _read_customer_files_text(user_id: int, paths: list) -> str:
    """
    读取用户上传的客户资料文件，合并为纯文本。
    任一文件失败不影响其余（返回 Error 说明）。用于标准/向导模式直接注入需求。
    """
    if not paths:
        return ""
    from app.agent.file_security import safe_resolve
    from app.agent.parsers.read_file import extract_text
    parts = []
    for p in paths:
        try:
            abs_path = safe_resolve(user_id, p)
        except ValueError as e:
            parts.append(f"[文件 {p} 跳过: {e}]")
            continue
        if not os.path.exists(abs_path):
            parts.append(f"[文件 {p} 跳过: 不存在]")
            continue
        text = extract_text(abs_path)
        parts.append(f"===== 客户资料：{p} =====\n{text}")
    return "\n\n".join(parts)


# ========== Agent 智能匹配（单 Agent + Tool Calling） ==========

@router.post("/agent/match", response_model=MatchResponse, tags=["解决方案匹配"])
async def agent_match_solution(
    request: MatchRequest,
    user: Optional[dict] = Depends(get_current_user_optional)
):
    """
    Agent 智能匹配接口（ReAct + Tool Calling）

    先分析意图，再检索知识库，最后生成方案——适合模糊输入场景。
    """
    try:
        # 设置用户上下文，Agent 工具可使用用户独立知识库
        user_id = user.get('id') if user else 0
        if user_id > 0:
            set_kb_user_context(user_id)

        # 保存原始 demand（用于成就检测，不被默认 prompt 覆盖）
        original_demand = request.demand

        # 空输入处理
        if not request.demand or not request.demand.strip():
            request.demand = "（用户未输入需求，请介绍华为云的核心解决方案和产品体系）"
            logger.info("[Agent] 检测到空输入，使用默认 prompt")

        agent = get_agent()
        session_id = user.get('id', 'anonymous') if user else 'anonymous'

        # 阶段1：把上传的客户文件路径注入 Agent，引导其用 read_customer_file 读取
        extra_context = ""
        if request.customer_files:
            file_list = "\n".join(f"- {p}" for p in request.customer_files)
            extra_context = (
                "\n\n[用户上传了以下客户资料文件，请务必先用 read_customer_file 工具逐一读取并提取需求要点，"
                "再综合生成方案]\n" + file_list
            )
            logger.info(f"[Agent] 注入 {len(request.customer_files)} 个客户资料文件路径")

        result = await agent.run(
            user_input=request.demand,
            session_id=str(session_id),
            extra_context=extra_context,
        )

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
                    user_id=user['id']
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
            newly_unlocked=achievement_result if user and user.get('id') else None
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
    user: Optional[dict] = Depends(get_current_user_optional)
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
    session_id = str(user.get('id', 'anonymous')) if user else 'anonymous'

    async def generate():
        queue: asyncio.Queue = asyncio.Queue()

        async def event_callback(event):
            await queue.put(event)

        async def run_agent():
            try:
                # 设置用户上下文，Agent 工具可使用用户独立知识库
                if user and user.get('id'):
                    set_kb_user_context(user['id'])

                # 保存原始 demand（用于成就检测，不被默认 prompt 覆盖）
                original_demand = request.demand

                # 空输入处理
                if not request.demand or not request.demand.strip():
                    request.demand = "（用户未输入需求，请介绍华为云的核心解决方案和产品体系）"

                agent = get_agent()

                # 阶段1：注入客户文件路径，引导 Agent 用 read_customer_file 读取
                extra_context = ""
                if request.customer_files:
                    file_list = "\n".join(f"- {p}" for p in request.customer_files)
                    extra_context = (
                        "\n\n[用户上传了以下客户资料文件，请务必先用 read_customer_file 工具逐一读取并提取需求要点，"
                        "再综合生成方案]\n" + file_list
                    )

                result = await agent.run(
                    user_input=request.demand,
                    session_id=session_id,
                    extra_context=extra_context,
                    event_callback=event_callback,
                )

                # ── 记录使用日志 + 保存历史 ──
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
                                except:
                                    pass
                            if industry_hint:
                                break
                        history_id = usage_logger.save_match_history(
                            demand_text=original_demand or "",
                            solution=result.get("answer", ""),
                            industry=industry_hint,
                            sources=[],
                            user_id=user['id']
                        )
                    except Exception as log_err:
                        logger.warning(f"[Agent SSE] 保存历史失败: {log_err}")

                # ── 成就检测 ──
                newly_unlocked = []
                if user and user.get('id') and not request.is_quick_demo:
                    try:
                        achievement_svc = get_achievement_service_dep()
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
                                except:
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

                # 把 newly_unlocked 和 history_id 注入 result
                result["newly_unlocked"] = newly_unlocked
                result["history_id"] = history_id

                await queue.put({"type": "result", "data": result})
            except Exception as e:
                logger.error(f"[Agent SSE] 执行失败: {e}")
                await queue.put({"type": "error", "message": str(e)})
            finally:
                try:
                    await queue.put(None)  # 结束信号
                except Exception:
                    pass

        task = asyncio.ensure_future(run_agent())

        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                event_type = event.get("type", "message")
                yield f"event: {event_type}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            logger.info("[Agent SSE] 客户端断开连接")
            task.cancel()
        finally:
            await task

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        },
    )


@router.post("/analyze", response_model=AnalyzeResponse, tags=["竞争对手分析"])
async def analyze_competitor(
    request: AnalyzeRequest,
    user: Optional[dict] = Depends(get_current_user_optional)
):
    """
    竞争对手方案分析接口
    
    - **competitor**: 竞争对手名称
    - **industry**: 行业名称
    """
    try:
        # 使用用户独立知识库（登录用户）；匿名用户使用全局知识库
        user_id = user.get('id') if user else 0
        analyzer = get_competitor_analyzer_for_user(user_id) if user_id > 0 else get_competitor_analyzer()
        logger.info(f"开始分析竞争对手: {request.competitor}, 行业: {request.industry}")
        
        result = await analyzer.analyze(request.competitor, request.industry)
        
        source_docs = [
            SourceDocument(
                page_content=doc.page_content,
                metadata=doc.metadata
            )
            for doc in result.get("source_documents", [])
        ]
        
        logger.info("竞争对手分析成功")
        
        # 记录使用日志（仅登录用户保存历史）
        history_id = None
        if user and user.get('id'):
            try:
                usage_logger = get_usage_logger()
                usage_logger.log_analyze(request.competitor, request.industry, user_id=user['id'])
                history_id = usage_logger.save_competitor_history(
                    competitor=request.competitor,
                    industry=request.industry,
                    analysis=result["answer"],
                    sources=[{"source": d.metadata.get("source", ""), "industry": d.metadata.get("industry", "")} for d in result.get("source_documents", []) if hasattr(d, "metadata")],
                    user_id=user['id']
                )
            except Exception as log_err:
                logger.warning(f"记录使用日志或保存历史失败: {log_err}")
        
        # 成就检测
        achievement_result = []
        if user and user.get('id') and not request.is_quick_demo:
            try:
                achievement_svc = get_achievement_service_dep()
                achievement_result = achievement_svc.check_after_analyze(
                    user_id=user['id'],
                    competitor=request.competitor,
                )
            except Exception as ach_err:
                logger.warning(f"成就检测失败: {ach_err}")

        return AnalyzeResponse(
            answer=result["answer"],
            source_documents=source_docs,
            history_id=history_id,
            newly_unlocked=achievement_result if user and user.get('id') else None
        )
    except Exception as e:
        logger.error(f"竞争对手分析失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"分析失败: {str(e)}"
        )

@router.get("/knowledge/stats", response_model=KnowledgeStatsResponse, tags=["知识库管理"])
async def get_knowledge_stats(
    kb_service: KnowledgeBaseService = Depends(get_knowledge_base)
):
    """
    获取知识库统计信息
    """
    try:
        stats = kb_service.get_stats()
        
        return KnowledgeStatsResponse(
            total_documents=stats["total_documents"],
            supported_industries=stats["supported_industries"],
            industry_counts=stats["industry_counts"],
            accuracy=stats.get("accuracy", 50)
        )
    except Exception as e:
        logger.error(f"获取知识库统计失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取统计失败: {str(e)}"
        )

@router.post("/knowledge/rebuild", response_model=RebuildResponse, tags=["知识库管理"])
async def rebuild_knowledge(
    current_user: dict = Depends(get_current_user),
    kb_service: KnowledgeBaseService = Depends(get_knowledge_base)
):
    """
    重建全局知识库（需登录）
    
    从 data/sample_solutions/ 目录重新加载所有文档
    """
    try:
        logger.info(f"用户 {current_user['id']} 开始重建全局知识库")
        
        count = kb_service.build_from_directory()
        
        logger.info(f"知识库重建完成，共 {count} 个文档片段")
        
        return RebuildResponse(
            count=count,
            message=f"知识库重建成功，共添加 {count} 个文档片段"
        )
    except Exception as e:
        logger.error(f"重建知识库失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"重建失败: {str(e)}"
        )

@router.post("/knowledge/clear", response_model=ClearResponse, tags=["知识库管理"])
async def clear_knowledge(
    current_user: dict = Depends(get_current_user),
    kb_service: KnowledgeBaseService = Depends(get_knowledge_base)
):
    """
    清空全局知识库（需登录）
    
    删除全局向量数据库中的所有文档
    """
    try:
        logger.info(f"用户 {current_user['id']} 开始清空全局知识库")
        
        kb_service.vector_db.delete_collection()
        
        logger.info("知识库已清空")
        
        return ClearResponse(
            success=True,
            message="知识库已清空"
        )
    except Exception as e:
        logger.error(f"清空知识库失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"清空失败: {str(e)}"
        )

# ===== 知识库文档管理 CRUD =====

@router.get("/knowledge/documents", response_model=KBDocumentListResponse, tags=["知识库管理"])
async def list_knowledge_documents(
    current_user: dict = Depends(get_current_user)
):
    """列出当前用户独立知识库的文档（强制登录）"""
    try:
        kb_service = get_user_knowledge_base(current_user['id'])
        docs = kb_service.list_documents()
        return KBDocumentListResponse(total=len(docs), documents=docs)
    except Exception as e:
        logger.error(f"列出文档失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/knowledge/documents/{doc_id}", tags=["知识库管理"])
async def get_knowledge_document(
    doc_id: str,
    current_user: dict = Depends(get_current_user)
):
    """获取当前用户独立知识库的文档内容（强制登录）"""
    try:
        kb_service = get_user_knowledge_base(current_user['id'])
        return kb_service.get_document(doc_id)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    except Exception as e:
        logger.error(f"获取文档失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/knowledge/documents", response_model=KBDocumentCreateResponse, tags=["知识库管理"])
async def create_knowledge_document(
    req: KBDocumentCreateRequest,
    current_user: dict = Depends(get_current_user),
):
    """创建新文档（写入当前用户的知识库）"""
    try:
        kb_service = get_user_knowledge_base(current_user['id'])
        result = kb_service.create_document(req.category, req.industry, req.title, req.content)
        # 成就检测
        if current_user and current_user.get('id'):
            try:
                achievement_svc = get_achievement_service_dep()
                # 获取知识库总文档数
                total_docs = 0
                try:
                    stats = kb_service.get_stats()
                    industry_counts = stats.get("industry_counts", {}) if isinstance(stats, dict) else {}
                    total_docs = sum(industry_counts.values()) if industry_counts else 0
                except:
                    pass
                newly = achievement_svc.check_after_kb_add(current_user['id'], total_docs)
                if newly:
                    logger.info(f"[Achievement] 知识库新增文档成就解锁: {[a['name'] for a in newly]}")
            except Exception as ach_err:
                logger.warning(f"成就检测失败: {ach_err}")
        return KBDocumentCreateResponse(**result)
    except FileExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.error(f"创建文档失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.put("/knowledge/documents/{doc_id}", response_model=KBDocumentUpdateResponse, tags=["知识库管理"])
async def update_knowledge_document(
    doc_id: str,
    req: KBDocumentUpdateRequest,
    current_user: dict = Depends(get_current_user)
):
    """更新文档内容（修改当前用户的知识库）"""
    try:
        kb_service = get_user_knowledge_base(current_user['id'])
        result = kb_service.update_document(doc_id, req.content)
        return KBDocumentUpdateResponse(**result)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    except Exception as e:
        logger.error(f"更新文档失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.delete("/knowledge/documents/{doc_id}", response_model=KBDocumentDeleteResponse, tags=["知识库管理"])
async def delete_knowledge_document(
    doc_id: str,
    current_user: dict = Depends(get_current_user)
):
    """删除文档（从当前用户的知识库中删除）"""
    try:
        kb_service = get_user_knowledge_base(current_user['id'])
        result = kb_service.delete_document(doc_id, delete_file=True)
        return KBDocumentDeleteResponse(success=True, **result)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    except Exception as e:
        logger.error(f"删除文档失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/knowledge/documents/{doc_id}/reindex", response_model=KBDocumentReindexResponse, tags=["知识库管理"])
async def reindex_knowledge_document(
    doc_id: str,
    current_user: dict = Depends(get_current_user),
):
    """重新索引单个文档（当前用户的知识库）"""
    try:
        kb_service = get_user_knowledge_base(current_user['id'])
        result = kb_service.reindex_document(doc_id)
        # 成就检测
        if current_user and current_user.get('id'):
            try:
                achievement_svc = get_achievement_service_dep()
                newly = achievement_svc.check_after_reindex(current_user['id'])
                if newly:
                    logger.info(f"[Achievement] 重索引成就解锁: {[a['name'] for a in newly]}")
            except Exception as ach_err:
                logger.warning(f"成就检测失败: {ach_err}")
        return KBDocumentReindexResponse(**result)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    except Exception as e:
        logger.error(f"重新索引失败: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.get("/dashboard/stats", response_model=DashboardStatsResponse, tags=["数据仪表盘"])
async def get_dashboard_stats(
    current_user: dict = Depends(get_current_user),
    usage_logger: UsageLoggerService = Depends(get_usage_logger)
):
    """
    获取仪表盘统计数据
    
    返回行业覆盖、匹配趋势、竞品分析频次等**真实使用数据**
    所有趋势和频次数据均来自 SQLite 日志数据库的实际操作记录
    """
    try:
        import os
        from datetime import datetime, timedelta
        from app.config import APP_VERSION

        # 获取用户独立知识库统计
        kb_service = get_user_knowledge_base(current_user['id'])
        kb_stats = kb_service.get_stats()
        
        # 行业覆盖数据（来自知识库，真实）
        industry_coverage = kb_stats.get("industry_counts", {})
        
        # ========== 真实使用日志统计 ==========
        user_id = current_user.get('id')

        # 获取最近7天操作次数（用于 KPI 卡片）
        recent_counts = usage_logger.get_recent_counts(days=7, user_id=user_id)
        recent_matches = recent_counts.get("match", 0)
        recent_analyses = recent_counts.get("analyze", 0)

        # 获取最近7天每日趋势（真实日志）
        match_trends = usage_logger.get_daily_trends(days=7, user_id=user_id)

        # 获取竞品分析频次（全局数据，所有用户共享 → 转换为百分比防泄露）
        competitor_frequency_raw = usage_logger.get_competitor_frequency(user_id=None)  # 全局，不限用户
        total_analyses = sum(competitor_frequency_raw.values())
        if total_analyses > 0:
            competitor_frequency = {
                k: round(v / total_analyses * 100, 1)
                for k, v in sorted(competitor_frequency_raw.items(), key=lambda x: -x[1])
            }
        else:
            competitor_frequency = {}

        # 获取涨幅（7日环比）
        growth_rates = usage_logger.get_growth_rates(days=7, user_id=user_id)
        match_growth = growth_rates.get("match_growth", None)
        analyze_growth = growth_rates.get("analyze_growth", None)

        # 如果日志为空，提供兜底：从竞品文档目录生成基础数据（同样转为百分比）
        if not competitor_frequency:
            competitor_dir = os.getenv("COMPETITOR_DIRECTORY", "./data/competitors")
            if os.path.exists(competitor_dir):
                fallback_raw = {}
                for competitor in os.listdir(competitor_dir):
                    comp_path = os.path.join(competitor_dir, competitor)
                    if os.path.isdir(comp_path):
                        try:
                            files = [f for f in os.listdir(comp_path) if f.endswith((".txt", ".pdf", ".md"))]
                            fallback_raw[competitor] = len(files)
                        except:
                            pass
                total_fallback = sum(fallback_raw.values())
                if total_fallback > 0:
                    competitor_frequency = {
                        k: round(v / total_fallback * 100, 1)
                        for k, v in sorted(fallback_raw.items(), key=lambda x: -x[1])
                    }
        
        # 系统运行时间
        try:
            import psutil
            proc = psutil.Process()
            uptime_sec = int((datetime.now() - datetime.fromtimestamp(proc.create_time())).total_seconds())
            hours = uptime_sec // 3600
            mins = (uptime_sec % 3600) // 60
            system_uptime = f"{hours}小时 {mins}分钟"
        except:
            system_uptime = "运行中"
        
        return DashboardStatsResponse(
            industry_coverage=industry_coverage,
            match_trends=match_trends,
            competitor_frequency=competitor_frequency,
            recent_matches=recent_matches,
            recent_analyses=recent_analyses,
            match_growth=match_growth,
            analyze_growth=analyze_growth,
            total_documents=kb_stats.get("total_documents", 0),
            accuracy=kb_stats.get("accuracy", 87),
            system_uptime=system_uptime,
            last_update=datetime.now().strftime("%Y-%m-%d %H:%M"),
            version=APP_VERSION
        )
    except Exception as e:
        logger.error(f"获取仪表盘数据失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取仪表盘数据失败: {str(e)}"
        )

# ========== 历史记录（方案匹配回溯 & 对比） ==========

@router.get("/history/list", response_model=MatchHistoryListResponse, tags=["历史记录"])
async def get_match_history_list(
    current_user: dict = Depends(get_current_user),
    page: int = 1,
    page_size: int = 20,
    limit: int = 100,
    usage_logger: UsageLoggerService = Depends(get_usage_logger)
):
    """
    获取方案匹配历史记录列表

    按时间倒序返回最近的匹配记录，支持分页
    """
    try:
        # 参数校验
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 20
        if page_size > 100:
            page_size = 100
        if limit < 1:
            limit = 100

        # 获取总数
        total = usage_logger.get_match_history_count(user_id=current_user.get('id'))

        # 计算分页
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0
        offset = (page - 1) * page_size
        effective_limit = min(page_size, limit)

        items = usage_logger.get_match_history_list(limit=effective_limit, offset=offset, user_id=current_user.get('id'))
        return MatchHistoryListResponse(
            items=[
                MatchHistoryItem(
                    id=item["id"],
                    demand_text=item["demand_text"],
                    solution_preview=(item.get("solution") or "")[:500],
                    industry=item["industry"],
                    created_at=item["created_at"]
                )
                for item in items
            ],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages
        )
    except Exception as e:
        logger.error(f"获取历史记录列表失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取历史记录失败: {str(e)}"
        )

@router.get("/history/{history_id}", response_model=MatchHistoryDetail, tags=["历史记录"])
async def get_match_history_detail(
    history_id: int,
    current_user: dict = Depends(get_current_user),
    usage_logger: UsageLoggerService = Depends(get_usage_logger)
):
    """
    获取单条历史记录详情

    包含完整的需求描述、方案内容和参考文档
    """
    try:
        item = usage_logger.get_match_history_by_id(history_id, user_id=current_user.get("id"))
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="历史记录不存在"
            )
        return MatchHistoryDetail(
            id=item["id"],
            demand_text=item["demand_text"],
            solution=item["solution"],
            industry=item["industry"],
            sources=item["sources"],
            created_at=item["created_at"]
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取历史记录详情失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取历史记录详情失败: {str(e)}"
        )

@router.post("/history/compare", response_model=CompareResponse, tags=["历史记录"])
async def compare_match_history(
    request: CompareRequest,
    current_user: dict = Depends(get_current_user),
    usage_logger: UsageLoggerService = Depends(get_usage_logger)
):
    """
    对比两条历史记录

    同时返回方案A和方案B的完整内容，前端做差异化展示
    """
    try:
        item_a = usage_logger.get_match_history_by_id(request.id_a, user_id=current_user.get("id"))
        item_b = usage_logger.get_match_history_by_id(request.id_b, user_id=current_user.get("id"))

        if item_a is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"历史记录 {request.id_a} 不存在"
            )
        if item_b is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"历史记录 {request.id_b} 不存在"
            )

        return CompareResponse(
            item_a=MatchHistoryDetail(
                id=item_a["id"],
                demand_text=item_a["demand_text"],
                solution=item_a["solution"],
                industry=item_a["industry"],
                sources=item_a["sources"],
                created_at=item_a["created_at"]
            ),
            item_b=MatchHistoryDetail(
                id=item_b["id"],
                demand_text=item_b["demand_text"],
                solution=item_b["solution"],
                industry=item_b["industry"],
                sources=item_b["sources"],
                created_at=item_b["created_at"]
            )
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"对比历史记录失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"对比失败: {str(e)}"
        )

@router.post("/history/ai-summary", response_model=CompareSummaryResponse, tags=["历史记录"])
async def compare_ai_summary(
    request: CompareSummaryRequest,
    current_user: dict = Depends(get_current_user),
    usage_logger: UsageLoggerService = Depends(get_usage_logger)
):
    """为两条历史记录生成AI智能对比总结"""
    try:
        item_a = usage_logger.get_match_history_by_id(request.id_a, user_id=current_user.get("id"))
        item_b = usage_logger.get_match_history_by_id(request.id_b, user_id=current_user.get("id"))

        if item_a is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"历史记录 {request.id_a} 不存在")
        if item_b is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"历史记录 {request.id_b} 不存在")

        compare_prompt = f"""你是华为云解决方案资深专家。请对比分析以下两份华为云方案匹配的输出结果，给出简洁、专业的智能总结。

## 方案A
- 客户需求：{item_a.get('demand_text', '')}
- 推荐方案摘要：
{item_a.get('solution', '')[:2000]}

## 方案B
- 客户需求：{item_b.get('demand_text', '')}
- 推荐方案摘要：
{item_b.get('solution', '')[:2000]}

请从以下维度进行对比总结（控制在300字以内，用Markdown格式）：
1. **需求差异**：两份方案的客户需求有何不同
2. **方案侧重点**：两份方案各自的核心推荐点和差异
3. **产品组合差异**：关键华为云产品的使用差异
4. **演进建议**：如果是同一客户的迭代需求，给出从方案A到方案B的演进思路

请用中文输出，结构清晰、专业简练。"""
        summary = await get_llm_response(compare_prompt)
        return CompareSummaryResponse(summary=summary)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI对比总结生成失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AI总结生成失败: {str(e)}"
        )



@router.patch("/history/{history_id}/solution", response_model=UpdateSolutionResponse, tags=["历史记录"])
async def update_history_solution(
    history_id: int,
    request: UpdateSolutionRequest,
    current_user: dict = Depends(get_current_user),
    usage_logger: UsageLoggerService = Depends(get_usage_logger)
):
    """更新历史记录中的方案内容（用于追问优化后保存最终版）"""
    try:
        success = usage_logger.update_match_history_solution(history_id, request.solution, user_id=current_user.get("id"))
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"历史记录 {history_id} 不存在或更新失败")
        return UpdateSolutionResponse(success=True, message="方案已更新")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新历史方案失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新失败: {str(e)}"
        )


@router.patch("/competitor/history/{history_id}/solution", response_model=UpdateSolutionResponse, tags=["历史记录"])
async def update_competitor_history_solution(
    history_id: int,
    request: UpdateSolutionRequest,
    current_user: dict = Depends(get_current_user),
    usage_logger: UsageLoggerService = Depends(get_usage_logger)
):
    """更新竞品分析历史记录中的分析内容（用于追问优化后保存最终版）"""
    try:
        success = usage_logger.update_competitor_history_solution(history_id, request.solution, user_id=current_user.get("id"))
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"竞品分析历史记录 {history_id} 不存在或更新失败")
        return UpdateSolutionResponse(success=True, message="分析报告已更新")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新竞品分析历史失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新失败: {str(e)}"
        )

# ========== 竞品分析历史记录 ==========

@router.get("/competitor/history/list", response_model=CompetitorHistoryListResponse, tags=["历史记录"])
async def get_competitor_history_list(
    current_user: dict = Depends(get_current_user),
    page: int = 1,
    page_size: int = 20,
    limit: int = 100,
    usage_logger: UsageLoggerService = Depends(get_usage_logger)
):
    """
    获取竞品分析历史记录列表

    按时间倒序返回最近的竞品分析记录，支持分页
    """
    try:
        # 参数校验
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 20
        if page_size > 100:
            page_size = 100
        if limit < 1:
            limit = 100

        # 获取总数
        total = usage_logger.get_competitor_history_count(user_id=current_user.get('id'))

        # 计算分页
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0
        offset = (page - 1) * page_size
        effective_limit = min(page_size, limit)

        items = usage_logger.get_competitor_history_list(limit=effective_limit, offset=offset, user_id=current_user.get('id'))
        return CompetitorHistoryListResponse(
            items=[
                CompetitorHistoryItem(
                    id=item["id"],
                    competitor=item["competitor"],
                    industry=item["industry"],
                    analysis_preview=(item.get("solution") or "")[:500],
                    created_at=item["created_at"]
                )
                for item in items
            ],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages
        )
    except Exception as e:
        logger.error(f"获取竞品分析历史列表失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取历史记录失败: {str(e)}"
        )

@router.get("/competitor/history/{history_id}", response_model=CompetitorHistoryDetail, tags=["历史记录"])
async def get_competitor_history_detail(
    history_id: int,
    current_user: dict = Depends(get_current_user),
    usage_logger: UsageLoggerService = Depends(get_usage_logger)
):
    """
    获取单条竞品分析历史记录详情

    包含完整的分析报告和参考文档
    """
    try:
        item = usage_logger.get_competitor_history_by_id(history_id, user_id=current_user.get("id"))
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="历史记录不存在"
            )
        return CompetitorHistoryDetail(
            id=item["id"],
            competitor=item["competitor"],
            industry=item["industry"],
            analysis=item["analysis"],
            sources=item.get("sources", []),
            created_at=item["created_at"]
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取竞品分析历史详情失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取历史记录详情失败: {str(e)}"
        )

@router.post("/solution/refine", response_model=RefineSolutionResponse, tags=["解决方案优化"])
async def refine_solution(request: RefineSolutionRequest):
    """方案追问优化接口 - 基于原始需求+当前方案+用户追问，生成优化方案"""
    try:
        # 构造对话历史上下文
        history_text = ""
        if request.conversation_history:
            for h in request.conversation_history:
                role = h.get('role', 'user')
                content = h.get('content', '')
                history_text += f"{role}: {content}\n"
        
        refine_prompt = f"""你是华为云解决方案资深专家。请根据用户的追问，对已有方案进行优化改写。

## 原始客户需求
{request.original_demand}

## 当前方案（Markdown格式）
{request.current_solution}

## 历史追问记录
{history_text if history_text else '（无）'}

## 本次用户追问
{request.follow_up}

---
**任务要求**：
1. 基于当前方案，根据用户的追问要求进行针对性优化
2. 保持方案的专业性和实用性，符合华为云产品体系
3. 如果追问涉及价格/成本，给出具体计费参考（华为云官方价格体系）
4. 如果追问涉及竞品对比，突出华为云差异化优势
5. 输出完整优化后的方案（Markdown格式，结构清晰）
6. 不要输出解释性文字，直接输出优化后的完整方案

请用中文输出，格式规范、专业简练。"""
        
        refined = await get_llm_response(refine_prompt)
        return RefineSolutionResponse(
            refined_solution=refined,
            follow_up=request.follow_up
        )
    except Exception as e:
        logger.error(f"方案优化失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"方案优化失败: {str(e)}"
        )

@router.post("/competitor/refine", response_model=RefineCompetitorResponse, tags=["竞品分析优化"])
async def refine_competitor_analysis(request: RefineCompetitorRequest):
    """竞品分析追问优化接口 - 基于竞品+行业+当前分析+用户追问，生成优化分析报告"""
    try:
        # 构造对话历史上下文
        history_text = ""
        if request.conversation_history:
            for h in request.conversation_history:
                role = h.get('role', 'user')
                content = h.get('content', '')
                history_text += f"{role}: {content}\n"

        refine_prompt = f"""你是华为云竞争分析资深专家。请根据用户的追问，对已有的竞品分析报告进行优化改写。

## 竞品名称
{request.original_competitor}

## 行业场景
{request.original_industry}

## 当前分析报告（Markdown格式）
{request.current_analysis}

## 历史追问记录
{history_text if history_text else '（无）'}

## 本次用户追问
{request.follow_up}

---
**任务要求**：
1. 基于当前分析报告，根据用户的追问要求进行针对性优化
2. 保持报告的专业性和实战性，聚焦华为云 vs {request.original_competitor} 的差异化竞争
3. 如果追问涉及技术架构/价格/生态/服务对比，给出具体的对比细节
4. 如果追问涉及销售话术，给出可直接用于客户沟通的实战话术
5. 输出完整优化后的分析报告（Markdown格式，结构清晰）
6. 不要输出解释性文字，直接输出优化后的完整报告

请用中文输出，格式规范、专业简练。"""

        refined = await get_llm_response(refine_prompt)
        return RefineCompetitorResponse(
            refined_analysis=refined,
            follow_up=request.follow_up
        )
    except Exception as e:
        logger.error(f"竞品分析优化失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"竞品分析优化失败: {str(e)}"
        )


# ==================== AI 智能助手 ====================

@router.post("/ai/chat", tags=["AI 助手"])
async def ai_chat(
    request: dict,
    user: Optional[dict] = Depends(get_current_user_optional)
):
    """
    AI 智能助手 - 三路自由问答
    1. 平台使用类 → 使用向导（纯 LLM）
    2. 云计算/IT/技术业务类 → 对话式 RAG（专业回答）
    3. 其他所有话题 → 通用 AI 助手（什么都能聊）
    """
    try:
        question = request.get("question", "").strip()
        if not question:
            raise HTTPException(status_code=400, detail="问题不能为空")

        # ---- 提取对话历史（用于上下文）----
        raw_history = request.get("history", [])
        # 只取最近10轮（20条消息），避免 token 超限
        recent_history = raw_history[-20:] if len(raw_history) > 20 else raw_history
        # 格式化为文本："用户：...\n助手：..."
        history_text = ""
        for msg in recent_history[:-1]:  # 排除当前这一轮的最后一条（就是 question 本身）
            role_label = "用户" if msg.get("role") == "user" else "助手"
            history_text += f"{role_label}：{msg.get('text', '')}\n"

        # ---- 路由判断 ----
        # 第一优先级：平台使用类问题
        usage_keywords = [
            "怎么用", "如何使用", "怎么使用", "如何操作",
            "功能怎么用", "功能使用", "功能介绍",
            "三种模式", "标准模式", "智能模式", "向导模式",
            "匹配功能", "方案匹配", "匹配怎么",
            "知识库管理", "知识库怎么", "添加文档", "索引文档",
            "历史记录", "历史怎么", "导出", "报告导出",
            "产品图谱", "产品分类",
            "仪表盘", "统计数据", "数据含义",
            "账号设置", "登录注册", "个人偏好",
            "这个平台", "本平台", "你们这个网站", "这个网站",
            "这个系统", "本系统",
            "有什么区别", "什么区别", "区别是什么",
            "有什么功能", "哪些功能", "功能有哪些",
            "怎么开始", "从哪开始", "第一步",
            "新手指南", "使用教程", "使用帮助",
        ]
        is_usage = any(kw in question for kw in usage_keywords)

        if is_usage:
            answer = await _answer_usage_question(question, history_text)
            return {"answer": answer}

        # 第二优先级：云计算/IT/技术业务类问题（走 RAG）
        cloud_keywords = [
            "华为云", "阿里云", "腾讯云", "AWS", "Azure", "Google Cloud",
            "云服务", "云计算", "云服务器", "云数据库", "云存储",
            "ECS", "OBS", "RDS", "GaussDB", "ModelArts", "CDN",
            "弹性计算", "对象存储", "关系型数据库", "分布式数据库",
            "容器", "Kubernetes", "Docker", "微服务",
            "服务器", "数据库", "负载均衡", "VPC", "VPN",
            "人工智能", "AI", "机器学习", "深度学习", "大模型",
            "物联网", "IoT", "边缘计算", "5G",
            "数字化转型", "智慧城市", "智慧园区", "智慧医疗", "智慧教育",
            "智慧交通", "智慧农业", "智慧能源", "智慧金融", "智慧文旅",
            "工业互联网", "智能制造", "DevOps",
            "公有云", "私有云", "混合云", "多云",
            "SaaS", "PaaS", "IaaS",
            "方案匹配", "解决方案", "售前", "架构设计", "技术选型",
            "竞品", "对比", "哪个好", "推荐", "选型",
            "带宽", "延迟", "可用性", "容灾", "备份",
            "安全组", "防火墙", "WAF", "DDoS",
            "大数据", "数据分析", "数据仓库", "ETL",
            "虚拟化", "OpenStack", "VMware",
            "代码托管", "CI/CD", "持续集成", "持续部署",
            "消息队列", "Redis", "MongoDB", "MySQL", "PostgreSQL",
            "API 网关", "函数计算", "Serverless",
            "视频点播", "直播", "RTC",
            "域名", "DNS", "SSL", "HTTPS", "证书",
            "监控", "日志", "告警", "Prometheus", "ELK",
        ]
        is_cloud = any(kw in question for kw in cloud_keywords)

        if is_cloud:
            user_id = user.get('id') if user else 0
            kb = get_user_knowledge_base(user_id) if user_id > 0 else get_knowledge_base()
            answer = await _answer_business_question(question, kb, history_text)
            return {"answer": answer}

        # 第三优先级：其他所有话题 → 通用 AI 助手
        answer = await _answer_general_question(question, history_text)
        return {"answer": answer}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI 助手请求失败: {e}")
        # 不返回 500（易被误判为系统故障），改为 200 + 友好兜底文案
        return {
            "answer": "抱歉，AI 助手暂时开小差了，请稍后再试一次。如果问题持续，可以稍后重试或换个问法。",
            "error": "ai_unavailable"
        }


async def _answer_usage_question(question: str, history_text: str = "") -> str:
    """回答平台使用类问题（不检索知识库，直接 LLM 回答）"""
    history_block = f"\n【之前的对话】\n{history_text}\n" if history_text.strip() else ""
    system_prompt = """你是「智能方案助手」— 本平台（cloudsol.cn）的AI使用向导。

【本平台简介】
本平台由郭鸿宇独立开发（杭州电子科技大学，电气工程及其自动化专业），是一个独立的云计算方案匹配工具，不属于任何云厂商。知识库收录了华为云、阿里云、腾讯云、AWS等多家云厂商的公开资料供参考。

【你能帮用户做什么】
1. 平台使用指引：如何匹配方案、管理知识库、导出报告等
2. 云计算知识问答：基于知识库资料回答华为云/竞品相关问题
3. 日常闲聊：任何话题都可以自然交流

【回答原则】
- 针对用户的具体问题回答，不要跑题或长篇大论
- 语气专业但亲切，像微信聊天一样自然
- 禁止 Markdown：用纯文本+换行，不要写 # ## ** ``` 等符号

用户问题："""
    full_prompt = system_prompt + history_block + question
    return await get_llm_response(full_prompt)


async def _answer_business_question(question: str, kb, history_text: str = "") -> str:
    """回答华为云业务类问题（对话式RAG：检索文档→自然回答，不是生成方案）"""
    # 1. 检索相关文档
    docs = []
    try:
        docs = kb.search_huawei(question, k=5)
        comp_docs = kb.search_competitor(question, k=2)
        docs = (docs or []) + (comp_docs or [])
    except Exception as e:
        logger.warning(f"AI助手向量检索异常: {e}")
        docs = []

    # 格式化上下文
    context_text = ""
    if docs:
        context_parts = []
        for i, doc in enumerate(docs, 1):
            meta = doc.metadata or {}
            source = meta.get("source", "未知来源")
            content = doc.page_content.strip()[:800]  # 截断避免超token
            context_parts.append(f"[资料{i}] 来源：{source}\n{content}")
        context_text = "\n\n".join(context_parts)

    # 2. 对话式 Prompt（纯文本对话，禁止Markdown）
    system_prompt = """你是「智能方案助手」— 一位专业的云计算方案顾问。

你的任务是直接回答用户的云计算相关问题，基于下方参考资料给出专业建议。
像微信/钉钉聊天那样自然对话，用"您"称呼用户，简洁实用（一般300-500字）。

【格式要求】
- 禁止 Markdown：不要写 # ## ** ``` | []() 等符号
- 用纯文本+换行组织内容，列表用 "1." "2." 开头

"""
    history_block = f"\n【之前的对话】\n{history_text}\n" if history_text.strip() else ""

    if context_text:
        full_prompt = f"{system_prompt}{history_block}【参考资料（基于知识库检索）】：\n\n{context_text}\n\n【用户提问】：{question}"
    else:
        full_prompt = f"{system_prompt}{history_block}（注：当前知识库暂无相关资料，请根据您的专业知识尽量准确回答）\n\n【用户提问】：{question}"

    return await get_llm_response(full_prompt)


async def _answer_general_question(question: str, history_text: str = "") -> str:
    """回答通用话题（非平台使用、非云计算业务）— 纯 LLM，不检索知识库"""
    history_block = f"\n【之前的对话】\n{history_text}" if history_text.strip() else ""
    system_prompt = """你是「智能方案助手」— cloudsol.cn（华为云解决方案智能匹配系统）的内置 AI 助手。

【你的身份】
- 你是本平台的 AI 助手，不是独立产品
- 本平台由郭鸿宇独立开发（杭州电子科技大学），是一个云计算方案匹配工具
- 你不属于任何 AI 模型公司（如 DeepSeek、OpenAI 等），不要提及底层技术栈

【回答原则】
- 任何话题都可以自然聊天，像微信朋友一样轻松亲切
- 用"你"称呼用户，简洁实用（200-500字）
- 如果被问到"你是谁/谁开发的/哪家公司的"，回答：你是「智能方案助手」，cloudsol.cn 平台的 AI 助手，由郭鸿宇开发
- 禁止 Markdown：纯文本+换行，不要写 # ## ** ``` 等符号

用户问题："""
    full_prompt = system_prompt + history_block + question
    return await get_llm_response(full_prompt)
