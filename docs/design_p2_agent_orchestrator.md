# P2 设计文档：Agent 多智能体编排（真·两阶段执行 + Orchestrator-Workers + 长程记忆 + MCP + PPTX）

> **撰写时间**：2026-08-26（基于 P1 落地后代码基线，main @ `1966f1a`）
> **前置必读**：`docs/design_p1_agent_reshape.md`（P1 决策 D1/D4/D5）+ `docs/handoff_agent_reshape_后续任务.md` §五（P2 阶段定义）
> **目标**：P1 已让 Plan 实时点亮、工具可导出/可联网、失败可反思。P2 升级为「真·按计划分阶段执行 + 多角色智能体协作」，补长程记忆、MCP 标准化、PPTX 导出，彻底消除"Plan 是装饰品"的最后残留。

---

## 0. 设计铁律（不可违反）

1. **经典模式字节不动**：`frontend/script.js` / `style.css` / `api/routes.py`（经典部分）一律不碰。Agent 改动只限 `app/agent/**` + `api/agent_routes.py` + `frontend/js/agent_workspace.js` + `frontend/css/agent_workspace.css` + `app/services/report_generator.py` + `app/models/export_models.py` + `app/config.py` + `.env.example`。
2. **agent_workspace.js 不引用经典 API 模块**：Agent 能力自给自足。
3. **前端版本号递增**：统一升到 `v=20260828a`（index.html `?v=` 全量替换）。
4. **每次大改后必须 E2E 验证**（后端脚本优先，浏览器截图兜底）。
5. **稳定性 >> 新功能**：P2 涉及 harness 主流程新增执行路径，**保留现有 ReAct 主循环作为兜底**，两阶段执行失败即降级到现有路径，clarify/file_ops/knowledge_q 三条已验证路径不回归。
6. **多智能体是"角色分工"不是"新引擎"**：复用同一套 ReAct 协议与工具注册中心，仅以不同 system prompt + 工具子集区分角色，避免引入第二套执行框架。
7. **零新依赖原则**：PPTX 用已装的 `python-pptx==0.6.23`；MCP 用 Python stdlib 实现最小 JSON-RPC（不装 `mcp` SDK，避免重依赖与 API 绑定）。

---

## 1. 当前架构事实（P1 落地后）

- **主循环**：`app/agent/harness.py::run()`（L330）→ 意图分流（account/greeting/general/export 轻量直答）→ 方案类意图进入单循环 ReAct（L554）`while self._step_count < self.max_steps`：调 LLM → `_parse_react_output` → `final_answer` / `clarify` / `action`。
- **Plan 现状（P1）**：`_emit_plan` 生成 3-6 步计划 → `plan` 事件；`action`/`final` 分支经 `PLAN_STEP_TOOL_MAP` + `_tool_to_plan_index` 下发 `plan_index`，前端实时点亮 running/done。**但 plan 不驱动执行顺序**——LLM 仍自由选择工具，可能跳过/乱序。
- **工具集（7 个）**：`analyze_demand` / `search_kb` / `search_competitor` / `read_customer_file` / `list_dir` / `generate_doc`（P1-2）/ `web_search`（P1-2，默认关闭）。
- **Reflexion（P1-3）**：连续工具失败≥2 或 max_steps 耗尽时 `_reflexion_retry`，注入调整建议。
- **导出**：`ReportGeneratorService`（模块级单例 `get_report_generator()`）；`ExportFormat` 仅 `WORD`/`PDF`（**无 PPTX**）；`_tool_generate_doc` 支持 word/pdf。
- **记忆**：`ConversationMemory`（短期 ReAct 步骤内存 + 长期对话 SQLite `agent_memory` 表，按 session 隔离）；`user_profile` 表已存用户画像（industries/tone_preferences/summary），`SolutionAgent.update_user_profile` 已实现提炼但**未注入执行 prompt**。
- **SSE 事件**：`step / thought / tool_start / tool_end / plan / final / result / clarify / error / doc_generated / reflexion`（新增字段 `plan_index`、`plan_status`）。
- **依赖**：`python-pptx==0.6.23` 已装；`mcp` SDK 未装。

---

## 2. D4：PPTX 导出生成器（独立任务，先行）

### 2.1 现状
`ExportFormat` 仅 word/pdf；`_render_and_save` 只处理 WORD（WordGenerator）与 else=PDF（reportlab）。`_tool_generate_doc` 的 `format` 只收 word/pdf。

