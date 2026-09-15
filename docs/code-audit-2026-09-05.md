# 代码事实审计 + 全量回归报告（2026-09-05）

> 审计方式：不采信 docs/ 声明，逐文件核对代码证据（后端约 1.78 万行 Python + 前端 SPA + tests/ + data/）。
> 背景：当日 harness 核心改动（强制成本步 / `_synthesize_final` 容错 / self_check 注入真实调用记录 / 单步重跑实参错位修复）部署后，按铁律做全量回归。

---

## 一、全量回归 E2E 结果（生产 cloudsol.cn 实单，6 条路径）

| 用例 | 结论 | 答案长度 | 工具数 | self_check | 强制cost触发 | 耗时 |
|---|---|---|---|---|---|---|
| 1 知识问答 | PASS | 199 | 0 | - | 否 | 1.4s |
| 2 文件操作 | WARN | 84 | 0 | - | 否 | 1.0s |
| 3 竞品对比 | PASS | 7220 | 2 | pass/88 | 否 | 148s |
| 4 方案生成 | PASS | 5607 | 3 | pass/90 | 否 | 101s |
| 5 单步重跑 | PASS | 5102 | 3 | pass/88 | 否 | 108s |
| 6 文档导出 | PASS | 123 | 0 | - | 否 | 1.1s |

**总判定：✅ 无回归。** 关键确认：
- `_synthesize_final` 容错改动对全部意图无副作用（竞品/方案/重跑均正常汇总）。
- **单步重跑路径实参错位修复在生产验证通过**（用例 5：重跑 plan 第 2 步 → 重新汇总 → self_check pass/88）。
- 强制成本步**未在非定价意图误触发**（知识问答/文件/竞品/方案均无 cost_calc 调用）——守卫触发条件足够窄。

### 回归抓到的新问题（非本轮改动引入）
- **R1 文件操作意图路由疑似失效**：`列出我上传的客户资料文件` 未触发 `list_dir`，直接 LLM 作答（0 工具 / 1.0s / 84 字）。需核对意图分类对 file_ops 的判定。
- **R2 result 事件携带旧 plan**：知识问答（不走 plan 的直接回答路径）的 result 里带上了上一轮 TCO 运行的 `plan`（单例 agent 状态残留），纯展示层瑕疵。

---

## 二、功能清单（按代码证据）

### ✅ 已实现完整（证据充分）
- **钉钉/飞书群机器人通知**：`app/services/notify.py`（439 行，签名/卡片/部分更新 upsert/脱敏/测试推送全齐）；绑定表 `user_notify_bindings`；REST `/user/notify/*`；触发点 2 处（经典 match_stream + Agent chat 成功分支，自动附分享链接）。
- **MCP 全家桶**：stdio 客户端 + **HTTP/Streamable HTTP+SSE 客户端（P1-B 已实现）**、`MCP_SERVERS` env + `data/mcp_servers.json` manifest 合并发现、参数归一、重名跳过、超时治理；内置 2 个 Server（本地 7 工具暴露 `mcp_server.py`，支持 `--http` 双向暴露 + 成本测算 `mcp_server_cost_calc.py`）；权限网关覆盖 `mcp__*`。
- **多租户 per-user 知识库**：ContextVar 传递 user_id → `data/user_docs/{user_id}/` 物理目录隔离（约 37 个用户目录实证）、注册时 `copy_from_default`、上传走 per-user 安全校验、召回过滤 `doc_origin=user_uploaded`。
- **账号体系**：注册/登录/图形验证码/刷新/改资料/改密/**忘记+重置密码（reset_token + 163 SMTP HTML 邮件）**/登录锁定（5 次 15 分钟）/登录日志。
- **CRM + Plan A 客户上下文**：clients CRUD、历史方案带 client_id、`_select_relevant_client_solutions` BGE 余弦 top-5 注入 4 处匹配入口（经典 match、match/stream、agent/match、agent/match/stream）。
- **三模式生成 + 分享页**：经典 Standard/Agent/匿名分享（独立 share.db + share.html + 二维码）。
- **三格式导出**：WORD/PPTX/PDF（report_generator 608 行）+ 任务查询/下载；成就体系（独立 db）；资讯/华为云动态/展会/天气/报价参考/平台助手。
- **前端**：经典/Agent 双分支物理隔离 + shared_runtime（Session+TaskGuard）+ 语音输入 + 成就 UI + 主题肤色切换；**TODO/FIXME 计数为 0**。

