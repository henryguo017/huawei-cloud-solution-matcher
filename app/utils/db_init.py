import sqlite3
import os
import logging
from app.config import ADMIN_INITIAL_PASSWORD
from app.utils.auth_utils import hash_password, verify_password

logger = logging.getLogger(__name__)

def get_db_connection():
    # 使用绝对路径，防止工作目录切换导致加载错误的数据库
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    db_path = os.path.join(base_dir, "data", "users.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    # WAL 模式：读写不互斥，大幅降低并发下 "database is locked" 概率。
    # journal_mode=WAL 对数据库文件持久生效（每次执行幂等）；
    # synchronous 是连接级设置，WAL 下 NORMAL 为官方推荐档（掉电不丢库，仅可能丢最后一个事务）。
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.Error:
        pass  # PRAGMA 失败不应阻断业务连接
    return conn

def init_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'user' CHECK(role IN ('admin', 'user')),
            status TEXT DEFAULT 'active' CHECK(status IN ('active', 'inactive', 'locked')),
            created_at DATETIME DEFAULT (datetime('now', 'localtime')),
            updated_at DATETIME DEFAULT (datetime('now', 'localtime')),
            last_login TIMESTAMP,
            failed_login_count INTEGER DEFAULT 0,
            locked_until TIMESTAMP,
            token_version INTEGER DEFAULT 1,
            reset_token TEXT,
            reset_token_expiry TIMESTAMP
        )
    """)
    
    # 迁移：为已有数据库添加 token_version 列
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN token_version INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass  # 列已存在
    
    # 迁移：为已有数据库添加密码重置相关列
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN reset_token TEXT")
    except sqlite3.OperationalError:
        pass  # 列已存在
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN reset_token_expiry TIMESTAMP")
    except sqlite3.OperationalError:
        pass  # 列已存在

    # 迁移：为已有数据库添加邮箱改绑验证码相关列（待验证新邮箱 + 6位验证码 + 有效期）
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN pending_email TEXT")
    except sqlite3.OperationalError:
        pass  # 列已存在
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN email_code TEXT")
    except sqlite3.OperationalError:
        pass  # 列已存在
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN email_code_expiry TIMESTAMP")
    except sqlite3.OperationalError:
        pass  # 列已存在
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_status ON users(status)")
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            query_type TEXT NOT NULL CHECK(query_type IN ('match', 'analyze')),
            query_content TEXT NOT NULL,
            result_content TEXT,
            created_at DATETIME DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_user_id ON history(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_query_type ON history(query_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_created_at ON history(created_at)")
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            solution_name TEXT NOT NULL,
            solution_content TEXT NOT NULL,
            industry TEXT,
            created_at DATETIME DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(user_id, solution_name)
        )
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_favorites_user_id ON favorites(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_favorites_industry ON favorites(industry)")
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            preferred_industries TEXT,
            theme TEXT DEFAULT 'light',
            language TEXT DEFAULT 'zh-CN',
            created_at DATETIME DEFAULT (datetime('now', 'localtime')),
            updated_at DATETIME DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_preferences_user_id ON user_preferences(user_id)")

    # ===== 用户级 IM 通知绑定（飞书/钉钉，按账号隔离） =====
    # secret 明文存储（API 不回传原文，仅返启用态+脱敏）；DB 在自托管服务器，风险可控。
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_notify_bindings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            platform TEXT NOT NULL CHECK(platform IN ('feishu', 'dingtalk')),
            webhook TEXT NOT NULL,
            secret TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at DATETIME DEFAULT (datetime('now', 'localtime')),
            updated_at DATETIME DEFAULT (datetime('now', 'localtime')),
            UNIQUE(user_id, platform),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_notify_user_platform ON user_notify_bindings(user_id, platform)")

    # ===== 客户档案（方案B：Agent 记忆按客户维度隔离） =====
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            note TEXT,
            created_at DATETIME DEFAULT (datetime('now', 'localtime')),
            updated_at DATETIME DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(user_id, name)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_clients_user_id ON clients(user_id)")

    # 迁移：客户档案结构化字段（2026-07 客户档案升级，幂等 ALTER）
    # note 保留作「其他备注」；以下为新增结构化列
    _client_columns = [
        ("industry", "TEXT"),          # 所属行业
        ("company_size", "TEXT"),      # 企业规模
        ("region", "TEXT"),            # 所在区域
        ("contact_name", "TEXT"),      # 联系人姓名
        ("contact_title", "TEXT"),     # 联系人职位
        ("contact_phone", "TEXT"),     # 联系电话
        ("contact_email", "TEXT"),     # 联系邮箱
        ("stage", "TEXT"),             # 商机阶段（初步接触/需求调研/方案报价/商务谈判/已成交/已流失）
        ("budget", "TEXT"),            # 预算范围
        ("pain_points", "TEXT"),       # 核心痛点
        ("decision_chain", "TEXT"),    # 决策链/关键角色
        ("tags", "TEXT"),              # 标签（逗号分隔）
    ]
    for _col, _type in _client_columns:
        try:
            cursor.execute(f"ALTER TABLE clients ADD COLUMN {_col} {_type}")
        except sqlite3.OperationalError:
            pass  # 列已存在

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS captchas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            captcha_key TEXT UNIQUE NOT NULL,
            captcha_value TEXT NOT NULL,
            created_at DATETIME DEFAULT (datetime('now', 'localtime')),
            expires_at TIMESTAMP NOT NULL
        )
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_captchas_key ON captchas(captcha_key)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_captchas_expires_at ON captchas(expires_at)")
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS login_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT NOT NULL,
            ip_address TEXT,
            user_agent TEXT,
            login_status TEXT NOT NULL CHECK(login_status IN ('success', 'failed')),
            failure_reason TEXT,
            created_at DATETIME DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_login_logs_user_id ON login_logs(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_login_logs_created_at ON login_logs(created_at)")

    # ===== 阶段2：Agent 持久记忆 =====
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agent_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_memory_user ON agent_memory(user_id, session_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_memory_created ON agent_memory(created_at)")

    # Agent 会话元数据（2026-09-08 对话管理真服务端化）：标题/归档标记的服务端真身。
    # 前端 localStorage 仍作侧栏缓存，但 rename/archive/delete 双写到这里，
    # 修复"右上角管理按钮只改本地、服务端无感"的双轨问题。
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agent_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 0,
            session_id TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL DEFAULT '',
            archived INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
            updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_sessions_user ON agent_sessions(user_id, session_id)")

    # ===== 2026-09-09 跨设备历史同步（方案A'）：扩列 =====
    # 已有库 CREATE TABLE IF NOT EXISTS 不会补新列，必须 ALTER TABLE；
    # 列已存在时 ALTER 报 duplicate column，直接吞掉（幂等）。
    def _add_column(table, col, ddl):
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        except Exception:
            pass

    _add_column("agent_sessions", "cap", "TEXT NOT NULL DEFAULT ''")
    _add_column("agent_sessions", "client_id", "INTEGER")
    _add_column("agent_sessions", "client_name", "TEXT NOT NULL DEFAULT ''")
    _add_column("agent_sessions", "docs", "TEXT NOT NULL DEFAULT '[]'")
    _add_column("agent_memory", "images", "TEXT NOT NULL DEFAULT '[]'")


    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agent_memory_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP,
            archived_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_memory_archive_user ON agent_memory_archive(user_id, session_id)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_profile (
            user_id INTEGER PRIMARY KEY,
            profile_json TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # ===== P2-2：长程记忆（episodic 情景记忆） =====
    # 每次成功完成方案生成，把 (需求, 终稿摘要) 编码为向量存这里；
    # 新任务启动时用 BGE 对该用户历史记忆做余弦检索 top-k，注入 extra_context。
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agent_episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            session_id TEXT NOT NULL,
            demand TEXT NOT NULL,
            summary TEXT NOT NULL,
            embedding_json TEXT,
            client_id INTEGER,
            created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_episodes_user ON agent_episodes(user_id, created_at)")

    # 幂等迁移：老库补 client_id 列（2026-09-07 客户级记忆隔离）——必须先于下方 client_id 索引
    # 注意：不能用裸 except pass——若被其他常驻进程（IM 机器人）持锁导致 "database is locked"，
    # 静默吞掉会让 client_id 列缺失、后续 INSERT 全部失败且难排查。PRAGMA 预检 + 锁重试。
    cols = [r[1] for r in cursor.execute("PRAGMA table_info(agent_episodes)").fetchall()]
    if "client_id" not in cols:
        for _attempt in range(3):
            try:
                cursor.execute("ALTER TABLE agent_episodes ADD COLUMN client_id INTEGER")
                logger.info('[OK] agent_episodes migrated: added client_id column')
                break
            except Exception as e:
                if "duplicate column" in str(e).lower():
                    break
                logger.warning(f"[MIGRATE] agent_episodes 加列第{_attempt+1}次失败（将重试）: {e}")
                import time as _t
                _t.sleep(2)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_episodes_client ON agent_episodes(user_id, client_id)")

    # ==================== 情报订阅（定时自动化，2026-09-09） ====================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL,
            name          TEXT NOT NULL DEFAULT '',
            prompt        TEXT NOT NULL DEFAULT '',
            industry      TEXT NOT NULL DEFAULT '',
            competitors   TEXT NOT NULL DEFAULT '[]',
            frequency     TEXT NOT NULL DEFAULT 'weekly_mon_9',
            scheduled_at  TEXT,
            prompt_extra  TEXT NOT NULL DEFAULT '',
            enabled       INTEGER NOT NULL DEFAULT 1,
            channel       TEXT NOT NULL DEFAULT 'feishu',
            last_run_at   TEXT,
            next_run_at   TEXT,
            created_at    TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    # 兼容早期建表（2026-09-09 当天无 name/prompt 列的库）：幂等加列
    _sub_cols = [r[1] for r in cursor.execute("PRAGMA table_info(subscriptions)").fetchall()]
    if "name" not in _sub_cols:
        cursor.execute("ALTER TABLE subscriptions ADD COLUMN name TEXT NOT NULL DEFAULT ''")
    if "prompt" not in _sub_cols:
        cursor.execute("ALTER TABLE subscriptions ADD COLUMN prompt TEXT NOT NULL DEFAULT ''")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_subs_user ON subscriptions(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_subs_due ON subscriptions(enabled, next_run_at)")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscription_runs (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            subscription_id INTEGER NOT NULL,
            ok             INTEGER NOT NULL DEFAULT 0,
            summary        TEXT NOT NULL DEFAULT '',
            elapsed        REAL NOT NULL DEFAULT 0,
            created_at     TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_subruns_sub ON subscription_runs(subscription_id, created_at)")

    conn.commit()
    conn.close()
    
    logger.info('[OK] Database initialized successfully')
    return True

def init_admin_user():
    conn = get_db_connection()
    cursor = conn.cursor()
    admin_password = ADMIN_INITIAL_PASSWORD.strip()

    cursor.execute("SELECT id, password_hash FROM users WHERE username = ?", ("admin",))
    row = cursor.fetchone()
    if row:
        if admin_password and verify_password("admin123", row["password_hash"]):
            cursor.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (hash_password(admin_password), row["id"]),
            )
            conn.commit()
            logger.warning("[SECURITY] 已轮换默认 admin 密码")
        elif not admin_password and verify_password("admin123", row["password_hash"]):
            logger.warning("[SECURITY] admin 仍在使用默认密码，请设置 ADMIN_INITIAL_PASSWORD 后重启")
        conn.close()
        return

    if not admin_password:
        logger.warning("[SECURITY] 未设置 ADMIN_INITIAL_PASSWORD，跳过自动创建 admin")
        conn.close()
        return

    password_hash = hash_password(admin_password)
    
    cursor.execute("""
        INSERT INTO users (username, email, password_hash, role, status)
        VALUES (?, ?, ?, 'admin', 'active')
    """, ("admin", "admin@huawei.com", password_hash))
    
    conn.commit()
    conn.close()
    
    logger.info("[OK] Default admin account created")

if __name__ == "__main__":
    init_database()
    init_admin_user()