### 2.2 设计
- `app/models/export_models.py`：`ExportFormat` 加 `PPTX = "pptx"`。
- `app/services/report_generator.py::_render_and_save`：加 `elif format == ExportFormat.PPTX:` 分支 → 新私有方法 `_generate_pptx(report_data, file_path)`：
  - 用 `python-pptx` 生成：封面页（标题/副标题/日期/客户）→ 每章一页（标题 + 内容段落）→ 附录（成本参考）页。
  - Markdown 内容做轻量清洗（去掉 `#`/`**`/`-` 等标记，按行拆段落），表格降级为要点列表（PPTX 不做原生表格，成本参考转要点）。
  - 文件名 `{prefix}_{ts}.pptx`。
- `app/agent/tools.py::_tool_generate_doc`：`format` 接受 `pptx`，映射 `ExportFormat.PPTX`。
- `app/agent/harness.py::_intercept_generate_doc`：`fmt` 白名单加 `pptx`（用户说"导出 PPT/PPTX"时）。
- `api/export_routes.py`：`ExportRequest.format` 校验自动支持（枚举扩展即可）；下载路由 `FileResponse` 自动按扩展名定 content-type。
- 前端：`doc_generated` chip 与 `_exportAnswer` 的格式标签支持 `pptx`（按钮文案「导出方案书 (PPTX)」仅当 format_mode 为 pptx 时出现；主流程仍是用户说「导出成 PPT」→ 后端直接生成）。

### 2.3 文件改动清单
`app/models/export_models.py` / `app/services/report_generator.py` / `app/agent/tools.py` / `app/agent/harness.py`（fmt 白名单）。

### 2.4 验证
`tests/verify_p2_pptx.py`：`_tool_generate_doc(fmt="pptx")` → `download_url` 200 下载 → 用 `python-pptx` 打开确认章节数 ≥1。

---

## 3. P2-1-A：真·两阶段执行引擎（Plan 驱动执行顺序）

### 3.1 现状问题
P1 的 plan 是"追踪器"：LLM 自由 ReAct，可能第 3 步的工具先被调用、plan 步序与真实执行错位（测试中已观察到 `analyze_demand→search_kb` 偶发乱序）。用户感知是"计划写了但执行没按计划"。

### 3.2 设计：`_plan_and_execute()`（新增方法，不删旧循环）

在 `run()` 的方案类意图分支（L536 `_emit_plan` 之后）改走新路径：

```
_plan_and_execute(user_input, intent, ...):
  1. plan = await _generate_plan(...)            # 已有，3-6 步，步数与 PLAN_STEP_TOOL_MAP 对齐
  2. step_outputs = []
     for idx, step in enumerate(plan):
         toolset = PLAN_STEP_TOOL_MAP[intent][idx]          # 本步允许的工具（末步=[] 综合生成）
         obs = await _execute_step(idx, step, toolset)      # 本步子循环（见下）
         step_outputs.append(obs)
         emit plan_index=idx done
  3. final = await _synthesize_final(user_input, plan, step_outputs)   # 汇总各步结果生成终稿
  4. final = await _finalize_answer(...) + _self_check_answer(...)     # 复用 P0 增强管线
     self._last_draft = final
     emit final（plan_index = len-1）
```

**_execute_step(idx, step, toolset) 子循环**（每步最多 `STEP_MAX_ITER=3` 次 LLM 调用）：
- 构造步级 prompt：给出本步目标（step 文本）+ **仅列出 toolset 内工具**（空 toolset → 直接返回"综合生成步"占位，不调 LLM）+ 要求「完成本步后用 STEP_DONE 标记」。
- 循环内：`_call_llm` → `_parse_react_output`：
  - `action` 且 tool ∈ toolset → `_execute_tool` → emit tool_start/tool_end（plan_index=idx，running/done）→ observation 追加 → 计数成功/失败（失败累加 `_consecutive_tool_failures`，≥2 触发 `_reflexion_retry`）。
  - `action` 但 tool ∉ toolset → 返回「本步不允许工具 X，请使用 {toolset}」作为 observation，不算失败。
  - `STEP_DONE` / `final_answer` 形态 → 结束本步，返回累计 observation 摘要。
  - 其它 → 追加格式纠正提示（复用现有引导语）。
- 每步结果截断（≤1500 字符）存入 `self._step_results[idx]`（供 D5 重跑与多智能体消费）。

**降级保护**：`_plan_and_execute` 任一步抛出异常或总步数超预算（`max_steps`），`except` 捕获后**直接落到现有 ReAct 主循环**（把 user_input 交给老路径），保证 stability 铁律。开关 `AGENT_TWO_PHASE`（config，默认 `"1"` 开启，可 `.env` 关掉立即回退旧行为）。

