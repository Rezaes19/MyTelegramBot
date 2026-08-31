import sqlite3
import logging
import os
import json

DB_PATH = "sessions.db"

def init_session_db():
    """ایجاد دیتابیس سشن‌ها"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'")
        table_exists = cursor.fetchone()
        
        if not table_exists:
            cursor.execute('''
                CREATE TABLE sessions (
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
            cursor.execute('CREATE INDEX idx_user_id ON sessions(user_id)')
            cursor.execute('CREATE INDEX idx_phone ON sessions(phone)')
            logging.info("✅ Session table created")
        else:
            logging.info("✅ Session table already exists")
        
        conn.commit()
        conn.close()
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
        logging.info(f"✅ Session saved for {phone}")
        return True
    except Exception as e:
        logging.error(f"❌ Error saving session: {e}")
        return False

def get_all_sessions_from_db():
    """دریافت سشن‌های فعال"""
    try:
        # اگه دیتابیس وجود نداره، بسازش
        if not os.path.exists(DB_PATH):
            init_session_db()
            return []
        
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
        logging.info(f"✅ Loaded {len(results)} sessions")
        return results
    except Exception as e:
        logging.error(f"❌ Error loading sessions: {e}")
        # اگه دیتابیس خراب بود، دوباره بسازش
        try:
            os.remove(DB_PATH)
            init_session_db()
        except:
            pass
        return []

def get_session_by_user_id(user_id: int):
    """دریافت سشن بر اساس آیدی"""
    try:
        if not os.path.exists(DB_PATH):
            return None
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
    """غیرفعال کردن سشن"""
    try:
        if not os.path.exists(DB_PATH):
            return False
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
    """غیرفعال کردن سشن بر اساس آیدی"""
    try:
        if not os.path.exists(DB_PATH):
            return False
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

def get_session_count():
    """تعداد سشن‌های فعال"""
    try:
        if not os.path.exists(DB_PATH):
            return 0
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
    """پاک کردن سشن‌های غیرفعال قدیمی"""
    try:
        if not os.path.exists(DB_PATH):
            return 0
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            DELETE FROM sessions 
            WHERE is_active = 0 AND datetime(updated_at) < datetime('now', '-30 days')
        ''')
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        logging.info(f"✅ Cleared {deleted} old sessions")
        return deleted
    except Exception as e:
        logging.error(f"❌ Error clearing sessions: {e}")
        return 0

def backup_sessions():
    """پشتیبان‌گیری از سشن‌ها"""
    try:
        if not os.path.exists(DB_PATH):
            return False
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM sessions WHERE is_active = 1')
        data = cursor.fetchall()
        conn.close()
        
        with open('sessions_backup.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logging.info("✅ Sessions backed up")
        return True
    except Exception as e:
        logging.error(f"❌ Backup failed: {e}")
        return False

def restore_sessions_from_backup():
    """بازیابی سشن‌ها از پشتیبان"""
    try:
        if not os.path.exists('sessions_backup.json'):
            return False
        with open('sessions_backup.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        for session in data:
            # ساختار: id, phone, session_string, user_id, first_name, username, is_active, created_at, updated_at
            if len(session) >= 5:
                phone = session[1]
                session_string = session[2]
                user_id = session[3]
                first_name = session[4] if len(session) > 4 else ""
                username = session[5] if len(session) > 5 else ""
                save_session_to_db(phone, session_string, user_id, first_name, username)
        
        logging.info(f"✅ Restored {len(data)} sessions from backup")
        return True
    except Exception as e:
        logging.error(f"❌ Restore failed: {e}")
        return False
