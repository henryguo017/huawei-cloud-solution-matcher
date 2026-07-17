# 演进规划 PRD · 阶段 3~4（从 agentic workflow 到 autonomous agent）

> 本文档是「从生成式到执行式、再到自治式 Agent」演进路线的后两阶段详细 PRD。
> 阶段 1（文件交互 MVP）与阶段 2（持久记忆 / 客户隔离 / 成就 / 登录闸）**已完成并上线验证**（见 `演进规划_PRD_阶段1-3.md`）。
> 本文档**只改规划、不改代码**，目标是把阶段 3、4 的内容补全、完善，作为下一步拍板的依据。
>
> **当前状态（v1.1.0，已上线）**：Agent 模式 = 单轮 ReAct 循环（analyze → search → 生成方案），注册 **5 个工具且全部只读**：`analyze_demand` / `search_kb` / `search_competitor` / `read_customer_file` / `list_dir`。具备持久记忆、用户画像、成就体系、强制登录闸、客户档案隔离。

---

## 0. 现状与差距分析：我们离"真 Agent"还差多远

### 0.1 当前 Agent 的实际能力边界
| 维度 | 现状 |
|---|---|
| 工具数量 / 性质 | 5 个，**全部只读**（3 个检索 + 2 个读文件） |
| 执行动作 | 无任何"改变外部状态"的动作（不写文件、不跑命令、不外发） |
| 循环形态 | 单次请求内一个 ReAct 循环，出最终方案即结束（单轮、短 horizon） |
| 工具关系 | 各自独立，**无组合 / 依赖串联** |
| 自我验证 | 生成方案后**不校验**对错、不核查引用真实性 |
| 人类确认闸 HITL | 无（但当前动作全只读，风险天然低） |
| 长程目标 | 无多步自主规划，一次只服务一个明确需求 |
| 安全基座 | 进程级 + 路径白名单（够用，但执行类动作需要更强隔离） |

### 0.2 当前本质：agentic workflow，不是 autonomous agent
- 它"像 Agent"是因为有 ReAct 循环 + 工具调用 + 记忆；
- 但它**没有手**（不能对世界产生副作用）、**没有自治闭环**（规划→执行→验证→修正的循环）、**没有长程目标追踪**。
- 准确叫法：**工具增强的生成引擎 / agentic workflow**。对外表述应坚持此称呼，避免称"自研 Agent"。

### 0.3 与"真 Agent"的差距地图（对应补齐阶段）
| 真 Agent 该有的能力 | 现状 | 补齐阶段 |
|---|---|---|
| 能**执行动作**（动世界） | 仅只读 | **阶段 3**（命令沙箱：跑脚本 / 生成产物） |
| 工具**组合 / 编排**（A 输出喂 B） | 无 | 阶段 3 雏形 → 阶段 4 完善 |
| **自我验证 / 反思**（校验产物） | 无 | **阶段 4** |
| **长程自主规划**（拆目标为子任务） | 无 | **阶段 4** |
| **人类确认闸 HITL**（写/外发需确认） | 无 | **阶段 3**（写操作确认） |
| **安全基座升级**（隔离执行） | 进程级 | **阶段 4**（容器化） |
| 自主产出**可交付物**（图表 / 报告 / Word） | 仅文本方案 | 阶段 3（落盘）+ 阶段 4 |

### 0.4 结论
当前是「会检索、会读客户文件、会写方案文本的聪明助手」。缺两样东西：
1. **手**（阶段 3）：能跑受控命令、生成图表 / 数据产物；
2. **自治闭环**（阶段 4）：能自主规划多步任务、组合工具、自我验证、长程追踪，并用容器化保证安全。

阶段 3 给它"手"，阶段 4 给它"脑子里的闭环"。两阶段做完，才真正从 agentic workflow 跃迁为 autonomous agent。

---

## 1. 阶段 3 · 命令执行沙箱（细化完善）

**文档版本**：v1.1（在阶段1-3 PRD 基础上细化 + 差距补足）  **优先级**：P2  **预估工作量**：1~1.5 周

### 1.1 目标
让 Agent 从「只读助手」升级为「能动手的助手」：可运行**受控命令**（主要 `python` 做数据分析、生成图表、生成报告产物），写操作必须用户确认。这是迈向真 Agent 的"手"。

