# 演进规划 PRD · 阶段 1~3（文件交互型 Agent）

> 本文档为「从生成式到执行式 Agent」演进路线的前三阶段详细产品需求文档（PRD）。
> 当前状态：**v1.0 待拍板**。所有改动仅涉及新增/修改 Python 工具与记忆层，不动现有匹配核心逻辑。
> 评审重点：改动文件清单是否准确、安全边界是否合理、验收标准是否可测。
>
> **已拍板硬约束（全局）**
> 1. DeepSeek 为纯文本模型、无视觉能力 → 图片必须走 OCR 提取文字再喂模型，**绝不能用视觉模型看图片**。
> 2. 上传入口在「标准 / 智能 / 向导」三种匹配模式**都要有**。
> 3. OCR 进第一阶段（图片类 png/jpg 也要支持）。
> 4. 安全护栏（白名单目录 + 沙箱 + 人类确认 HITL）不可省。
> 5. 单文件大小上限 **100MB**；最多同时上传 **10 个**文件；OCR 用**免费本地 pytesseract**。
> 6. 提取文本**不做盲截断**，采用「分块全量提取」保证长文档零内容丢弃。
> 7. 文件操作白名单根目录 = **`data/user_docs/{user_id}/`**（复用现有 per-user 隔离 + contextvars）。

---

## 阶段 1 · 文件交互 MVP

**文档版本**：v1.0（待拍板）  **优先级**：P0  **预估工作量**：1.5~2 周（单人）

### 1. 背景与目标
当前 `tools.py` 仅有 3 个**只读**工具（`analyze_demand` / `search_kb` / `search_competitor`），Agent 产出文本，方案导出依赖前端触发 HTTP 下载，Agent 自身无法读写用户文件。
**目标**：让 Agent 具备最小可用的"手脚"——能读取客户发来的**任意格式**需求材料（含图片 OCR）、把生成的方案直接落盘为 Word，从"写方案的机器"进化为"能碰文件的助理"。

### 2. 用户场景
- 场景 A：销售在匹配页上传客户发来的 `客户需求.docx` / `招标.pdf` / `痛点照片.jpg`，对 AI 说"帮我把这份需求整理成方案"，AI 读文档（图片 OCR）→ 提取痛点 → 生成方案 → 存成 `方案_客户名.docx`。
- 场景 B：AI 生成方案后，销售说"存到我的方案库"，AI 直接落盘到白名单目录，返回文件路径（并登记进"我的方案/收藏"供前端展示）。
- 场景 C：客户材料是 200 页 PDF，AI 仍逐块处理全覆盖，不丢埋在末尾的关键需求。

### 3. 功能需求
| 编号 | 功能 | 优先级 | 说明 |
|------|------|------|------|
| FR-1.1 | 多格式读取客户文件 | P0 | 支持 `.docx`/`.xlsx`/`.pdf`/`.pptx`/`.txt`/`.csv` + 图片 `.png`/`.jpg`（OCR）。统一入口 `read_customer_file(path)`，内部按扩展名分发 |
| FR-1.2 | 方案落盘 | P0 | 复用 `ReportGeneratorService` 生成 docx，写入白名单目录；同名自动加时间戳不覆盖 |
| FR-1.3 | 目录列举 | P1 | 列出白名单目录下文件，供 Agent 选择 |
| FR-1.4 | 路径安全校验 | P0 | 所有路径必须落在 `data/user_docs/{user_id}/` 内，越界拒绝 |
| FR-1.5 | 三模式上传入口 | P0 | 标准/智能/向导三匹配页顶部均加「上传客户资料」控件；后端上传接口存 `customer_uploads/`，返回路径 |
| FR-1.6 | OCR 引擎集成 | P0 | 图片经 pytesseract 转文本后喂 DeepSeek（硬约束：DeepSeek 无视觉，不用视觉模型） |
| FR-1.7 | 分块全量提取 | P0 | 超 token 预算时按重叠窗口切片、逐块抽需求后合并，全文覆盖、零丢弃（**不盲截断**） |

### 4. 非功能需求
- NFR-1.1 性能：单文件读取 < 5s（≤ 100MB）；OCR 图片 < 10s；落盘 < 5s
- NFR-1.2 安全：禁止读取白名单外任何路径（含 `../` 穿越、符号链接逃逸防护）
- NFR-1.3 兼容：Windows / Linux 路径均支持；上传并发 ≤ 10 文件、单文件 ≤ 100MB
- NFR-1.4 健壮性：解析异常 `try/except` 返回 `Error:` 字符串，不中断 ReAct 主循环

