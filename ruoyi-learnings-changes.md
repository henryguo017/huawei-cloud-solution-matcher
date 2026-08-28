# ruoyi-ai 学习项落地变更文档（feature/ruoyi-learnings）

> 目标：把 ruoyi-ai 里值得借鉴的工程模式落到 cloudsol.cn，**全程不破坏现有生产行为**。
> 所有新能力均经 feature toggle 默认关闭，未开启时代码路径与现状逐字一致。
> 状态：**已合并 main（commit `97a408b`）并推送到 GitHub，本地冒烟 73 路由通过。生产默认开启 `ENABLE_HYBRID_RETRIEVAL` 与 `SSE_HEARTBEAT_ENABLED`；待按标准流程部署到阿里云即上线。**

## 一、6 项改动总览

| # | 改动 | 提交 | 对应避坑点 |
|---|---|---|---|
| 1 | 集中 feature toggle 配置 | `272e413` | #3 需求清晰 / 配置驱动 |
| 2 | 统一错误枚举 ErrorCode + AppError + 全局 handler | `2b585da` | #5 文档 / #8 不盲信 |
| 3 | SSE 流式心跳保活 + 超时治理 | `501848a` | #4 喂优质项目 |
| 4 | 知识库加载/切分抽象为策略族 | `732428f` | #2 分支隔离 / #4 |
| 5 | RAG 三段式（混合召回+RRF+可插拔重排+阈值） | `2fb7988` | #1 小步提交 / #4 |
| 6 | 生产 Swagger 暴露检查 + nginx 片段 | 见本文档 | #5 防扯皮 |

## 二、各开关与开启方式（在 `.env` 设置后重启）

| 开关 | 默认 | 作用 | 开启效果 |
|---|---|---|---|
| `ENABLE_HYBRID_RETRIEVAL` | true（生产默认开） | 开启 RAG 三段式混合召回 | 检索从单路向量升级为「向量+关键词→RRF融合→重排→阈值」 |
| `ENABLE_RERANK` | false | 开启重排钩子 | 接入重排后端时生效；未配置后端则安全透传（仅告警） |
| `RAG_RRF_ALPHA` | 0.5 | 向量召回在 RRF 中的权重 | 1-alpha 给关键词召回 |
| `RAG_RRF_K` | 60 | RRF 常数 | 避免并列除零 |
| `RAG_THRESHOLD` | 0.0 | 融合后最低分阈值 | >0 时过滤低分片段 |
| `SSE_HEARTBEAT_ENABLED` | true（生产默认开） | 开启 SSE 心跳+超时 | 发 SSE 注释心跳(: ping)防连接僵死，超 `SSE_TIMEOUT` 主动结束 |
| `SSE_HEARTBEAT_INTERVAL` | 30 | 心跳间隔(秒) | — |
| `SSE_TIMEOUT` | 300 | 单次流式最长(秒) | — |

## 三、各项说明

### 1. 配置开关（`app/config.py`）
沿用项目原有 `os.getenv` 风格（不强行重构为 pydantic-settings，避免引入风险）。集中暴露所有新能力开关。

### 2. 统一错误（`app/core/errors.py` + `api/main.py`）
- 新增 `ErrorCode` 枚举 + `AppError` 异常 + `app_error_handler`，注册为 `AppError` 的全局 handler，返回 `{"code","message","detail"}`。
- **保留原 `Exception` handler 与现有 HTTPException/422 形态不变**（前端依赖 `detail` 字段，未动）。
- 新代码建议统一 `raise AppError(ErrorCode.XXX, "...")`；旧代码无需改动即可继续工作。

### 3. SSE 治理（`api/routes.py` 两处流式端点）
- `agent/match/stream` 与 `agent/clarify` 生成器增加受控路径。
- 开启 `SSE_HEARTBEAT_ENABLED` 后：每 `SSE_HEARTBEAT_INTERVAL` 秒发一条 SSE 注释心跳 `: ping\n\n`（客户端忽略，仅保活）；超过 `SSE_TIMEOUT` 主动结束流式。
- **默认关闭时，代码路径与原实现逐字一致**，行为不变。