### 1.2 用户场景（在阶段1-3 PRD 基础上扩充）
- 场景 A：销售说"统计本月匹配 Top5 行业" → AI 跑只读分析脚本返回结果。
- 场景 B：AI 想生成一页行业对比图 / 架构图 → 跑脚本生成图片产物（**写操作，HITL**）。
- 场景 C："给我出一份本季度客户行业分布饼图" → 生成图表文件落盘。
- 场景 D：数据分析结果自动回灌，作为下一轮 `search_kb` / 方案生成的输入（**工具组合雏形**）。

### 1.3 功能需求
| 编号 | 功能 | 优先级 | 说明 |
|------|------|------|------|
| FR-3.1 | 执行白名单内命令 | P0 | 默认仅 `python` / `python3` |
| FR-3.2 | 超时强杀 | P0 | 单命令 ≤ 30s，`wait_for` 超时 kill |
| FR-3.3 | 危险命令拦截 | P0 | `rm -rf` / `sudo` / `mkfs` / `:(){` 等危险词 |
| FR-3.4 | 输出截断 | P0 | ≤ 2000 字，超出截断返回 |
| FR-3.5 | 写操作 HITL 确认 | P1 | 前端弹确认框，用户回传 `confirm_token` 才执行 |
| FR-3.6 | 产物落盘到白名单目录 | P1 | `data/user_docs/{user_id}/agent_artifacts/`，复用 `file_security` 白名单 |
| FR-3.7 | 产物登记与展示 | P2 | 返回路径 + 可选登记进"我的方案/收藏"供前端展示 |
| FR-3.8 | 与匹配工作流打通 | P2 | 命令结果可作下一轮工具输入（工具组合雏形，为阶段 4 铺垫） |

### 1.4 非功能需求
- NFR-3.1 单命令超时 ≤ 30s，超时 kill
- NFR-3.2 输出截断 ≤ 2000 字
- NFR-3.3 沙箱：仅访问白名单工作目录，清理敏感 env
- NFR-3.4 并发限制（同时最多 1~2 个命令任务）

### 1.5 技术方案
**新增工具** `run_command(cmd, confirm_token?)`：
- 白名单仅 `python` / `python3`；`asyncio` + `wait_for(30s)` 执行；输出截断返回。
- **HITL 流**：写操作 → `_emit` 推 `confirm_required`(SSE) → 前端弹框 → 用户回传 `confirm_token` → 二次调用 `exec_now=True` 执行 → 超时（60s）自动取消。
- **产物落盘**：默认写 `agent_artifacts/`，同名加时间戳不覆盖。
**涉及文件**：
- 修改：`app/agent/tools.py`（+工具）、`app/agent/agent.py`（传 user_id/白名单根）、`app/agent/harness.py`（`confirm_required` 事件 + 暂停等确认）、`app/agent/file_security.py`（命令白名单 + 危险词）、`api/routes.py`/`SSE`（+`/api/agent/confirm`）、`frontend/script.js`（确认弹窗 + 产物展示）
- 新增：`app/agent/sandbox.py`（命令白名单 / 危险词 / cwd 限制 / 资源限制）

### 1.6 安全设计（本阶段核心）
- 命令白名单（默认仅 `python` / `python3`）
- 危险词拦截（`rm -rf` / `sudo` / `mkfs` / `:(){`）
- 目录限制（cwd 限白名单目录，清理敏感 env）
- 资源限制（超时强杀 + 输出截断）
- HITL（写操作必须用户显式确认）

### 1.7 验收标准
- [ ] `run_command("python analyze.py")` 白名单内正常返回
- [ ] `run_command("rm -rf /")` 被拦截
- [ ] 超时命令被 kill 返回"执行超时"
- [ ] 写操作触发前端确认框，未确认不执行
- [ ] 输出超 2000 字被截断
- [ ] 生成的图表 / 产物落盘到白名单目录，路径可被前端展示
- [ ] 命令结果能作为下一轮工具输入（FR-3.8 冒烟）

### 1.8 待拍板问题
1. 命令白名单是否开放到 `python` 之外（如 `ffmpeg`）？建议本期仅 `python`。
2. HITL 确认超时时长？建议 60s。
3. 沙箱是否上 Docker？建议进程级 + 白名单，**容器化留阶段 4**。
4. 产物是否登记进前端"我的方案"？建议登记，提升可用性。

