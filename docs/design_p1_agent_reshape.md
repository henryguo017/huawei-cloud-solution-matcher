# P1 设计文档：Agent 模式真正 Agent 化（Plan-and-Execute / 工具补全 / Reflexion）

> **撰写时间**：2026-08-26  
> **基于分支**：`feature/agent-platform`（commit 已含 P0 + BUG-1 修复，前端 `v=20260826e`）  
> **前置必读**：`docs/handoff_agent_reshape_后续任务.md` + `docs/agent_vs_mainstream_评估报告_2026-08-26.md`  
> **目标**：消除 P0 之后残留的「包装感」，让 Agent 真正「先计划→按步执行→反思纠错」，并补上 2 个高价值工具。

---

## 0. 设计铁律（不可违反）

1. **经典模式字节不动**：`frontend/script.js` / `style.css` / `api/routes.py` 一律不碰。Agent 改动只限 `app/agent/**` + `api/agent_routes.py` + `frontend/js/agent_workspace.js` + `frontend/css/agent_workspace.css`。
2. **agent_workspace.js 不引用经典 API 模块**：导出/取数等能力 Agent 自己实现。
3. **前端版本号必须递增**：本次实现统一升到 `v=20260827a`（index.html 里 `?v=` 全量替换）。
4. **每次大改后必须 E2E 验证**（后端脚本优先，浏览器截图兜底），不能只改代码就汇报。
5. **稳定性 >> 新功能**：P1 涉及 `harness.py` 主循环大改，任何拆分都要保留澄清（clarify）/文件操作（file_ops）/知识查询（knowledge_q）三条已验证路径不回归。

---

## 1. 当前架构事实（写设计前先对齐）

- **主循环**：`app/agent/harness.py::run()`（L268）首轮 `classify_intent` 分流后，非轻量意图进入 `while self._step_count < self.max_steps`（L461）单循环：调 LLM → `_parse_react_output` → `final_answer` / `clarify` / `action`。纯文本 ReAct 协议（Action/Final Answer/Clarify），不依赖原生 function calling。
- **Plan 现状（P0）**：`_emit_plan`（L259）在进循环前生成 `self._plan`（L190），仅通过 `plan` 事件推前端展示，**不驱动执行顺序**，也没有 plan↔tool 的映射。前端 Plan 面板只是静态清单。
- **工具集**：`app/agent/tools.py::create_default_tools()`（L308）注册 5 个：`analyze_demand` / `search_kb` / `search_competitor` / `read_customer_file` / `list_dir`。
- **增强管线**：`_finalize_answer`（L902）统一重写终稿（含 P0 自检 `_self_check_answer` L1003），`format_mode` 取自 `self._format_mode`（solution/competitor）。
- **导出**：`app/services/report_generator.py::generate_report(report_type, content, format, metadata)`（L152）接收 Markdown 内容，返回 `ExportTask`（含 `download_url`/`file_name`/`status`）；`ExportFormat` 仅 `WORD`/`PDF`（**无 PPTX**）。路由在 `api/export_routes.py`。
- **SSE 事件**：`step / thought / tool_start / tool_end / plan / final / result / clarify / error`（见 `api/agent_routes.py` 桥接）。

---

## 2. P1-1：Plan-and-Execute 重构

### 2.1 现状问题
Plan 是「装饰品」：用户看到 3-6 步计划，但实际执行是 LLM 自由 ReAct，计划步与实际工具调用无关联，无法感知「走到哪一步了」，也不能单独重跑某步。

### 2.2 方案选型（**需你拍板，见 §6 决策 D1**）

**选项 A（本文推荐，低风险）— Plan 作为实时进度追踪器 + 步级归属 + 可选重跑**
- 保留现有 ReAct 引擎不动（零回归风险），只新增「plan 步 ↔ 工具调用」的归属映射，让 Plan 面板实时点亮。
- 理由：直接命中「去包装感」目标（用户能看到计划被真实推进），diff 小、可灰度、三天可交付；真正的「重写执行引擎」留给 P2 多智能体（与 Orchestrator-Workers 重叠）。

**选项 B（高收益高风险）— 真·Plan-and-Execute 两阶段重写**
- 把 `run()` 主循环拆为 `_plan_and_execute()` → 对 plan 每步开子循环 `_execute_step()` → `_synthesize_final()`。plan 真正决定执行顺序。
- 风险：clarify/file_ops/knowledge_q 三条路径需全部重新适配，回归面大，且与 P2 多智能体重叠，不建议在 P1 做。

> 下文按 **选项 A** 给出可落地的改动清单。若你选 B，需另写 design doc 并单独拍版。