### 5. 技术方案
**新增工具类**（`app/agent/tools.py`），沿用现有 `Tool` 基类（`name/description/parameters/func`）+ `ToolRegistry.register` 模式，在 `create_default_tools()` 中注册：

| 工具 | 实现函数 | 复用点 |
|------|------|------|
| `read_customer_file` | `_tool_read_customer_file(path)` | 解析层 `parsers/read_file.py` 按扩展名分发；文本喂 `analyze_demand` |
| `save_solution_file` | `_tool_save_solution_file(solution_json, filename)` | 直接调 `ReportGeneratorService.generate_report_from_json(...)` 拿 `file_path`，复制到白名单 `generated_solutions/` |
| `list_dir` | `_tool_list_dir(dir)` | `os.listdir` + 白名单校验 |

**解析层分发**（`app/agent/parsers/read_file.py`，新增）：
- `.docx` → `python-docx`；`.xlsx` → `openpyxl`（遍历多 sheet）；`.pdf` → `pymupdf(fitz)`（空文本则转 OCR 分支）；`.pptx` → `python-pptx`；`.txt`/`.csv`/`.md` → 直接读
- `.png`/`.jpg` → OCR 引擎提取
- **分块全量提取**：估算 token（≈字符数/2）超安全预算（默认 8000 字符/块、重叠 500 字符）时切片，逐块抽取需求要点后合并；默认不截断

**OCR 模块**（`app/agent/parsers/ocr.py`，新增）：封装 `pytesseract.image_to_string`，中文 `lang='chi_sim'`；识别失败返回友好 Error 不中断

**上传接口**（`api/routes.py` 或新增 `api/upload_routes.py`）：
- `POST /api/upload/customer-file`：接收文件，校验扩展名白名单 + 大小 ≤100MB + 数量 ≤10，存 `data/user_docs/{user_id}/customer_uploads/`，返回相对路径
- 通过现有 `get_current_user` + contextvars 隔离用户目录

**复用点（不改现有代码）**：
- `app/services/report_generator.py` → `ReportGeneratorService.generate_report_from_json(report_type, chapters, format, metadata)` 返回 task（含 `file_path`）
- `app/agent/tools.py` → `Tool` / `ToolRegistry` / `create_default_tools()` 扩展点已就绪
- `data/user_docs/{user_id}/` 隔离机制（contextvars `kb_user_context`）已就绪

**涉及文件清单**：
- 修改：`app/agent/tools.py`（新增 3 个 `_tool_*` + 注册）
- 修改：`app/agent/agent.py`（把 `user_id`/白名单根通过 context 传给工具）
- 修改：`api/routes.py`（或新增 `upload_routes.py`）——上传接口
- 修改：`frontend/index.html` + `frontend/script.js`——三匹配页上传 UI（标准/智能/向导）
- 新增：`app/agent/file_security.py`（`safe_join(base, user_path)` 白名单校验，拒绝绝对路径/`../`/符号链接逃逸）
- 新增：`app/agent/parsers/__init__.py` + `read_file.py` + `ocr.py`
- 不改：`harness.py`（工具返回 Observation 即可）/ `memory.py` / 导出 HTTP 路由（前端下载仍保留）

### 6. 安全设计
- `ALLOWED_ROOT` = `data/user_docs/{user_id}/`；所有文件操作先 `safe_join` 校验，越界返回 `Error: path not allowed`
- `../`、绝对路径、符号链接逃逸一律拒绝
- 上传扩展名白名单 + 单文件 ≤100MB + 并发 ≤10；落盘同名加时间戳不覆盖
- OCR 仅本地 pytesseract，不把图片外传任何第三方

### 7. 风险与缓解
| 风险 | 缓解 |
|------|------|
| Agent 被诱导读取服务器敏感文件 | 白名单根 + 严格 `safe_join`，禁止绝对路径 |
| docx/pdf 损坏导致异常 | `try/except` 返回友好 Error，不中断 ReAct |
| 长文档撑爆上下文 | 分块全量提取（重叠窗口 + 合并），不盲截断 |
| OCR 中文识别一般 | 免费版可接受（客户材料多为 docx/pdf）；精度不足后续切云 OCR，仅改解析层一个分支 |
| 上传大文件拖慢 | 100MB 上限 + 异步处理 + 前端进度提示 |

