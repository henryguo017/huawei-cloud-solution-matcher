# cloudsol.cn 功能全景清单（2026-09-06）

> 用途：AI 助手知识库基线。记录产品上线以来**全部已落地功能**，供后续开发/测试/答疑对齐。
> 口径：生产 = GitHub main（aa96a08），阿里云 ECS 47.96.109.234，全部经公网验证。

---

## 一、经典模式（`#classic-solution`，script.js/style.css 字节级冻结为视觉基准）

### 1. 方案匹配（核心）
- **三种匹配模式**：标准 / 对话式向导 / Agent（后两者未登录弹框拦截；快速体验走 `/match` 匿名）
- 对话式需求引导向导（澄清式补充，「跳过向导，自由输入」）
- 结果页：方案覆盖度展示、分章节方案书、成本明细
- **客户上下文感知（Plan A）**：BGE 嵌入选取 top-5 客户历史注入 LLM 提示词，结果页显示「已参考客户 X 的 N 条历史」
- **快速体验**：匿名 Demo（制造业预测性维护 / 智慧农业植物方舱 / 智慧园区管理三案例，自动填充+演示匹配+注册引导条）
- 欢迎引导页（每天一次、跳过、下次不再显示勾选）

### 2. 导出
- **导出方案书（Word）**：结构化 solution_json 优先、Markdown 回退；含成本表格
- **导出 PPT**：华为红 12 页满版引擎（详见第三节）；失败自动降级毛坯渲染
- 导出 PDF（wqy-zenhei 字体兜底 Linux 缺 SimSun）
- 临时分享页 `share.html?id=<id>`（匿名只读、30 天 TTL）

### 3. 周边功能页
- 客户管理（CRM 式：客户列表/背景/历史方案）
- 竞品分析（12 竞品厂商对比，导出竞品分析 Word）
- 产品图谱（华为云产品能力边界与关联）
- 数据仪表盘（图表渲染）
- 历史记录
- 成就中心（`/api/achievements`）
- 知识库管理：25 行业 / 12 竞品 / 800+ 向量片段；自建文档上传（.docx/.pptx/.pdf OCR/.txt/.md/.csv）；per-user 多租户隔离 KB；`/knowledge/rebuild` 增量重建
- 设置：欢迎引导页开关、4 主题皮肤（经典蓝/浅葱绿/盛夏黄/桃桃粉）

### 4. 顶栏 / 信息流
- 科技资讯（9 RSS，24h 缓存）、华为云动态、展会日历（AIWW+IDCTalk，只留未来）
- 天气条（高德，点击换城市）、最新更新滚动横幅、顶部 AI 提问条
- 视图切换胶囊（Agent 对话 / 经典功能）

### 5. 账号体系
- 登录/注册（图形验证码）、密码找回（163 SMTP + reset_token）、邮箱绑定/改绑
- 生产账号 guo（user_id=2）

## 二、Agent 模式（`#workspace-solution`，agent_workspace.js，与经典物理隔离）

### 1. 对话工作台
- SSE 流式对话、Plan 实时点亮、工具执行可见性（工具行+结果摘要）
- 方案预览抽屉（产品/竞品/成本三类清单）
- 对话管理：归档/重命名/删除/重新生成/复制
- 上下文用量浮层、通知绑定弹窗（飞书/钉钉）、语音输入
- 导出：答案卡「导出方案书 (Word)」+「导出 PPT」双按钮（红底胶囊同款样式）

### 2. 自研 AgentHarness（对外称 agentic workflow）
- **P1**：Plan 驱动、generate_doc 单例复用、web_search（默认关）、Reflexion
- **P2**：两阶段执行（plan→执行）、3 角色 Orchestrator-Workers、单步重跑 `rerun_plan_index`、长程记忆 `agent_episodes` top-3、MCP 集成（JSON-RPC stdio）、PPTX 导出
- **P3**：自检 Gate（critic 6 维，pass≥70，注入真实工具调用历史）、反思-重规划（≤2 次）、并行子体（≤3）、`_normalize_args` 参数漂移吸收
- **确定性成本计算**：`_force_cost_step` harness 强制链路（取 SKU 目录→结构化抽参→直接调计算器），MCP `cost_calc` 已生产激活
- **行业技能包**（已激活）：制造/医疗/政务/金融/零售 5 包，harness 三注入点（匹配事件/角色提示词/终稿口径）
- 意图路由：export / file_ops / knowledge_q / PPT 口语生成（`_PPT_GEN_RE`，疑问句排除）/ client_id 透传

## 三、PPT 引擎（`app/services/ppt_engine/`，2026-09-06 生产上线）
- 五模块：tokens(v9 设计令牌) → primitives(绘制原语) → layouts(12 版式几何固化+SLOT_SPEC 槽位白名单/容量/表格行数门禁) → engine(render_deck+validate_deck 出稿门禁) → generator(DeepSeek 两段式)
- 门禁拦截五类：幻觉槽位/未知版式/超容量/表格超行/页数≠12
- 两段式：12 页序列硬编码（LLM 无权增删页）；大纲→分 3 批填槽（批级校验+问题回喂重试）；cover/toc/end 程序化
- 成本页双路径：有 cost_reference → 程序化 SKU 表；无 → 用 LLM 费用结构合成（LLM 不碰金额）
- 韧性：单批抖动批级重试 + 整单重试一次（p→p²）
- 工具链：make_ppt_sample.py / check_ppt_sample.py(v9 断言) / audit_whitespace.py(0.4" 带审计)

## 四、通知与生态
- 钉钉/飞书群机器人通知：方案/Agent 完成推送（卡片链临时分享页，免登录）；飞书常驻生产，钉钉代码就绪未上线
- per-user 通知绑定（partial-upsert 保空值、toggle 单独可存）
- MCP：权限网关覆盖 `mcp__*` + 自带 cost_calc Server（已激活）

## 五、部署与运维（阿里云 ECS）
- systemd `huawei-cloud-api` + nginx `sites-available/huaiwei-cloud`；Python 3.10，venv numpy<2
- 标准流程：codeload.github.com main.zip → cp -r → restart（绝不 rsync --delete）
- 单文件热部署：api.github.com contents API + base64
- 铁律⑤：部署后 curl 新版本号内容级核验；回滚仅靠 `/tmp/pre-agent-backup-*.tar.gz`

## 六、质量资产
- 测试脚本：`scripts/`（引擎 E2E/意图单测/Playwright UI 冒烟）；生产 E2E：`.workbuddy/Temp/prod_export_e2e.py`、`prod_agent_e2e.py`
- 验证基线：意图 13/13、样张回归 issues:0、生产公网 E2E 全绿（Word 单元格级/PPTX 12 页/Agent SSE 全链路/空草稿兜底）