### 2.3 选项 A 具体改动

**(a) plan 步状态机（harness.py）**
- 新增 `self._plan_status: list[str] = []`（`"pending"/"running"/"done"`），在 `_emit_plan`（L259）里随 `self._plan` 一起初始化为全 `pending`。
- 新增每意图「工具→步」映射表（放在 `_PLAN_INTENT_META` 附近，L204）：
  ```python
  PLAN_STEP_TOOL_MAP = {
      "solution":     [["analyze_demand"], ["search_kb", "search_competitor"], []],  # 第3步=综合生成，在 final_answer 时点亮
      "competitor":   [["search_competitor", "search_kb"], []],
      "knowledge_q":  [["search_kb"], []],
      "file_ops":     [["list_dir"], ["read_customer_file"], []],
  }
  ```
- 在 `action` 分支（L538 起）的 `tool_start` 事件里计算 `plan_index`：取「映射表该意图里、要求工具包含本 tool、且状态≠done 的第一条」索引；将其置 `running` 并随事件下发 `plan_index`。`tool_end` 事件里置 `done` 并下发 `plan_index`。
- `final_answer` 分支（L491）：把该意图最后一步（综合/生成步，映射为空列表那项）置 `done`，`final` 事件带 `plan_index = len-1`。

**(b) SSE 事件扩展**
- `tool_start` / `tool_end` / `final` 事件新增字段 `plan_index: int`（无归属填 `-1`）。
- `api/agent_routes.py` 的 `run_agent` 收尾 `result` 事件已含 `plan`，**无需改**；前端从 `tool_start/tool_end/final` 的 `plan_index` 驱动点亮。

**(c) 前端 Plan 面板（agent_workspace.js / css）**
- `_renderPlan(plan)`（现有）改为按 `plan_index` 渲染每行状态点；监听 `tool_start`→`running`、`tool_end`/`final`→`done`。
- **重跑能力（P1-1 拉伸项，非必须）**：每行加「重跑」按钮，点击后向后端 `/api/agent/chat` 发带 `rerun_plan_index` 的消息，harness 从该行对应工具用原参数重跑、回灌 observation。若时间紧，先只做「实时点亮」，重跑留作 P1-1 收尾或 P2。

**(d) 文件改动清单**
- `app/agent/harness.py`：`_emit_plan` 增 `_plan_status`；`action`/`final_answer` 分支算并下发 `plan_index`；新增 `PLAN_STEP_TOOL_MAP`。
- `frontend/js/agent_workspace.js`：`_renderPlan` 支持状态点 + `plan_index` 事件消费。
- `frontend/css/agent_workspace.css`：`.ws-plan-step.pending/.running/.done` 三态样式。
- `frontend/index.html`：版本升 `v=20260827a`。

### 2.4 风险与回滚
- 风险：映射表覆盖不到的 intent（如 `general` 不进 ReAct，无 plan）— 已隔离，不影响。
- 回滚：Plan 面板改动纯前端 + 事件附加字段（旧前端忽略未知字段），后端可独立回滚。

---

## 3. P1-2：补 2 个高价值工具

### 3.1 A. `generate_doc` —— 把方案导出为 Word/PDF（做成 Agent 工具）

**现状**：导出能力已在 `report_generator.py` + `api/export_routes.py` 实现，但前端只是手动点按钮（`agent_workspace.js::_exportAnswer`），不是 Agent 工具——用户说「导出成 Word」时 Agent 不会自己调。

**设计**：
- `app/agent/tools.py` 新增 `_tool_generate_doc(format: str = "word")`，**不自己实现生成**，而是复用 `ReportGeneratorService.generate_report`：
  ```python
  from app.services.report_generator import ReportGeneratorService, ReportType, ExportFormat
  rg = ReportGeneratorService()
  rt = ReportType.COMPETITOR if getattr(self_harness, "_format_mode", "solution") == "competitor" else ReportType.SOLUTION
  # content 取 harness 当前终稿（见 3.3 的 _last_draft 透传）
  task = await asyncio.to_thread(rg.generate_report, rt, content, ExportFormat(format))
  return json.dumps({"status": task.status.value, "download_url": task.download_url,
                     "file_name": task.file_name, "task_id": task.task_id})
  ```
- **调用拦截（关键）**：LLM 没有终稿文本，不能只靠它传参。在 `harness.py` 的 `action` 分支（L538）新增：若 `tool_name == "generate_doc"`，从 `self._last_draft`（见 3.3）取终稿、`self._format_mode` 取 report_type，直接调 `_tool_generate_doc` 并构造 observation，跳过「让 LLM 填 content」的死路。
- 注册进 `create_default_tools()`（L308），description 写明「当用户要求导出/生成 Word/PDF 方案时调用」。
- `format` 仅接受 `word`/`pdf`；`pptx` 返回「暂仅支持 Word/PDF」（report_generator 无 PPTX，见 §6 决策 D4）。
- 安全：无终稿时（过早调用）返回「请先完成方案生成」提示，不报错。