---

## 2. 阶段 4 · 自治闭环 / 真 Agent（新建）

**文档版本**：v1.0（新建）  **优先级**：P3  **预估工作量**：3~4 周

### 2.1 目标
从「agentic workflow」（单轮、只读、无验证）跃迁到「autonomous agent」：能**自主规划多步任务**、**组合工具**、**自我验证**、**长程目标追踪**，并以**容器化沙箱**为安全基座。这是"脑子里的闭环"——让 Agent 真正像一个能端到端干活的数字员工。

### 2.2 用户场景
- 场景 A："帮我跟进客户甲从需求到方案全流程" → Agent 自主：读客户档案 → 检索知识库 → 生成初稿 → 生成行业分布图（阶段 3 能力）→ 存档 → 汇报进度，每步异常自纠。
- 场景 B：多步研究："对比华为云与阿里云在智慧医疗的优劣势，出对比报告" → 自主拆解：搜竞品 → 搜知识库 → 跑分析脚本 → 生成对比表/图 → 合成报告。
- 场景 C：长程目标："本周把我的 5 个制造客户都出一份方案" → Agent 拆成 5 子任务，逐个执行并汇总。
- 场景 D：自我验证："检查这份方案里引用的产品是否真实存在" → Agent 调产品图谱 / 知识库校验，发现错漏自修。

### 2.3 功能需求
| 编号 | 功能 | 优先级 | 说明 |
|------|------|------|------|
| FR-4.1 | 任务规划器 Planner | P0 | 把用户目标拆成有序子任务 DAG，逐步执行 |
| FR-4.2 | 工具组合 / 编排 | P0 | 工具输出可作另一工具输入（pipeline），支持依赖串联 |
| FR-4.3 | 自我验证 / 反思 Reflector | P0 | 对产物做校验（事实核查、格式校验、引用真实性），不达标则重试 / 自修 |
| FR-4.4 | 长程记忆与状态机 | P1 | 跨多轮追踪任务进度，支持暂停 / 恢复 / 续跑 |
| FR-4.5 | 自主产物交付 | P1 | 组合阶段 3 能力，产出报告 / 图表 / Word 并可一键发送 / 存档 |
| FR-4.6 | 容器化安全基座 | P0 | Agent 执行环境跑在 Docker 沙箱，资源 / 网络 / 文件系统隔离 |
| FR-4.7 | 分级 HITL | P1 | 低风险动作自动执行，高风险（外发 / 删除 / 大额）必须确认 |
| FR-4.8 | 可观测性 | P2 | 任务树 / 步骤日志前端可视化，用户可随时介入接管 |

### 2.4 技术方案
- **Planner**（新增）：LLM 拆解目标 → 子任务计划（DAG），驱动逐步执行。
- **Reflector**（新增）：校验节点，对产物做事实 / 格式 / 引用核查。
- **Orchestrator**（新增，替代 / 增强现有 harness 单轮循环）：驱动多步 DAG，管理"规划→执行→验证→修正"闭环。
- **工具接口升级**：工具返回结构化 `Observation` + 元数据（可否作下游输入），支持 pipeline。
- **容器化**：新增 `app/agent/sandbox_docker.py`，挂载白名单目录为 volume，限制 CPU / 内存 / 网络（默认**禁外网**，仅允许访问 `127.0.0.1:8000` 内部 API）。
- **状态机持久化**：`task_state` 表（`task_id`, `user_id`, `plan`, `progress`, `status`）。
- **前端**：任务树面板、步骤进度、介入 / 停止按钮。
- **涉及文件**：`app/agent/orchestrator.py`(新增)、`planner.py`(新增)、`reflector.py`(新增)、`sandbox_docker.py`(新增)、`memory.py`(任务状态)、`harness.py`(演进为可多步)、`routes.py`(SSE 增 `task_tree` 事件)、`frontend`(任务面板)。

### 2.5 安全设计（本阶段核心）
- **容器化隔离**（文件系统 / 网络 / 资源）——所有执行类动作在容器内跑
- 分级 HITL（低风险自动，高风险确认）
- 工具输出校验（Reflector 前置）
- 所有写 / 执行仍限白名单根 `data/user_docs/{user_id}/`
- 任务可一键中止（用户随时停止）

