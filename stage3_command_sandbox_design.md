# 阶段 3：命令沙箱（Command Sandbox）设计文档

- **版本**：v1 设计稿（待评审）
- **日期**：2026-07-18
- **状态**：设计阶段，尚未写代码
- **关联**：华为云解决方案智能匹配系统（cloudsol.cn）

---

## 0. 文档目的

把"让 Agent 能执行受控命令"这一能力，从设想落成一个**可评审、可实现的工程设计**。本文覆盖：架构接入点、命令注册表、执行引擎、安全模型、命令契约、API/前端交互、配置项、文件改动清单、数据流、测试用例、风险与缓解、推荐范围、待决策项。

> 范围档位（仅安全命令 / 安全命令+受限 shell / 先出设计文档）尚未最终定档——本文同时给出两档设计，评审时由你拍板 v1 落点。

---

## 1. 背景与目标

### 1.1 现状
当前 Agent（`SolutionAgent` + `AgentHarness`）走**纯文本 ReAct 协议**：LLM 输出 `Action:` + `Action Input:`，正则解析后调度工具，工具返回 `Observation` 回灌下一轮。现有 5 个工具均为"检索/读取"类：
- `analyze_demand`（需求结构化）、`search_kb`（华为云向量检索）、`search_competitor`（竞品检索）、`read_customer_file`（读用户文件，已走文件沙箱）、`list_dir`（列白名单目录）。

**短板**：Agent 只能"检索 + 生成"，无法做**结构化数据聚合**（如"这个客户近 30 天几次匹配"）、**计算**（如 ROI/规格测算）、**受限诊断**。这些对售前决策很有价值。

### 1.2 目标
1. 让 Agent 在 ReAct 循环内调用一组**受控、可审计**的命令，辅助售前决策。
2. **安全优先**：默认无任意命令执行；所有命令白名单化、作用域隔离、超时/输出截断保护、全程审计。
3. **无缝接入**：复用现有 `Tool`/`ToolRegistry` 框架，不改 `harness.py`/`agent.py` 主循环。
4. **不破坏现有功能**：新增命令与既有 5 个工具正交，不影响标准/向导/Agent 匹配。

### 1.3 非目标（v1 不做）
- 任意代码执行 / 任意 shell（即使做受限 shell 也默认关闭、需确认）。
- 多进程/分布式会话（现有 `ClarifySessionStore` 是进程内字典；多 worker 需迁外部存储，本阶段不改，标注为已知限制）。
- 阶段 4 自治闭环（多轮自主推进方案）。

---

## 2. 架构接入点（基于代码探查，含 file:line）

| 关注点 | 位置 | 对阶段 3 的意义 |
|---|---|---|
| 工具抽象 | `app/agent/tools.py:32-64` `Tool` 类；`:67-93` `ToolRegistry` | 新命令 = `registry.register(Tool(...))`，LLM 经 `get_tools_prompt()`（`:83-90`）自动可见 |
| 工具注册处 | `app/agent/tools.py:344-436` `create_default_tools()` | 在此追加 `run_command` 工具即可，**无需改 harness/agent** |
| ReAct 引擎 | `app/agent/harness.py:141-406` 主循环；`:443-551` `_parse_react_output`；`:427-439` `_execute_tool` | 纯文本协议，新工具零侵入 |
| 系统提示词 | `app/agent/harness.py:41-88` `REACT_SYSTEM_PROMPT_BASE`，`{tools}` 占位符 | 工具描述自动注入，无需改此处 |
| 文件沙箱范式 | `app/agent/file_security.py:30-55` `safe_resolve`（防 `../` 穿越、锁 `data/user_docs/{user_id}/`） | 命令沙箱借鉴其"白名单 + 目录 jail"思路 |
| 身份上下文 | `app/services/knowledge_base.py:13-24` `get_kb_user_context()`（ContextVar，路由入口 `set_kb_user_context`，`routes.py:448/589/691`） | 命令工具内取 `user_id` 做作用域隔离 |
| 暂停-确认骨架 | `app/agent/clarify_store.py`（进程内 dict+TTL）；`harness.py:284-315` 暂停 / `:173-212` 恢复 | 受限 shell 的"用户确认"可复用此机制 |
| 审计缺口 | `app/services/usage_logger.py` 仅记 `log_match`/`log_analyze` | 本阶段补 `log_command_exec`，填逐命令审计空白 |
| 配置 | `app/config.py`；`agent.max_steps/timeout` 写死在 `get_agent()`（`agent.py:254-255`） | 新增沙箱专用配置项 |

---

## 3. 核心设计

