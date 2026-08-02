# S0 架构草案：Agent 代码沙箱（售前垂直 Codex 第一步）

> 版本：S0 草案 v1 ｜ 日期：2026-08-02 ｜ 状态：待评审（评审通过后再写码）
> 关联：stage3_command_sandbox_design.md（B 类命令沙箱的旧设计，本文将其升级为"subprocess 沙箱"落地）

---

## 1. 目标与范围

**S0 一句话目标**：给现有 ReAct Agent 加一个 `run_code` 工具，让它在**隔离沙箱**里跑 Python，做成本测算 / 生成真实 `PPTX·Excel·PNG`，自检，并把产物交付给用户下载。

**In scope（S0 做）**
- 新增 `run_code` 工具 + `SandboxExecutor`（subprocess 隔离运行）。
- Agent 能"动手产出文件"并自检（对标 Codex 的"它把活干完了"灵魂）。
- 产物经新增端点交付用户下载。
- 安全底线：jail + 低权限 + 禁网 + 资源限 + 超时 + 输出截断。

**Out of scope（本阶段不做，留给后续）**
- Docker 容器化（现状：Dockerfile=0 行、docker-compose 空、生产未装 Docker → 暂缓）。
- 原生 function calling 迁移（S3）。
- Planner 任务拆解 / 放开规划词表（S2）。
- 跨会话记忆深化、CRM/邮箱闭环（S4）。

---

## 2. 关键技术决策（基于代码探查，含 file:line）

| 关注点 | 探查结论 | 对 S0 的意义 |
|---|---|---|
| Docker 现状 | `Dockerfile` 0 行、`docker-compose.yml` 空；`which docker` 找不到 | **S0 用 subprocess 沙箱，不依赖 Docker** |
| 产物库 | `requirements.txt` 含 `python-pptx==0.6.23`、`openpyxl==3.1.2`，venv 已装 | 生成 PPTX/Excel **无需联网、库现成** |
| 生产权限 | `deploy/huawei-cloud-api.service:7-8` `User=www-data`，单 worker | subprocess 继承**低权限**，天然减面 |
| 工具框架 | `app/agent/tools.py:67-93` `ToolRegistry`；`:344-436` `create_default_tools()` | 注册即见 LLM（注入 `{tools}`），**零侵入加工具** |
| ReAct 主循环 | `app/agent/harness.py:323-376` `action→_execute_tool→observation` | `run_code` 直接挂进现有循环 |
| 流式管道 | `harness.py:139-145` `_emit(event_callback)`；`api/routes.py:1505` `/agent/match/stream` 已用 `event_callback` | **实时推沙箱 stdout 的 SSE 管道现成** |
| 文件 jail | `app/agent/file_security.py:30-55` `safe_resolve`（防 `../` 穿越） | 沙箱工作目录复用同一 jail 范式 |
| 产物交付 | `api/export_routes.py:107` `GET /export/download/{task_id}` 下载模式 | 新增 artifact 端点**照此模式** |

---

## 3. 架构总览（端到端数据流）

```
用户需求 ──▶ /api/agent/match/stream ──▶ get_agent().run(event_callback)
                                          │
                                          ▼
                                   harness ReAct 循环
                                     │
                                     │  LLM 决定调用 run_code
                                     ▼
                       _execute_tool("run_code", {code, ...})
                                     │
                                     ▼
                       SandboxExecutor.execute(code, user_id)
                         1. 建 jail: data/user_docs/{uid}/generated_solutions/sb_{uuid}/
                         2. 写 code ──▶ task.py
                         3. subprocess: python task.py
                              · cwd = jail
                              · env = 最小（剥离 DEEPSEEK_API_KEY 等密钥）
                              · 资源限: RLIMIT_CPU / AS / NPROC (Linux)
                              · 禁网: unshare -n (Linux)
                              · timeout 30s 硬杀
                              · stdout/stderr 实时回传 (event: tool_log) + 截断
                         4. 清点产物: .pptx / .xlsx / .png 相对路径
                         5. 返回 observation = {stdout, files:[...]}
                                     │
                                     ▼
                          observation 回灌 LLM ──▶ Final Answer（方案中给出产物下载链接）
                                          │
                                          ▼
                           前端渲染方案 + 产物下载按钮（新增 /api/agent/artifact）
```