### 2.6 验收标准
- [ ] 给出一个多步目标，Agent 能自主拆计划并执行到产出交付物
- [ ] 工具组合：A 工具输出成功喂给 B 工具
- [ ] 自我验证：故意植入错误引用，Agent 能识别并修正
- [ ] 长程任务可暂停 / 恢复 / 续跑
- [ ] 容器逃逸 / 越权被拦截
- [ ] 高风险动作弹确认，用户可中止

### 2.7 待拍板问题
1. Orchestrator 自研还是 LangGraph？建议**自研轻量**（沿用现有 harness 演进，避免重依赖）。
2. 容器化成本 vs 进程级？建议阶段 4 上 Docker（执行类动作风险高，隔离必要）。
3. 自主到什么程度？建议**"半自治"**：规划 + 执行自主，外发 / 删除等人确认。
4. 任务超时 / 最大步数上限？建议单任务 ≤ 20 步、总时长 ≤ 10min。

---

## 2.5 阶段 2.5 · 交互式澄清（Agent 主动提问 / clarify）【本迭代优先】

**文档版本**：v1.0（新建）  **优先级**：P1（高于阶段 3/4，ROI 极高、零新增安全风险）  **预估工作量**：2~3 天

### 2.5.1 目标与定位
让 Agent 在 ReAct 循环里**主动识别"前置信息不足"**，向用户抛出 1~2 个关键问题并**暂停**，等用户回答后以同一上下文**续跑**，最终产出方案。这是 ReAct 协议里的 **human-input 节点**，纯循环增强，**不需要命令沙箱 / 容器化**，可以早于阶段 3/4 独立交付。

> 价值：当前 Agent 一旦拿到模糊需求就硬编（容易幻觉 / 偏题）。澄清节点让它"先问清楚再动手"，方案质量与用户信任立刻提升；且完全复用现有只读工具，无新攻击面。

### 2.5.2 用户场景
- 场景 A：用户说"帮我写个智慧园区的方案" → Agent 判断缺行业细分 / 规模 / 痛点 → 弹卡问："园区类型（产业园/科技园/物流园）？当前最大痛点（安防/能耗/招商）？"
- 场景 B：用户给的需求自相矛盾 → Agent 问"你更看重成本还是性能？"避免硬猜。
- 场景 C：用户上传了客户文件但没说要啥 → Agent 问"希望产出侧重投标技术方案，还是内部立项建议？"

### 2.5.3 功能需求
| 编号 | 功能 | 优先级 | 说明 |
|------|------|------|------|
| FR-2.5.1 | clarify 动作类型 | P0 | LLM 可在 ReAct 输出里发 `Clarify:` 触发提问（协议扩展） |
| FR-2.5.2 | SSE `clarify` 事件 | P0 | 推送 `{type:"clarify", questions:[{id,text,options?}]}`，前端弹卡 |
| FR-2.5.3 | 循环暂停 / 续跑 | P0 | 命中 clarify 即结束当前 SSE 流，状态存 session store（TTL 30min） |
| FR-2.5.4 | 回答回注接口 | P0 | `POST /api/agent/clarify` 带 `session_id`+`answers` → 新 SSE 流用续跑状态接回 |
| FR-2.5.5 | 触发策略护栏 | P0 | 仅当前置信息不足时触发；每轮 ≤ 1~2 问；最多连续澄清 2 轮，第 3 轮强制基于已有信息出 Final Answer |
| FR-2.5.6 | 选项式提问 | P1 | 问题可带 `options`（候选按钮），降低用户输入成本；也支持自由文本 |
| FR-2.5.7 | 前端提问卡 | P1 | 弹卡展示问题 + 选项/输入框 + "提交"；提交后自动发起续跑请求并衔接思考流 |

### 2.5.4 技术方案

**① harness 协议扩展**（`app/agent/harness.py`）
- `_parse_react_output` 新增 `clarify` 类型：正则匹配 `Clarify\s*[:：]\s*(.*)`，解析为 JSON 数组 `[{text, options?}]`（options 可选）。
- `run()` 主循环新增分支：
  ```
  elif parse_result["type"] == "clarify":
      await self._emit(event_callback, {"type":"clarify","questions": parse_result["questions"],"session_id": session_id})
      # 保存续跑状态到 session store，然后 RETURN（结束本次 SSE 流）
      session_store.save(session_id, {
          "current_prompt": current_prompt,        # 已累积的 prompt（含之前 Thought/Observation）
          "tool_calls_log": tool_calls_log,
          "step_count": self._step_count,
          "pending": True,
      })
      return self._make_result("", tool_calls_log, success=False, paused=True)  # paused 标记
  ```