### 8. 验收标准
- [ ] 对 `客户需求.docx` / `招标.pdf` / `痛点.jpg` 调用 `read_customer_file` 均能返回文本且被 `analyze_demand` 消费
- [ ] `save_solution_file` 在白名单目录生成合法 `.docx`（status=completed，复用之前冒烟口径）
- [ ] 传入白名单外路径返回明确拒绝，不报 500
- [ ] 三匹配页均出现「上传客户资料」控件，上传 10 个 ≤100MB 文件成功、超限被拒
- [ ] 200 页 PDF 全量提取，末尾需求不丢（分块合并验证）
- [ ] 三个新工具出现在工具 Prompt 描述中，Agent 能自主决定是否调用

### 9. 待拍板问题（Open Questions）
1. **落盘文件是否登记进「我的方案/收藏」前端展示？**（我建议：登记，提升可用性；若否仅落盘前端不感知）
2. **分块预算默认值**：每块 8000 字符 / 重叠 500 字符，是否合适？（可调）
3. OCR 后续是否要预留云 OCR API 切换开关？（我建议：解析层留 `ocr_backend` 配置项，默认 `local`，后续可切 `cloud`）

---

## 阶段 2 · 持久记忆

**文档版本**：v1.0（待拍板）  **优先级**：P1  **预估工作量**：3~5 天

### 1. 背景与目标
`app/agent/memory.py` 的 `ConversationMemory` 是**纯内存**（`_sessions` dict），进程重启即清，无法跨会话学偏好。
**目标**：记忆落库（SQLite），按 `user_id` 隔离，使 Agent 跨会话记住"该销售常做制造行业""偏好政企话术"。

### 2. 用户场景
- 场景 A：销售周一分析 3 个制造客户，周三再对话 AI 主动说"结合您常做的制造行业，建议侧重设备预测性维护"。
- 场景 B：服务重启后历史对话不丢失，销售回来继续上次话题。

### 3. 功能需求
| 编号 | 功能 | 优先级 |
|------|------|------|
| FR-2.1 | 长期记忆落库 | P0 |
| FR-2.2 | 按 user_id 隔离 | P0 |
| FR-2.3 | 保留窗口（最近 N 轮） | P1 |
| FR-2.4 | 用户偏好画像（行业/话术倾向） | P1 |

### 4. 非功能需求
- NFR-2.1 对 ReAct 循环零侵入（不改动 `harness.py` 主循环）
- NFR-2.2 读取延迟 < 50ms

### 5. 技术方案
**修改 `app/agent/memory.py`**：接口不变，新增落库实现（或 `PersistentConversationMemory` 子类）。

**新增表**（`app/utils/db_init.py` 幂等）：
```sql
CREATE TABLE IF NOT EXISTS agent_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_agent_memory_user ON agent_memory(user_id, session_id);
```
**涉及文件**：`app/utils/db_init.py`（+表）、`app/agent/memory.py`（长期记忆读写 DB）、`app/agent/agent.py`（实例化时传入 `user_id`）、不改 `harness.py`。
**关键点**：短期记忆（ReAct 步骤）留内存，不落库，避免 IO 放大。

### 6. 安全设计
- `user_id` 严格隔离，参数化查询防注入
- 长期记忆单条截断上限 500 字落库

### 7. 风险与缓解
| 风险 | 缓解 |
|------|------|
| DB 写入失败影响对话 | catch 后降级内存，仅记日志 |
| 记忆膨胀 | 保留最近 N 轮，超出的归档/删除 |
| 隐私 | 仅存需求文本与方案摘要，不存凭证 |

### 8. 验收标准
- [ ] 重启后旧 session 长期记忆仍能读回
- [ ] 不同 user_id 记忆互不可见
- [ ] 连续对话中 Agent 能引用前序轮次输入
- [ ] `harness.py` 主循环代码零改动

### 9. 待拍板问题
1. 记忆保留窗口 N 取多少轮？（建议 10~20）
2. 是否做「用户偏好画像」自动提炼（存 `user_profile` 表）？还是本期仅存原始对话、画像留阶段 4？
3. 记忆清理：超 30 天归档还是删除？

---

## 阶段 3 · 命令执行（沙箱化）

