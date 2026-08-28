# cloudsol.cn 后续任务交接文档（Agent 模式重塑 P1/P2 + 待办清单）

> **适用对象**：接手 Agent 模式重塑的下一位开发同事/模型  
> **撰写时间**：2026-08-26  
> **当前分支**：`feature/agent-platform`（worktree 路径 `E:\newai\huawei-cloud-solution-matcher`）  
> **线上版本**：v=20260826d  
> **最近一次部署**：本地直接启动（非生产服务器 47.96.109.234）

---

## 一、项目背景与产品定位（30 秒读完）

- 个人作品集，面向 ToB 售前/解决方案求职，目标用户=售前/销售鼠标用户
- 已上线部署在云端云端（www.cloudsol.cn），华为云 ECS 47.96.109.234
- 简历口径：**317 篇方案资料 / 800+ 向量片段 / 25 行业 / 12 竞品厂商**
- 优先级：**功能/体验/稳定性 >> a11y**（不主动优化 a11y）
- 经典模式（**不重塑**）是核心销售路径，已经稳定，**严格冻结不动**
- Agent 模式（**重塑区**）目前经过 P0 阶段"去包装感"，已具备初步自主智能体形态

---

## 二、当前技术栈

```
后端：FastAPI + Uvicorn (:8000) + SQLite + ChromaDB + BGE-small-zh + DeepSeek API
前端：Vanilla JS SPA + Nginx（index.html 单页 + module 化 JS）
模型：DeepSeek-V4-Pro / DeepSeek-V4-Flash（前端可切）
权限：三匹配模式未登录弹框拦截；快速体验走 /match 匿名；Agent 端点需登录
agent 引擎：app/agent/（自研 harness + ReAct loop + 5 RAG 工具 + LangChain）
```

---

## 三、P0 阶段已完成 ✅（"去包装感"4 项）

| # | 子项 | 文件 |
|---|---|---|
| 1 | Plan 面板：执行前 LLM 生成 3-6 步计划，前端逐步打勾（Devin 式） | `app/agent/harness.py` `_generate_plan` / `frontend/js/agent_workspace.js` `_renderPlan` / `agent_workspace.css` `.ws-plan` |
| 2 | 工具结果摘要：tool_end 事件附"检索到 N 篇，最相关《xxx》" | `app/agent/harness.py` `_summarize_tool_result` / `agent_workspace.js` tool_end 处理 |
| 3 | 模板降权（对话侧不强制 14 章） + **Agent 模式一键导出 Word**（模板在导出端应用） | `app/services/solution_prompt.py` `build_agent_format_block()` / `app/services/solution_matcher.py` `format_mode="agent"` / `agent_workspace.js` `_appendExportActions` + `_exportAnswer` |
| 4 | 完整性自检（Evaluator-Optimizer 轻量版）：LLM 自查方案是否覆盖关键元素 | `app/agent/harness.py` `_self_check_answer` |

### P0 关键改动文件清单

```
app/agent/harness.py           # P0 Plan/自检/工具摘要核心
app/agent/intent.py            # 微调
app/services/demand_analyzer.py # NEW 共享函数（经典/Agent 共用）
app/services/solution_prompt.py # 新增 build_agent_format_block
app/services/solution_matcher.py # 支持 format_mode="agent"
api/agent_routes.py            # 收拢所有 Agent 路由（已从 routes.py 迁出）
api/sse_utils.py            # NEW sse_json_default 共享工具
api/routes.py                  # 收拢后只剩经典路由（零 Agent 业务）
app/agent/tools.py             # _tool_analyze_demand 委托共享服务
frontend/js/agent_workspace.js # Plan 面板 + 工具摘要 + 导出按钮 + 导出 fetch
frontend/css/agent_workspace.css # .ws-plan / .ws-think-tool-result / .ws-export-btn 等
```

### P0 验证脚本（可重跑）

- `tests/verify_p0_reshape.py` — P0 完整链路验证（Plan + 摘要 + 模板降权）
- `tests/verify_export_p0.py` — Agent 模式导出 Word 链路验证

---

## 四、评估报告 P1 阶段（2-4 周）：真正 Agent 化的骨架

> 评估报告：`docs/agent_vs_mainstream_评估报告_2026-08-26.md`

### P1-1：Plan-and-Execute 架构重构

**当前问题**：solution/competitor 意图走的还是单循环 ReAct（harness.py run() 主体），没有真正的"先 plan → 按 plan 逐步执行 → 汇总"。