### ❌ 完全没有（声明与代码脱节项）
- **交互式 IM 机器人**：无任何 webhook/event callback 入站端点——群里 @机器人 不能触发任何动作，只有单向推送。
- **Skills / 行业技能包**：`data/skill_packs/` 不存在、加载代码零命中、无 skills 模块。

---

## 三、缺口 / 半成品清单（按影响排序）

| # | 缺口 | 影响 | 量级 |
|---|---|---|---|
| 1 | 交互式 IM 机器人（钉钉 event callback / 飞书 webhook receiver） | 生态故事停在"单向推送"，群里无法反向交互 | 3–5 天/平台 |
| 2 | 行业技能包 Skills 体系 | 售前"行业化"卖点无代码支撑 | 2–4 天 |
| 3 | `/agent/chat` 的 client_id 仅透传未消费 | Agent 对话模式没吃到 Plan A 客户上下文（4 个匹配入口都已接，唯独对话没接） | 半天 |
| 4 | 文件操作意图路由（回归 R1） | 用户要列文件却得到 LLM 直答 | 2–4 小时 |
| 5 | 邮箱改绑无验证流程 | 改邮箱不发验证邮件 → 邮箱丢失即密码重置链路失效（安全弱环） | 半天 |
| 6 | SMTP 默认未配置时忘记密码"静默成功" | 防探测设计掩盖了配置缺失，线上可能根本发不出邮件 | 检查 10 分钟 |
| 7 | MCP 热加载端点缺失 | 改 MCP_SERVERS/manifest 必须重启 | 半天 |
| 8 | MCP 远端结果无限流/缓存 | 远端工具可被会话内无节制调用 | 半天 |
| 9 | GaussDB 向量库纯占位（vector_db.py:136 真 TODO） | config 五个变量齐全、接线为零；Chroma 已够用，可长期搁置 | 大，暂缓 |
| 10 | 4 个 0 字节遗留库（app/captcha/huawei_cloud/usage.db） | 误导部署排查 | 删文件 |
| 11 | 死代码 `notify_match_complete/notify_agent_result` + share debug_info 临时字段 | 维护噪音 | 1 小时 |
| 12 | MCP HTTP server 每请求新建事件循环 + 硬编码 session id | 双向暴露仅测试靶机质量，不能上生产 | 按需 |
| 13 | 测试体系无统一入口（60 个散装 verify_* 脚本） | 回归靠手工 | 按需 |

### 路线图勘误
`docs/roadmap-next-2026-09-02.md` 中「P1 MCP HTTP+SSE 传输 + 工具发现」**实际已实现**（`MCPHttpClient` L176 + manifest 合并 + `verify_p1_mcp_http.py`/`verify_p1_discovery.py`），文档执行记录未更新。路线图剩余真实未做项：P2 交互机器人、P2 行业技能包、P3 小程序、P3 MCP 运维配套。

---

## 四、建议执行顺序

1. **半天清尾批**（#3 client_id 接入 + #4 文件意图路由 + #6 SMTP 配置核查 + #10/#11 清理）——全是审计/回归实锤的坑，便宜且立即提升完整度。
2. **行业技能包（P2）**——低风险、demo 价值最高、填补 Skills 完全空白，与售前求职叙事强相关。
3. **钉钉/飞书交互机器人（P2）**——工作量最大，但让生态从"推送"进化为"交互闭环"，作品集叙事完整。
4. 暂缓：GaussDB、MCP HTTP 生产化、深色模式、pytest 化。