### 3.1 命令注册表 `CommandRegistry`
对标 `ToolRegistry`，专管"命令"：
- `register(name, handler, schema, risk_level)`：`risk_level ∈ {safe, needs_confirm}`。
- 白名单即注册表本身：LLM 传入的 `command` 名不在表中 → 拒绝（返回 `Error: unknown command: <name>`）。
- 参数用 **JSON Schema 校验**（复用 `pydantic` 或 `jsonschema`），校验失败直接拒绝，绝不把脏参数交给 handler。

### 3.2 两类命令
**A 类 · 安全内置命令（`safe`，直接执行，无需确认）**
- `usage_stats`：只读聚合 `usage_logs`/`match_history`，按 `user_id` 作用域。
- `kb_query`：带过滤条件的精确向量检索（比 `search_kb` 更可控，支持 `industry`/`competitor`/`top_k`）。
- `calc`：安全算术/财务表达式求值——**自写 tokenizer+parser，禁用 `eval`/`exec`**，仅允许数字、四则运算符、括号、白名单函数。

**B 类 · 受限 shell（`needs_confirm`，默认关闭，开启后需用户确认）**
- `run_shell`：仅允许白名单二进制（`ping`/`nslookup`/`date`/`wc`/`cat` 等），**禁 shell 元字符**（`; | & $ \` > < ` 换行），`cwd` jail 到用户目录，超时、输出截断、剥离敏感 env。

### 3.3 执行引擎 `SandboxExecutor`
统一入口 `execute(command: str, params: dict, user_id: int) -> str`：
1. 查表：未知命令 → `Error: unknown command`。
2. 校验参数：JSON Schema 失败 → `Error: invalid params`。
3. 危险等级：
   - `safe` → 直接执行。
   - `needs_confirm` → 若未携带有效授权令牌 → 抛 `PendingConfirmation`（由 harness 转成暂停-确认流程）。
4. 执行 handler（见 §5 各命令）。
5. 护栏：超时（见 §4.3）、输出截断（见 §4.4）、异常兜底（返回 `Error: ...`，**绝不崩循环**，复用 `Tool.execute` 模式 `tools.py:62-64`）。
6. 审计：调用 `usage_logger.log_command_exec(...)`（见 §4.5）。
7. 返回 observation 字符串。

---

## 4. 安全模型（重点）

### 4.1 白名单原则
- 能执行的命令 = 注册表里存在的命令；LLM 无法构造注册表外的命令。
- `run_shell` 的**子命令**再套一层二进制白名单（§3.2 B 类）。

### 4.2 身份与作用域隔离
- 所有命令入口先取 `get_kb_user_context()`，要求 `user_id > 0`（匿名用户禁止执行命令，呼应现有 `read_customer_file` 的鉴权 `tools.py:274-276`）。
- `usage_stats` 的 SQL 强制 `WHERE user_id = ?`；`kb_query` 走用户独立知识库（`get_competitor_analyzer_for_user` 同款隔离）；`run_shell` 的 `cwd` 锁 `data/user_docs/{user_id}/`。

### 4.3 超时
- 纯 Python handler（`usage_stats`/`kb_query`/`calc`）：在线程中执行，用 `threading` + `future.result(timeout=SANDBOX_TIMEOUT)` 兜底。
- 子进程（`run_shell`）：`asyncio.wait_for(subprocess_timeout=SANDBOX_TIMEOUT)`。
- 超时 → 返回 `Error: command timed out after Ns`，终止执行，不拖累主循环。

### 4.4 输出截断
- 单条命令输出超过 `SANDBOX_MAX_OUTPUT`（默认 4096 字节）→ 截断并追加 `\n[output truncated, N bytes omitted]`。
- 防止超大输出撑爆 ReAct prompt 上下文。

### 4.5 审计（补现有缺口）
- `usage_logger.log_command_exec(user_id, command, params_hash, status, output_len)`：
  - 记谁、什么命令、参数指纹（不存明文敏感参数）、成功/失败、输出长度。
  - 落 `data/usage_logs.db` 新表 `command_logs`，供后续审计与风控。

### 4.6 受限 shell 的 jail 规则（B 类）
- 二进制必须在 `SANDBOX_SHELL_ALLOWLIST`。
- 参数禁止 shell 元字符（`; | & $ \` > < \n ( ) { }`）——整体做字符串扫描，命中即拒。
- `cwd` 固定为用户目录 jail，禁止绝对路径参数。
- 剥离环境变量中的密钥（不传 `DEEPSEEK_API_KEY` 等），仅保留最小 env。
- 默认 `SANDBOX_SHELL_ENABLED=False`；即使开启，每次执行前需用户确认。

