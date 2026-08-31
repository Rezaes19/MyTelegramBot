import sqlite3
import logging
import os

DB_PATH = "sessions.db"

def init_session_db():
    """ایجاد دیتابیس سشن‌ها"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT UNIQUE NOT NULL,
                session_string TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                first_name TEXT,
                username TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # ایندکس برای جستجوی سریع‌تر
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_id ON sessions(user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_phone ON sessions(phone)')
        
        conn.commit()
        conn.close()
        logging.info("✅ Session database initialized")
        return True
    except Exception as e:
        logging.error(f"❌ Error initializing database: {e}")
        return False

def save_session_to_db(phone: str, session_string: str, user_id: int, first_name: str = "", username: str = ""):
    """ذخیره سشن در دیتابیس"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO sessions (phone, session_string, user_id, first_name, username, is_active, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
        ''', (phone, session_string, user_id, first_name, username))
        conn.commit()
        conn.close()
        logging.info(f"✅ Session saved for {phone} (User: {user_id})")
        return True
    except Exception as e:
        logging.error(f"❌ Error saving session: {e}")
        return False

def get_all_sessions_from_db():
    """دریافت همه سشن‌های فعال از دیتابیس"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT phone, session_string, user_id, first_name, username 
            FROM sessions 
            WHERE is_active = 1
            ORDER BY created_at DESC
        ''')
        results = cursor.fetchall()
        conn.close()
        logging.info(f"✅ Loaded {len(results)} active sessions from database")
        return results
    except Exception as e:
        logging.error(f"❌ Error loading sessions: {e}")
        return []

def get_session_by_user_id(user_id: int):
    """دریافت سشن بر اساس آیدی کاربر"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT phone, session_string, user_id, first_name, username 
            FROM sessions 
            WHERE user_id = ? AND is_active = 1
        ''', (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result
    except Exception as e:
        logging.error(f"❌ Error getting session: {e}")
        return None

def delete_session_from_db(phone: str):
    """حذف سشن از دیتابیس (غیرفعال کردن)"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('UPDATE sessions SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE phone = ?', (phone,))
        conn.commit()
        conn.close()
        logging.info(f"✅ Session deactivated for {phone}")
        return True
    except Exception as e:
        logging.error(f"❌ Error deleting session: {e}")
        return False

def delete_session_by_user_id(user_id: int):
    """حذف سشن بر اساس آیدی کاربر"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('UPDATE sessions SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        logging.info(f"✅ Session deactivated for user {user_id}")
        return True
    except Exception as e:
        logging.error(f"❌ Error deleting session: {e}")
        return False

def update_session_status(phone: str, is_active: int):
    """فعال/غیرفعال کردن سشن"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('UPDATE sessions SET is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE phone = ?', (is_active, phone))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logging.error(f"❌ Error updating session: {e}")
        return False

def get_session_count():
    """تعداد سشن‌های فعال"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM sessions WHERE is_active = 1')
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except Exception as e:
        logging.error(f"❌ Error getting session count: {e}")
        return 0

def clear_inactive_sessions():
    """پاک کردن سشن‌های غیرفعال قدیمی (بیشتر از 30 روز)"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            DELETE FROM sessions 
            WHERE is_active = 0 AND datetime(updated_at) < datetime('now', '-30 days')
        ''')
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        logging.info(f"✅ Cleared {deleted} old inactive sessions")
        return deleted
    except Exception as e:
        logging.error(f"❌ Error clearing sessions: {e}")
        return 0