---

## 3.5 执行流协议（raw 优先）：S0 输出即 S1 接口

> **核心原则（2026-08-02 与用户对齐）**：要让用户"看到它在干活、在产生文件、在卡住再爬起来"，**必须原样透传沙箱里真实发生的，少加工**。抽象的状态点/人话摘要会让人觉得"背后有人替我翻译"，真实命令 + 可见报错 + 自我修复才像 Codex。
>
> 本节的事件协议**既是 S0 的 `run_code` 输出契约，也是 S1 前端流式终端的接口**——S0 落地时就把事件 emit 出来，S1 只是把这些事件接成面板，零新管道。

### 3.5.1 事件类型（走现有 `event_callback` SSE，复用 `harness._emit`）

两类并存（双轨）：

- **L1 原样透传（S0 即可用，零成本）**：把 `python task.py` 的 stdout/stderr **逐行原样**推给用户，不整理成摘要。脚本里 `print("检索知识库：12 篇命中")`、`print("! 错误 L88: industry_chart 未定义")` 都原样出现 → 这就是 raw 的灵魂。
- **L2 结构化（S1 完整，S0 预留）**：脚本按约定 `print('<<EVT>> '+json.dumps({...}))`，`SandboxExecutor` 解析后 emit 结构化事件，驱动"产物卡片 / 文件树 / 自愈重跑"面板。L2 不替换 L1——原始 stdout 始终可见。

| event | payload | 来源 | 前端呈现 |
|---|---|---|---|
| `exec_cmd` | `{cmd:"python task.py"}` | `SandboxExecutor` 启动 subprocess 前 | 终端首行 `$ python task.py` |
| `exec_stdout` | `{line:"..."}` | subprocess stdout 逐行 | 终端原样滚动（L1） |
| `exec_stderr` | `{line:"! 错误 L88: ..."}` | subprocess stderr 逐行 | 终端红色滚动（L1） |
| `exec_status` | `{status:"running"\|"done"\|"error", code:int}` | subprocess 结束 | 终端尾行 ✓/✗ |
| `file_created` | `{path, size, kind:"pptx"\|"xlsx"\|"png"}` | 产物清点（L2） | 左侧"已产出文件"卡片 |
| `file_edit` | `{path, line:142}` | 脚本约定 emit（自愈时） | 左侧文件树"编辑中 142行" |
| `tool_log`（现有） | 兼容保留 | 非沙箱工具 | 现有日志 |

### 3.5.2 "自愈"观感如何产生（关键）

Codex 最勾人的是"它犯错→自己改→再跑通"。本协议让这件事**自然涌现**，不靠预编排：
1. agent 写 v1 脚本 → `run_code` → 报错 `exec_stderr: ! 错误 L88...`；
2. **主循环不崩**（容错） → LLM 看到错误 observation → 改写脚本；
3. 二次 `run_code` → `file_created: solution_v2.pptx`；
4. 前端：终端先红后绿 + 产物卡片从 v1 变 v2 = "它在自己改自己的产出"。

### 3.5.3 前端三面板（S1 完整形态，S0 先出终端）

- **接管态**：任务进行中顶部 `接管中` 徽标，agent 占屏、聊天退后台（主角是 agent 不是仪表盘）。
- **左·工作区文件树**：`file_created`/`file_edit` 驱动，显示 `build_proposal.py 编辑中 142行` 这种真实编辑态。
- **右·终端（占大头）**：`exec_cmd`/`exec_stdout`/`exec_stderr` 原样滚动。
- **左下·产物卡片**：`file_created` 驱动，从"生成中"变可下载（带大小/页数）。

