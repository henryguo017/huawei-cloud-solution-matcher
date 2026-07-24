# 知识库月度自动更新 + 文档版本溯源（规划）

> 状态：规划中（仅设计，未改动任何代码/部署）
> 目标：① 定时（每月）爬取各厂商在各行业的解决方案白皮书，自动纳入知识库；② 知识库每一份文档都标记「来自哪次月度更新（时间版本）」，检索/展示可溯源。
> 范围：华为云 + 12 家竞品厂商，覆盖现有 25 个行业。

---

## 1. 现状对齐

- 知识库源文档：`data/sample_solutions/{行业}/`（华为）+ `data/competitors/{公司}/`（竞品），手工放置，被 git 跟踪（312 文件）。
- 向量库：`data/vector_db`（ChromaDB，集合 `huawei_solutions`），**gitignore**；由 `KnowledgeBaseService.build_from_directory()` 从源文档构建。
- 文档按父目录自动打 `industry` / `company` 标签。
- 铁律④：源文档变更后必须**停服 → 重建向量库 → 起服**，否则线上不生效。
- 当前**无自动爬取**，文档靠人工维护；文档**无版本标记**。

---

## 2. 整体架构（月度流水线）

```
种子配置(公司/行业/URL)
   └─ 每月定时触发
        └─ 爬取: 下载 PDF/HTML → 解析文本 → content_hash 去重
             └─ 落盘: data/{sample_solutions|competitors}/{行业|公司}/文件名_{版本}.pdf|.md
                  └─ 停服重建向量库(build_from_directory, 带版本 metadata)
                       └─ 生成 changelog + 知识库页/检索结果展示版本标签
```

---

## 3. 模块设计

### 3.1 种子配置（驱动式，不硬编码）
- `scripts/crawl_config.yaml`：
  ```yaml
  schedule: "0 3 1 * *"        # 每月1号 03:00
  rate_limit_sec: 2            # 请求间隔, 防封
  targets:
    - company: huawei
      industry: 政务
      url: https://.../whitepaper.pdf
    - company: aliyun
      industry: 金融
      url: https://.../solution.html
    # ... 华为云 + 12 家竞品 × 25 行业
  ```
- 新增厂商/行业只改配置，不动代码。

### 3.2 爬虫（`scripts/crawl_whitepapers.py`）
- **下载器**：`requests` + 随机 UA + `rate_limit_sec` 限速 + 遵守 `robots.txt`。
- **解析器**：
  - PDF → 文本：`pdfplumber` / `pypdf`。
  - HTML → 正文：`trafilatura`（适合官网文章/白皮书页）或 `BeautifulSoup`。
  - 若目标为 JS 渲染页，需 `Playwright` headless（重，列为可选项，非默认）。
- **去重**：`content_hash = sha256(正文)`；与上次快照比对，未变则跳过（不重复落盘）。
- **输出**：本次结果 JSON `{added, updated, skipped, failed, by_company}`。

### 3.3 版本溯源 schema（核心）
**两个层面都打版本：**

1. **文件命名**（人类可读 + 可追溯）：
   ```
   data/competitors/aliyun/金融/aliyun_金融_2026-07.pdf
   data/sample_solutions/政务/huawei_政务_2026-07.md
   ```
   版本号 = 爬取年月（`2026-07`），同一文档多次更新保留历史文件。

2. **向量库 metadata**（检索可溯源）：每个 chunk 带
   ```json
   {
     "company": "aliyun",
     "industry": "金融",
     "doc_version": "2026-07",
     "crawled_at": "2026-07-01T03:12:00",
     "source_url": "https://...",
     "content_hash": "a1b2c3..."
   }
   ```
   检索返回片段时连同 `doc_version` / `crawled_at` 一起给前端，实现「这段方案来自 2026-07 版白皮书」。

### 3.4 调度（每月）
- 服务器用 **systemd timer** 或 **cron**：`0 3 1 * *` 触发 `crawl_whitepapers.py`。
- 脚本尾部自动串联重建流程（见 3.5）。

### 3.5 向量库重建（衔接铁律④）
- 爬取落盘后，脚本调用：
  ```
  systemctl stop huawei-cloud-api
  python -c "KnowledgeBaseService(user_id=0).build_from_directory(use_default_dirs=True)"
  systemctl start huawei-cloud-api
  ```
- 重建时把 3.3 的 metadata 写入 ChromaDB（改 `build_from_directory` 让其在 load 时读取文件名/配置里的版本）。
- 维度注意：embedding 模型不变则兼容；若改模型须按铁律 rm 向量库后全量重建。

### 3.6 更新日志 changelog
- 每次运行产出 `data/kb_changelog/2026-07.json`：新增/更新/跳过/失败清单 + 版本号。
- 知识库管理页可展示最近 N 次更新的 changelog。

### 3.7 UI 版本展示
- **知识库管理页（`#page-knowledge`）**：文档列表增加「版本 / 爬取时间」列。
- **检索结果卡片**：来源标注「2026-07 版 · 阿里云 · 金融」，可点击溯源原文件/URL。

---

## 4. 与部署铁律衔接

- **铁律②**：新表/新字段（如 changelog 表、向量 metadata 字段）须幂等建表/迁移，写进 `db_init.py`。
- **铁律④**：月度爬取 = 源文档变更，必须走「停服 → 重建 → 起服」，脚本自动化此流程。
- **铁律⑤**：重建后 `curl` 验证 `/api/knowledge/stats` 文档数与版本覆盖符合预期。
- `data/` 仍 gitignore（爬取文档在服务器本地，不进 git），与现状一致。

---

## 5. 风险与合规（重点）

1. **版权 / 合规（最高优先级）**：爬取竞品白皮书存入自建知识库并用于 AI 匹配，存在合规风险。建议：
   - 仅用于**个人作品集 / 学习**，不商用闭源分发匹配结果中的竞品原文；
   - 保留 `source_url` 与出处署名，遵守 `robots.txt`；
   - 简历/面试中如实说明「数据来源为各厂商公开官网白皮书，自动采集」。
2. **可爬性**：部分白皮书需登录/表单下载或 JS 渲染，`requests` 抓不到，需 Playwright（重、慢、易被风控）。种子 URL 需人工校验可用性。
3. **反爬 / 封 IP**：大厂官网有 WAF，限速 + 随机 UA 是底线，仍可能被临时封。建议低频次（每月一次）降低风险。
4. **解析质量**：PDF/HTML 解析噪声多，需清洗（去页眉页脚/导航），否则污染向量库、拉低匹配质量。
5. **维护成本**：官网改版、URL 失效需持续维护种子配置。

---

## 6. 工作量估算（供排期，非承诺）

| 模块 | 估时 |
|---|---|
| 种子配置 + 下载器 + PDF/HTML 解析 + 去重 | ~1.5–2 人日 |
| 版本 schema（文件命名 + 向量 metadata + build 改造） | ~0.5 人日 |
| 调度（systemd timer）+ 自动停服重建脚本 | ~0.5 人日 |
| changelog + 知识库页/检索结果版本展示 | ~0.5–1 人日 |
| 解析清洗 + 合规处理 | ~0.5 人日 |
| **合计** | **约 4–5 人日** |

---

## 7. 明确排除

- ❌ 实时/每周爬取（仅每月，降合规与反爬风险）
- ❌ 竞品原文商用分发（仅个人作品集/学习用途）
- ❌ 自动登录抓付费/受限资源
- ❌ 跨版本 diff 高亮（MVP 仅打版本标签，不做逐字对比）