---

## 5. 命令契约（接口签名伪代码）

### 5.1 `usage_stats`
```python
# 输入
{ "metric": "matches|analyses|trends",   # 可选，默认全部
  "days": 30 }                             # 可选，默认 30
# 输出（observation 文本，JSON）
{ "matches_30d": 12, "analyses_30d": 5,
  "recent_trends": [ {...} ] }
# 危险级：safe
# 作用域：WHERE user_id = ? 强约束
```

### 5.2 `kb_query`
```python
# 输入
{ "query": "对象存储跨地域复制",
  "industry": "制造",        # 可选过滤
  "competitor": "阿里云",    # 可选过滤（竞品库）
  "top_k": 5 }               # 可选，默认 5
# 输出
[ { "title": "...", "content": "...(截断)", "source": "..." }, ... ]
# 危险级：safe
```

### 5.3 `calc`
```python
# 输入
{ "expression": "(100000 * 0.12) / 12" }
# 输出
{ "result": 1000.0,
  "note": "支持 + - * / ^ % 及 round/log/sqrt 等白名单函数" }
# 危险级：safe
# 安全：自写 parser，禁用 eval/exec、禁用名字空间访问（防 __import__ 注入）
```

### 5.4 `run_shell`（B 类，默认关闭）
```python
# 输入
{ "command": "ping", "args": ["-c","1","huaweicloud.com"],
  "timeout": 15 }
# 前置：SANDBOX_SHELL_ENABLED=True 且用户已确认
# 输出：stdout（截断后）
# 危险级：needs_confirm
# 约束：二进制白名单、禁元字符、cwd jail、env 剥离
```

---

## 6. API / 前端交互（仅 B 类需要）

复用现有暂停-确认骨架，零新机制：
1. harness 解析到 `needs_confirm` 命令且未授权 → 仿 `Clarify` 分支（`harness.py:284-315`）生成 `confirm_id`，把"待执行命令 + 参数"存入 `ClarifySessionStore`（或新增轻量 `CommandConfirmStore`）。
2. 发 `confirm` 事件（SSE），`paused=True`。
3. 前端弹**确认卡**（复用 clarify 卡片样式），展示"Agent 请求执行命令：`<command>`，是否允许？"。
4. 用户同意 → 带 `confirm_id` 调 `/api/agent/clarify` 续跑，执行真实命令，回灌 Observation。
5. A 类命令不触发确认，正常走 Observation。

> 注：现有 `/api/agent/clarify` 续跑骨架（`routes.py:667-777`）已能恢复状态，仅需在 store 中多存一种"命令确认"类型即可。

---

## 7. 配置项（新增于 `app/config.py`，从 env 读取，带默认值）

| 配置 | 默认 | 说明 |
|---|---|---|
| `SANDBOX_ENABLED` | `True` | 总开关；关则 `run_command` 工具直接返回未启用 |
| `SANDBOX_SHELL_ENABLED` | `False` | 受限 shell 开关；关则 `run_shell` 恒拒 |
| `SANDBOX_TIMEOUT` | `15` | 单条命令超时（秒） |
| `SANDBOX_MAX_OUTPUT` | `4096` | 输出截断字节数 |
| `SANDBOX_SHELL_ALLOWLIST` | `("ping","nslookup","date","wc","cat")` | shell 二进制白名单 |

---

## 8. 文件改动清单

| 动作 | 文件 | 内容 |
|---|---|---|
| 新建 | `app/agent/command_sandbox.py` | `CommandRegistry` + `SandboxExecutor` + A 类三个 handler +（B 类）`run_shell` jail |
| 改 | `app/agent/tools.py` | `create_default_tools()` 注册 `run_command` 工具（指向 `SandboxExecutor.execute`） |
| 改 | `app/services/usage_logger.py` | 新增 `log_command_exec` + `command_logs` 表（建表幂等，遵循"部署铁律②"写进 `db_init.py`） |
| 改 | `app/config.py` | 新增 §7 五个配置项 |
| 改（B 类） | `app/agent/clarify_store.py` | 支持存"命令确认"类型（或新增 `CommandConfirmStore`） |
| 改（B 类） | `api/routes.py` + 前端 | `confirm` 事件续跑；前端确认卡 |

> 部署铁律提醒：新增 DB 列/表必须写进 `db_init.py` 建表+幂等 ALTER，否则生产静默失败。改 `config.py` 默认值需同步 `.env.example`（`.env` 被 gitignore）。

---

## 9. 数据流（端到端步骤）