**改造方向**：
- 把 `app/agent/harness.py` 的 `_run_react` 拆为：
  - `_plan_and_execute(user_input)` → 第一阶段：调 LLM 生成结构化 plan（已实现）
  - `_execute_step(step)` → 第二阶段：每步独立调工具，已实现部分（tool_call）
  - `_synthesize_final()` → 第三阶段：汇总所有 step 结果生成最终答案
- plan 不只是给前端看，而是真的驱动执行顺序
- 每步可独立失败/重试，不影响其他步骤

**涉及文件**：
- `app/agent/harness.py`（主战场）
- `app/agent/intent.py`（plan 默认结构）
- `frontend/js/agent_workspace.js`（Plan 面板升级：可点击单独重跑某步）

### P1-2：补 2 个高价值工具

#### A. `generate_doc(format)` —— 把方案导出为 Word/PPT（做成 agent 工具）

**现状**：导出能力**已在 `api/export_routes.py` + `app/services/report_generator.py` 实现**，但前端只是手动点击按钮触发，不是 agent 工具。

**改造**：
- 新增 `_tool_generate_doc(format: str)` in `app/agent/tools.py`：
  - 入参：format（word/pdf/pptx）
  - 调用 report_generator 生成文档
  - 返回：task_id + download_url
- 注册到 `agent.harness.tools` 的 TOOLS 字典
- 在 agent `_finalize_answer` 之后可自动调用，或用户对话中说"导出"时调用
- agent prompt 增加工具描述：让 LLM 知道有这个工具

**涉及文件**：
- `app/agent/tools.py`（新工具实现）
- `app/agent/harness.py`（TOOLS 注册）
- `frontend/js/agent_workspace.js`（工具调用结果显示 + 自动下载）

#### B. `web_search(query)` —— 补充知识库之外的最新资讯

**现状**：Agent 只能查知识库（317 篇本地资料），无法查互联网。华为云产品页/白皮书/新闻查不到。

**改造**：
- 新增 `_tool_web_search(query: str)` in `app/agent/tools.py`：
  - 可选 provider：serper.dev / tavily / bing search API
  - 需要 .env 加 `WEB_SEARCH_API_KEY` 配置
  - 返回：top 5 搜索结果（url + title + snippet）
- 注册到 harness TOOLS
- 限流：每会话最多 N 次（避免 token 爆炸）
- 安全：禁止外链，搜索结果仅作为参考摘要回传给 LLM，不作为可点击 URL

**涉及文件**：
- `app/agent/tools.py`
- `app/agent/harness.py`（TOOLS + 限流）
- `app/config.py`（新配置项）
- `.env.example`（同步）
- `frontend/js/agent_workspace.js`（工具结果展示）

### P1-3：Reflexion 反思机制

**当前问题**：当 max_steps 耗尽或工具连续失败时，直接 fallback 到 `_generate_fallback`，没有"反思哪里不对"再试一次的逻辑。

**改造**：
- 在 `app/agent/harness.py` `_run_react` 失败时调 `_reflexion_retry`：
  - 把最近 3-5 步 observation 喂给 LLM，反问"刚才哪里不对？"
  - LLM 输出调整后的下一步 action，重试一次
  - 二次失败才 fallback
- 加 metric 统计：reflexion 成功率

**涉及文件**：
- `app/agent/harness.py`（新增 `_reflexion_retry`）
- `app/agent/prompts.py`（如已有 prompts 模块，新加 reflexion prompt）

---

## 五、评估报告 P2 阶段（可选，1-2 周）：进阶形态

### P2-1：多智能体（Orchestrator-Workers）

```
需求分析师 → 方案架构师 → 质量校验官（3 个 sub-agent）
```

- 各 sub-agent 配独立工具集
- orchestrator 协调工作流
- 适合复杂方案生成场景

### P2-2：长程记忆（episodic + procedural）

- 把用户历史方案/偏好做成向量记忆
- 新任务自动注入历史上下文（Plan A 客户上下文基础上扩展）
- 注意 token 预算

### P2-3：MCP 集成（Model Context Protocol）

- 把工具生态做成标准 MCP server
- 第三方工具可插拔
- 当前优先级最低

---

## 六、独立 Bug 修复（不属 P0/P1，但影响体验）

### BUG-1：`.welcome-page` 在 view-agent 视图未隐藏 ✅（已修复 2026-08-26）

**症状**：切到 Agent 视图后，经典首页（304 文档 / 25 行业 / 12 竞品背景页）仍可见，与 Agent 内容共存。