**文档版本**：v1.0（待拍板）  **优先级**：P2  **预估工作量**：1~1.5 周

### 1. 背景与目标
阶段 1/2 让 Agent 读写文件、记偏好。售前常需"统计匹配数据""跑脚本生成图表"——需执行命令。
**目标**：新增 `run_command`，跑受控本地命令（主要 `python` 做数据分析），**全程沙箱化、写操作需用户确认**。

### 2. 用户场景
- 场景 A：销售说"统计本月匹配 Top5 行业"，AI 跑只读分析脚本返回结果。
- 场景 B：AI 想执行写操作，前端弹确认框，用户点"允许"才执行。

### 3. 功能需求
| 编号 | 功能 | 优先级 |
|------|------|------|
| FR-3.1 | 执行白名单内命令 | P0 |
| FR-3.2 | 超时强杀 | P0 |
| FR-3.3 | 危险命令拦截 | P0 |
| FR-3.4 | 输出截断 | P0 |
| FR-3.5 | 写操作 HITL 确认 | P1 |

### 4. 非功能需求
- NFR-3.1 单命令超时 ≤ 30s，超时 kill
- NFR-3.2 输出截断 ≤ 2000 字
- NFR-3.3 沙箱：仅访问白名单工作目录，禁系统目录

### 5. 技术方案
**新增工具** `run_command(cmd, confirm_token?)`：白名单仅 `python`/`python3`；`asyncio` 执行 + `wait_for(30)`；输出截断返回。
**HITL 流**：写操作 → `_emit` 推 `confirm_required`(SSE) → 前端弹框 → 用户回传 `confirm_token` → 二次调用 `exec_now=True` 执行 → 超时取消。
**涉及文件**：`tools.py`（+工具）、`harness.py`（`confirm_required` 事件 + 暂停等确认）、`file_security.py`（命令白名单+危险词）、`routes.py`/`SSE`（+`/api/agent/confirm`）、`frontend/script.js`（确认弹窗）、新增 `app/agent/sandbox.py`。

### 6. 安全设计（本阶段核心）
- 命令白名单（默认仅 `python`/`python3`）
- 危险词拦截（`rm -rf`/`sudo`/`mkfs`/`:(){}`）
- 目录限制（cwd 限白名单目录，清理敏感 env）
- 资源限制（超时强杀 + 输出截断）
- HITL（写操作必须用户显式确认）

### 7. 风险与缓解
| 风险 | 缓解 |
|------|------|
| 命令注入 | 不拼用户输入进 shell，用参数列表 + 白名单 |
| 子进程失控 | `wait_for` 超时 kill，限并发 |
| 误执行破坏性脚本 | 白名单+危险词+HITL 三重防护 |
| 确认流卡死主循环 | 确认超时（60s）自动取消 |

### 8. 验收标准
- [ ] `run_command("python analyze.py")` 白名单内正常返回
- [ ] `run_command("rm -rf /")` 被拦截
- [ ] 超时命令被 kill 返回"执行超时"
- [ ] 写操作触发前端确认框，未确认不执行
- [ ] 输出超 2000 字被截断

### 9. 待拍板问题
1. 命令白名单是否开放到 `python` 之外（如 `ffmpeg`）？建议本期仅 `python`。
2. HITL 确认超时时长？（建议 60s）
3. 沙箱是否上 Docker？建议进程级 + 白名单，容器化留阶段 4。

---

## 三阶段依赖与节奏总览

```
阶段1（文件读写/落盘/OCR/上传）  ──►  阶段2（记忆落库）  ──►  阶段3（命令沙箱）
   P0, 1.5-2周                      P1, 3-5天              P2, 1-1.5周
   安全：路径白名单+上传校验        安全：user_id隔离       安全：命令白名单+HITL
```

**建议节奏**：先交付阶段 1（最能体现"AI 能碰文件"演示价值），阶段 2 紧随（成本低、体验提升明显），阶段 3 进阶（安全设计复杂，稳定后再做）。

**全局安全红线（三阶段共同）**：
- 所有文件/命令操作必须落在白名单根目录 `data/user_docs/{user_id}/` 内
- 任何写操作（落盘、命令写）需用户确认或明确授权
- 工具异常一律 `try/except` 返回 `Error:` 字符串，绝不中断 ReAct 主循环
- DeepSeek 纯文本模型 → 图片必走 OCR，不用视觉模型
