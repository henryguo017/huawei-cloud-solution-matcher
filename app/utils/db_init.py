import sqlite3
import os
from datetime import datetime
from app.utils.auth_utils import hash_password

def get_db_connection():
    db_path = "./data/users.db"
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
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
            token_version INTEGER DEFAULT 1
        )
    """)
    
    # 迁移：为已有数据库添加 token_version 列
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN token_version INTEGER DEFAULT 1")
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
    
    conn.commit()
    conn.close()
    
    print("[OK] Database initialized successfully")
    return True

def init_admin_user():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM users WHERE username = ?", ("admin",))
    if cursor.fetchone():
        conn.close()
        return
    
    password_hash = hash_password("admin123")
    
    cursor.execute("""
        INSERT INTO users (username, email, password_hash, role, status)
        VALUES (?, ?, ?, 'admin', 'active')
    """, ("admin", "admin@huawei.com", password_hash))
    
    conn.commit()
    conn.close()
    
    print("[OK] Default admin account created")
    print("[INFO] Username: admin, Password: admin123")
    print("[WARN] Please change default password in production!")

if __name__ == "__main__":
    init_database()
    init_admin_user()
