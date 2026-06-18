"""
成就勋章服务 — 定义 45 个成就、检测触发、管理解锁
"""
import sqlite3
import os
import json
import logging
from datetime import datetime, time
from typing import Dict, List, Any, Optional, Tuple
from threading import Lock

logger = logging.getLogger(__name__)

# ── 45 个成就定义（铜7+银7+金8+钻5+隐藏18） ──────────────────────
ACHIEVEMENTS = [
    # ===== 铜 · 入门 (7) =====
    {"id": "first_match",    "name": "初出茅庐",   "desc": "完成第一次方案匹配",       "rarity": "copper", "icon": "🌱", "is_hidden": False},
    {"id": "first_analyze",  "name": "竞品初探",   "desc": "完成第一次竞品分析",       "rarity": "copper", "icon": "🔍", "is_hidden": False},
    {"id": "first_kb_view",  "name": "知识初窥",   "desc": "首次打开知识库页面",       "rarity": "copper", "icon": "📖", "is_hidden": False},
    {"id": "first_login",     "name": "登录成功",     "desc": "首次登录账号",           "rarity": "copper", "icon": "👋", "is_hidden": False},
    {"id": "complete_wizard", "name": "向导学员",   "desc": "通过向导模式完成一次匹配", "rarity": "copper", "icon": "🧭", "is_hidden": False},
    {"id": "view_dashboard",  "name": "数据爱好者", "desc": "首次打开仪表盘",         "rarity": "copper", "icon": "📊", "is_hidden": False},
    {"id": "first_share",     "name": "分享达人",   "desc": "首次分享匹配结果",       "rarity": "copper", "icon": "🔗", "is_hidden": False},

    # ===== 银 · 进阶 (7) =====
    {"id": "match_10",       "name": "渐入佳境",   "desc": "累计完成 10 次方案匹配",  "rarity": "silver", "icon": "⚡", "is_hidden": False},
    {"id": "analyze_10",     "name": "竞品猎手",   "desc": "累计完成 10 次竞品分析",  "rarity": "silver", "icon": "🎯", "is_hidden": False},
    {"id": "use_all_modes",  "name": "模式体验官", "desc": "使用过全部 3 种匹配模式", "rarity": "silver", "icon": "🎛️", "is_hidden": False},
    {"id": "add_kb_doc",     "name": "知识贡献者", "desc": "在知识库新增一篇文档",     "rarity": "silver", "icon": "✍️", "is_hidden": False},
    {"id": "match_3_day",    "name": "三连击",     "desc": "连续 3 天使用系统",      "rarity": "silver", "icon": "🔥", "is_hidden": False},
    {"id": "industry_5",      "name": "行业探索者", "desc": "匹配覆盖 5 个不同行业",   "rarity": "silver", "icon": "🗺️", "is_hidden": False},
    {"id": "night_owl",      "name": "夜猫子",     "desc": "在 22:00–02:00 使用系统", "rarity": "silver", "icon": "🦉", "is_hidden": False},

    # ===== 金 · 高阶 (8) =====
    {"id": "match_50",       "name": "方案大师",   "desc": "累计完成 50 次方案匹配",  "rarity": "gold",   "icon": "👑", "is_hidden": False},
    {"id": "analyze_50",     "name": "竞品专家",   "desc": "累计完成 50 次竞品分析",  "rarity": "gold",   "icon": "🏆", "is_hidden": False},
    {"id": "industry_10",     "name": "行业通",     "desc": "匹配覆盖全部 10 个行业",   "rarity": "gold",   "icon": "🌐", "is_hidden": False},
    {"id": "agent_master",    "name": "Agent 觉醒", "desc": "使用 Agent 模式完成 10 次匹配", "rarity": "gold", "icon": "🤖", "is_hidden": False},
    {"id": "kb_docs_10",     "name": "知识库管理员", "desc": "知识库文档总数达到 10 篇", "rarity": "gold", "icon": "📚", "is_hidden": False},
    {"id": "match_7_day",     "name": "一周坚守",   "desc": "连续 7 天使用系统",      "rarity": "gold",   "icon": "📅", "is_hidden": False},
    {"id": "competitor_12",   "name": "竞品全图鉴", "desc": "完成全部 12 家竞品分析",  "rarity": "gold",   "icon": "🃏", "is_hidden": False},
    {"id": "reindex_20",      "name": "索引工程师", "desc": "累计重建索引 20 次",      "rarity": "gold",   "icon": "🔧", "is_hidden": False},

    # ===== 钻 · 大师 (5) =====
    {"id": "match_200",      "name": "终极匹配王", "desc": "累计完成 200 次方案匹配",  "rarity": "diamond", "icon": "💎", "is_hidden": False},
    {"id": "analyze_200",    "name": "终极分析师", "desc": "累计完成 200 次竞品分析",  "rarity": "diamond", "icon": "🧠", "is_hidden": False},
    {"id": "all_achieve_50", "name": "成就达人",   "desc": "累计解锁 50% 的成就",     "rarity": "diamond", "icon": "🏅", "is_hidden": False},
    {"id": "perfect_week",    "name": "完美一周",   "desc": "连续 7 天每天至少使用 3 次", "rarity": "diamond", "icon": "⭐", "is_hidden": False},
    {"id": "early_bird",     "name": "早起鸟",     "desc": "在 05:00–07:00 使用系统", "rarity": "diamond", "icon": "🐦", "is_hidden": False},

    # ===== 谜 · 隐藏 (18) =====
    {"id": "easter_april_fool",    "name": "愚人快乐",   "desc": "4 月 1 日当天使用系统",     "rarity": "hidden", "icon": "🤡", "is_hidden": True},
    {"id": "easter_new_year",       "name": "跨年达人",   "desc": "除夕或元旦当天使用系统",     "rarity": "hidden", "icon": "🎆", "is_hidden": True},
    {"id": "easter_520",            "name": "520告白",    "desc": "5 月 20 日当天使用系统",      "rarity": "hidden", "icon": "💕", "is_hidden": True},
    {"id": "easter_late_night",     "name": "深夜修仙",   "desc": "凌晨 3:00–5:00 使用系统",   "rarity": "hidden", "icon": "🌙", "is_hidden": True},
    {"id": "easter_birthday",       "name": "生日快乐",   "desc": "生日当天使用系统",          "rarity": "hidden", "icon": "🎂", "is_hidden": True},
    {"id": "easter_friday_eve",     "name": "周五狂欢",   "desc": "周五 17:00 后使用系统",     "rarity": "hidden", "icon": "🍻", "is_hidden": True},
    {"id": "easter_mid_autumn",     "name": "月圆之夜",   "desc": "中秋节当天使用系统",         "rarity": "hidden", "icon": "🥮", "is_hidden": True},
    {"id": "easter_search_harmony", "name": "鸿蒙探索者", "desc": "搜索内容包含「鸿蒙」",       "rarity": "hidden", "icon": "🔷", "is_hidden": True},
    {"id": "easter_hello_world",    "name": "Hello World","desc": "搜索内容包含「hello world」","rarity": "hidden", "icon": "💻", "is_hidden": True},
    {"id": "easter_dev_name",       "name": "我是郭鸿宇", "desc": "搜索内容包含「郭鸿宇」",     "rarity": "hidden", "icon": "😎", "is_hidden": True},
    {"id": "easter_hidden_word",     "name": "彩蛋猎人",   "desc": "搜索内容包含「隐藏成就」",   "rarity": "hidden", "icon": "🎪", "is_hidden": True},
    {"id": "easter_empty_search",    "name": "无声胜有声", "desc": "不输入任何内容直接匹配",     "rarity": "hidden", "icon": "🫥", "is_hidden": True},
    {"id": "easter_retry_3",        "name": "锲而不舍",   "desc": "同一需求匹配 3 次",         "rarity": "hidden", "icon": "🔁", "is_hidden": True},
    {"id": "easter_first_agent",     "name": "Agent 觉醒", "desc": "首次使用 Agent 模式",       "rarity": "hidden", "icon": "✨", "is_hidden": True},
    {"id": "easter_mode_master",     "name": "模式大师",   "desc": "同一天用完所有 3 种匹配模式","rarity": "hidden", "icon": "🎮", "is_hidden": True},
    {"id": "easter_konami",         "name": "秘技大师",   "desc": "触发 Konami Code 秘技",     "rarity": "hidden", "icon": "🕹️", "is_hidden": True},
    {"id": "easter_404_wait",        "name": "40.4 秒",    "desc": "在 404 页面停留 40.4 秒",   "rarity": "hidden", "icon": "🌀", "is_hidden": True},
    {"id": "easter_egg_hunter",      "name": "彩蛋收藏家", "desc": "累计解锁 10 个隐藏成就",    "rarity": "hidden", "icon": "🥚", "is_hidden": True},
]