**SSE / 前端**：
- 工具 observation 即为 `{download_url,...}` JSON；`tool_end` 摘要可显示「已生成 Word 方案」。
- 额外发一个 `type: "doc_generated"` 事件（带 `download_url`/`file_name`），前端 `_appendExportActions` 复用导出按钮样式渲染一个下载 chip，点开即下。手动导出按钮保留不变。

### 3.2 B. `web_search` —— 补充知识库之外的联网检索

**现状**：Agent 只能查 317 篇本地资料，华为云官网/白皮书/新闻查不到。

**设计（provider 可插拔，默认关闭）**：
- 新建 `app/agent/tools_search.py`：`WebSearchProvider` 抽象 + `TavilyProvider` / `SerperProvider` / `BingProvider` 实现；统一返回 `[{title, url, snippet}]`（top 5）。
- `app/agent/tools.py` 新增 `_tool_web_search(query: str)`：
  - 读 `config.WEB_SEARCH_PROVIDER`；为空 → 返回「当前未配置联网搜索，仅基于知识库作答」，LLM 自动降级。
  - 否则调用 provider，返回 top 5 结果 JSON；**URL 做脱敏**（仅留来源域名，不在 observation 暴露完整外链，防幻觉外链；LLM 只引来源名）。
  - **限流**：`self._web_search_count` 累加，超过 `WEB_SEARCH_MAX_PER_SESSION`（默认 3）返回「已达本会话联网检索上限」。
- 注册进 `create_default_tools()`，description 写明「查知识库之外的互联网最新资料（产品页/白皮书/新闻）时使用」。
- `app/config.py` 新增：`WEB_SEARCH_PROVIDER = ""`（默认关）、`WEB_SEARCH_API_KEY = ""`、`WEB_SEARCH_MAX_PER_SESSION = 3`。`.env.example` 同步。
- **provider 选型（见 §6 决策 D2）**：推荐 **Tavily**（LLM 友好、有免费额度）；Serper 备选。密钥需你提供或在服务器 `.env` 配置（铁律：不写死代码）。

**前端**：`web_search` 的 `tool_end` 摘要显示「联网检索到 N 条」；结果卡片展示来源域名（不含可点外链）。

### 3.3 配套：harness 透传终稿
- `run()` 在 `final_answer` 分支（L493 `final_answer = parse_result["content"]`）后新增 `self._last_draft = final_answer`，供 `generate_doc` 拦截使用。
- 澄清续跑路径也要在恢复后保留上一次的 `_last_draft`（或续跑完成再写），避免续跑后导出空内容。

### 3.4 文件改动清单（P1-2）
- `app/agent/tools.py`：`_tool_generate_doc` + `_tool_web_search` + 注册。
- `app/agent/tools_search.py`：（NEW）provider 抽象与实现。
- `app/agent/harness.py`：`action` 分支拦截 `generate_doc`；新增 `self._last_draft`、`self._web_search_count`。
- `app/config.py` + `.env.example`：web search 配置。
- `api/agent_routes.py`：透传 `doc_generated` 事件（基本无需改，SSE 已通用）。
- `frontend/js/agent_workspace.js` + `css`：`doc_generated` 下载 chip + `web_search` 卡片展示。
- `frontend/index.html`：版本升 `v=20260827a`。

---

## 4. P1-3：Reflexion 反思机制

### 4.1 现状问题
`run()` 在「max_steps 耗尽」（L626）/「LLM 调用异常」（L481）/「循环异常」（L630）时直接 `_generate_fallback`，没有「反思哪里不对再试一次」。

### 4.2 设计
- 新增 `async def _reflexion_retry(self, trajectory: list) -> dict`（harness.py）：
  - 入参 `trajectory` = 最近 3-5 步的 `(thought, action, observation)` 摘要（从 `self._logs` 或 `tool_calls_log` 提取）。
  - 调 LLM 反问：「刚才执行中哪里不对/信息不足？请给出调整后的下一步 Action（或说明已无法继续）。」
  - 解析返回：若得到合法 `action` → 执行一次（受 `max_steps` 保护，不无限递归）；若得到 `final_answer` → 走 `_finalize_answer`；否则 fallback。
