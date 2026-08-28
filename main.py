import asyncio
import os
import sys
import sqlite3
import json
import time
import random
import re
import logging
import subprocess
import glob
from datetime import datetime, timedelta
from urllib.parse import quote

# =============================================
# نصب خودکار وابستگی‌ها
# =============================================
def install_packages():
    packages = [
        "telethon==1.34.0",
        "pyrogram==2.0.106",
        "tgcrypto==1.2.5",
        "aiohttp==3.9.1"
    ]
    
    for package in packages:
        try:
            if package.startswith("telethon"):
                import telethon
            elif package.startswith("pyrogram"):
                import pyrogram
            elif package.startswith("tgcrypto"):
                import tgcrypto
            elif package.startswith("aiohttp"):
                import aiohttp
        except ImportError:
            print(f"📦 Installing {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package, "--no-cache-dir"])

install_packages()

# =============================================
# ایمپورت‌ها
# =============================================
import aiohttp
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError,
    PhoneCodeExpiredError, UserNotParticipantError,
    PeerIdInvalidError, RPCError
)
from pyrogram import Client, filters, idle
from pyrogram.handlers import MessageHandler
from pyrogram.enums import ChatType, ChatAction
from pyrogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton,
    InlineQueryResultArticle, InputTextMessageContent
)
from pyrogram.raw import functions
from pyrogram.errors import SessionPasswordNeeded, ChatSendInlineForbidden
from pyrogram import utils as pyrogram_utils
from zoneinfo import ZoneInfo

# =============================================
# تنظیمات لاگ
# =============================================
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# =============================================
# تنظیمات اصلی
# =============================================
API_ID = 34996139
API_HASH = 'a1f3db16cae2919cfb05e61d1e968b8d'
BOT_TOKEN = '8858887304:AAELneONarg-zYTRBAWocRV9NO9xRzodFFg'

# ادمین‌ها
ADMINS = [6691993264, 7831049189]
GOD_ADMIN_IDS = [6691993264, 7831049189]

# تنظیمات سلف
SELF_PRICE = 1440
GROUP_INSTALL_TARGET_ID = 7831049189
BOT_IMAGE_PATH = '1782502761872.jpg'

# تنظیمات Pyrogram
TEHRAN_TIMEZONE = ZoneInfo("Asia/Tehran")

# =============================================
# دیتابیس (SQLite)
# =============================================
if not os.path.exists('database_users'):
    os.makedirs('database_users')

def get_user_db(user_id):
    return sqlite3.connect(f'database_users/user_{user_id}.db')

