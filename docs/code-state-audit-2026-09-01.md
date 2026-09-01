# 代码真·状态审计（2026-09-01）

> 目的：基于代码事实（grep + 关键文件精读）核对"已做 vs 真未做"，纠正此前基于旧待办清单的误判。
> 范围：Agent 各阶段、CRM、密码/邮箱、KB 多租户、客户上下文匹配 Plan A、资讯/展会等。

## ✅ 已做（代码核验通过）

| 模块 | 证据 | 状态 |
|---|---|---|
| **Agent P1** plan 实时点亮 / generate_doc / web_search / reflexion | `harness.PLAN_STEP_TOOL_MAP`（L248）、`agents.py`、`tools_search.WebSearchProvider`、`_reflexion_retry` | DONE |
| **Agent P2** 两阶段 plan 驱动 / 多智能体 / 长程记忆 / 单步重跑 / PPTX | `_plan_and_execute`(L351)、`agents.py`、`memory_profiles.py`(save_episode/build_memory_context)、`_rerun_plan_step`(L667)、`ExportFormat.PPTX`(tools.py:341) | DONE |
| **Agent P3** 自检 Gate / 真反思-重规划 / 并行子体 + 工具参数修复 | `_self_check_gate`(L1871)、`_reflexion_replan`(L2164)、`_parse_react_actions`/`_exec_one_action`、`tools._normalize_args` | DONE |
| **CRM（P6）** 客户表 + 全套 CRUD + 历史方案 | `db_init.clients` 表(L119)、`api/routes.py` `/clients` GET/POST/PUT/DELETE(L1416-1532) + `match_history` 全套(L2338-2650)、`frontend/script.js` 客户管理 CRM 页(L6035+)、`CustomerFileUploader`(L5550) | DONE |
| **密码找回** | `auth_routes.py` `/forgot-password`(L159) `/reset-password`(L168)、`auth_service.forgot_password/reset_password`、`email_utils.send_reset_email`(163 SMTP)、`db_init.reset_token` 列 | DONE |
| **邮箱绑定** | 后端 `PATCH /auth/profile` 写 email；前端 `script.js` `_showEmailBindingPrompt`(L292) 含"暂不绑定"跳过 | DONE |
| **KB 多租户隔离** | `tools.get_kb_user_context`(L18/L25)、`get_user_knowledge_base`(L27)、`file_security.get_user_root` | DONE |
| **UI 标签** "匹配准确率"→"方案覆盖度" | 前端已无"匹配准确率"；`agent_workspace.js:63` 已用"方案覆盖度" | DONE |
| **客户上下文匹配 Plan A** | `agent_routes._build_client_context_block`(L1325)：归属校验 + 客户档案 + `_select_relevant_client_solutions(top_k=5)`(L1374, BGE 余弦) 注入提示词；`harness._client_context` 透传(L193/828/1767)；经典结果页提示 `script.js:6565` | DONE（见 🟡 小缺口） |
| **资讯 / 展会 / 华为云动态** | `platform_knowledge.py`、`api/routes.py` 行业展会(L537/L677) | DONE |

## 🟡 真未做 / 部分（实打实的缺口）

1. **Agent 模式结果页未渲染"已参考客户背景"提示** — Plan A 在 Agent 侧把 `client_context` 注入了提示词（`harness._client_context`），但 `agent_workspace.js` 结果页**没有**渲染 `result.client_context_used`（经典 `script.js:6565` 有）。即 Agent 侧"注入了、没提示"。**minor**，对齐经典即可修。
2. **MCP 远程工具（P2-3 拉伸项）** — `app/agent/mcp_client.py:87` `register_remote_tools` 为结构占位/stub（`TODO(原实现)`），未接真实远程 MCP server。可选能力，非核心。
3. **GaussDB 向量库** — `app/models/vector_db.py:20` `raise NotImplementedError("华为云GaussDB向量数据库后续接入")`，当前用 ChromaDB。未来接入，非阻塞。
4. **生产部署 Agent 栈** — 实测 `cloudsol.cn` 仍是经典模式基底（v=20260801t，index.html 无 `agent_workspace` 引用），Agent 视图（P1/P2/P3）从未上线。最大"未完成"＝**部署动作**，非代码缺失（用户暂缓中）。

## ⚪ 非缺口（澄清，避免误判）

- **web_search 默认关闭**（`WEB_SEARCH_PROVIDER=""`）：`TavilyProvider`/`SerperProvider` 为真实实现，需配 key 才启用；`WebSearchProvider` 基类 `search` 的 `NotImplementedError`(tools_search.py:30) 是抽象模板方法，非缺失。无 key 时优雅降级（仅知识库作答）。
- Agent 与经典**同一套登录/用户**：单 `users` 表 + 单 JWT，`shared_runtime.Session` 同源；切换经典↔Agent 仅 `<body>` 切 `view-classic/view-agent`，非换账号。

## 结论

此前基于旧待办清单列的"密码找回 / 邮箱绑定 / CRM / KB 多租户 / 方案覆盖度标签 / Plan A"**全部已实现**，属 stale 误判。代码侧功能基本齐备，真正可推进的只有：
- **A. 部署 Agent 到生产**（用户暂缓）；
- **B. 修 Agent 模式客户上下文提示小缺口**（对齐经典，约 10 行）；
- **C. 接 MCP 远程工具真实实现**（如需）；
- **D. 用户点名的具体新需求 / bug**。

下一步优先级由用户拍板。