> S0 只需先把 `exec_stdout`/`exec_stderr`/`file_created` 接到"终端面板 + 下载卡片"；S1 补"接管态占屏 + 文件树 + 失败自愈重跑动画"。接口在本节已定死。

---

## 4. 文件改动清单（S0）

| 动作 | 文件 | 内容 |
|---|---|---|
| **新建** | `app/agent/sandbox.py` | `SandboxExecutor`：jail 目录创建、subprocess 运行、资源限制、禁网、超时、截断、产物清点；复用 `file_security` 的 safe 模式 |
| 改 | `app/agent/tools.py` | `create_default_tools()` 注册 `run_code`；实现 `_tool_run_code(code, user_id)` 调 `SandboxExecutor` |
| 改 | `app/agent/harness.py` | `_execute_tool` 把 `event_callback` 透传给 Tool（支持 `run_code` 流式 `tool_log`）；新增事件类型 `tool_log` |
| 改 | `app/agent/harness.py` | `REACT_SYSTEM_PROMPT_BASE` 增加 `run_code` 使用指引（"需精确计算 / 生成 PPTX·Excel 时调用"） |
| 改 | `app/config.py` | 新增 `SANDBOX_TIMEOUT` / `SANDBOX_MAX_OUTPUT` / `SANDBOX_ENABLED` / `SANDBOX_NET_OFF` 配置项（带默认） |
| 改 | `api/routes.py` 或 `api/export_routes.py` | 新增 `GET /api/agent/artifact?user_id=&path=` 经 `safe_resolve` 交付 jail 产物（复用 export 下载模式） |
| 改（S0 先终端） | `frontend` | agent 模式接 §3.5 raw 事件：S0 先把 `exec_stdout`/`exec_stderr` 原样滚进终端面板 + `file_created` 出下载卡片；S1 再补"接管态占屏 + 文件树 + 失败自愈重跑" |

---

## 5. 安全模型（S0 不可让步的底线）

- **目录 jail**：复用 `file_security.safe_resolve`，代码只能读写 `generated_solutions/sb_*` 子目录；越界（绝对路径 / `../` / 读 `/etc`）即拒。
- **低权限**：生产以 `www-data` 运行，subprocess 继承，无 root。
- **禁网**：`unshare -n`（Linux）或依赖"生成库无需联网"；S0 默认 `SANDBOX_NET_OFF=True`。
- **资源硬限**：`RLIMIT_CPU=30`、`RLIMIT_AS=512MB`、`RLIMIT_NPROC=64`；subprocess `timeout=30s` 硬杀。
- **密钥剥离**：subprocess env 不含 `DEEPSEEK_API_KEY` 等，只传最小 `PATH`/`HOME=jail`。
- **输出截断**：stdout/stderr 单条 ≤ 8KB，防撑爆 prompt。
- **容错不崩循环**：整个执行 `try/except`，失败返回 `Error:` observation，主循环继续或收尾。
- **（可选强化 S0.5）**：后续若要更强隔离，把 `SandboxExecutor` 后端从 subprocess 换成 Docker 容器，**接口不变**，风险隔离从"进程级"升到"容器级"。

---

## 6. LLM 契约（让 Agent 可靠用工具）

`run_code` 工具描述写明：
- 可用库（S0 强制白名单三件套）：`pptx`、`openpyxl`、`pandas`、`json`、`csv`、`math`。`pandas` 已写入 requirements.txt(2.2.2)。
  - `matplotlib` **暂不强制**：探查发现 dev/prod venv 均未安装，headless 服务器还需配置 Agg 后端；S0 优先用 `pptx`/`openpyxl` 原生图表能力。如需 PNG 图表列为 S0.5 可选增强（需验证 headless 安装与 Agg 后端）。