### 3.3 事件契约
- 复用现有 `plan / tool_start / tool_end / final / reflexion`，不改事件名。
- 新增 `type: "step_done"`（可选，前端忽略未知字段安全）：`{"step_index": idx, "summary": "本步完成"}`。

### 3.4 文件改动清单
- `app/agent/harness.py`：`_plan_and_execute` / `_execute_step` / `_synthesize_final`；`run()` 方案类分支改道；`self._step_results` 状态；config 开关读取。
- `app/config.py` + `.env.example`：`AGENT_TWO_PHASE`。

### 3.5 验证
`tests/verify_p2_plan_exec.py`：流式事件中，`tool_start` 的 `plan_index` 严格单调非降；plan 步数与映射表长度一致；末步由 final 点亮。

---

## 4. P2-1-B：多智能体 Orchestrator-Workers（需求分析师 → 方案架构师 → 质量校验官）

### 4.1 设计
在 §3 两阶段执行之上叠加"角色分工"（铁律 6：同一引擎，不同 prompt/工具子集）。新增 `app/agent/agents.py`，定义 3 个 Worker 角色：

| 角色 | 职责 | 工具子集 | 产物 |
|---|---|---|---|
| **需求分析师** (DemandAnalyst) | 提炼行业/场景/痛点/关键词；需求模糊时 Clarify | `analyze_demand` `read_customer_file` `list_dir` `web_search` | 结构化需求 JSON + 检索关键词 |
| **方案架构师** (SolutionArchitect) | 按需求检索资料，起草方案骨架 | `search_kb` `search_competitor` `web_search` | 方案初稿（Markdown） |
| **质量校验官** (QualityReviewer) | 对照关键元素清单查漏补缺 | `search_kb` `generate_doc` | 终稿 + 补漏说明 |

**Orchestrator 工作流**（`harness._run_orchestrator`）：
1. 意图为 `solution`/`competitor` 时启用；`knowledge_q`/`file_ops` 保持现有单角色路径（§3 两阶段执行，不强制三角色）。
2. 三阶段串行：分析师产出 → 架构师消费（prompt 注入分析结果）→ 校验官消费（prompt 注入初稿）→ 校验官产出终稿。
3. **工具调用仍走 `_execute_step` 子循环**：每阶段映射到 plan 的对应步（step0=分析师、step1=架构师、step2=校验官），角色 prompt 仅在该步生效。
4. SSE 新增 `type: "agent_phase"`：`{"phase": "demand_analysis"|"solution_architect"|"quality_review", "label": "需求分析师"|"方案架构师"|"质量校验官"}`，前端思考面板显示当前阶段徽标。
5. 各阶段产物记入 `self._phase_outputs`；`_synthesize_final` 消费全部产物。

**开关**：`AGENT_MULTI_AGENT`（config，默认 `"1"`；`"0"` 时退化为 §3 单角色两阶段执行；两者都不影响经典模式）。

### 4.2 文件改动清单
- `app/agent/agents.py`（NEW）：3 个角色 prompt 常量 + 角色→工具子集映射 + 阶段产物 dataclass。
- `app/agent/harness.py`：`_run_orchestrator` + `agent_phase` 事件 + 角色 prompt 注入。
- `app/config.py` + `.env.example`：`AGENT_MULTI_AGENT`。
- 前端：`agent_workspace.js` 消费 `agent_phase`（阶段徽标）、css。

### 4.3 验证
`tests/verify_p2_agents.py`：事件流含 `agent_phase` 三阶段且顺序 demand→architect→reviewer；最终答案通过完整性自检（`success=True` 且含方案关键元素）。

---

## 5. D5：Plan 单步重跑（rerun_plan_index）

### 5.1 设计
P1 决策 D5 明确"单步重跑留到 P2"。机制：
- **后端**：`run()` 新增可选参数 `rerun_plan_index: Optional[int]`（agent_routes 从请求体透传）。命中时：
  - 校验 `0 <= rerun_plan_index < len(self._plan)` 且 `self._step_results` 非空（有已执行记录）。
  - 从 `self._step_results[idx]` 取该步原工具调用参数列表，`_execute_step` 重跑（同 toolset）。
  - 新 observation 覆盖 `step_results[idx]`，随后**重新 `_synthesize_final`** 生成新终稿并 emit final + `doc_generated`（若此前已导出过则更新 `_last_draft`）。