**根因**（已确认）：`.welcome-page` 直接挂在 `<body>` 下（index.html:78），**不在** `#classic-solution`（index.html:550）内，所以 `#classic-solution { display:none }` 没法隐藏它。且其显隐由 `welcome-script.js` 的 `WelcomeManager.show()/hide()` 用**内联** `style.display` 控制，纯 CSS 不加 `!important` 会被内联样式盖掉。

**修复（已落地）**：在 Agent 模式样式文件 `frontend/css/agent_workspace.css` 末尾加（铁律①：不碰经典文件）：
```css
body.view-agent .welcome-page,
body.view-agent #demo-selector-modal {
    display: none !important;
}
```
> 同时把同源且挂在 `<body>` 下、不在 `#classic-solution` 内的 `#demo-selector-modal`（index.html:146）一并隐藏，避免经典 Demo 选择浮层在 Agent 视图泄漏。
> `frontend/index.html` 版本号 `css/agent_workspace.css?v=20260826d` → `v=20260826e`（铁律③ 破缓存）。

**验证**：`tests/verify_bug1_e2e.mjs`（Playwright，全新上下文首日逻辑）：经典 `welcome.display=flex` → 切 `view-agent` 后 `welcome.display=none` / `demo.display=none` → 切回 `view-classic` 恢复 `flex`。**通过 ✅**

### BUG-2：导出按钮状态已修复 ✅

**症状**：v=20260826c 下载成功后按钮卡在"生成中..."
**根因**：`_exportAnswer` 只在 `catch` 块还原按钮，成功路径无还原
**修复**：v=20260826d 在 `.then()` 末尾统一还原（已上线本地版本）

---

## 七、其他待办 / In-Progress 任务（来自 TaskList）

```
#52  [pending] Add streaming reasoning/thinking display to Agent chat
            # 已在 P0 阶段覆盖（_renderPlan + tool 摘要）。可关。
#85  [pending] Playwright 端到端验证 + 截图
            # 之前 localStorage 流式进度相关；本地已验证。补一次完整 E2E 截图。
#100 [pending] 生成测试报告文档并展示
            # 把 50 题测试结果写成 docs/agent_test_report_2026-08-XX.md
#102 [in_progress] E. harness 账户意图真实取数
            # 让"我的客户"类查询真的从 SQLite users/clients 表取数，不要返回硬编码话术
#103 [in_progress] 重测账户问题与回归
            # 把账户类问题（"我有多少客户"/"上次和某客户的方案"）重测一遍
#104 [pending] F. 报告 markdown 渲染修复
            # agent 答案 markdown 渲染器某些边界 case（嵌套列表/代码块/中文标点）需修
#108 [in_progress] Agent 模式深度测试（问问题+操作类）
            # 跑 50-100 题压测，覆盖 solution/competitor/knowledge_q/file_ops/账户 5 类
```

---

## 八、设计铁律（必须遵守，否则破坏架构）

### 铁律 ①：双模式代码物理隔离

- 经典模式文件：`frontend/script.js` + `frontend/style.css` + `api/routes.py`（仅经典部分）
- Agent 模式文件：`frontend/js/agent_workspace.js` + `frontend/css/agent_workspace.css` + `api/agent_routes.py`
- 共享：`frontend/js/shared_runtime.js`（Session/Token + TaskGuard）+ `app/services/*`（向下依赖共享合理）
- 切换：`body.view-classic / view-agent`，由 `ViewManager` 统一调度
- **经典模式字节不动**，Agent 模式可任意修改

### 铁律 ②：agent_workspace.js 不引用经典 API 模块

- 经典 API（`API.match`、`API.exportReport`、`UI.showToast` 等）在 `script.js`
- Agent 必须**独立实现**对应能力（fetch + UI 封装）
- 例：导出按钮的 fetch 是自己写的，不调用 `API.exportReport`

### 铁律 ③：前端版本号必须递增

- `frontend/index.html` 里 `?v=20260826d` 必须递增（目前 `d`）
- 后端 API 路由**不要加随机版本号**（会被客户端缓存，影响接口稳定性）

### 铁律 ④：经典模式 sales 结果缓存不动

- `State.resultCache.solution` 是经典模式的核心数据结构
- Agent 模式有自己的 localStorage 存储（`agent_convos_v1`），不混用

### 铁律 ⑤：本地开发端口冲突解决

- 8000 端口冲突时（WinError 10013）：用 `netstat -ano | grep ":8000"` 找占用 PID，PowerShell `Stop-Process -Id <PID> -Force` 杀掉
- 后端测试脚本：`tests/_kill_8000.py`（Windows 专用，已落库）

---

## 九、关键代码路径（快速定位）

### 后端 Agent 入口