- **触发点**（只改失败分支，不碰正常路径）：
  - L626 `超过最大步数` → 先 `_reflexion_retry`，失败再 `_generate_fallback`。
  - 新增「连续工具失败计数」`self._consecutive_tool_failures`：`action` 分支执行工具返回含 `Error:` 时 +1，成功清零；≥2 时在下一轮前触发一次 `_reflexion_retry`（避免盲目重试同一错误参数）。
  -LLM 异常（L481）/ 循环异常（L630）保持直接 fallback（已无上下文可反思）。
- **metric**：`self._reflexion_count` + `self._reflexion_success`；在 `_make_result`（L1377）追加 `reflexion_used: bool` / `reflexion_success: bool`（前端/日志可选消费）。
- **SSE**：反思期间发 `type: "reflexion"` + `text`（前端显示「正在反思上一步…」气泡）。

### 4.3 文件改动清单（P1-3）
- `app/agent/harness.py`：`_reflexion_retry` + 触发点改造 + 连续失败计数 + `_make_result` 字段。
- `frontend/js/agent_workspace.js` + `css`：`reflexion` 事件气泡。
- `frontend/index.html`：版本升 `v=20260827a`。

---

## 5. 验证计划（实现后必跑）

| 验证项 | 脚本 | 断言 |
|---|---|---|
| P1-1 plan 步归属 | `tests/verify_p1_plan_step.py` | `/api/agent/chat` 的 `tool_start` 事件含 `plan_index≥0`；结束时对应步 `done` |
| P1-2 generate_doc | `tests/verify_p1_tools.py` | 对话说「导出 Word」→ 收到 `doc_generated` 事件且 `download_url` 可 200 下载 |
| P1-2 web_search | `tests/verify_p1_tools.py` | 未配 key → 优雅降级文案；配 key → `tool_end` 显示「检索到 N 条」 |
| P1-3 reflexion | `tests/verify_p1_reflexion.py` | 构造连续工具失败 → 收到 `reflexion` 事件且最终仍出答案 |
| 回归 | `tests/verify_export_p0.py` | P0 链路不受影响（plan+摘要+导出） |
| E2E | `tests/verify_p1_e2e.mjs`（Playwright） | 浏览器内 Plan 面板实时点亮 + 导出 chip 可点 |

> 后端脚本用 `venv/Scripts/python.exe` 跑；E2E 用 Playwright（见 BUG-1 修复里的 `verify_bug1_e2e.mjs` 装浏览器方式）。

---

## 6. 决策已锁定（2026-08-26 拍版）

> 以下为最终决定，后续实现严格照此执行，无需再议。

- **D1（P1-1 方案）→ 选项 A**：Plan 实时追踪 + 步级归属 + 实时点亮。保留现有 ReAct 引擎，真·两阶段重写留到 P2 多智能体阶段。
- **D2（web_search provider）→ Tavily**：实现 `TavilyProvider`（可插拔抽象，默认关闭）。需在服务器 `.env` 配 `WEB_SEARCH_API_KEY`（铁律：绝不写死代码，同步 `.env.example`）。未配 Key 时优雅降级。
- **D3（generate_doc 触发）→ 仅用户说导出时**：对话中用户明确要求「导出/生成 Word/PDF」才调工具；保留手动导出按钮，不做 final 后自动下载。
- **D4（PPTX）→ 本次不做**：`report_generator` 仅支持 Word/PDF，`generate_doc` 的 `format` 只接受 `word`/`pdf`，`pptx` 返回「暂仅支持 Word/PDF」。PPTX 生成器留作独立任务。
- **D5（Plan 重跑）→ 留到 P2**：P1 只做 Plan 实时点亮（去包装感核心）；单步重跑涉及上下文回灌，复杂度高，纳入 P2 多智能体阶段。

**实现基线版本号**：`frontend/index.html` 前端资源统一升 `v=20260827a`。

---

## 7. 实现顺序建议（若拍板选项 A）

1. 搭 `self._plan_status` + 映射表 + `plan_index` 事件（P1-1 核心，低风险）→ 跑 `verify_p1_plan_step.py`。
2. `generate_doc` 工具 + 拦截 + `doc_generated` 事件（P1-2-A）→ 跑 `verify_p1_tools.py`。
3. `web_search` 工具 + provider 抽象（默认关闭）→ 跑降级断言。
4. `reflexion_retry`（P1-3）→ 跑 `verify_p1_reflexion.py`。
5. 前端三处展示（Plan 状态点 / doc chip / reflexion 气泡）+ 版本升 `v=20260827a` → 跑 `verify_p1_e2e.mjs`。
6. 回归 `verify_export_p0.py` + 手动 50 题抽检（来自 TaskList #108）。
