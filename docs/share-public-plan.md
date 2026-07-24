# 方案④：匿名公开方案页 + 二维码（外部分享）

> 状态：规划中（仅设计，未改动任何代码/部署）
> 目标：用户把自己的某次匹配结果生成一个**匿名公开链接 + 二维码**，发到微信/朋友圈，客户扫码即可查看方案；无需登录、不涉及社区。
> 适用场景：售前把生成的华为云方案发给客户，客户点链接/扫码即看，专业且轻量。

---

## 1. 用户流程

```
结果页/历史页
   └─ 点「分享为公开链接」
        └─ 后端存快照 + 生成 token
             └─ 前端弹层显示 公开URL + 二维码 + 复制/撤销
                  └─ 用户转发微信/朋友圈
                       └─ 客户扫码 / 点链接
                            └─ 匿名公开页 /s/{token} 查看方案（无需登录）
```

---

## 2. 数据模型（新增表 `public_shares`）

按部署铁律②：新表必须在 `db_init.py` 里幂等建表（CREATE TABLE IF NOT EXISTS）+ 必要 ALTER，不能只在代码里建。

```sql
CREATE TABLE IF NOT EXISTS public_shares (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  token       TEXT UNIQUE NOT NULL,          -- URL 安全随机串, 用于 /s/{token}
  owner_id    INTEGER NOT NULL,              -- 分享者(外键 users.id)
  title       TEXT,                          -- 方案标题
  industry    TEXT,                          -- 行业
  demand      TEXT,                          -- 需求描述(由用户决定是否含敏感信息)
  content_json TEXT NOT NULL,                -- 方案内容快照(已匿名化, JSON)
  created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  expires_at  TIMESTAMP,                     -- 可选过期, 默认 NULL=长期
  view_count  INTEGER DEFAULT 0,
  is_active   BOOLEAN DEFAULT 1,             -- 撤销置 0
  FOREIGN KEY (owner_id) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_public_shares_token ON public_shares(token);
```

**匿名化要点**
- 公开页**不显示 owner 用户名/邮箱**，仅底部标注「由 cloudsol.cn 智能生成」。
- 方案正文来自 AI 生成结果，本身不含用户隐私；`demand` 字段由用户自行决定分享内容（MVP 不做自动打码，避免误伤正常需求）。
- `content_json` 存储的是结果快照，分享后即使原历史被删也不影响公开页。

---

## 3. 后端接口

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/api/share/create` | 登录 | 入参 `history_id`（推荐，复用已存历史）或完整 result payload → 生成 token、存快照、返回 `{token, url, qr_text, first_share_unlocked}`；并触发 `first_share` 成就 |
| GET | `/api/share/{token}` | 匿名 | 返回公开方案内容（只读，is_active=1 且未过期才返回，否则 404/410） |
| DELETE | `/api/share/{token}` | 登录+owner | 撤销（is_active=0） |
| GET | `/api/share/mine` | 登录 | 列出当前用户分享过的（含 view_count、is_active） |

**安全**
- `token = secrets.token_urlsafe(16)`，不可猜测。
- 公开接口不泄露 `owner_id` 映射；返回体只含方案内容 + 元信息（行业/时间）。
- 撤销即 `is_active=0`；可选 `expires_at` 支持定时失效。

**接通死成就**：`POST /api/share/create` 成功后，调用现有 `achievement_service` 的 share 计数/`check_page_view("share")` 路径，使 `first_share`「分享达人」从死成就变活。语义完全契合「首次分享匹配结果」。

---

## 4. 前端改动点

1. **入口按钮**：结果页（`#page-solution`）与历史页（`#page-history`）加「分享为公开链接」按钮 → 调 `POST /api/share/create`。
2. **分享弹层**：显示公开 URL + 二维码 + 「复制链接」+「撤销分享」。二维码用前端轻量库（如 `qrcode` JS）把 URL 渲染成 canvas/SVG，**零后端改动**。
3. **匿名公开页**：新建无需登录的查看页（SPA 内 `#page-share-view` 或独立路由 `/s/{token}`，由 `GET /api/share/{token}` 拉数据）。复用现有方案渲染样式，底部标注「由 cloudsol.cn 智能生成」+ 跳转官网入口。
4. **我的分享管理**：`#page-mine` 或历史页增加「我分享的」列表（调 `GET /api/share/mine`），可撤销。

**二维码实现选择**
- 推荐：前端生成（引入 `qrcode` 库，把公开 URL 画成 canvas）。零后端依赖、加载快。
- 备选：后端 `python-qrcode` 生成 PNG base64 随接口返回（增一个依赖，不推荐）。

---

## 5. 工作量估算（供后续开发排期，非承诺）

| 模块 | 估时 |
|---|---|
| 后端：建表 + 4 接口 + 匿名化 | ~0.5 人日 |
| 前端：按钮 + 弹层 + 二维码 + 匿名页 | ~1 人日 |
| 接通 `first_share` 成就 | ~0.5 小时 |
| 联调 + 部署 + 验证 | ~0.5 人日 |
| **合计** | **约 2–2.5 人日** |

---

## 6. 明确排除（不在本方案范围）

- ❌ 站内社区 / 评论 / 点赞 / 关注
- ❌ 站内公开列表页（`page-share` 不做成发现流；仅做「我的分享」管理）
- ❌ 微信 SDK 真·分享朋友圈（需服务号认证 + 备案域名 + JS-SDK，个人项目性价比低；用「复制链接 + 二维码」绕开）
- ❌ 自动敏感信息打码（MVP 由用户自行决定分享内容）

---

## 7. 与现有系统的衔接

- **结果数据来源**：优先引用历史表 `history_id` 取快照（已有存储，最稳），而非前端重传 result。
- **成就系统**：复用 `achievement_service` 现有 share 钩子，无需新成就定义。
- **部署**：纯后端表结构变更走铁律②（db_init.py 幂等）；前端改动升 index.html 版本号；部署后按铁律⑤ curl 验证。