### 4. 入库策略族（`app/knowledge/loaders.py` + `splitters.py`）
- 新增 `BaseLoader`(PdfLoader/TextLoader) + `BaseSplitter`(RecursiveCharacterSplitter)，均带注册表，新增格式零侵入。
- `app/utils/document_loader.py` 改为委托新策略族；`DocumentLoader` / `load_documents_from_directory` 对外签名与行为不变。
- **额外加固**：纯文本加载改用内置 `open` 读取，规避本机 venv（langchain_community 0.0.38）`TextLoader` 签名怪象，跨版本更稳。

### 5. RAG 三段式（`app/services/knowledge_base.py`）
- `_similarity_pool` 增加受控分支：开启后走 `_hybrid_pool`。
- `_hybrid_pool`：向量召回(`similarity_search_with_score`) + 关键词全文召回(内存扫描全库) → RRF 倒数排名融合(`_rrf_fuse`, alpha 加权) → 可插拔重排(`_rerank`, 默认 no-op) → 阈值过滤。
- 重排经 `RERANKER_REGISTRY` 可插拔：接入 bge-reranker 等时注册 `"default"` 实现即可，未配置则安全透传。
- **默认关闭时 `_similarity_pool` 逐字返回 `similarity_search`**，匹配行为 100% 不变。

### 6. 生产 Swagger 暴露检查（#185）
本地实测 `/docs`、`/openapi.json`、`/redoc` 均返回 200，**生产环境对外暴露了接口文档**。建议生产 nginx 屏蔽（见下方片段）。本项不改代码，仅文档与运维动作。

## 四、生产 Nginx 屏蔽 Swagger（运维动作，需你在服务器执行）

在 cloudsol.cn 的 nginx 配置（代理 API 的 `location` 块）增加：

```nginx
# 屏蔽 API 文档暴露（安全项）
location ~ ^/(docs|redoc|openapi\.json) {
    deny all;
    return 404;
}
```

改完 `nginx -t && nginx -s reload`。本地/调试环境可保留。

## 五、回滚方式（对应避坑点 #1 小步提交 + #2 分支隔离）

所有改动已拆成 5 个独立 commit，可单点回滚：

```bash
git log --oneline feature/ruoyi-learnings   # 查看 5 个提交
git revert <commit-hash>                    # 单点回退某个改动
# 或整体放弃分支（不影响 main）：
git checkout main && git branch -D feature/ruoyi-learnings
```

## 六、部署说明（重要）

- **已合并 main 并推送 GitHub（commit `97a408b`），本地冒烟 73 路由通过。**
- 上线步骤（在阿里云服务器 root 执行，详见对话中「服务器操作清单」）：
  1. 拉取最新 main 压缩包并覆盖代码（`cp -r`，不动 venv/data）
  2. `systemctl restart huawei-cloud-api`
  3. 按下方 nginx 片段屏蔽 `/docs` 等
- **回退最快方式**（无需重新部署）：在服务器 `.env` 追加 `ENABLE_HYBRID_RETRIEVAL=false` 与 `SSE_HEARTBEAT_ENABLED=false` 后 `systemctl restart huawei-cloud-api`。

## 七、验证记录（对应避坑点 #8 实测不盲信）

- 每个 commit 后本地 `import api.main` 全量冒烟（73 路由）通过。
- 真起 uvicorn 跑匿名 `POST /api/match`：默认全关时返回 200，方案字段完整，`source_documents`=6，与现状一致。
- RAG 融合逻辑用桩对象单测：开启后「智慧农业」(0.016) > 「工业互联网」(0.008)，排序符合预期；默认关闭时确认走原 `similarity_search` 路径。
- SSE / 入库 / 错误模块均通过 import 冒烟与针对性单元验证。