- 续跑入口：给 `run()` 增加可选参数 `resume_answers: List[str] = None`。当传入时，**不重新 clear 短期记忆、不重建 prompt**，而是从 session store 取出 `current_prompt`，把用户回答作为一条 Observation 追加：
  ```
  Observation: [用户回答] Q1: ... A1: ... 请根据以上补充信息继续分析。
  ```
  然后直接进入下一轮 LLM 调用（复用现有循环）。

**② session store**（新增 `app/agent/session_store.py`）
- 进程内 `dict` + TTL（30min 自动过期），key=`session_id`。
- 单 uvicorn 进程足够；多实例场景（当前未用）后续可换 Redis。明确标注"非持久化，仅用于单次澄清续跑"。

**③ 路由**（`api/routes.py`）
- 现有 `/api/agent/match`（SSE）增加可选 query/body 字段 `session_id` + `answers`：
  - 若带 `answers` → 调 `agent.run(..., resume_answers=answers)`（续跑）。
  - 否则正常 `run()`（首轮）。
- `session_id` 当前由 routes 生成并传进 harness（用于 memory）；澄清续跑复用同一 `session_id`。

**④ 前端**（`frontend/script.js` + 提问卡组件）
- SSE 收到 `type:"clarify"` → 渲染提问卡（问题列表 + 选项按钮 / 文本输入）。
- 用户提交 → 用同一 `session_id` + `answers` 重新 `POST /api/agent/match` 并复用同一 SSE 渲染通道，衔接思考流。
- 超时/放弃：30min 内未答则 session 过期，前端提示"请重新发起匹配"。

**涉及文件**：`app/agent/harness.py`（+clarify 解析/分支/续跑参数）、`app/agent/session_store.py`（新增）、`api/routes.py`（SSE 路由 +answers 分支）、`frontend/script.js`（clarify 事件 + 提问卡）、`frontend/index.html`/`style.css`（提问卡样式）。

### 2.5.5 安全设计
- 复用现有只读工具，**无新增写/执行动作**，攻击面不变。
- `session_id` 由服务端生成，用户不可伪造跨用户续跑（store 按 session_id 隔离，且续跑仅追加 Observation，不读他人数据）。
- 连续澄清上限 2 轮，防"死循环提问"卡死用户。
- 所有异常 `try/except` 回退 Final Answer，绝不静默中断。

### 2.5.6 验收标准
- [ ] 构造模糊需求，Agent 触发 `clarify` 事件，前端弹出提问卡（含问题 + 选项）。
- [ ] 用户回答后，新 SSE 流接回原上下文，方案基于回答生成（非重头再来）。
- [ ] 每轮问题 ≤ 2 个；连续澄清第 3 轮强制出 Final Answer。
- [ ] 续跑后方案质量明显优于"不澄清硬编"的对照。
- [ ] session 过期（>30min）前端正确提示重发，不报错崩溃。
- [ ] 标准 / 向导模式不受任何影响（clarify 仅 Agent 模式）。

---

## 2.6 方案版本化管理（应用内自动持久化，不依赖每次下载）

**文档版本**：v1.0（新建）  **优先级**：P1（与阶段 2.5 同批，解决"聊一次下载一次"痛点）  **预估工作量**：3~4 天

### 2.6.1 目标与定位
把"一次匹配 = 一条历史"升级为"**一个方案可有多份版本（v1/v2/v3…）**"：每次细化 / 重新生成都存为新版本，**不再逼迫用户每次下载到本地**；只有定稿要发给客户时才一次性导出 Word。版本可对比、可回滚。

> 现状基础（已具备，可直接复用）：`match_history` 表已有 `user_id`（隔离）、`downloaded`/`archived` 标记、`conversation`（追问记录 JSON）列；后端已有 `/history/list`、`/history/{id}`、`/history/compare`、`/history/{id}/solution`（PATCH 改方案）、`/history/{id}/archive`、`/history/{id}/download`、导出 Word（`/api/export/report`）。版本化是在这套之上**加分组 + 版本号 + 定稿**，不推翻重来。