- 脚本须**独立可跑**，结果写 cwd 文件，摘要 `print` 到 stdout；**不联网**。
- 在 system prompt 给 1 个 few-shot，例如：
  > 用户要"算 X 方案三年 TCO 并出 Excel" → 写脚本用 `openpyxl` 生成 `cost.xlsx`，`print` 总成本与分项。

---

## 7. 部署步骤（遵循生产铁律）

1. **本地开发 + 冒烟**：`import api.main` 通过；起 uvicorn 跑一次 `run_code` 生成 xlsx 验证。
2. `git push` → 服务器 `cp -r` 部署（铁律①，目录名必须 `huawei`）。
3. **铁律②b**：服务器手动 `venv/bin/pip install -r requirements.txt`，确保 `pptx`/`openpyxl` 在 prod venv。
4. 改 `config.py` 默认值 → 同步 `.env.example`（`.env` 被 gitignore，铁律③）。
5. `systemctl restart huawei-cloud-api`。
6. **铁律⑤**：`curl` 验证 `/api/agent/artifact` 可达 + 跑一次真实匹配触发 `run_code`。

---

## 8. 验证用例（S0 完成标准）

- ✅ Agent 收到"帮我算 X 方案三年 TCO 并出 Excel" → 调 `run_code` → 生成 `cost.xlsx` → 用户可下载 → 文件能打开、数字正确。
- ✅ Agent 收到"生成一页方案概览 PPT" → `run_code` 用 `pptx` 生成 → 下载打开正常。
- 🛡️ 注入防护：code 写 `os.system('rm -rf /')` 或读 `/etc/passwd` → 被 jail/权限挡住，主循环不崩。
- 🛡️ 超时：code 写 `while True: pass` → 30s 被杀，返回超时 `Error`，不拖垮服务。
- 🛡️ 禁网：code 尝试 `urllib.request.urlopen('https://...')` → 失败（无网），不泄露。

---

## 9. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 代码逃逸 jail | `safe_resolve` + `www-data` 低权 + 禁网 + 资源限 |
| 密钥泄露 | subprocess env 剥离，不传 API key |
| 资源耗尽（fork bomb / 内存） | `RLIMIT_*` + timeout 硬杀 |
| LLM 生成非法/语法错代码 | 失败返回 `Error`，循环容错；S1 加"先 dry-run 语法检查" |
| prod 缺库 | 铁律②b 手动 `pip install` |
| 多 worker 状态 | 单 worker 已定（service 明确），沙箱无跨进程状态，无影响 |

---

## 10. 为什么这是"垂直 Codex"的第一步（对齐目标）

- 之前 Agent 只能"检索 + 生成文字"；S0 让它**真正动手产出文件并自检**——这就是 Codex "它把活干完了"的灵魂。
- **不动主循环、不碰 Docker、不重写前端大改** → 低风险、最快见体感。
- 后续 S1（流式终端感）/ S2（放开规划让模型 Drive）/ S3（FC+记忆）在这个地基上逐个加，每步独立可上、可回退。

---

## 11. 待评审决策点

1. **沙箱后端**：S0 用 subprocess（推荐，零基建）还是现在就装 Docker 上容器（更隔离但 ops 重）？
2. **可用库白名单（已定：pptx+openpyxl+pandas 三件套）**：原草案三件套含 matplotlib，但探查发现 dev/prod venv 均未安装 matplotlib（headless 还需 Agg 后端），故 S0 强制白名单定为 `pptx`+`openpyxl`+`pandas`；matplotlib 降级为可选增强（S0.5）。pandas 已加 requirements.txt(2.2.2)。
3. **流式粒度（已定：raw 优先）**：S0 即做实时原样透传（`exec_stdout`/`exec_stderr` 逐行滚、不加工成摘要），结构化事件（`file_created`/`file_edit`）双轨并行；详见 §3.5。
4. **产物交付**：jail 内文件直接给下载链接（推荐），还是先落 `generated_solutions` 再走现有历史机制？