```
POST /api/agent/chat             → api/agent_routes.py:chat_agent()
                                       ↓ 调 get_agent().run()
POST /api/agent/match            → api/agent_routes.py:agent_match_solution()
                                       ↓ 调 get_agent().run()
POST /api/agent/match/stream     → api/agent_routes.py:agent_match_stream()
POST /api/agent/clarify          → api/agent_routes.py:agent_clarify_resume()

Agent 引擎：app/agent/agent.py → app/agent/harness.py
意图分类：app/agent/intent.py
工具实现：app/agent/tools.py
记忆：app/agent/memory.py
澄清状态：app/agent/clarify_store.py
文件安全：app/agent/file_security.py
文件解析：app/agent/parsers/read_file.py
```

### 前端 Agent 入口

```
welcome-script.js → ViewManager.setView('agent') → ViewManager._apply('agent')
        → window.AgentWorkspace.init()
                → DOM 渲染 + 事件绑定
                → 用户输入 → fetch(AGENT_ENDPOINT='/api/agent/chat', ...)
                → SSE 解析 → onEvent 处理
```

### 关键方法（agent_workspace.js）

```
_appendAgentShell()        # 创建消息气泡容器（answer/actions/clarify）
_appendThinkingStep(text, kind)  # 流式追加思考步骤
_renderPlan(plan)          # P0：渲染 Plan 面板
_appendExportActions()     # P0：答案就绪后追加导出按钮
_exportAnswer()            # P0：调用 /api/export/report 生成 Word
_markLastToolStepDone()    # 工具步骤完成打勾
_finishThinking()          # 思考面板结束（变 ✓）
```

### 关键方法（harness.py）

```
run()                       # 主入口
_classify_intent()          # 意图分类（7 类：solution/competitor/knowledge_q/file_ops/clarify/account/...)
_generate_plan()            # P0：执行前生成 3-6 步计划
_run_react()                # ReAct 主循环（max_steps 限制）
_execute_tool()             # 工具分发
_finalize_answer()          # 输出整理（已用 format_mode="agent" 模板降权）
_self_check_answer()        # P0：完整性自检（Evaluator-Optimizer 轻量版）
_summarize_tool_result()    # P0：tool_end 摘要
_make_result()              # P0：透传 plan + format_mode
```

---

## 十、环境与登录

```
本地用户：guo（user_id=3）
本地密码：123456
测试 token 生成：cd tests && node _gen_token.js
邮箱（发送）：henryguo0523@163.com
邮箱（接收）：3324507839@qq.com
```

### 本地启动后端

```bash
# 注意：先确保 8000 端口空闲
netstat -ano | grep ":8000"   # 看是否有 LISTENING

# 启动
cd /e/newai/huawei-cloud-solution-matcher
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false \
  e:/newai/huawei-cloud-solution-matcher/venv/Scripts/python.exe -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

### 本地启动前端

```bash
# 直接打开 frontend/index.html（或双击运行项目根目录的启动脚本）
# 浏览器访问 http://localhost:8000
```

---

## 十一、给接手模型的建议

1. **先看 docs/agent_vs_mainstream_评估报告_2026-08-26.md** — 理解为什么这么改
2. **再读本文件** — 了解当前状态和剩余任务
3. **再跑 `tests/verify_export_p0.py`** — 确认 P0 端到端可用（应在 ~2 分钟内跑通）
4. **开始 P1 改造前先写 design doc** — P1 涉及 harness 大改，不能直接动手
5. **每次大改前先 grep 铁律** — 防止破坏双模式隔离
6. **Agent 模式 E2E 测试优先用 backend script（Python+httpx）** — agent-browser 经常 timeout，效率低
7. **bug 修复后必须 E2E 验证** — 不能只改代码就汇报

---

## 十二、变更日志（最近 5 天）

```
2026-08-26 (P0 完成)
  - Agent 模式 Plan 面板 / 工具摘要 / 模板降权 / 完整性自检 / 导出 Word
  - 路由收拢（3 agent 路由从 routes.py 迁入 agent_routes.py）
  - 抽共享函数 demand_analyzer.py（经典/Agent 共用）
  - frontend v=20260826a → v=20260826b → v=20260826c → v=20260826d
```

```
2026-08-25 (Agent UI 重塑)
  - 输入工具栏补全（深度思考 / 模型选择 / 语音）
  - 工具栏两行布局（输入栏 + 工具行）
  - 快捷场景 chip
  - 视觉对齐经典模式
```

```
2026-08-24 (Agent UI 起步)
  - 初始 Agent 视图基础布局
```