### 2.6.2 用户流程（已与用户确认）
```
你提需求 → 系统自动存 v1（落库，不弹下载）
   ↓ 你让 Agent 细化 / 自己改 / 重新生成
系统自动存 v2（仍不弹下载）
   ↓ 反复打磨 ……
系统自动存 v3 …
   ↓ 你点"定稿"
标记 is_final=1（同组其他版本取消定稿）
   ↓ 你点"导出 Word"
仅这一次调用 /api/export/report 落盘下载
```
邮件发送 / 生成分享链接：**本期不做**，后续再说。

### 2.6.3 数据模型（扩展 `match_history`，部署安全）
在 `app/services/usage_logger.py` 的 `_init_db()` 追加**幂等 ALTER**（沿用现有 `try/except pass` 模式，旧库自动迁移，不碰已有数据）：
```sql
ALTER TABLE match_history ADD COLUMN group_id INTEGER;   -- 同组方案的版本簇，首版=自身 id
ALTER TABLE match_history ADD COLUMN version   INTEGER DEFAULT 1;
ALTER TABLE match_history ADD COLUMN is_final  INTEGER DEFAULT 0;
ALTER TABLE match_history ADD COLUMN title     TEXT;       -- 方案名，如"XX客户智慧园区方案"
```
- **首版**：`save_match_history` 写入后，把该行 `id` 回填为 `group_id`（同组根），`version=1`。
- **派生版（fork）**：复制 `group_id` + `demand_text`，`version = 同组最大 version + 1`，新 `solution`。
- `user_id` 隔离沿用现有逻辑；`compare`/`detail` 路由已按 `user_id` 过滤。

### 2.6.4 功能需求
| 编号 | 功能 | 优先级 | 说明 |
|------|------|------|------|
| FR-2.6.1 | 自动版本化 | P0 | 首版 version=1；用户"另存为新版本 / 重新生成"→ fork 出 v2/v3，全部落库 |
| FR-2.6.2 | 工作态编辑不新建版本 | P0 | 编辑器里改错别字等 → 复用现有 `PATCH /history/{id}/solution` 原地改当前版 |
| FR-2.6.3 | 版本列表 / 簇 | P0 | 历史页按 `group_id` 聚合展示版本徽标 v1/v2/v3，可切换查看 |
| FR-2.6.4 | 版本对比 | P1 | 复用 `/history/compare`，支持同组跨版本对比（diff 高亮） |
| FR-2.6.5 | 回滚 | P1 | 把某历史版本复制为新的最新版（fork），原版本保留，不破坏链 |
| FR-2.6.6 | 定稿 | P0 | `POST /history/{id}/finalize` → 该组 `is_final` 仅此条=1，其余=0 |
| FR-2.6.7 | 定稿一次性导出 | P0 | 定稿版详情页"导出 Word"按钮 → 调 `/api/export/report`，标记 `downloaded=1` |
| FR-2.6.8 | 版本命名 | P2 | 用户可编辑 `title`；默认取首行 / 行业 + 需求摘要 |

### 2.6.5 技术方案
**后端**（`app/services/usage_logger.py` + `api/routes.py`）
- `save_match_history` 改造：插入后 `UPDATE match_history SET group_id=id WHERE id=?`（首版自引用）；返回 `history_id`。
- 新增 `create_version(parent_id, solution, user_id)`：查父版取 `group_id`/`demand_text`，算 `max(version)+1`，插新行返回新 id。
- 新增 `finalize_version(history_id, user_id)`：`UPDATE ... SET is_final=0 WHERE group_id=? AND user_id=?` 再 `SET is_final=1 WHERE id=?`。
- 新增/扩展路由：
  - `POST /api/history/{id}/version` → 基于现有方案 fork 新版本（请求体可带新 solution，或留空表示"复制当前为 vN+1 草稿"）。
  - `GET  /api/history/group/{group_id}` → 返回同组所有版本（轻量列表：id/version/title/is_final/created_at）。
  - `POST /api/history/{id}/finalize` → 定稿。
  - 现有 `/history/compare` 已支持两 id 对比，无需改；前端传入同组两版本 id 即可。
- **部署铁律遵守**：所有新列走 `_init_db()` 里的 `ALTER ... try/except pass`，**绝不手动改生产库**。