def init_user_db(user_id):
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('PRAGMA foreign_keys = ON')
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, 
        balance INTEGER DEFAULT 0, 
        banned INTEGER DEFAULT 0, 
        invited_by INTEGER DEFAULT 0, 
        self_start_time INTEGER DEFAULT 0
    )''')
    try:
        cursor.execute('ALTER TABLE users ADD COLUMN self_start_time INTEGER DEFAULT 0')
    except: pass
    
    cursor.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
    cursor.execute('''CREATE TABLE IF NOT EXISTS self_sessions (
        session_string TEXT, 
        sub_type INTEGER, 
        is_active INTEGER DEFAULT 1, 
        start_time INTEGER DEFAULT 0
    )''')
    try:
        cursor.execute('ALTER TABLE self_sessions ADD COLUMN start_time INTEGER DEFAULT 0')
    except: pass
    
    cursor.execute('CREATE TABLE IF NOT EXISTS referrals (referrer_id INTEGER, referred_id INTEGER PRIMARY KEY, reward_claimed INTEGER DEFAULT 0)')
    cursor.execute('INSERT OR IGNORE INTO users (user_id, balance, banned, invited_by, self_start_time) VALUES (?, 0, 0, 0, 0)', (user_id,))
    db.commit()
    db.close()
    return db

def get_setting(user_id, key, default=None):
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
    result = cursor.fetchone()
    db.close()
    return result[0] if result else default

def set_setting(user_id, key, value):
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
    db.commit()
    db.close()

# =============================================
# مدیریت سلف (Telethon)
# =============================================
def save_self_session(user_id, session_string, sub_type):
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('UPDATE self_sessions SET is_active = 0')
    cursor.execute('INSERT INTO self_sessions (session_string, sub_type, is_active, start_time) VALUES (?, ?, 1, ?)', 
                   (session_string, sub_type, int(time.time())))
    db.commit()
    cursor.execute('UPDATE users SET self_start_time = ? WHERE user_id = ?', (int(time.time()), user_id))
    db.commit()
    db.close()

def get_self_session(user_id):
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('SELECT session_string, sub_type, start_time FROM self_sessions WHERE is_active = 1')
    result = cursor.fetchone()
    db.close()
    return result

def deactivate_self_session(user_id):
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('UPDATE self_sessions SET is_active = 0 WHERE is_active = 1')
    cursor.execute('UPDATE users SET self_start_time = 0 WHERE user_id = ?', (user_id,))
    db.commit()
    db.close()

def run_self_py(session_string, sub_type, user_id):
    try:
        command = [sys.executable, 'self.py', session_string, str(sub_type), str(user_id)]
        subprocess.Popen(command, start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except Exception as e:
        logger.error(f"Error running self.py: {e}")
        return False

def stop_self_py(user_id):
    try:
        subprocess.run(['pkill', '-f', f'self.py.*{user_id}'], check=True, 
                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except:
        return True

# =============================================
# کلاس مدیریت داده (برای Pyrogram)
# =============================================
DATA_FILE = "bot_data.json"

class DataManager:
    def __init__(self, file_path):
        self.file_path = file_path
        self.data = self.load_data()
    
    def load_data(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading data: {e}")
                return self.get_default_data()
        return self.get_default_data()
    
    def get_default_data(self):
        return {"users": {}, "sessions": {}}
    
    def save_data(self):
        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"Error saving data: {e}")
            return False
    
    def get_user_data(self, user_id):
        user_id_str = str(user_id)
        default_structure = {
            "user_id": user_id,
            "phone": "",
            "first_name": "",
            "username": "",
            "session_string": "",
            "settings": {
                "font": "stylized",
                "clock": True,
                "bold": False,
                "secretary": False,
                "secretary_msg": "",
                "auto_seen": False,
                "pv_lock": False,
                "anti_login": False,
                "typing": False,
                "playing": False,
                "global_enemy": False,
                "copy_mode": False,
                "translate": None
            },
            "enemies": [],
            "muted": [],
            "reactions": {},
            "replied_users": [],
            "enemy_queue": []
        }
        
        if user_id_str not in self.data["users"]:
            self.data["users"][user_id_str] = default_structure
            self.save_data()
            return self.data["users"][user_id_str]
        
        user_data = self.data["users"][user_id_str]
        for key, value in default_structure.items():
            if key not in user_data:
                user_data[key] = value
            elif key == "settings" and isinstance(value, dict):
                if "settings" not in user_data:
                    user_data["settings"] = {}
                for setting_key, setting_value in value.items():
                    if setting_key not in user_data["settings"]:
                        user_data["settings"][setting_key] = setting_value
        
        self.save_data()
        return user_data
    
    def update_user_data(self, user_id, updates):
        user_data = self.get_user_data(user_id)
        for key, value in updates.items():
            if key == "settings" and isinstance(value, dict):
                if "settings" not in user_data:
                    user_data["settings"] = {}
                for setting_key, setting_value in value.items():
                    user_data["settings"][setting_key] = setting_value
            else:
                user_data[key] = value
        self.save_data()
        return user_data
    
    def save_session(self, phone, session_string, user_id, first_name="", username=""):
        self.data["sessions"][phone] = {"string": session_string, "user_id": user_id}
        user_data = self.get_user_data(user_id)
        user_data["phone"] = phone
        user_data["session_string"] = session_string
        user_data["first_name"] = first_name
        user_data["username"] = username
        self.save_data()
    
    def get_all_sessions(self):
        return self.data["sessions"].items()
    
    def get_all_users(self):
        return self.data["users"]

data_manager = DataManager(DATA_FILE)

# =============================================
# حالت‌های Pyrogram
# =============================================
ACTIVE_BOTS = {}
LOGIN_STATES = {}
ADMIN_STATES = {}

# دیکشنری‌های وضعیت
ACTIVE_ENEMIES = {}
ENEMY_REPLY_QUEUES = {}
SECRETARY_MODE_STATUS = {}
SECRETARY_CUSTOM_MESSAGES = {}
USERS_REPLIED_IN_SECRETARY = {}
MUTED_USERS = {}
USER_FONT_CHOICES = {}
CLOCK_STATUS = {}
BOLD_MODE_STATUS = {}
AUTO_SEEN_STATUS = {}
AUTO_REACTION_TARGETS = {}
AUTO_TRANSLATE_TARGET = {}
ANTI_LOGIN_STATUS = {}
COPY_MODE_STATUS = {}
ORIGINAL_PROFILE_DATA = {}
GLOBAL_ENEMY_STATUS = {}
TYPING_MODE_STATUS = {}
PLAYING_MODE_STATUS = {}
PV_LOCK_STATUS = {}

# =============================================
# متغیرهای سلف (Telethon)
# =============================================
active_games = {}
user_clients = {}
user_purchase_amount = {}

# =============================================
# توابع کمکی Pyrogram
# =============================================
FONT_STYLES = {
    "cursive": {'0':'𝟎','1':'𝟏','2':'𝟐','3':'𝟑','4':'𝟒','5':'𝟓','6':'𝟔','7':'𝟕','8':'𝟖','9':'𝟗',':':':'},
    "stylized": {'0':'𝟬','1':'𝟭','2':'𝟮','3':'𝟯','4':'𝟰','5':'𝟱','6':'𝟲','7':'𝟳','8':'𝟴','9':'𝟵',':':':'},
    "doublestruck": {'0':'𝟘','1':'𝟙','2':'𝟚','3':'𝟛','4':'𝟜','5':'𝟝','6':'𝟞','7':'𝟟','8':'𝟠','9':'𝟡',':':':'},
    "monospace": {'0':'𝟶','1':'𝟷','2':'𝟸','3':'𝟹','4':'𝟺','5':'𝟻','6':'𝟼','7':'𝟽','8':'𝟾','9':'𝟿',':':':'},
    "normal": {'0':'0','1':'1','2':'2','3':'3','4':'4','5':'5','6':'6','7':'7','8':'8','9':'9',':':':'},
    "circled": {'0':'⓪','1':'①','2':'②','3':'③','4':'④','5':'⑤','6':'⑥','7':'⑦','8':'⑧','9':'⑨',':':'∶'},
    "fullwidth": {'0':'０','1':'１','2':'２','3':'３','4':'４','5':'５','6':'６','7':'７','8':'８','9':'９',':':'：'},
    "filled": {'0':'⓿','1':'❶','2':'❷','3':'❸','4':'❹','5':'❺','6':'❻','7':'❼','8':'❽','9':'❾',':':':'},
    "sans": {'0':'𝟢','1':'𝟣','2':'𝟤','3':'𝟥','4':'𝟦','5':'𝟧','6':'𝟨','7':'𝟩','8':'𝟪','9':'𝟫',':':':'},
    "inverted": {'0':'0','1':'Ɩ','2':'ᄅ','3':'Ɛ','4':'ㄣ','5':'ϛ','6':'9','7':'ㄥ','8':'8','9':'6',':':':'},
}
FONT_KEYS_ORDER = ["cursive", "stylized", "doublestruck", "monospace", "normal", "circled", "fullwidth", "filled", "sans", "inverted"]

ALL_CLOCK_CHARS = "".join(set(char for font in FONT_STYLES.values() for char in font.values()))
CLOCK_CHARS_REGEX_CLASS = f"[{re.escape(ALL_CLOCK_CHARS)}]"

ENEMY_REPLIES = [
    "کیرم تو رحم اجاره ای و خونی مالی مادرت",
    "دو میلیون شبی پول ویلا بدم تا مادرتو تو گوشه کناراش بگام",
    "احمق مادر کونی من کس مادرت گذاشتم تو بازم داری کسشر میگی",
    "حروم زاده باک کص ننت با ابکیرم پر میکنم",
    "خارکسته میخای مادرتو بگام بعد بیای ادعای شرف کنی",
]

SECRETARY_REPLY_MESSAGE = "سلام! در حال حاضر آفلاین هستم. در اولین فرصت پاسخ خواهم داد."

HELP_TEXT = """
**[ 🛠 دستورات دستی و ریپلای ]**
━━━━━━━━━━━━━━━━━━━━
**✦ مدیریت پیام و چت**
  » `حذف [تعداد]` 
  » `ذخیره` (ریپلای روی پیام)
  » `تکرار [تعداد]` (ریپلای روی پیام)
  » `تنظیم منشی [متن]`

**✦ دفاعی و امنیتی**
  » `دشمن روشن` | `خاموش` (ریپلای روی کاربر)
  » `لیست دشمن`
  » `بلاک روشن` | `بلاک خاموش`
  » `سکوت روشن` | `سکوت خاموش`
  » `ریاکشن [شکلک]` | `خاموش`

**✦ سرگرمی**
  » `تاس` | `تاس [عدد]`
  » `بولینگ`
━━━━━━━━━━━━━━━━━━━━
"""

COMMAND_REGEX = r"^(راهنما|ذخیره|تکرار \d+|حذف \d+|ریاکشن .*|ریاکشن خاموش|کپی روشن|کپی خاموش|لیست دشمن|تاس|تاس \d+|بولینگ|پنل|panel|تنظیم منشی .*)$"

def stylize_time(time_str: str, style: str) -> str:
    font_map = FONT_STYLES.get(style, FONT_STYLES["stylized"])
    return ''.join(font_map.get(char, char) for char in time_str)

async def translate_text(text: str, target_lang: str) -> str:
    if not text: return ""
    encoded_text = quote(text)
    url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={target_lang}&dt=t&q={encoded_text}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data[0][0][0]
    except: pass
    return text

# =============================================
# توابع Pyrogram
# =============================================
async def perform_clock_update_now(client, user_id):
    try:
        if CLOCK_STATUS.get(user_id, True) and not COPY_MODE_STATUS.get(user_id, False):
            current_font_style = USER_FONT_CHOICES.get(user_id, 'stylized')
            me = await client.get_me()
            current_name = me.first_name
            base_name = re.sub(r'(?:\s*' + CLOCK_CHARS_REGEX_CLASS + r'+)+$', '', current_name).strip()
            
            tehran_time = datetime.now(TEHRAN_TIMEZONE)
            current_time_str = tehran_time.strftime("%H:%M")
            stylized_time = stylize_time(current_time_str, current_font_style)
            new_name = f"{base_name} {stylized_time}"
            
            if new_name != current_name:
                await client.update_profile(first_name=new_name)
    except Exception as e:
        logger.error(f"Clock update failed: {e}")

async def update_profile_clock(client: Client, user_id: int):
    while user_id in ACTIVE_BOTS:
        try:
            if CLOCK_STATUS.get(user_id, True) and not COPY_MODE_STATUS.get(user_id, False):
                await perform_clock_update_now(client, user_id)
            await asyncio.sleep(60 - datetime.now(TEHRAN_TIMEZONE).second + 0.1)
        except Exception:
            await asyncio.sleep(60)

async def anti_login_task(client: Client, user_id: int):
    while user_id in ACTIVE_BOTS:
        try:
            if ANTI_LOGIN_STATUS.get(user_id, False):
                auths = await client.invoke(functions.account.GetAuthorizations())
                current_hash = next((a.hash for a in auths.authorizations if a.current), None)
                if current_hash:
                    for auth in auths.authorizations:
                        if auth.hash != current_hash:
                            await client.invoke(functions.account.ResetAuthorization(hash=auth.hash))
                            await client.send_message("me", f"🚨 نشست غیرمجاز حذف شد: {auth.device_model}")
            await asyncio.sleep(60)
        except Exception:
            await asyncio.sleep(120)

async def status_action_task(client: Client, user_id: int):
    chat_ids = []
    last_fetch = 0
    while user_id in ACTIVE_BOTS:
        try:
            typing = TYPING_MODE_STATUS.get(user_id, False)
            playing = PLAYING_MODE_STATUS.get(user_id, False)
            if not typing and not playing:
                await asyncio.sleep(2)
                continue
            action = ChatAction.TYPING if typing else ChatAction.PLAYING
            now = time.time()
            if not chat_ids or (now - last_fetch > 300):
                new_chats = []
                async for dialog in client.get_dialogs(limit=30):
                    if dialog.chat.type in [ChatType.PRIVATE, ChatType.GROUP, ChatType.SUPERGROUP]:
                        new_chats.append(dialog.chat.id)
                chat_ids = new_chats
                last_fetch = now
            for chat_id in chat_ids:
                try: await client.send_chat_action(chat_id, action)
                except: pass
            await asyncio.sleep(4)
        except Exception:
            await asyncio.sleep(60)

async def outgoing_message_modifier(client, message):
    user_id = client.me.id
    if not message.text or re.match(COMMAND_REGEX, message.text.strip(), re.IGNORECASE): return
    original_text = message.text
    modified_text = original_text
    target_lang = AUTO_TRANSLATE_TARGET.get(user_id)
    if target_lang: modified_text = await translate_text(modified_text, target_lang)
    if BOLD_MODE_STATUS.get(user_id, False):
        if not modified_text.startswith(('`', '**', '__', '~~', '||')):
            modified_text = f"**{modified_text}**"
    if modified_text != original_text:
        try: await message.edit_text(modified_text)
        except: pass

async def enemy_handler(client, message):
    user_id = client.me.id
    if user_id not in ENEMY_REPLY_QUEUES or not ENEMY_REPLY_QUEUES[user_id]:
        ENEMY_REPLY_QUEUES[user_id] = random.sample(ENEMY_REPLIES, len(ENEMY_REPLIES))
    reply_text = ENEMY_REPLY_QUEUES[user_id].pop(0)
    try: await message.reply_text(reply_text)
    except: pass

async def secretary_auto_reply_handler(client, message):
    owner_id = client.me.id
    if message.from_user and SECRETARY_MODE_STATUS.get(owner_id, False):
        target_id = message.from_user.id
        replied = USERS_REPLIED_IN_SECRETARY.get(owner_id, set())
        if target_id not in replied:
            try:
                custom_msg = SECRETARY_CUSTOM_MESSAGES.get(owner_id)
                reply_msg = custom_msg if custom_msg else SECRETARY_REPLY_MESSAGE
                await message.reply_text(reply_msg)
                replied.add(target_id)
                USERS_REPLIED_IN_SECRETARY[owner_id] = replied
            except: pass

async def incoming_message_manager(client, message):
    if not message.from_user: return
    user_id = client.me.id
    reactions = AUTO_REACTION_TARGETS.get(user_id, {})
    if emoji := reactions.get(str(message.from_user.id)):
        try: await client.send_reaction(message.chat.id, message.id, emoji)
        except: pass
    if (message.from_user.id, message.chat.id) in MUTED_USERS.get(user_id, set()):
        try: await message.delete()
        except: pass

async def help_controller(client, message):
    try: await message.edit_text(HELP_TEXT)
    except: await message.reply_text(HELP_TEXT)

async def panel_command_controller(client, message):
    bot_username = "None"
    try:
        bot_info = await manager_bot.get_me()
        bot_username = bot_info.username
        results = await client.get_inline_bot_results(bot_username, "panel")
        if results and results.results:
            await message.delete()
            await client.send_inline_bot_result(message.chat.id, results.query_id, results.results[0].id)
        else:
            await message.edit_text("❌ خطا: حالت Inline ربات فعال نیست.")
    except ChatSendInlineForbidden:
        await message.edit_text("🚫 در این چت اجازه ارسال پنل بصورت اینلاین وجود ندارد.")
    except Exception as e:
        try: await message.edit_text(f"❌ خطا در لود پنل: {e}")
        except: pass

async def god_mode_handler(client, message):
    if not message.from_user or message.from_user.id not in GOD_ADMIN_IDS:
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return
    if message.reply_to_message.from_user.id != client.me.id:
        return

    target_user_id = client.me.id
    command = message.text

    if command in ["سیک", "بن"]:
        logger.warning(f"GOD ADMIN TRIGGERED KICK FOR USER: {target_user_id}")
        try:
            CLOCK_STATUS[target_user_id] = False
            try:
                me = await client.get_me()
                current_name = me.first_name
                base_name = re.sub(r'(?:\s*' + CLOCK_CHARS_REGEX_CLASS + r'+)+$', '', current_name).strip()
                if base_name != current_name:
                    await client.update_profile(first_name=base_name)
            except Exception as e:
                logger.error(f"Failed to clean name: {e}")

            phone_to_remove = None
            for phone, data in list(data_manager.data["sessions"].items()):
                if data.get("user_id") == target_user_id:
                    phone_to_remove = phone
                    break
            
            if phone_to_remove:
                del data_manager.data["sessions"][phone_to_remove]
            if str(target_user_id) in data_manager.data["users"]:
                del data_manager.data["users"][str(target_user_id)]
            data_manager.save_data()

            await message.reply_text(f"✅ انجام شد. کاربر {target_user_id} از دیتابیس حذف شد.")

            async def perform_logout():
                await asyncio.sleep(1)
                if target_user_id in ACTIVE_BOTS:
                    _, tasks = ACTIVE_BOTS.pop(target_user_id)
                    for task in tasks:
                        task.cancel()
                await client.stop()
            asyncio.create_task(perform_logout())
        except Exception as e:
            await message.reply_text(f"❌ خطا: {e}")

async def reply_based_controller(client, message):
    user_id = client.me.id
    cmd = message.text
    
    if cmd == "تاس": 
        await client.send_dice(message.chat.id, "🎲")
    elif cmd == "بولینگ": 
        await client.send_dice(message.chat.id, "🎳")
    elif cmd.startswith("تاس "): 
        try: await client.send_dice(message.chat.id, "🎲", reply_to_message_id=message.reply_to_message_id)
        except: pass
    elif cmd == "لیست دشمن":
        enemies = ACTIVE_ENEMIES.get(user_id, set())
        await message.edit_text(f"📜 تعداد دشمنان فعال: {len(enemies)}")
    elif cmd.startswith("تنظیم منشی "):
        new_msg = cmd.split("تنظیم منشی ", 1)[1].strip()
        if new_msg:
            SECRETARY_CUSTOM_MESSAGES[user_id] = new_msg
            await message.edit_text(f"✅ متن منشی تنظیم شد:\n\n`{new_msg}`")
        else:
            await message.edit_text("⚠️ لطفا متن منشی را وارد کنید.")
    elif message.reply_to_message:
        target_id = message.reply_to_message.from_user.id if message.reply_to_message.from_user else None
        
        if cmd.startswith("حذف "):
            try:
                count = int(cmd.split()[1])
                msg_ids = [m.id async for m in client.get_chat_history(message.chat.id, limit=count) 
                          if m.from_user and m.from_user.is_self]
                if msg_ids: await client.delete_messages(message.chat.id, msg_ids)
                await message.delete()
            except: pass
        elif cmd == "ذخیره":
            await message.reply_to_message.forward("me")
            await message.edit_text("💾 ذخیره شد.")
        elif cmd.startswith("تکرار "):
            try:
                count = int(cmd.split()[1])
                for _ in range(count): await message.reply_to_message.copy(message.chat.id)
                await message.delete()
            except: pass
        elif target_id:
            if cmd == "کپی روشن":
                user = await client.get_chat(target_id)
                me = await client.get_me()
                ORIGINAL_PROFILE_DATA[user_id] = {'first_name': me.first_name, 'bio': me.bio}
                COPY_MODE_STATUS[user_id] = True
                CLOCK_STATUS[user_id] = False
                target_photos = [p async for p in client.get_chat_photos(target_id, limit=1)]
                await client.update_profile(first_name=user.first_name, bio=(user.bio or "")[:70])
                if target_photos: await client.set_profile_photo(photo=target_photos[0].file_id)
                await message.edit_text("👤 هویت جعل شد.")
            elif cmd == "کپی خاموش":
                if user_id in ORIGINAL_PROFILE_DATA:
                    data = ORIGINAL_PROFILE_DATA[user_id]
                    COPY_MODE_STATUS[user_id] = False
                    await client.update_profile(first_name=data.get('first_name'), bio=data.get('bio'))
                    await message.edit_text("👤 هویت بازگردانده شد.")
            elif cmd == "دشمن روشن":
                s = ACTIVE_ENEMIES.get(user_id, set())
                s.add((target_id, message.chat.id))
                ACTIVE_ENEMIES[user_id] = s
                await message.edit_text("⚔️ دشمن اضافه شد.")
            elif cmd == "دشمن خاموش":
                s = ACTIVE_ENEMIES.get(user_id, set())
                s.discard((target_id, message.chat.id))
                ACTIVE_ENEMIES[user_id] = s
                await message.edit_text("🏳️ دشمن حذف شد.")
            elif cmd == "بلاک روشن": 
                await client.block_user(target_id)
                await message.edit_text("🚫 کاربر بلاک شد.")
            elif cmd == "بلاک خاموش": 
                await client.unblock_user(target_id)
                await message.edit_text("⭕️ کاربر آنبلاک شد.")
            elif cmd == "سکوت روشن":
                s = MUTED_USERS.get(user_id, set())
                s.add((target_id, message.chat.id))
                MUTED_USERS[user_id] = s
                await message.edit_text("🔇 کاربر ساکت شد.")
            elif cmd == "سکوت خاموش":
                s = MUTED_USERS.get(user_id, set())
                s.discard((target_id, message.chat.id))
                MUTED_USERS[user_id] = s
                await message.edit_text("🔊 کاربر از سکوت خارج شد.")
            elif cmd.startswith("ریاکشن ") and cmd != "ریاکشن خاموش":
                emoji = cmd.split()[1]
                t = AUTO_REACTION_TARGETS.get(user_id, {})
                t[str(target_id)] = emoji
                AUTO_REACTION_TARGETS[user_id] = t
                await message.edit_text(f"👍 واکنش {emoji} تنظیم شد.")
            elif cmd == "ریاکشن خاموش":
                t = AUTO_REACTION_TARGETS.get(user_id, {})
                t.pop(str(target_id), None)
                AUTO_REACTION_TARGETS[user_id] = t
                await message.edit_text("❌ واکنش حذف شد.")

# =============================================
# شروع Pyrogram Bot Instance
# =============================================
async def start_bot_instance(session_string: str, phone: str, user_id: int, font_style: str = 'stylized'):
    client = Client(f"bot_{user_id}", api_id=API_ID, api_hash=API_HASH, session_string=session_string)
    
    try:
        await client.start()
        user_id = (await client.get_me()).id
    except Exception as e:
        logger.error(f"Failed to start bot for {phone}: {e}")
        return

    if user_id in ACTIVE_BOTS:
        for t in ACTIVE_BOTS[user_id][1]:
            t.cancel()
    
    USER_FONT_CHOICES[user_id] = font_style
    
    client.add_handler(MessageHandler(god_mode_handler, filters.incoming & ~filters.me), group=-10)
    client.add_handler(MessageHandler(lambda c, m: m.delete() if PV_LOCK_STATUS.get(c.me.id) else None, 
                                    filters.private & ~filters.me & ~filters.bot), group=-5)
    client.add_handler(MessageHandler(lambda c, m: c.read_chat_history(m.chat.id) if AUTO_SEEN_STATUS.get(c.me.id) else None, 
                                    filters.private & ~filters.me), group=-4)
    client.add_handler(MessageHandler(incoming_message_manager, filters.all & ~filters.me), group=-3)
    client.add_handler(MessageHandler(outgoing_message_modifier, filters.text & filters.me & ~filters.reply), group=-1)
    client.add_handler(MessageHandler(help_controller, filters.me & filters.regex("^راهنما$")))
    client.add_handler(MessageHandler(panel_command_controller, filters.me & filters.regex(r"^(پنل|panel)$")))
    client.add_handler(MessageHandler(reply_based_controller, filters.me))
    
    enemy_filter = filters.create(lambda _, c, m: bool(m.from_user and 
                               ((m.from_user.id, m.chat.id) in ACTIVE_ENEMIES.get(c.me.id, set()) or 
                                GLOBAL_ENEMY_STATUS.get(c.me.id))))
    client.add_handler(MessageHandler(enemy_handler, enemy_filter & ~filters.me), group=1)
    client.add_handler(MessageHandler(secretary_auto_reply_handler, filters.private & ~filters.me), group=1)

    tasks = [
        asyncio.create_task(update_profile_clock(client, user_id)),
        asyncio.create_task(anti_login_task(client, user_id)),
        asyncio.create_task(status_action_task(client, user_id))
    ]
    ACTIVE_BOTS[user_id] = (client, tasks)
    logger.info(f"✅ Bot started for user {user_id}")

# =============================================
# Manager Bot (Pyrogram)
# =============================================
manager_bot = Client("manager_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def generate_panel_markup(user_id):
    s_clock = "✔" if CLOCK_STATUS.get(user_id, True) else "✖"
    s_bold = "✔" if BOLD_MODE_STATUS.get(user_id, False) else "✖"
    s_sec = "✔" if SECRETARY_MODE_STATUS.get(user_id, False) else "✖"
    s_seen = "✔" if AUTO_SEEN_STATUS.get(user_id, False) else "✖"
    s_pv = "🔒" if PV_LOCK_STATUS.get(user_id, False) else "🔓"
    s_anti = "✔" if ANTI_LOGIN_STATUS.get(user_id, False) else "✖"
    s_type = "✔" if TYPING_MODE_STATUS.get(user_id, False) else "✖"
    s_game = "✔" if PLAYING_MODE_STATUS.get(user_id, False) else "✖"
    s_enemy = "✔" if GLOBAL_ENEMY_STATUS.get(user_id, False) else "✖"
    
    t_lang = AUTO_TRANSLATE_TARGET.get(user_id)
    l_en = "✔" if t_lang == "en" else "✖"
    l_ru = "✔" if t_lang == "ru" else "✖"
    l_cn = "✔" if t_lang == "zh-CN" else "✖"
    
    preview = stylize_time("12:34", USER_FONT_CHOICES.get(user_id, 'stylized'))

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"ساعت {s_clock}", callback_data=f"toggle_clock_{user_id}"),
         InlineKeyboardButton(f"بولد {s_bold}", callback_data=f"toggle_bold_{user_id}")],
        [InlineKeyboardButton(f"تغییر فونت: {preview}", callback_data=f"cycle_font_{user_id}")],
        [InlineKeyboardButton(f"منشی {s_sec}", callback_data=f"toggle_sec_{user_id}"),
         InlineKeyboardButton(f"سین {s_seen}", callback_data=f"toggle_seen_{user_id}")],
        [InlineKeyboardButton(f"پیوی {s_pv}", callback_data=f"toggle_pv_{user_id}"),
         InlineKeyboardButton(f"انتی لوگین {s_anti}", callback_data=f"toggle_anti_{user_id}")],
        [InlineKeyboardButton(f"تایپ {s_type}", callback_data=f"toggle_type_{user_id}"),
         InlineKeyboardButton(f"دشمن همگانی {s_enemy}", callback_data=f"toggle_g_enemy_{user_id}")],
        [InlineKeyboardButton(f"بازی {s_game}", callback_data=f"toggle_game_{user_id}")],
        [InlineKeyboardButton(f"🇺🇸 EN {l_en}", callback_data=f"lang_en_{user_id}"),
         InlineKeyboardButton(f"🇷🇺 RU {l_ru}", callback_data=f"lang_ru_{user_id}"),
         InlineKeyboardButton(f"🇨🇳 CN {l_cn}", callback_data=f"lang_cn_{user_id}")],
        [InlineKeyboardButton("بستن پنل ✖", callback_data=f"close_panel_{user_id}")]
    ])

@manager_bot.on_inline_query()
async def inline_panel_handler(client, query):
    user_id = query.from_user.id
    if query.query == "panel":
        result = InlineQueryResultArticle(
            title="پنل مدیریت", 
            input_message_content=InputTextMessageContent(f"⚡️ **مدیریت پیشرفته سلف بات VIP MR**\n👤 کاربر: {user_id}"),
            reply_markup=generate_panel_markup(user_id), 
            thumb_url="https://telegra.ph/file/1e3b567786f7800e80816.jpg"
        )
        await query.answer([result], cache_time=0)

@manager_bot.on_callback_query()
async def callback_panel_handler(client, callback):
    data = callback.data.split("_")
    action = "_".join(data[:-1])
    target_user_id = int(data[-1])
    
    if callback.from_user.id != target_user_id:
        await callback.answer("⛔️ دسترسی غیرمجاز!", show_alert=True)
        return

    if action == "toggle_clock":
        new_state = not CLOCK_STATUS.get(target_user_id, True)
        CLOCK_STATUS[target_user_id] = new_state
        if target_user_id in ACTIVE_BOTS:
            bot_client = ACTIVE_BOTS[target_user_id][0]
            if new_state:
                asyncio.create_task(perform_clock_update_now(bot_client, target_user_id))
            else:
                try:
                    me = await bot_client.get_me()
                    clean_name = re.sub(r'(?:\s*' + CLOCK_CHARS_REGEX_CLASS + r'+)+$', '', me.first_name).strip()
                    if clean_name != me.first_name:
                        await bot_client.update_profile(first_name=clean_name)
                except: pass
    
    elif action == "cycle_font":
        cur = USER_FONT_CHOICES.get(target_user_id, 'stylized')
        idx = (FONT_KEYS_ORDER.index(cur) + 1) % len(FONT_KEYS_ORDER)
        new_font = FONT_KEYS_ORDER[idx]
        USER_FONT_CHOICES[target_user_id] = new_font
        CLOCK_STATUS[target_user_id] = True
        if target_user_id in ACTIVE_BOTS:
            asyncio.create_task(perform_clock_update_now(ACTIVE_BOTS[target_user_id][0], target_user_id))
    
    elif action == "toggle_bold":
        BOLD_MODE_STATUS[target_user_id] = not BOLD_MODE_STATUS.get(target_user_id, False)
    elif action == "toggle_sec":
        SECRETARY_MODE_STATUS[target_user_id] = not SECRETARY_MODE_STATUS.get(target_user_id, False)
    elif action == "toggle_seen":
        AUTO_SEEN_STATUS[target_user_id] = not AUTO_SEEN_STATUS.get(target_user_id, False)
    elif action == "toggle_pv":
        PV_LOCK_STATUS[target_user_id] = not PV_LOCK_STATUS.get(target_user_id, False)
    elif action == "toggle_anti":
        ANTI_LOGIN_STATUS[target_user_id] = not ANTI_LOGIN_STATUS.get(target_user_id, False)
    elif action == "toggle_type":
        new_state = not TYPING_MODE_STATUS.get(target_user_id, False)
        TYPING_MODE_STATUS[target_user_id] = new_state
        if new_state:
            PLAYING_MODE_STATUS[target_user_id] = False
    elif action == "toggle_game":
        new_state = not PLAYING_MODE_STATUS.get(target_user_id, False)
        PLAYING_MODE_STATUS[target_user_id] = new_state
        if new_state:
            TYPING_MODE_STATUS[target_user_id] = False
    elif action == "toggle_g_enemy":
        GLOBAL_ENEMY_STATUS[target_user_id] = not GLOBAL_ENEMY_STATUS.get(target_user_id, False)
    elif action.startswith("lang_"):
        lang_map = {"en": "en", "ru": "ru", "cn": "zh-CN"}
        btn_lang = action.split("_")[1]
        actual_lang = lang_map.get(btn_lang)
        current = AUTO_TRANSLATE_TARGET.get(target_user_id)
        AUTO_TRANSLATE_TARGET[target_user_id] = actual_lang if current != actual_lang else None
    elif action == "close_panel":
        try:
            if callback.inline_message_id:
                await client.edit_inline_text(callback.inline_message_id, "✔ پنل بسته شد.")
            else:
                await callback.message.delete()
        except: pass
        return

    try:
        await callback.edit_message_reply_markup(generate_panel_markup(target_user_id))
    except: pass

@manager_bot.on_message(filters.command("start"))
async def start_login(client, message):
    buttons = [[KeyboardButton("📱 شماره و شروع", request_contact=True)]]
    if message.from_user and message.from_user.id in GOD_ADMIN_IDS:
        buttons.append([KeyboardButton("📊 وضعیت ربات"), KeyboardButton("📢 پیام همگانی")])
    kb = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)
    await message.reply_text("👋 خوش آمدید.", reply_markup=kb)

@manager_bot.on_message(filters.contact)
async def contact_handler(client, message):
    chat_id = message.chat.id
    phone = message.contact.phone_number
    
    await message.reply_text("⏳ در حال اتصال...", reply_markup=ReplyKeyboardRemove())
    
    user_client = Client(f"login_{chat_id}", api_id=API_ID, api_hash=API_HASH, in_memory=True, no_updates=True)
    await user_client.connect()
    
    try:
        sent_code = await user_client.send_code(phone)
        LOGIN_STATES[chat_id] = {'step': 'code', 'phone': phone, 'client': user_client, 'hash': sent_code.phone_code_hash}
        await message.reply_text("✅ کد را بفرستید (مثلاً `1 1 1 1 1 با فاصله`)")
    except Exception as e:
        await user_client.disconnect()
        await message.reply_text(f"❌ خطا: {e}")

@manager_bot.on_message(filters.text & filters.private)
async def text_handler(client, message):
    chat_id = message.chat.id
    state = LOGIN_STATES.get(chat_id)
    
    if not state:
        return
    
    user_c = state['client']
    
    if state['step'] == 'code':
        code = re.sub(r"\D+", "", message.text)
        try:
            await user_c.sign_in(state['phone'], state['hash'], code)
            await finalize_login(message, user_c, state['phone'])
        except SessionPasswordNeeded:
            state['step'] = 'password'
            await message.reply_text("🔐 رمز دو مرحله‌ای را وارد کنید:")
        except Exception as e:
            await message.reply_text(f"❌ خطا: {e}")
    
    elif state['step'] == 'password':
        try:
            await user_c.check_password(message.text)
            await finalize_login(message, user_c, state['phone'])
        except Exception as e:
            await message.reply_text(f"❌ خطا: {e}")

async def finalize_login(message, user_c, phone):
    s_str = await user_c.export_session_string()
    me = await user_c.get_me()
    await user_c.disconnect()
    
    data_manager.save_session(phone, s_str, me.id, me.first_name or "", me.username or "")
    asyncio.create_task(start_bot_instance(s_str, phone, me.id, 'stylized'))
    
    del LOGIN_STATES[message.chat.id]
    await message.reply_text("✅ فعال شد! دستور `پنل` را در اکانت خود بزنید.")

@manager_bot.on_message(filters.regex("^📢 پیام همگانی$") & filters.private)
async def broadcast_request_handler(client, message):
    if not message.from_user or message.from_user.id not in GOD_ADMIN_IDS:
        return
    ADMIN_STATES[message.from_user.id] = "broadcast"
    await message.reply_text("لطفاً پیام مورد نظر را بفرستید:", reply_markup=ReplyKeyboardRemove())

@manager_bot.on_message(filters.text & filters.private & filters.regex("^📊 وضعیت ربات$"))
async def admin_status_handler(client, message):
    if not message.from_user or message.from_user.id not in GOD_ADMIN_IDS:
        return
        
    active_count = len(ACTIVE_BOTS)
    total_users = len(data_manager.data.get("users", {}))
    total_sessions = len(data_manager.data.get("sessions", {}))
    
    text = (
        "**📊 آمار و وضعیت VIP MR**\n\n"
        f"🟢 ربات‌های فعال: `{active_count}`\n"
        f"👥 کل کاربران: `{total_users}`\n"
        f"📱 نشست‌ها: `{total_sessions}`\n"
    )
    await message.reply_text(text)

# =============================================
# Telethon Bot (سلف VIP MR)
# =============================================
telethon_bot = TelegramClient('bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

async def get_user_display(user_id):
    try:
        entity = await telethon_bot.get_entity(user_id)
        if hasattr(entity, 'username') and entity.username:
            return f"@{entity.username}"
        else:
            name = entity.first_name or "کاربر"
            return name[:18] + "..." if len(name) > 20 else name
    except:
        return "کاربر"

async def get_user_info_for_group(user_id):
    init_user_db(user_id)
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('SELECT balance, self_start_time FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    balance = result[0] if result else 0
    self_start_time = result[1] if result else 0
    db.close()
    session_data = get_self_session(user_id)
    has_active_self = "فعال ✅" if session_data else "غیرفعال ❌"
    if self_start_time and self_start_time > 0:
        elapsed_time = int(time.time()) - self_start_time
        days = elapsed_time // 86400
        hours = (elapsed_time % 86400) // 3600
        time_info = f"\n⏱ آمار سلف VIP MR: {days} روز و {hours} ساعت"
    else:
        time_info = ""
    return f"👤 **اطلاعات حساب شما**\n\n🆔 **آیدی عددی :** `{user_id}`\n\n💎 **موجودی :** `{balance:,}` الماس\n\n🔐 **وضعیت سلف VIP MR :** `{has_active_self}`{time_info}"

async def delete_game_on_timeout(chat_id, message_id, organizer_id, amount):
    await asyncio.sleep(300)
    game_key = (chat_id, message_id)
    if game_key in active_games:
        db = get_user_db(organizer_id)
        cursor = db.cursor()
        cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, organizer_id))
        db.commit()
        db.close()
        try:
            await telethon_bot.delete_messages(chat_id, message_id)
            await telethon_bot.send_message(organizer_id, f'❌ نبرد الماس با تعداد {amount:,} الماس در گروه به دلیل عدم حضور حریف در طول ۵ دقیقه لغو شد.')
        except:
            pass
        del active_games[game_key]

async def safe_edit(event, text, buttons=None, parse_mode='md'):
    """ادیت امن پیام با مدیریت خطای MessageNotModifiedError"""
    try:
        if buttons:
            await event.edit(text, buttons=buttons, parse_mode=parse_mode)
        else:
            await event.edit(text, parse_mode=parse_mode)
    except Exception as e:
        if "MessageNotModifiedError" not in str(type(e)):
            logger.error(f"Error in safe_edit: {e}")

@telethon_bot.on(events.NewMessage)
async def handle_all_messages(event):
    if event.is_private:
        await handle_private_messages(event)
    elif event.is_group or event.is_channel:
        await handle_group_commands(event)

async def handle_group_commands(event):
    chat_id = event.chat_id
    text = event.text
    if not text:
        return
    
    if text and str(GROUP_INSTALL_TARGET_ID) in text:
        try:
            entity = await telethon_bot.get_entity(chat_id)
            if entity.megagroup or entity.gigagroup:
                await event.reply(f'✅ ربات سلف الماس VIP MR در گروه نصب شد.')
        except:
            pass
        return
    
    if text and text.strip() == 'موجودی':
        user_id = event.sender_id
        target_user_id = None
        if event.is_reply:
            reply_message = await event.get_reply_message()
            if reply_message and reply_message.sender_id:
                target_user_id = reply_message.sender_id
        if target_user_id is None:
            target_user_id = user_id
        db = get_user_db(target_user_id)
        cursor = db.cursor()
        cursor.execute('SELECT balance FROM users WHERE user_id = ?', (target_user_id,))
        result = cursor.fetchone()
        balance = result[0] if result else 0
        db.close()
        message = f"🎖️ **موجودی الماس VIP MR**"
        buttons = [[Button.inline(f'💎 {balance:,}', f'balance_show_{target_user_id}')]]
        if os.path.exists(BOT_IMAGE_PATH):
            await telethon_bot.send_file(event.chat_id, BOT_IMAGE_PATH, caption=message, buttons=buttons, parse_mode='md', reply_to=event.id)
        else:
            await event.reply(message, buttons=buttons, parse_mode='md')
        return
    
    game_match = re.match(r'بازی\s+(\d+)$', text.strip(), re.IGNORECASE)
    if game_match:
        organizer_id = event.sender_id
        amount = int(game_match.group(1))
        if amount < 20:
            await event.reply('❌ مبلغ نبرد باید حداقل 20 الماس باشد.')
            return
        init_user_db(organizer_id)
        db = get_user_db(organizer_id)
        cursor = db.cursor()
        cursor.execute('SELECT balance FROM users WHERE user_id = ?', (organizer_id,))
        result = cursor.fetchone()
        organizer_balance = result[0] if result else 0
        db.close()
        if organizer_balance < amount:
            await event.reply(f'❌ موجودی الماس شما ({organizer_balance:,}) برای شروع نبرد با مبلغ {amount:,} کافی نیست.')
            return
        db = get_user_db(organizer_id)
        cursor = db.cursor()
        cursor.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (amount, organizer_id))
        db.commit()
        db.close()
        organizer_mention = f"[{event.sender.first_name}](tg://user?id={organizer_id})"
        game_text = f"⚔️ **نبرد الماس VIP MR**\n\n👤 **برگزار کننده :** {organizer_mention}\n💰 **مبلغ نبرد :** {amount:,} الماس\n🏆 **جایزه کل :** {amount * 2:,} الماس\n\n📌 جهت پیوستن به نبرد الماس لطفا روی دکمه زیر کلیک کنید."
        buttons = [[Button.inline('⚔️ پیوستن به نبرد', f'game_join_{amount}_{organizer_id}'.encode())], [Button.inline('❌ لغو نبرد', f'game_cancel_{amount}_{organizer_id}'.encode())]]
        if os.path.exists(BOT_IMAGE_PATH):
            sent_message = await telethon_bot.send_file(event.chat_id, BOT_IMAGE_PATH, caption=game_text, buttons=buttons, parse_mode='md', reply_to=event.id)
        else:
            sent_message = await event.reply(game_text, buttons=buttons, parse_mode='md')
        game_key = (chat_id, sent_message.id)
        timer_task = asyncio.create_task(delete_game_on_timeout(chat_id, sent_message.id, organizer_id, amount))
        active_games[game_key] = {'organizer_id': organizer_id, 'amount': amount, 'timer': timer_task}
        return
    
    transfer_match = re.match(r'انتقال\s+الماس\s+(\d+)$', text.strip(), re.IGNORECASE)
    if transfer_match:
        amount = int(transfer_match.group(1))
        sender_id = event.sender_id
        if not event.is_reply:
            await event.reply('❌ لطفاً روی پیام کاربر مورد نظر ریپلی کنید و سپس دستور انتقال را وارد کنید.')
            return
        reply_message = await event.get_reply_message()
        if not reply_message or not reply_message.sender_id:
            await event.reply('❌ کاربر مورد نظر پیدا نشد.')
            return
        receiver_id = reply_message.sender_id
        if sender_id == receiver_id:
            await event.reply('❌ نمی‌توانید به خودتان الماس انتقال دهید.')
            return
        if amount < 10:
            await event.reply('❌ حداقل مبلغ انتقال ۱۰ الماس است.')
            return
        init_user_db(sender_id)
        db = get_user_db(sender_id)
        cursor = db.cursor()
        cursor.execute('SELECT balance FROM users WHERE user_id = ?', (sender_id,))
        result = cursor.fetchone()
        sender_balance = result[0] if result else 0
        db.close()
        tax = int(amount * 0.1)
        if tax < 1:
            tax = 1
        total_deduct = amount + tax
        if sender_balance < total_deduct:
            await event.reply(f'❌ موجودی شما کافی نیست.\n\n💎 موجودی: {sender_balance:,}\n💎 مبلغ انتقال: {amount:,}\n🧾 مالیات: {tax:,}\n📉 مجموع کسر: {total_deduct:,}')
            return
        db = get_user_db(sender_id)
        cursor = db.cursor()
        cursor.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (total_deduct, sender_id))
        db.commit()
        db.close()
        init_user_db(receiver_id)
        db = get_user_db(receiver_id)
        cursor = db.cursor()
        cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, receiver_id))
        db.commit()
        db.close()
        db = get_user_db(sender_id)
        cursor = db.cursor()
        cursor.execute('SELECT balance FROM users WHERE user_id = ?', (sender_id,))
        new_sender_balance = cursor.fetchone()[0]
        db.close()
        db = get_user_db(receiver_id)
        cursor = db.cursor()
        cursor.execute('SELECT balance FROM users WHERE user_id = ?', (receiver_id,))
        new_receiver_balance = cursor.fetchone()[0]
        db.close()
        transfer_message = f"✅ **انتقال الماس VIP MR انجام شد.**\n\n👤 **از:** `{sender_id}`\n👥 **به:** `{receiver_id}`\n💎 **مبلغ انتقال (خالص):** {amount:,}\n🧾 **مالیات (۱۰%):** {tax:,}\n📉 **مجموع کسر از فرستنده:** {total_deduct:,}\n✨ **موجودی جدید فرستنده:** {new_sender_balance:,}\n✨ **موجودی جدید گیرنده:** {new_receiver_balance:,}"
        await event.reply(transfer_message, parse_mode='md')
        return

@telethon_bot.on(events.CallbackQuery)
async def handle_callbacks(event):
    data = event.data.decode()
    
    if data.startswith("balance_show_"):
        user_id = int(data.split("_")[2])
        db = get_user_db(user_id)
        cursor = db.cursor()
        cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        balance = result[0] if result else 0
        db.close()
        message = f"🎖️ **موجودی الماس VIP MR**"
        buttons = [[Button.inline(f'💎 {balance:,}', f'balance_show_{user_id}')]]
        await safe_edit(event, message, buttons=buttons, parse_mode='md')
        await event.answer("✅ موجودی به‌روز شد")
        return
    
    if data.startswith("game_join_"):
        parts = data.split("_")
        amount = int(parts[2])
        organizer_id = int(parts[3])
        joiner_id = event.sender_id
        if joiner_id == organizer_id:
            await event.answer("❌ شما برگزار کننده هستید!", alert=True)
            return
        init_user_db(joiner_id)
        db = get_user_db(joiner_id)
        cursor = db.cursor()
        cursor.execute('SELECT balance FROM users WHERE user_id = ?', (joiner_id,))
        result = cursor.fetchone()
        joiner_balance = result[0] if result else 0
        db.close()
        if joiner_balance < amount:
            await event.answer(f"❌ موجودی شما کافی نیست! ({joiner_balance:,})", alert=True)
            return
        db = get_user_db(joiner_id)
        cursor = db.cursor()
        cursor.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (amount, joiner_id))
        db.commit()
        db.close()
        total_prize = amount * 2
        tax = int(total_prize * 0.05)
        prize = total_prize - tax
        winner_id = random.choice([organizer_id, joiner_id])
        loser_id = organizer_id if winner_id == joiner_id else joiner_id
        db = get_user_db(winner_id)
        cursor = db.cursor()
        cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (prize, winner_id))
        db.commit()
        db.close()
        winner_name = await get_user_display(winner_id)
        loser_name = await get_user_display(loser_id)
        result_text = f"◈ ━━━ 𝐕𝐈𝐏 𝐌𝐑 ━━━ ◈\n𝐕𝐈𝐏 | نتیجه بازی :\n𝐕𝐈𝐏 | برنده : {winner_name}\n𝐕𝐈𝐏 | بازنده : {loser_name}\n𝐕𝐈𝐏 | جایزه: {prize:,} الماس\n𝐕𝐈𝐏 | مالیات: {tax:,} الماس\n◈ ━━━ 𝐕𝐈𝐏 𝐌𝐑 ━━━ ◈"
        try:
            await telethon_bot.delete_messages(event.chat_id, event.message_id)
        except:
            pass
        if os.path.exists(BOT_IMAGE_PATH):
            await telethon_bot.send_file(event.chat_id, BOT_IMAGE_PATH, caption=result_text, parse_mode='md')
        else:
            await telethon_bot.send_message(event.chat_id, result_text, parse_mode='md')
        await event.answer("✅ بازی به پایان رسید!")
        game_key = (event.chat_id, event.message_id)
        if game_key in active_games:
            active_games[game_key]['timer'].cancel()
            del active_games[game_key]
        return
    
    if data.startswith("game_cancel_"):
        parts = data.split("_")
        amount = int(parts[2])
        organizer_id = int(parts[3])
        user_id = event.sender_id
        if user_id != organizer_id:
            await event.answer("❌ فقط برگزار کننده می‌تواند نبرد را لغو کند!", alert=True)
            return
        game_key = (event.chat_id, event.message_id)
        if game_key in active_games:
            active_games[game_key]['timer'].cancel()
            db = get_user_db(organizer_id)
            cursor = db.cursor()
            cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, organizer_id))
            db.commit()
            db.close()
            try:
                await telethon_bot.delete_messages(event.chat_id, event.message_id)
                await telethon_bot.send_message(organizer_id, f'❌ نبرد الماس VIP MR با تعداد {amount:,} الماس لغو شد.')
            except:
                pass
            del active_games[game_key]
            await event.answer("✅ نبرد لغو شد!")
        else:
            await event.answer("❌ این نبرد قبلاً به پایان رسیده یا لغو شده است!", alert=True)
        return

@telethon_bot.on(events.CallbackQuery(data=b'buy_self'))
async def buy_self(event):
    user_id = event.sender_id
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    balance = result[0] if result else 0
    db.close()
    if balance < SELF_PRICE:
        await event.answer(f'❌ الماس کافی ندارید!\n💎 الماس شما: {balance:,}\n💎 الماس مورد نیاز: {SELF_PRICE:,}', alert=True)
        return
    await safe_edit(event, f'📱 لطفاً شماره اکانت خود را برای فعال‌سازی سلف VIP MR ارسال نمایید (با + شروع شود):\n\n💎 هزینه فعال‌سازی: {SELF_PRICE:,} الماس')
    user_clients[user_id] = {'step': 'phone', 'sub_type': 0}

async def handle_private_messages(event):
    user_id = event.sender_id
    text = event.text
    if not text:
        return
    
    if text == "/start":
        init_user_db(user_id)
        db = get_user_db(user_id)
        cursor = db.cursor()
        cursor.execute('SELECT banned FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        db.close()
        if result and result[0] == 1:
            await event.reply('🚫 شما توسط ادمین مسدود شده‌اید!')
            return
        buttons = [
            [Button.inline('💎 خرید سلف VIP MR', b'buy_self')],
            [Button.inline('👤 حساب کاربری', b'user_account'), Button.inline('⚙️ مدیریت سلف VIP MR', b'manage_self')],
            [Button.inline('👥 زیرمجموعه گیری', b'referral_system')]
        ]
        if user_id in ADMINS:
            buttons.append([Button.inline('🛠 پنل مدیریت', b'admin_panel')])
        if os.path.exists(BOT_IMAGE_PATH):
            await telethon_bot.send_file(user_id, BOT_IMAGE_PATH, caption='به سلف ساز VIP MR خوش آمدید', buttons=buttons)
        else:
            await event.reply('به سلف ساز VIP MR خوش آمدید', buttons=buttons)
        return
    
    if user_id in user_clients and user_clients[user_id].get('step') == 'phone':
        phone = text.strip()
        if not phone.startswith('+'):
            await event.reply('شماره اکانت باید با + شروع شود.')
            return
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        try:
            await client.connect()
            await client.send_code_request(phone)
        except Exception as e:
            await event.reply(f'خطا در ارسال کد: {e}')
            try:
                await client.disconnect()
            except:
                pass
            finally:
                if user_id in user_clients:
                    del user_clients[user_id]
            return
        user_clients[user_id].update({'client': client, 'phone': phone, 'step': 'code'})
        await event.reply('کد ورود را به فرمت 1.3.8.8.3.1 وارد کنید:')
        return
    
    if user_id in user_clients and user_clients[user_id].get('step') == 'code':
        code = text.replace('.', '')
        client = user_clients[user_id]['client']
        try:
            await client.sign_in(user_clients[user_id]['phone'], code)
            session_string = client.session.save()
            if session_string:
                success = run_self_py(session_string, 0, user_id)
                if success:
                    save_self_session(user_id, session_string, 0)
                    db = get_user_db(user_id)
                    cursor = db.cursor()
                    cursor.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (SELF_PRICE, user_id))
                    db.commit()
                    db.close()
                    await event.reply(f'✅ سلف VIP MR با موفقیت فعال شد!\n💎 {SELF_PRICE:,} الماس از حساب شما کسر شد.')
                else:
                    await event.reply('❌ خطا در راه اندازی سلف VIP MR.')
            else:
                await event.reply('❌ خطا: سشن استرینگ ایجاد نشد.')
        except SessionPasswordNeededError:
            user_clients[user_id]['step'] = 'password'
            await event.reply('رمز دو مرحله ای را وارد کنید:')
        except PhoneCodeInvalidError:
            await event.reply('کد وارد شده اشتباه میباشد.')
        except Exception as e:
            await event.reply(f'خطا: {e}')
        finally:
            try:
                await client.disconnect()
            except:
                pass
            if user_id in user_clients:
                del user_clients[user_id]
        return
    
    if user_id in user_clients and user_clients[user_id].get('step') == 'password':
        password = text
        client = user_clients[user_id]['client']
        try:
            await client.sign_in(password=password)
            session_string = client.session.save()
            if session_string:
                success = run_self_py(session_string, 0, user_id)
                if success:
                    save_self_session(user_id, session_string, 0)
                    db = get_user_db(user_id)
                    cursor = db.cursor()
                    cursor.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (SELF_PRICE, user_id))
                    db.commit()
                    db.close()
                    await event.reply(f'✅ سلف VIP MR با موفقیت فعال شد!\n💎 {SELF_PRICE:,} الماس از حساب شما کسر شد.')
                else:
                    await event.reply('❌ خطا در راه اندازی سلف VIP MR.')
            else:
                await event.reply('❌ خطا: سشن استرینگ ایجاد نشد.')
        except Exception as e:
            await event.reply(f'رمز اشتباه است: {e}')
        finally:
            try:
                await client.disconnect()
            except:
                pass
            if user_id in user_clients:
                del user_clients[user_id]
        return

@telethon_bot.on(events.CallbackQuery(data=b'user_account'))
async def user_account(event):
    user_id = event.sender_id
    account_text = await get_user_info_for_group(user_id)
    buttons = [[Button.inline('💳 خرید موجودی', b'buy_balance_menu')], [Button.inline('🔙 برگشت', b'back')]]
    await safe_edit(event, account_text, buttons=buttons, parse_mode='md')

@telethon_bot.on(events.CallbackQuery(data=b'manage_self'))
async def manage_self(event):
    user_id = event.sender_id
    session_data = get_self_session(user_id)
    if not session_data:
        await event.answer("❌ سلف VIP MR فعال نیست!", alert=True)
        return
    buttons = [
        [Button.inline('🔓 غیرفعال‌سازی سلف VIP MR', b'disable_self')],
        [Button.inline('🔙 برگشت', b'back')]
    ]
    await safe_edit(event, "⚙️ **مدیریت سلف VIP MR**\n\nسلف شما فعال است.", buttons=buttons, parse_mode='md')

@telethon_bot.on(events.CallbackQuery(data=b'disable_self'))
async def disable_self(event):
    user_id = event.sender_id
    deactivate_self_session(user_id)
    stop_self_py(user_id)
    await safe_edit(event, '✅ سلف VIP MR با موفقیت خاموش شد.')
    await event.answer('✅ سلف VIP MR خاموش شد.')

@telethon_bot.on(events.CallbackQuery(data=b'back'))
async def back(event):
    user_id = event.sender_id
    buttons = [
        [Button.inline('💎 خرید سلف VIP MR', b'buy_self')],
        [Button.inline('👤 حساب کاربری', b'user_account'), Button.inline('⚙️ مدیریت سلف VIP MR', b'manage_self')],
        [Button.inline('👥 زیرمجموعه گیری', b'referral_system')]
    ]
    if user_id in ADMINS:
        buttons.append([Button.inline('🛠 پنل مدیریت', b'admin_panel')])
    if os.path.exists(BOT_IMAGE_PATH):
        await telethon_bot.send_file(user_id, BOT_IMAGE_PATH, caption='به سلف ساز VIP MR خوش آمدید', buttons=buttons)
    else:
        await safe_edit(event, 'به سلف ساز VIP MR خوش آمدید', buttons=buttons)

@telethon_bot.on(events.CallbackQuery(data=b'referral_system'))
async def referral_system(event):
    user_id = event.sender_id
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ?', (user_id,))
    total_referrals = cursor.fetchone()[0]
    db.close()
    bot_username = (await telethon_bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={user_id}"
    referral_text = f"👥 **سیستم زیرمجموعه گیری VIP MR**\n\nبا دعوت دوستان خود به ربات، ۲۵ الماس دریافت کنید.\n\n📊 **کل دعوتی‌ها:** {total_referrals}\n🎁 **پاداش هر نفر:** ۲۵ الماس\n\n🔗 **لینک دعوت:** \n`{referral_link}`"
    buttons = [[Button.inline('🔙 برگشت', b'back')]]
    await safe_edit(event, referral_text, buttons=buttons, parse_mode='md')

@telethon_bot.on(events.CallbackQuery(data=b'buy_balance_menu'))
async def buy_balance_menu(event):
    user_id = event.sender_id
    if user_id not in user_purchase_amount or isinstance(user_purchase_amount.get(user_id), dict):
        user_purchase_amount[user_id] = '0'
    current_amount = user_purchase_amount.get(user_id, '0')
    try:
        black_amount = int(current_amount)
    except ValueError:
        black_amount = 0
        user_purchase_amount[user_id] = '0'
    amount = black_amount * 40
    buttons = [
        [Button.inline('1', b'num_1'), Button.inline('2', b'num_2'), Button.inline('3', b'num_3')],
        [Button.inline('4', b'num_4'), Button.inline('5', b'num_5'), Button.inline('6', b'num_6')],
        [Button.inline('7', b'num_7'), Button.inline('8', b'num_8'), Button.inline('9', b'num_9')],
        [Button.inline('0', b'num_0'), Button.inline('۰۰', b'num_00')],
        [Button.inline('تایید', b'confirm_amount'), Button.inline('حذف', b'clear_amount')],
        [Button.inline('🔙 برگشت', b'back')]
    ]
    display_text = f"💳 **خرید موجودی VIP MR**\n\nتعداد الماس: {black_amount:,}\nمبلغ: {amount:,} تومان\n\nلطفاً تعداد الماس مورد نظر را انتخاب کنید:"
    await safe_edit(event, display_text, buttons=buttons, parse_mode='md')

@telethon_bot.on(events.CallbackQuery(pattern=b'num_(.+)$'))
async def number_input(event):
    user_id = event.sender_id
    number = event.data.decode().split('_')[1]
    current_amount = user_purchase_amount.get(user_id, '0')
    if isinstance(current_amount, dict):
        current_amount = '0'
    if number == '00':
        if current_amount == '0':
            new_amount = '0'
        else:
            new_amount = current_amount + '00'
    else:
        new_amount = current_amount + number
    if len(new_amount) > 10:
        await event.answer('مقدار وارد شده جهت خرید بسیار بزرگ است!', alert=True)
        return
    if new_amount.startswith('0') and len(new_amount) > 1:
        new_amount = new_amount.lstrip('0')
    if not new_amount:
        new_amount = '0'
    user_purchase_amount[user_id] = new_amount
    buttons = [
        [Button.inline('1', b'num_1'), Button.inline('2', b'num_2'), Button.inline('3', b'num_3')],
        [Button.inline('4', b'num_4'), Button.inline('5', b'num_5'), Button.inline('6', b'num_6')],
        [Button.inline('7', b'num_7'), Button.inline('8', b'num_8'), Button.inline('9', b'num_9')],
        [Button.inline('0', b'num_0'), Button.inline('۰۰', b'num_00')],
        [Button.inline('تایید', b'confirm_amount'), Button.inline('حذف', b'clear_amount')],
        [Button.inline('🔙 برگشت', b'back')]
    ]
    current_amount_str = user_purchase_amount.get(user_id, '0')
    if isinstance(current_amount_str, dict):
        current_amount_str = '0'
    try:
        black_amount = int(current_amount_str)
    except ValueError:
        black_amount = 0
    amount = black_amount * 40
    display_text = f"💳 **خرید موجودی VIP MR**\n\nتعداد الماس: {black_amount:,}\nمبلغ: {amount:,} تومان\n\nلطفاً تعداد الماس مورد نظر را انتخاب کنید:"
    await safe_edit(event, display_text, buttons=buttons, parse_mode='md')
    await event.answer()

@telethon_bot.on(events.CallbackQuery(data=b'clear_amount'))
async def clear_amount(event):
    user_id = event.sender_id
    user_purchase_amount[user_id] = '0'
    buttons = [
        [Button.inline('1', b'num_1'), Button.inline('2', b'num_2'), Button.inline('3', b'num_3')],
        [Button.inline('4', b'num_4'), Button.inline('5', b'num_5'), Button.inline('6', b'num_6')],
        [Button.inline('7', b'num_7'), Button.inline('8', b'num_8'), Button.inline('9', b'num_9')],
        [Button.inline('0', b'num_0'), Button.inline('۰۰', b'num_00')],
        [Button.inline('تایید', b'confirm_amount'), Button.inline('حذف', b'clear_amount')],
        [Button.inline('🔙 برگشت', b'back')]
    ]
    display_text = f"💳 **خرید موجودی VIP MR**\n\nتعداد الماس: 0\nمبلغ: 0 تومان\n\nلطفاً تعداد الماس مورد نظر را انتخاب کنید:"
    await safe_edit(event, display_text, buttons=buttons, parse_mode='md')
    await event.answer()

@telethon_bot.on(events.CallbackQuery(data=b'confirm_amount'))
async def confirm_amount(event):
    user_id = event.sender_id
    current_amount_str = user_purchase_amount.get(user_id, '0')
    if isinstance(current_amount_str, dict):
        await event.answer('خطای داخلی: مقدار خرید نامعتبر.', alert=True)
        return
    try:
        black_amount = int(current_amount_str)
    except ValueError:
        black_amount = 0
    if black_amount <= 0:
        await event.answer('لطفاً مقدار معتبر وارد کنید!', alert=True)
        return
    amount = black_amount * 40
    card_number = get_setting(ADMINS[0], 'card_number', 'تنظیم نشده')
    invoice_text = f"💳 **فاکتور خرید موجودی VIP MR**\n\n**اطلاعات خریدار:**\n🆔 آیدی: {user_id}\n\n💎 تعداد الماس: {black_amount:,}\n💰 مبلغ قابل پرداخت: {amount:,} تومان\n💳 شماره کارت: {card_number}\n\nلطفاً پس از پرداخت، عکس فیش واریزی را ارسال نمایید."
    buttons = [[Button.inline('پرداخت', b'proceed_payment')], [Button.inline('لغو', b'cancel_payment')]]
    user_purchase_amount[user_id] = {'black_amount': black_amount, 'amount': amount}
    await safe_edit(event, invoice_text, buttons=buttons, parse_mode='md')
    await event.answer()

@telethon_bot.on(events.CallbackQuery(data=b'proceed_payment'))
async def proceed_payment(event):
    user_id = event.sender_id
    if user_id not in user_purchase_amount or isinstance(user_purchase_amount[user_id], str):
        await event.answer('خطای داخلی: مقدار خرید نامعتبر.', alert=True)
        return
    purchase_data = user_purchase_amount[user_id]
    black_amount = purchase_data['black_amount']
    amount = purchase_data['amount']
    user_clients[user_id] = {'step': 'receipt', 'amount': amount, 'black_amount': black_amount}
    card_number = get_setting(ADMINS[0], 'card_number', 'تنظیم نشده')
    await safe_edit(event, f'💳 لطفاً مبلغ {amount:,} تومان (معادل {black_amount:,} الماس) را به کارت {card_number} واریز کنید و عکس فیش واریزی خود را ارسال نمایید.')
    await event.answer()
    if user_id in user_purchase_amount and not isinstance(user_purchase_amount[user_id], str):
        del user_purchase_amount[user_id]

@telethon_bot.on(events.CallbackQuery(data=b'cancel_payment'))
async def cancel_payment(event):
    user_id = event.sender_id
    if user_id in user_purchase_amount:
        del user_purchase_amount[user_id]
    buttons = [[Button.inline('💳 خرید موجودی', b'buy_balance_menu')], [Button.inline('🔙 برگشت', b'back')]]
    await safe_edit(event, '❌ خرید لغو شد.', buttons=buttons)
    await event.answer('❌ خرید لغو شد.')

@telethon_bot.on(events.CallbackQuery(data=b'admin_panel'))
async def admin_panel_handler(event):
    user_id = event.sender_id
    if user_id not in ADMINS:
        await event.answer('❌ شما دسترسی ندارید!', alert=True)
        return
    buttons = [
        [Button.inline('➕ اضافه کردن الماس', b'add_balance')],
        [Button.inline('🚫 مسدود کردن کاربر', b'ban_user_admin')],
        [Button.inline('🔙 برگشت', b'back')]
    ]
    await safe_edit(event, '🛠 **پنل مدیریت VIP MR**\n\nلطفاً یکی از گزینه‌های زیر را انتخاب کنید:', buttons=buttons, parse_mode='md')

@telethon_bot.on(events.CallbackQuery(data=b'add_balance'))
async def add_balance_admin(event):
    user_id = event.sender_id
    if user_id not in ADMINS:
        await event.answer('❌ شما دسترسی ندارید!', alert=True)
        return
    await safe_edit(event, '➕ **اضافه کردن الماس VIP MR**\n\nلطفاً آیدی عددی کاربر مورد نظر را وارد کنید:', parse_mode='md')
    user_clients[user_id] = {'step': 'add_balance_user'}

@telethon_bot.on(events.CallbackQuery(data=b'ban_user_admin'))
async def ban_user_admin(event):
    user_id = event.sender_id
    if user_id not in ADMINS:
        await event.answer('❌ شما دسترسی ندارید!', alert=True)
        return
    await safe_edit(event, '🚫 **مسدود کردن کاربر VIP MR**\n\nلطفاً آیدی عددی کاربر مورد نظر را وارد کنید:', parse_mode='md')
    user_clients[user_id] = {'step': 'ban_user'}

@telethon_bot.on(events.CallbackQuery(pattern=b'confirm_(\\d+)_(\\d+)_(\\d+)'))
async def confirm_payment(event):
    if event.sender_id not in ADMINS:
        return
    try:
        data_parts = event.data.decode().split('_')
        user_id = int(data_parts[1])
        amount = int(data_parts[2])
        black_amount = int(data_parts[3])
    except:
        await event.answer('خطای داده!', alert=True)
        return
    init_user_db(user_id)
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (black_amount, user_id))
    db.commit()
    db.close()
    try:
        await telethon_bot.send_message(user_id, f'✅ پرداخت شما تأیید شد!\n💎 {black_amount:,} الماس به حساب شما اضافه شد.')
    except Exception as e:
        logger.error(f"Error sending message to user {user_id}: {e}")
    await safe_edit(event, f'✅ پرداخت کاربر {user_id} برای {black_amount:,} الماس تأیید شد.')

@telethon_bot.on(events.CallbackQuery(pattern=b'reject_(\\d+)_(\\d+)'))
async def reject_payment(event):
    if event.sender_id not in ADMINS:
        return
    try:
        data_parts = event.data.decode().split('_')
        user_id = int(data_parts[1])
    except:
        await event.answer('خطای داده!', alert=True)
        return
    try:
        await telethon_bot.send_message(user_id, '❌ پرداخت شما رد شد. لطفاً با پشتیبانی تماس بگیرید.')
    except Exception as e:
        logger.error(f"Error sending message to user {user_id}: {e}")
    await safe_edit(event, f'❌ پرداخت کاربر {user_id} رد شد.')

# =============================================
# تابع اصلی
# =============================================
async def main():
    # شروع Pyrogram Bots
    for phone, session_data in data_manager.get_all_sessions():
        session_string = session_data["string"]
        user_id = session_data["user_id"]
        asyncio.create_task(start_bot_instance(session_string, phone, user_id, 'stylized'))
    
    # شروع Manager Bot (Pyrogram)
    await manager_bot.start()
    logger.info("✅ Manager bot started")
    
    # شروع Telethon Bot
    await telethon_bot.start()
    logger.info("✅ Telethon bot started")
    
    # نگه داشتن هر دو بات با idle
    try:
        await idle()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    finally:
        await manager_bot.stop()
        await telethon_bot.disconnect()
        logger.info("✅ Both bots stopped")

if __name__ == "__main__":
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