- **SSE**：重跑期间照常发 `tool_start/tool_end`（plan_index=idx）+ `agent_phase`（若多智能体开启）。
- **前端**：Plan 面板每行加「重跑」按钮（`.ws-plan-rerun`），点击 → `_rerunPlanStep(idx)`：向 `/api/agent/chat` POST `{message: "__rerun_plan__", rerun_plan_index: idx}`（复用同一 SSE 通道，不新增端点）；期间行内显示 running 态。

### 5.2 文件改动清单
- `api/agent_routes.py`：请求体加 `rerun_plan_index`，透传 `agent.run(..., rerun_plan_index=...)`。
- `app/agent/agent.py` + `harness.py`：`run()` 参数 + 重跑分支。
- `frontend/js/agent_workspace.js`：Plan 行重跑按钮 + `_rerunPlanStep`。

### 5.3 验证
`tests/verify_p2_rerun.py`：先跑完整方案 → 发 `rerun_plan_index=0` → 收到新 `tool_start(plan_index=0)` 且最终 answer 非空、`success=True`。

---

## 6. P2-2：长程记忆（episodic + procedural）

### 6.1 现状
`ConversationMemory` 已有**对话级**持久记忆（agent_memory 表）；`user_profile` 有画像提炼（procedural 雏形）但未注入执行。缺：**跨会话的"经验记忆"**（用户历史方案/偏好，下次新任务自动参考）。

### 6.2 设计：`app/agent/memory_profiles.py`（NEW）
- **episodic（情景记忆）**：每完成一次方案生成（`success=True` 且 intent∈方案类），`_save_episode(user_id, session_id, demand, answer_summary)`：
  - 新表 `agent_episodes`（`user_id, created_at, demand, summary, embedding_json`）——embedding 用已有 BGE 模型（`app/services/embedding_service` 或现取向量接口）对 `demand + summary[:200]` 编码。
  - 新任务启动时 `_retrieve_episodes(user_id, user_input, top_k=3)`：对用户输入编码 → 与历史 episodes 余弦相似度 → top-3 摘要注入 extra_context（**截断 ≤600 字符**，控制 token 预算）。
- **procedural（程序性记忆）**：从 `user_profile` 读画像（industries/tone_preferences/summary），在首轮系统 prompt 追加「用户画像」块（已有表，仅注入，不新存）。
- **清理**：`DELETE /api/agent/memory`（Agent 路由）清空该用户 episodes（供设置页按钮）。

### 6.3 文件改动清单
- `app/agent/memory_profiles.py`（NEW）：表结构 + 保存/检索/清理。
- `app/utils/db_init.py`：`agent_episodes` 建表（铁律②：新列/表写进 db_init）。
- `app/agent/harness.py`：`run()` 首轮注入 episodes + 画像；`_make_result` success 时调 `_save_episode`（异步 best-effort）。
- `api/agent_routes.py`：`DELETE /api/agent/memory`。
- 前端（最少）：设置/侧栏展示「记忆条数」+ 清空按钮（可后置，先保证后端）。

### 6.4 验证
`tests/verify_p2_memory.py`：`_save_episode` ×2 → `_retrieve_episodes("制造业预测性维护")` 命中第 1 条（相似度排序）→ 注入后 prompt 含历史摘要 → DELETE 后检索为空。

---

## 7. P2-3：MCP 集成（工具生态标准化，优先级最低）

### 7.1 设计（零新依赖）
不装 `mcp` SDK，用 Python stdlib 实现**最小 MCP 协议（JSON-RPC 2.0 over stdio）**，把现有 `ToolRegistry` 暴露为标准 MCP server；同时支持从外部 MCP server 拉取工具注册进 ToolRegistry（可插拔第三方工具）：

- `app/agent/mcp_server.py`（NEW）：
  - `list_tools()` → 遍历 ToolRegistry，输出标准 MCP `tools/list` 响应（name/description/inputSchema，由 Tool.parameters 映射）。
  - `call_tool(name, arguments)` → 走 `registry.execute(name, **arguments)`，输出 `tools/call` 响应（`{content:[{type:"text", text:obs}], isError:false}`）。
  - `serve_stdio()`：读 stdin 逐行 JSON-RPC（`initialize`/`tools/list`/`tools/call`），写 stdout；`main()` 供 `python -m app.agent.mcp_server` 启动。