```
用户需求 → /api/agent/match（带 token）
  → harness 构建 prompt（含 run_command 工具描述）
  → LLM 输出 Action: run_command / Action Input: {"command":"usage_stats","params":{"days":30}}
  → _parse_react_output 解析 → _execute_tool → Tool.execute
  → SandboxExecutor.execute(command, params, user_id)
       1. 查 CommandRegistry（未知→拒）
       2. JSON Schema 校验参数（失败→拒）
       3. 危险级=safe → 执行 usage_stats handler（WHERE user_id=?）
       4. 超时/截断护栏
       5. log_command_exec(审计)
       6. 返回 observation 字符串
  → observation 回灌 current_prompt
  → LLM 结合 observation 生成 Final Answer
  → 前端渲染方案
```
（B 类 `run_shell` 在步骤 3 改为：未确认→抛 PendingConfirmation→发 confirm 事件暂停→用户确认后续跑。）

---

## 10. 测试用例

**A 类（安全命令）**
1. 白名单拒绝：传 `command:"rm -rf"` → 返回 `Error: unknown command`。
2. 参数校验：`usage_stats` 传 `days:"abc"` → `Error: invalid params`。
3. 作用域隔离：`usage_stats` 只返回当前 `user_id` 数据（用两个账号交叉验证）。
4. `calc` 注入防护：传 `expression:"__import__('os').system('ls')"` → 解析失败/`Error`，不执行。
5. 超时：`usage_stats` 注入人为慢查询超 `SANDBOX_TIMEOUT` → 返回超时错误，主循环不崩。
6. 输出截断：`kb_query` 命中超大 → 输出截断并标注。
7. 审计：每条命令在 `command_logs` 留痕（user_id/command/status/output_len）。
8. 集成：端到端起 uvicorn，Agent 匹配中确实调用 `run_command` 并基于 observation 产出更准确方案。

**B 类（受限 shell，启用后）**
9. `SANDBOX_SHELL_ENABLED=False` 时 `run_shell` 恒拒。
10. 白名单外二进制（如 `curl`）→ 拒。
11. 含 shell 元字符参数（`ping; rm -rf /`）→ 拒。
12. 确认前不执行；确认后执行且输出截断、cwd 在用户 jail 内。
13. 多 worker 已知限制：shell 确认态在单进程下可用，多 worker 需迁 Redis（标注，不本阶段修）。

---

## 11. 风险与缓解

| 风险 | 缓解 |
|---|---|
| LLM 注入命令参数绕过白名单 | 参数严格 JSON Schema 校验 + 命令内二次转义/扫描 |
| `calc` 表达式注入 | 自写 parser，禁 `eval`/`exec`、禁名字空间访问 |
| `run_shell` 逃逸 jail | 二进制白名单 + 禁元字符 + cwd jail + env 剥离 + 默认关闭 |
| 超大输出撑爆上下文 | `SANDBOX_MAX_OUTPUT` 截断 |
| 命令卡死拖垮循环 | `SANDBOX_TIMEOUT` 超时终止 |
| 多 worker 确认态丢失 | 单进程 uvicorn 足够；多 worker 标注为后续改造（迁 Redis） |
| 部署静默失败 | 新表/列写进 `db_init.py` 幂等建表；`.env` 变更同步 `.env.example` |

---

## 12. 推荐范围

- **强烈建议 v1 = A 类（安全内置命令）先上**：零命令执行风险、立即可用、直接提升 Agent 决策质量（能查用量、能算、能精确查知识）。
- **B 类（受限 shell）作为后续增强**：默认关闭，确认 UX 就绪后再开；涉及前端确认卡，工作量与风险更高。
- 无论哪档，`SANDBOX_ENABLED` 总开关保留，可一键停用。

---

## 13. 待你决策（评审问题）

1. **v1 落点**：只做 A 类（推荐）/ 连 B 类一起（含确认 UX）/ 仅 B 类？
2. **`calc` 能力边界**：基础四则 + 幂/对数/四舍五入即可，还是要接入实际**定价/ROI 公式**（如华为云某产品单价表）？
3. **`run_shell` 白名单**：维持 `ping/nslookup/date/wc/cat`，还是要加别的（建议不加 `python3`/`curl`）？
4. **`usage_stats` 维度**：除 matches/analyses/trends，要不要加"客户维度聚合"（需 client_id）？
5. **审计留存**：`command_logs` 保留多久（默认随 usage_logs 不清理）？

---

> 评审通过后，按 §8 改动清单实现；实现后走标准验证（本地 `import api.main` 冒烟 + 起 uvicorn 跑集成用例 §10）→ 部署（git push → 服务器 `cp -r` → restart）。