**前端**（`frontend/script.js` + 历史页 + 方案详情页）
- 历史列表：同 `group_id` 折叠为一行，展开见 v1/v2/v3 徽标；点击进详情。
- 方案详情页：顶部显示"当前 vN / 共 M 版" + 版本下拉；按钮：「保存为新版本」「设为定稿」「导出 Word（定稿后高亮）」「与某版本对比」。
- 编辑器保存（小改）→ 原地更新当前版（`PATCH /history/{id}/solution`）；「保存为新版本」→ `POST /version` 生成 vN+1。
- Agent 模式衔接：用户用"追问细化"得到的改进方案，可在结果区一键「存为新版本 vN+1」，而非每次下载。

**涉及文件**：`app/services/usage_logger.py`（ALTER + 3 个新方法）、`api/routes.py`（3 个新路由 + 改造 save 回填 group_id）、`api/models.py`（请求/响应模型）、`frontend/script.js`（历史聚合渲染 + 版本操作）、`frontend/index.html`/`style.css`（版本徽标/下拉样式）。

### 2.6.6 与现有能力衔接（避免重复造轮子）
- **对比**：直接复用 `/history/compare` + `/history/ai-summary`，不新建。
- **导出**：复用 `/api/export/report`（前轮已验证 status:completed + 合法 docx）。
- **追问对话**：现有 `conversation` 列记录追问；版本化不冲突——追问是"当前版内的对话流"，版本是"固化快照"。建议：追问产生的实质性新方案 → 提示「存为新版本」。
- **归档 / 下载标记**：`archived`/`downloaded` 列保留，`downloaded` 仅在定稿导出时置 1。

### 2.6.7 验收标准
- [ ] 首次匹配自动落库为 v1（无强制下载弹窗）。
- [ ] 点击「保存为新版本」→ 生成 v2，历史页同组显示 v1/v2 徽标。
- [ ] 编辑器小改 → 原地更新当前版，不新增版本。
- [ ] 「设为定稿」→ 该组仅一条 is_final=1，其余为 0。
- [ ] 定稿后「导出 Word」→ 生成 docx 且 `downloaded=1`；非定稿版导出按钮置灰/提示先定稿。
- [ ] 同组两版本 `/history/compare` 返回 diff，不串用户（user_id 隔离）。
- [ ] 老数据（无 group_id）兼容：视为独立单版本方案（group_id=自身 id 的兜底在查询时处理）。

---

## 3. 阶段依赖与节奏总览
```
阶段1（文件读写/OCR/上传）✅        阶段2（记忆落库/画像/成就）✅
        │                                  │
        ├──► 阶段2.5（Agent主动提问 clarify）  P1, 2~3天   ← 本迭代批，纯ReAct增强，无新风险
        ├──► 方案版本化（v1/v2/v3·定稿导出）   P1, 3~4天   ← 本迭代批，解决"聊一次下载一次"
        │
        └──────────► 阶段3（命令沙箱·手）──────► 阶段4（自治闭环·脑 + 容器化）
                     P2, 1~1.5周                P3, 3~4周
                     安全：命令白名单+HITL       安全：容器化+分级HITL+Reflector
```
**建议节奏**：
- **本迭代先做阶段 2.5 + 方案版本化**（P1，ROI 极高、零/低新增风险、直接提升日常可用性，且都不依赖命令沙箱/容器化）。
- 阶段 3 随后上（演示价值高、风险可控，给 Agent "手"）；阶段 4 在容器化基座稳固后做（给 Agent "自治闭环"）。
**全局安全红线（三四共同）**：
- 所有执行 / 写操作必须落在白名单根 `data/user_docs/{user_id}/` 内
- 写 / 外发需 HITL 确认
- 工具异常一律 `try/except` 返回 `Error:` 字符串，绝不中断主循环
- 执行类动作进沙箱 / 容器，禁敏感外网

---

## 4. 一句话定位
- **现在**：聪明的只读助手（agentic workflow）。
- **阶段 2.5 + 版本化后**：会先问清楚再动手、方案自动存多版可对比回滚、定稿才导出（日常可用性跃升，仍零执行风险）。
- **阶段 3 后**：能动手的助手（可跑脚本、产图表 / 报告）。
- **阶段 4 后**：半自治的数字员工（能规划多步任务、组合工具、自我验证、长程交付，安全隔离）。