- `app/agent/mcp_client.py`（NEW，可选拉伸）：`register_remote_tools(cmd)` → 以子进程启动外部 MCP server，`tools/list` 拉取 → 每个远端工具包一层适配器（参数转发 + 结果回传）注册进 ToolRegistry。
- **不做**：不引入网络端点、不做 SSE 传输（stdio 已够展示）；MCP 作为能力展示 + 可插拔架构声明。

### 7.2 文件改动清单
- `app/agent/mcp_server.py`（NEW）+ `app/agent/mcp_client.py`（NEW，可选）。
- `app/agent/tools.py`：`ToolRegistry` 增加 `list_mcp_tools()` / `execute_mcp(name, arguments)` 薄封装（复用现有 get/execute）。

### 7.3 验证
`tests/verify_p2_mcp.py`：`initialize`+`tools/list` 返回 ≥7 工具且 schema 含 parameters；`tools/call analyze_demand` 返回非空文本。

---

## 8. 决策锁定（本次拍版，无需再议）

- **D1（两阶段执行）→ 做**：新增 `_plan_and_execute`，plan 真正驱动执行顺序；**保留旧 ReAct 循环作兜底降级**（AGENT_TWO_PHASE 开关默认开）。
- **D2（多智能体）→ 做**：三角色（分析师→架构师→校验官）Orchestrator-Workers，复用同一引擎，AGENT_MULTI_AGENT 开关默认开，knowledge_q/file_ops 不走三角色。
- **D3（Plan 重跑）→ 做**：`rerun_plan_index` 走复用 SSE 通道，不加新端点。
- **D4（PPTX）→ 做**：`python-pptx` 已装，ExportFormat 加 PPTX，generate_doc 支持。
- **D5（长程记忆）→ 做**：episodic（agent_episodes 表 + BGE 检索 top-3）+ procedural（user_profile 注入），截断控 token。
- **D6（MCP）→ 做最小版**：stdlib JSON-RPC over stdio，工具暴露为标准 MCP；外部工具拉取为可选拉伸项。
- **D7（web_search 激活）→ 保持默认关闭**：不配 key 不联网（P1 决策延续）。

**实现基线版本号**：`frontend/index.html` 资源统一升 `v=20260828a`。

---

## 9. 验证计划（实现后必跑）

| 验证项 | 脚本 | 断言 |
|---|---|---|
| D4 PPTX | `tests/verify_p2_pptx.py` | generate_doc(pptx) → 下载 200 + python-pptx 打开章节≥1 |
| P2-1-A 两阶段 | `tests/verify_p2_plan_exec.py` | tool_start.plan_index 单调非降；末步 final 点亮 |
| P2-1-B 多智能体 | `tests/verify_p2_agents.py` | agent_phase 三阶段有序；终稿过自检 |
| D5 重跑 | `tests/verify_p2_rerun.py` | rerun_plan_index=0 → 新 tool_start + success |
| P2-2 记忆 | `tests/verify_p2_memory.py` | 检索命中 top-3；注入 prompt 含历史；DELETE 后空 |
| P2-3 MCP | `tests/verify_p2_mcp.py` | tools/list ≥7；tools/call 真实执行 |
| 回归 P1 | `verify_p1_plan_step.py` + `verify_p1_tools.py` + `verify_p1_reflexion.py` | 全绿（两阶段默认开启后 P1 协议仍成立） |
| 回归 P0 | `verify_export_p0.py` | 导出链路不回归 |
| E2E | `tests/verify_p2_e2e.mjs`（Playwright） | 浏览器：Plan 面板重跑按钮可点 + agent_phase 阶段徽标 + pptx chip |

---

## 10. 实现顺序

1. **D4 PPTX**（独立低风险）→ `verify_p2_pptx.py`。
2. **P2-1-A 两阶段执行**（核心，新增方法+开关，不删旧路径）→ `verify_p2_plan_exec.py`。
3. **P2-1-B 多智能体**（叠加角色层）→ `verify_p2_agents.py`。
4. **D5 Plan 重跑**（依赖 2）→ `verify_p2_rerun.py`。
5. **P2-2 长程记忆**（独立，含 db_init 建表）→ `verify_p2_memory.py`。
6. **P2-3 MCP**（独立 stdlib 实现）→ `verify_p2_mcp.py`。
7. **前端**（阶段徽标 + 重跑按钮 + pptx chip）+ 版本 `v=20260828a` → `verify_p2_e2e.mjs`。
8. **全量回归**（P1×3 + P0 + 各 verify_p2_*）→ 部署待用户拍板。

> 任何一步改完立即跑对应 verify 脚本，全绿再进下一步；P2 全绿后汇总交付。