# 稀有度显示名
RARITY_NAMES = {
    "copper":  "铜 · 入门",
    "silver":  "银 · 进阶",
    "gold":    "金 · 高阶",
    "diamond": "钻 · 大师",
    "hidden":  "谜 · 隐藏",
}

RARITY_ORDER = ["copper", "silver", "gold", "diamond", "hidden"]


class AchievementService:
    """成就服务：管理成就定义、解锁检测、进度查询"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, "achievements.db")
        self.db_path = db_path
        self._init_db()
        self._seed_achievements()

    # ── 内部工具 ──────────────────────────────────────────────────

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS achievements (
                    id          TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    description TEXT NOT NULL,
                    rarity      TEXT NOT NULL,
                    icon        TEXT NOT NULL,
                    is_hidden   INTEGER DEFAULT 0,
                    created_at  DATETIME DEFAULT (datetime('now', 'localtime'))
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_achievements (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id       INTEGER NOT NULL,
                    achievement_id TEXT NOT NULL,
                    unlocked_at   DATETIME DEFAULT (datetime('now', 'localtime')),
                    FOREIGN KEY (user_id)       REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (achievement_id) REFERENCES achievements(id) ON DELETE CASCADE,
                    UNIQUE(user_id, achievement_id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ua_user ON user_achievements(user_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ua_achievement ON user_achievements(achievement_id)")
            # 记录每用户的成就系统初始化状态（防止历史数据一次性爆发）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS achievement_meta (
                    user_id    INTEGER NOT NULL,
                    key        TEXT NOT NULL,
                    value      TEXT,
                    updated_at DATETIME DEFAULT (datetime('now', 'localtime')),
                    PRIMARY KEY (user_id, key),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            conn.commit()

    def _seed_achievements(self):
        """首次启动时把 45 个成就写入 achievements 表"""
        with self._get_connection() as conn:
            existing = {row["id"] for row in conn.execute("SELECT id FROM achievements").fetchall()}
            for ach in ACHIEVEMENTS:
                if ach["id"] not in existing:
                    conn.execute("""
                        INSERT INTO achievements (id, name, description, rarity, icon, is_hidden)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        ach["id"],
                        ach["name"],
                        ach["desc"],
                        ach["rarity"],
                        ach["icon"],
                        1 if ach["is_hidden"] else 0,
                    ))
            conn.commit()

    # ── 查询接口 ──────────────────────────────────────────────────

    def _is_backfill_done(self, user_id: int) -> bool:
        """检查该用户的成就历史回填是否已执行"""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM achievement_meta WHERE user_id = ? AND key = 'backfill_done'",
                (user_id,)
            ).fetchone()
            return row is not None

    def _mark_backfill_done(self, user_id: int):
        """标记该用户的成就历史回填已完成"""
        with self._get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO achievement_meta (user_id, key, value) VALUES (?, 'backfill_done', '1')",
                (user_id,)
            )
            conn.commit()

    def _ensure_backfill(self, user_id: int):
        """
        对已有历史使用记录的用户，首次触发成就检测时先把历史数据
        该解锁的成就 silently 解锁，避免一次性全部弹出。
        只在 backfill_done=0 时执行一次。
        """
        if self._is_backfill_done(user_id):
            return

        # 检查是否有历史 usage_logs 数据
        usage_db = os.path.join(os.path.dirname(self.db_path), "usage_logs.db")
        if not os.path.exists(usage_db):
            # 无历史数据，直接标记完成
            self._mark_backfill_done(user_id)
            return

        try:
            with sqlite3.connect(usage_db) as uconn:
                uconn.row_factory = sqlite3.Row
                total = uconn.execute(
                    "SELECT COUNT(*) as cnt FROM usage_logs WHERE user_id = ?", (user_id,)
                ).fetchone()["cnt"]
                if total == 0:
                    # 无历史数据，直接标记完成
                    self._mark_backfill_done(user_id)
                    return
        except Exception:
            self._mark_backfill_done(user_id)
            return

        # 执行回填：用临时 newly 列表收集，不触发 Toast
        newly = []
        _unlock = lambda aid: self._do_unlock(user_id, aid, newly)

        # ── 登录类 ──
        _unlock("first_login")

        # ── 匹配次数 ──
        match_count = self._count_action(user_id, "match")
        if match_count >= 1:   _unlock("first_match")
        if match_count >= 10:  _unlock("match_10")
        if match_count >= 50:  _unlock("match_50")
        if match_count >= 200: _unlock("match_200")

        # ── 竞品分析次数 ──
        analyze_count = self._count_action(user_id, "analyze")
        if analyze_count >= 1:   _unlock("first_analyze")
        if analyze_count >= 10:  _unlock("analyze_10")
        if analyze_count >= 50:  _unlock("analyze_50")
        if analyze_count >= 200: _unlock("analyze_200")

        # ── Agent 模式次数 ──
        agent_count = self._count_mode(user_id, "agent")
        if agent_count >= 1:   _unlock("easter_first_agent")
        if agent_count >= 10:  _unlock("agent_master")

        # ── 知识库浏览 ──
        kb_count = self._count_action(user_id, "view_kb")
        if kb_count >= 1:   _unlock("first_kb_view")

        # ── 仪表盘浏览 ──
        dash_count = self._count_action(user_id, "view_dashboard")
        if dash_count >= 1: _unlock("view_dashboard")

        # ── 分享 ──
        share_count = self._count_action(user_id, "share")
        if share_count >= 1: _unlock("first_share")

        # ── 行业覆盖 ──
        industries = self._get_unique_industries(user_id)
        if len(industries) >= 5:  _unlock("industry_5")
        if len(industries) >= 10: _unlock("industry_10")

        # ── 竞品覆盖 ──
        competitors_done = self._get_unique_competitors(user_id)
        if len(competitors_done) >= 12:
            _unlock("competitor_12")

        # ── 模式体验官（3种模式都用过）──
        self._check_all_modes(user_id, _unlock)

        # ── 时间类彩蛋 ──
        self._check_time_easter_backfill(user_id, _unlock)

        # ── 钻：成就达人（50%）──
        stats = self.get_user_stats(user_id)
        if stats["total"] > 0 and stats["unlocked"] >= stats["total"] * 0.5:
            _unlock("all_achieve_50")

        # 标记回填完成（不论实际解锁了几枚，只跑一次）
        self._mark_backfill_done(user_id)
        logger.info(f"[Achievement] Backfill done for user {user_id}, silently unlocked {len(newly)} achievements")

    def _check_time_easter_backfill(self, user_id: int, _unlock):
        """
        时间类彩蛋的回填检测：扫描 usage_logs 中所有历史记录，
        只要有一次命中即解锁（仅在 backfill 阶段调用）。
        """
        usage_db = os.path.join(os.path.dirname(self.db_path), "usage_logs.db")
        if not os.path.exists(usage_db):
            return
        try:
            with sqlite3.connect(usage_db) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT timestamp FROM usage_logs WHERE user_id = ?",
                    (user_id,)
                ).fetchall()
                for row in rows:
                    ts = row["timestamp"]
                    try:
                        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S") if isinstance(ts, str) else datetime.fromtimestamp(ts)
                        month, day = dt.month, dt.day
                        hour = dt.hour
                        # 愚人节
                        if month == 4 and day == 1:
                            _unlock("easter_april_fool")
                        # 跨年
                        if (month == 12 and day == 31) or (month == 1 and day == 1):
                            _unlock("easter_new_year")
                        # 520
                        if month == 5 and day == 20:
                            _unlock("easter_520")
                        # 深夜修仙
                        if 3 <= hour <= 5:
                            _unlock("easter_late_night")
                        # 夜猫子（22~02）
                        if hour >= 22 or hour <= 2:
                            _unlock("night_owl")
                        # 早起鸟
                        if 5 <= hour <= 7:
                            _unlock("early_bird")
                        # 周五狂欢
                        if dt.weekday() == 4 and hour >= 17:
                            _unlock("easter_friday_eve")
                    except Exception:
                        continue
        except Exception as e:
            logger.warning(f"[Achievement] Backfill time easter failed: {e}")

    def get_user_achievements(self, user_id: int) -> List[Dict[str, Any]]:
        """
        返回用户所有成就状态（含未解锁的）。
        隐藏成就未解锁时 name/desc/icon 用占位符。
        """
        self._ensure_backfill(user_id)
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT a.id, a.name, a.description, a.rarity, a.icon, a.is_hidden,
                       ua.unlocked_at
                FROM achievements a
                LEFT JOIN user_achievements ua
                       ON ua.achievement_id = a.id AND ua.user_id = ?
                ORDER BY CASE a.rarity
                    WHEN 'copper'  THEN 1
                    WHEN 'silver'  THEN 2
                    WHEN 'gold'    THEN 3
                    WHEN 'diamond' THEN 4
                    WHEN 'hidden'  THEN 5
                END, a.id
            """, (user_id,)).fetchall()

            result = []
            for row in rows:
                unlocked = row["unlocked_at"] is not None
                is_hidden = bool(row["is_hidden"])
                item = {
                    "id":           row["id"],
                    "rarity":       row["rarity"],
                    "rarity_name":  RARITY_NAMES.get(row["rarity"], ""),
                    "unlocked":     unlocked,
                    "unlocked_at":  row["unlocked_at"],
                }
                if unlocked or not is_hidden:
                    item["name"]        = row["name"]
                    item["description"] = row["description"]
                    item["icon"]        = row["icon"]
                else:
                    item["name"]        = "???"
                    item["description"] = "解锁后可见"
                    item["icon"]        = "❓"
                result.append(item)
            return result

    def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        """返回用户成就统计"""
        with self._get_connection() as conn:
            total      = conn.execute("SELECT COUNT(*) FROM achievements").fetchone()[0]
            unlocked   = conn.execute(
                "SELECT COUNT(*) FROM user_achievements WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
            hidden_total = conn.execute(
                "SELECT COUNT(*) FROM achievements WHERE is_hidden = 1"
            ).fetchone()[0]
            hidden_unlocked = conn.execute("""
                SELECT COUNT(*) FROM user_achievements ua
                JOIN achievements a ON a.id = ua.achievement_id
                WHERE ua.user_id = ? AND a.is_hidden = 1
            """, (user_id,)).fetchone()[0]
            return {
                "total":           total,
                "unlocked":        unlocked,
                "hidden_total":    hidden_total,
                "hidden_unlocked": hidden_unlocked,
                "percent":         round(unlocked / total * 100, 1) if total else 0,
            }

    def is_unlocked(self, user_id: int, achievement_id: str) -> bool:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM user_achievements WHERE user_id = ? AND achievement_id = ?",
                (user_id, achievement_id)
            ).fetchone()
            return row is not None

    # ── 解锁接口 ──────────────────────────────────────────────────

    def unlock(self, user_id: int, achievement_id: str) -> Tuple[bool, Optional[Dict]]:
        """
        解锁一个成就。返回 (是否新解锁, 成就信息)。
        已解锁的不会重复触发。
        """
        if self.is_unlocked(user_id, achievement_id):
            return False, None

        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO user_achievements (user_id, achievement_id) VALUES (?, ?)",
                (user_id, achievement_id)
            )
            conn.commit()

        ach = next((a for a in ACHIEVEMENTS if a["id"] == achievement_id), None)
        logger.info(f"[Achievement] User {user_id} unlocked: {achievement_id}")
        return True, ach

    # ── 触发检测（在业务动作后调用）───────────────────────────────

    def check_after_match(self, user_id: int, demand_text: str, mode: str,
                         industry: str) -> List[Dict]:
        """
        匹配完成后调用。
        返回新解锁的成就列表（供前端弹窗提示）。
        """
        self._ensure_backfill(user_id)
        newly = []
        _unlock = lambda aid: self._do_unlock(user_id, aid, newly)

        # 铜：初出茅庐
        _unlock("first_match")

        # 铜：向导学员（wizard 模式）
        if mode == "wizard":
            _unlock("complete_wizard")

        # 银：累计次数
        count = self._count_action(user_id, "match")
        if count >= 10:  _unlock("match_10")
        if count >= 50:  _unlock("match_50")
        if count >= 200: _unlock("match_200")

        # 金：Agent 觉醒
        if mode == "agent":
            agent_count = self._count_mode(user_id, "agent")
            if agent_count >= 10: _unlock("agent_master")
            _unlock("easter_first_agent")

        # 银：模式体验官
        self._check_all_modes(user_id, _unlock)

        # 银：行业探索者 / 金：行业通
        industries = self._get_unique_industries(user_id)
        if len(industries) >= 5:  _unlock("industry_5")
        if len(industries) >= 10: _unlock("industry_10")

        # 隐藏：空输入
        if not demand_text or demand_text.strip() == "":
            _unlock("easter_empty_search")

        # 隐藏：同一需求匹配 3 次
        if demand_text and demand_text.strip():
            dup_count = self._count_similar_demand(user_id, demand_text)
            if dup_count >= 3:
                _unlock("easter_retry_3")

        # 隐藏：搜索关键词
        text_lower = (demand_text or "").lower()
        if "鸿蒙" in text_lower:      _unlock("easter_search_harmony")
        if "hello world" in text_lower: _unlock("easter_hello_world")
        if "郭鸿宇" in text_lower:     _unlock("easter_dev_name")
        if "隐藏成就" in text_lower:    _unlock("easter_hidden_word")

        # 隐藏：同一天用完 3 种模式
        self._check_mode_master(user_id, _unlock)

        # 时间类彩蛋
        self._check_time_easter(user_id, _unlock)

        # 连续使用天数（三连击 / 一周坚守）
        self._check_continuous_days(user_id, _unlock)

        # 钻：完美一周（连续7天每天至少3次）
        self._check_perfect_week(user_id, _unlock)

        # 钻：成就达人（50%）
        stats = self.get_user_stats(user_id)
        if stats["total"] > 0 and stats["unlocked"] >= stats["total"] * 0.5:
            _unlock("all_achieve_50")

        return newly

    def check_after_analyze(self, user_id: int, competitor: str) -> List[Dict]:
        """竞品分析完成后调用"""
        self._ensure_backfill(user_id)
        newly = []
        _unlock = lambda aid: self._do_unlock(user_id, aid, newly)

        _unlock("first_analyze")

        count = self._count_action(user_id, "analyze")
        if count >= 10:  _unlock("analyze_10")
        if count >= 50:  _unlock("analyze_50")
        if count >= 200: _unlock("analyze_200")

        # 金：竞品全图鉴
        competitors_done = self._get_unique_competitors(user_id)
        if len(competitors_done) >= 12:
            _unlock("competitor_12")

        self._check_time_easter(user_id, _unlock)
        # 注意：竞品分析不记录 mode 字段，不检测 mode_master
        # 成就达人
        stats = self.get_user_stats(user_id)
        if stats["total"] > 0 and stats["unlocked"] >= stats["total"] * 0.5:
            _unlock("all_achieve_50")

        return newly

    def check_after_login(self, user_id: int) -> List[Dict]:
        """登录后调用"""
        self._ensure_backfill(user_id)
        newly = []
        _unlock = lambda aid: self._do_unlock(user_id, aid, newly)
        _unlock("first_login")
        self._check_time_easter(user_id, _unlock)
        self._check_continuous_days(user_id, _unlock)
        self._check_perfect_week(user_id, _unlock)
        return newly

    def check_page_view(self, user_id: int, page_name: str) -> List[Dict]:
        """页面访问触发（知识库/仪表盘/分享）"""
        self._ensure_backfill(user_id)
        newly = []
        _unlock = lambda aid: self._do_unlock(user_id, aid, newly)
        if page_name == "knowledge":
            _unlock("first_kb_view")
        elif page_name == "dashboard":
            _unlock("view_dashboard")
        elif page_name == "share":
            _unlock("first_share")
        self._check_time_easter(user_id, _unlock)
        return newly

    def check_after_kb_add(self, user_id: int) -> List[Dict]:
        """知识库新增文档后调用"""
        self._ensure_backfill(user_id)
        newly = []
        _unlock = lambda aid: self._do_unlock(user_id, aid, newly)
        _unlock("add_kb_doc")
        # 动态检查：知识库文档总数
        # （此处在服务层无法感知总文档数，由调用方传入或在 routes 层检查）
        return newly

    def check_kb_doc_count(self, user_id: int, total_docs: int) -> List[Dict]:
        """外部传入知识库文档总数，检查相关成就"""
        self._ensure_backfill(user_id)
        newly = []
        _unlock = lambda aid: self._do_unlock(user_id, aid, newly)
        if total_docs >= 10: _unlock("kb_docs_10")
        return newly

    def check_after_reindex(self, user_id: int, count: int) -> List[Dict]:
        """重建索引后调用（count 为累计次数）"""
        self._ensure_backfill(user_id)
        newly = []
        _unlock = lambda aid: self._do_unlock(user_id, aid, newly)
        if count >= 20: _unlock("reindex_20")
        return newly

    def check_konami(self, user_id: int) -> List[Dict]:
        """前端触发 Konami Code 时调用"""
        self._ensure_backfill(user_id)
        newly = []
        _unlock = lambda aid: self._do_unlock(user_id, aid, newly)
        _unlock("easter_konami")
        return newly

    def check_404_wait(self, user_id: int) -> List[Dict]:
        """前端在 404 页面停留 40.4 秒后调用"""
        self._ensure_backfill(user_id)
        newly = []
        _unlock = lambda aid: self._do_unlock(user_id, aid, newly)
        _unlock("easter_404_wait")
        return newly

    # ── 内部统计工具 ──────────────────────────────────────────────

    def _do_unlock(self, user_id: int, achievement_id: str, newly: list):
        ok, ach = self.unlock(user_id, achievement_id)
        if ok and ach:
            newly.append({
                "id":           ach["id"],
                "name":         ach["name"],
                "description":  ach["desc"],
                "rarity":       ach["rarity"],
                "rarity_name":  RARITY_NAMES.get(ach["rarity"], ""),
                "icon":         ach["icon"],
                "is_hidden":    ach["is_hidden"],
            })
        # 检查是否解锁了 10 个隐藏成就
        if ok and ach and ach.get("rarity") == "hidden":
            stats = self.get_user_stats(user_id)
            if stats["hidden_unlocked"] >= 10:
                self._do_unlock_single(user_id, "easter_egg_hunter", newly)

    def _do_unlock_single(self, user_id: int, achievement_id: str, newly: list):
        ok, ach = self.unlock(user_id, achievement_id)
        if ok and ach:
            newly.append({
                "id":          ach["id"],
                "name":         ach["name"],
                "description":  ach["desc"],
                "rarity":       ach["rarity"],
                "rarity_name":  RARITY_NAMES.get(ach["rarity"], ""),
                "icon":         ach["icon"],
                "is_hidden":    ach["is_hidden"],
            })

    def _count_action(self, user_id: int, action_type: str) -> int:
        """统计用户某类操作次数（match / analyze）"""
        # 使用 usage_logger 的数据库
        usage_db = os.path.join(os.path.dirname(self.db_path), "usage_logs.db")
        if not os.path.exists(usage_db):
            return 0
        try:
            with sqlite3.connect(usage_db) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM usage_logs WHERE user_id = ? AND action_type = ?",
                    (user_id, action_type)
                ).fetchone()
                return row["cnt"] if row else 0
        except Exception:
            return 0

    def _count_mode(self, user_id: int, mode: str) -> int:
        """统计指定模式使用次数（从 usage_logs 表）"""
        usage_db = os.path.join(os.path.dirname(self.db_path), "usage_logs.db")
        if not os.path.exists(usage_db):
            return 0
        try:
            with sqlite3.connect(usage_db) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM usage_logs WHERE user_id = ? AND action_type = 'match' AND mode = ?",
                    (user_id, mode)
                ).fetchone()
                return row["cnt"] if row else 0
        except Exception:
            return 0

    def _get_unique_industries(self, user_id: int) -> set:
        usage_db = os.path.join(os.path.dirname(self.db_path), "usage_logs.db")
        if not os.path.exists(usage_db):
            return set()
        try:
            with sqlite3.connect(usage_db) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT DISTINCT industry FROM usage_logs WHERE user_id = ? AND industry IS NOT NULL AND industry != ''",
                    (user_id,)
                ).fetchall()
                return {row["industry"] for row in rows if row["industry"]}
        except Exception:
            return set()

    def _get_unique_competitors(self, user_id: int) -> set:
        usage_db = os.path.join(os.path.dirname(self.db_path), "usage_logs.db")
        if not os.path.exists(usage_db):
            return set()
        try:
            with sqlite3.connect(usage_db) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT DISTINCT detail FROM usage_logs WHERE user_id = ? AND action_type = 'analyze' AND detail IS NOT NULL",
                    (user_id,)
                ).fetchall()
                return {row["detail"] for row in rows if row["detail"]}
        except Exception:
            return set()

    def _count_similar_demand(self, user_id: int, demand_text: str) -> int:
        """统计相似需求匹配次数（简化：同一用户相同需求文本）"""
        usage_db = os.path.join(os.path.dirname(self.db_path), "usage_logs.db")
        if not os.path.exists(usage_db):
            return 0
        try:
            with sqlite3.connect(usage_db) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM usage_logs WHERE user_id = ? AND action_type = 'match' AND detail = ?",
                    (user_id, demand_text[:200])
                ).fetchone()
                return row["cnt"] if row else 0
        except Exception:
            return 0

    def _check_all_modes(self, user_id: int, _unlock):
        """检查是否使用过全部 3 种模式"""
        usage_db = os.path.join(os.path.dirname(self.db_path), "usage_logs.db")
        if not os.path.exists(usage_db):
            return
        try:
            with sqlite3.connect(usage_db) as conn:
                # 检查 usage_logs 是否有 mode 字段
                cursor = conn.execute("PRAGMA table_info(usage_logs)")
                columns = {row[1] for row in cursor.fetchall()}
                if "mode" not in columns:
                    return
                rows = conn.execute(
                    "SELECT DISTINCT mode FROM usage_logs WHERE user_id = ? AND mode IS NOT NULL",
                    (user_id,)
                ).fetchall()
                modes = {row["mode"] for row in rows}
                if len(modes) >= 3:
                    _unlock("use_all_modes")
        except Exception:
            pass

    def _check_mode_master(self, user_id: int, _unlock):
        """检查同一天是否用完 3 种模式"""
        today = datetime.now().strftime("%Y-%m-%d")
        usage_db = os.path.join(os.path.dirname(self.db_path), "usage_logs.db")
        if not os.path.exists(usage_db):
            return
        try:
            with sqlite3.connect(usage_db) as conn:
                cursor = conn.execute("PRAGMA table_info(usage_logs)")
                columns = {row[1] for row in cursor.fetchall()}
                if "mode" not in columns:
                    return
                rows = conn.execute(
                    "SELECT DISTINCT mode FROM usage_logs WHERE user_id = ? AND DATE(created_at) = ? AND mode IS NOT NULL",
                    (user_id, today)
                ).fetchall()
                modes = {row["mode"] for row in rows}
                if len(modes) >= 3:
                    _unlock("easter_mode_master")
        except Exception:
            pass

    def _check_continuous_days(self, user_id: int, _unlock):
        """检查连续使用天数"""
        usage_db = os.path.join(os.path.dirname(self.db_path), "usage_logs.db")
        if not os.path.exists(usage_db):
            return
        try:
            with sqlite3.connect(usage_db) as conn:
                rows = conn.execute(
                    "SELECT DISTINCT DATE(created_at) as d FROM usage_logs WHERE user_id = ? ORDER BY d DESC",
                    (user_id,)
                ).fetchall()
                dates = [row["d"] for row in rows]
                if not dates:
                    return
                # 从最近一天往前数连续天数
                from datetime import timedelta
                streak = 0
                check_date = datetime.strptime(dates[0], "%Y-%m-%d").date()
                date_set = set(dates)
                while check_date.strftime("%Y-%m-%d") in date_set:
                    streak += 1
                    check_date -= timedelta(days=1)
                if streak >= 3: _unlock("match_3_day")
                if streak >= 7: _unlock("match_7_day")
        except Exception:
            pass

    def _check_perfect_week(self, user_id: int, _unlock):
        """检查完美一周：连续 7 天，每天至少使用 3 次"""
        usage_db = os.path.join(os.path.dirname(self.db_path), "usage_logs.db")
        if not os.path.exists(usage_db):
            return
        try:
            from datetime import timedelta
            with sqlite3.connect(usage_db) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """SELECT DATE(created_at) as d, COUNT(*) as cnt
                       FROM usage_logs WHERE user_id = ?
                       GROUP BY DATE(created_at)
                       ORDER BY d DESC""",
                    (user_id,)
                ).fetchall()
                if not rows:
                    return
                # 从最近一天开始，往前数连续且每天 >= 3 次的天数
                day_counts = {row["d"]: row["cnt"] for row in rows}
                check_date = datetime.strptime(rows[0]["d"], "%Y-%m-%d").date()
                perfect_streak = 0
                while check_date.strftime("%Y-%m-%d") in day_counts and day_counts[check_date.strftime("%Y-%m-%d")] >= 3:
                    perfect_streak += 1
                    check_date -= timedelta(days=1)
                if perfect_streak >= 7:
                    _unlock("perfect_week")
        except Exception:
            pass

    def _check_time_easter(self, user_id: int, _unlock):
        """检查时间类彩蛋"""
        now = datetime.now()
        month, day = now.month, now.day
        hour = now.hour

        # 愚人节 4/1
        if month == 4 and day == 1:
            _unlock("easter_april_fool")

        # 元旦 1/1 或除夕（简化：只看元旦）
        if month == 1 and day == 1:
            _unlock("easter_new_year")

        # 520
        if month == 5 and day == 20:
            _unlock("easter_520")

        # 凌晨 3-5 点（不含5点，与早起鸟区分）
        if 3 <= hour < 5:
            _unlock("easter_late_night")

        # 周五 17:00 后
        if now.weekday() == 4 and hour >= 17:
            _unlock("easter_friday_eve")

        # 中秋节（简化：农历不直接算，改为 9/29 附近，或用固定日期 9/29）
        if month == 9 and day == 29:
            _unlock("easter_mid_autumn")

        # 夜猫子（22-02 点，不含早起鸟范围）
        if hour >= 22 or hour <= 2:
            _unlock("night_owl")

        # 早起鸟（5-7 点，不含凌晨修仙范围）
        if 5 <= hour <= 7:
            _unlock("early_bird")


# ── 单例模式 ─────────────────────────────────────────────────────
_instance_lock = Lock()
_instance = None

def get_achievement_service() -> AchievementService:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = AchievementService()
    return _instance
