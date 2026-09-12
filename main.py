import os
import asyncio
import logging
import re
import aiohttp
import time
import json
import random
import sqlite3
from urllib.parse import quote
from pyrogram import Client, filters, idle
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.enums import ChatType, ChatAction, ParseMode
from pyrogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery,
    InlineQueryResultArticle, InputTextMessageContent, MessageEntity
)
from pyrogram.raw import functions
from pyrogram.errors import SessionPasswordNeeded, ChatSendInlineForbidden
from datetime import datetime
from zoneinfo import ZoneInfo
import pyrogram.utils

# =============================================
# ایمپورت دیتابیس
# =============================================
from database import (
    init_session_db,
    save_session_to_db,
    get_all_sessions_from_db,
    get_session_by_user_id,
    delete_session_from_db,
    delete_session_by_user_id,
    get_session_count,
    clear_inactive_sessions
)

# =============================================
# ایمپورت دانلودر
# =============================================
import subprocess
from yt_dlp import YoutubeDL

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s - %(message)s')

def patch_peer_id_validation():
    original_get_peer_type = pyrogram.utils.get_peer_type

    def patched_get_peer_type(peer_id: int) -> str:
        try:
            return original_get_peer_type(peer_id)
        except ValueError:
            if str(peer_id).startswith("-100"):
                return "channel"
            raise

    pyrogram.utils.get_peer_type = patched_get_peer_type
    logging.info("Pyrogram peer ID validation patched successfully.")

patch_peer_id_validation()

# =============================================
# تنظیمات اصلی
# =============================================
API_ID = 34996139
API_HASH = "a1f3db16cae2919cfb05e61d1e968b8d"

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN not found in environment variables!")

GOD_ADMIN_IDS = [6691993264]

# =============================================
# کانال‌های عضویت اجباری
# =============================================

FORCE_CHANNELS = [
    "@SELF_MR0"
]
SUPPORT_USERNAME = "ALONE_88_R"  # بدون @

async def force_subscribe_check(client, message) -> bool:
    """عضویت اجباری — ادمین‌ها مستثنی هستند"""
    try:
        user = message.from_user
        if not user:
            return True
        if user.id in GOD_ADMIN_IDS:
            return True
        if not FORCE_CHANNELS:
            return True
        missing = []
        for ch in FORCE_CHANNELS:
            try:
                member = await client.get_chat_member(ch, user.id)
                status = str(getattr(member, "status", "")).lower()
                if "left" in status or "kicked" in status or "banned" in status:
                    missing.append(ch)
            except Exception:
                missing.append(ch)
        if not missing:
            return True
        # پیام عضویت
        lines = "\n".join(f"• {c}" for c in missing)
        try:
            from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            buttons = []
            for c in missing:
                uname = c.lstrip("@")
                buttons.append([InlineKeyboardButton(f"عضویت در {c}", url=f"https://t.me/{uname}")])
            buttons.append([InlineKeyboardButton("🔄 بررسی مجدد عضویت", callback_data="check_subscription")])
            await message.reply_text(
                f"⚠️ برای استفاده از ربات باید در کانال‌های زیر عضو شوید:\n\n{lines}",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        except Exception as e:
            logging.error(f"force_subscribe msg: {e}")
            try:
                await message.reply_text(f"⚠️ لطفاً ابتدا در کانال‌ها عضو شوید:\n{lines}")
            except Exception:
                pass
        return False
    except Exception as e:
        logging.error(f"force_subscribe_check: {e}")
        return True


def backup_sessions():
    try:
        sessions = get_all_sessions_from_db()
        if sessions:
            logging.info(f"💾 Backed up {len(sessions)} sessions")
    except Exception as e:
        logging.error(f"Backup failed: {e}")


DATA_FILE = "bot_data.json"
DOWNLOAD_PATH = "downloads"
MAX_FILE_SIZE = 50 * 1024 * 1024

TEHRAN_TIMEZONE = ZoneInfo("Asia/Tehran")
LOGIN_STATES = {}
ADMIN_STATES = {}

if not os.path.exists(DOWNLOAD_PATH):
    os.makedirs(DOWNLOAD_PATH)

if not os.path.exists('database_users'):
    os.makedirs('database_users')

# =============================================
# دیتابیس کاربران + سیستم الماس (self MR)
# =============================================
SELF_PRICE = 50          # هزینه فعال‌سازی سلف
HOURLY_COST = 2          # کسر ساعتی
REFERRAL_REWARD = 75     # پاداش زیرمجموعه
MIN_GAME_AMOUNT = 20     # حداقل مبلغ نبرد
TRANSFER_TAX_PERCENT = 10
GAME_TAX_PERCENT = 5

# نبردهای فعال: (chat_id, message_id) -> info
active_games = {}


async def get_user_name(user_id: int) -> str:
    """نام قابل‌نمایش کاربر برای پیام نتیجه نبرد"""
    try:
        u = await manager_bot.get_users(int(user_id))
        name = (u.first_name or str(user_id)).replace("<", "").replace(">", "")
        return f'<a href="tg://user?id={user_id}">{name}</a>'
    except Exception:
        try:
            return f"<code>{int(user_id)}</code>"
        except Exception:
            return str(user_id)


async def check_all_channels(user_id: int):
    """لیست کانال‌هایی که کاربر عضو نیست"""
    missing = []
    for ch in FORCE_CHANNELS:
        try:
            member = await manager_bot.get_chat_member(ch, user_id)
            status = str(getattr(member, "status", "")).lower()
            if "left" in status or "kicked" in status or "banned" in status:
                missing.append(ch)
        except Exception:
            missing.append(ch)
    return missing


def get_user_db(user_id):
    return sqlite3.connect(f'database_users/user_{user_id}.db')

def init_user_db(user_id):
    """ایجاد و آماده‌سازی دیتابیس کاربر"""
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0,
            banned INTEGER DEFAULT 0,
            invited_by INTEGER DEFAULT 0,
            self_start_time INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS self_sessions (
            session_string TEXT,
            is_active INTEGER DEFAULT 1,
            start_time INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            referrer_id INTEGER,
            referred_id INTEGER PRIMARY KEY,
            reward_claimed INTEGER DEFAULT 0
        )
    ''')
    # اضافه کردن کاربر اگر وجود نداشته باشد
    cursor.execute('INSERT OR IGNORE INTO users (user_id, balance, banned, invited_by, self_start_time) VALUES (?, 0, 0, 0, 0)', (user_id,))
    db.commit()
    db.close()

def get_balance(user_id):
    init_user_db(user_id)
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    db.close()
    return result[0] if result else 0

def add_balance(user_id, amount):
    init_user_db(user_id)
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    db.commit()
    db.close()

def deduct_balance(user_id, amount):
    """کم کردن موجودی. اگر موجودی کافی نباشد False برمی‌گرداند"""
    init_user_db(user_id)
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    balance = result[0] if result else 0
    if balance < amount:
        db.close()
        return False
    cursor.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (amount, user_id))
    db.commit()
    db.close()
    return True

def is_banned(user_id):
    init_user_db(user_id)
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('SELECT banned FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    db.close()
    return bool(result and result[0] == 1)

def set_banned(user_id, status: bool):
    init_user_db(user_id)
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('UPDATE users SET banned = ? WHERE user_id = ?', (1 if status else 0, user_id))
    db.commit()
    db.close()

def set_self_start_time(user_id, timestamp=None):
    init_user_db(user_id)
    db = get_user_db(user_id)
    cursor = db.cursor()
    ts = timestamp if timestamp is not None else int(time.time())
    cursor.execute('UPDATE users SET self_start_time = ? WHERE user_id = ?', (ts, user_id))
    db.commit()
    db.close()

def get_self_start_time(user_id):
    init_user_db(user_id)
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('SELECT self_start_time FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    db.close()
    return result[0] if result else 0

def get_session(user_id):
    try:
        db = get_user_db(user_id)
        cursor = db.cursor()
        cursor.execute('SELECT session_string FROM self_sessions WHERE is_active = 1')
        result = cursor.fetchone()
        db.close()
        return result[0] if result else None
    except:
        return None

# =============================================
# تابع دانلود
# =============================================
async def download_media(url, media_type="video"):
    """دانلود از یوتیوب، تیک‌تاک، اینستا و ۱۰۰۰+ سایت"""
    try:
        safe_name = f"{int(time.time())}_{random.randint(1000,9999)}"
        outtmpl = f'{DOWNLOAD_PATH}/{safe_name}.%(ext)s'
        ydl_opts = {
            'outtmpl': outtmpl,
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': False,
            'noplaylist': True,
            'socket_timeout': 30,
            'retries': 3,
        }

        if media_type == "audio":
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
        else:
            ydl_opts.update({
                'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/best',
                'merge_output_format': 'mp4',
            })

        def _run():
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if not info:
                    return None, None
                filename = ydl.prepare_filename(info)
                if media_type == "audio":
                    base = filename.rsplit('.', 1)[0]
                    for ext in ('.mp3', '.m4a', '.webm', '.opus'):
                        if os.path.exists(base + ext):
                            return base + ('.mp3' if ext != '.mp3' and os.path.exists(base + '.mp3') else ext), info.get('title')
                    if os.path.exists(base + '.mp3'):
                        return base + '.mp3', info.get('title')
                if os.path.exists(filename):
                    return filename, info.get('title')
                # جستجو در پوشه
                for f in os.listdir(DOWNLOAD_PATH):
                    if f.startswith(safe_name):
                        return os.path.join(DOWNLOAD_PATH, f), info.get('title')
                return None, None

        filename, title = await asyncio.to_thread(_run)
        if not filename or not os.path.exists(filename):
            return None, "❌ دانلود ناموفق بود. لینک را بررسی کنید."

        file_size = os.path.getsize(filename)
        if file_size > MAX_FILE_SIZE:
            os.remove(filename)
            return None, "❌ حجم فایل بیشتر از ۵۰ مگابایت است!"
        if file_size < 1000:
            os.remove(filename)
            return None, "❌ فایل خیلی کوچک است یا دانلود ناقص بود."
        return filename, None
    except Exception as e:
        err = str(e)
        if "Unsupported URL" in err:
            return None, "❌ این لینک پشتیبانی نمی‌شود."
        if "Private video" in err or "private" in err.lower():
            return None, "❌ ویدیو خصوصی است."
        return None, f"❌ خطا در دانلود: {err[:120]}"

# =============================================
# تابع پاک‌سازی فایل‌های قدیمی
# =============================================

# =============================================
# قیمت ارز
# =============================================
CURRENCY_ALIASES = {
    "دلار": "usd", "dollar": "usd", "usd": "usd", "دلار آمریکا": "usd",
    "یورو": "eur", "euro": "eur", "eur": "eur",
    "پوند": "gbp", "gbp": "gbp",
    "درهم": "aed", "aed": "aed", "درهم امارات": "aed",
    "لیر": "try", "try": "try", "لیر ترکیه": "try",
    "یوان": "cny", "cny": "cny",
    "روبل": "rub", "rub": "rub",
    "بیتکوین": "btc", "بیت‌کوین": "btc", "btc": "btc", "bitcoin": "btc",
    "اتریوم": "eth", "eth": "eth",
    "تتر": "usdt", "usdt": "usdt",
    "طلا": "gold", "انس": "gold", "انس طلا": "gold",
    "سکه": "coin", "سکه امامی": "coin",
}

CURRENCY_NAMES = {
    "usd": "دلار آمریکا", "eur": "یورو", "gbp": "پوند انگلیس",
    "aed": "درهم امارات", "try": "لیر ترکیه", "cny": "یوان چین",
    "rub": "روبل روسیه", "btc": "بیت‌کوین", "eth": "اتریوم",
    "usdt": "تتر", "gold": "انس طلا", "coin": "سکه امامی",
}

async def fetch_currency_price(key: str):
    """دریافت قیمت از tgju.org"""
    key = key.lower()
    # کلیدهای tgju (مبالغ غالباً به ریال)
    TGJU_KEYS = {
        "usd": ("price_dollar_rl", True, "تومان"),
        "eur": ("price_eur", True, "تومان"),
        "gbp": ("price_gbp", True, "تومان"),
        "aed": ("price_aed", True, "تومان"),
        "try": ("price_try", True, "تومان"),
        "cny": ("price_cny", True, "تومان"),
        "rub": ("price_rub", True, "تومان"),
        "usdt": ("crypto-tether-irr", True, "تومان"),
        "btc": ("crypto-bitcoin-irr", True, "تومان"),
        "eth": ("crypto-ethereum-irr", True, "تومان"),
        "gold": ("ons", False, "دلار"),  # انس جهانی دلاری
        "coin": ("sekee", True, "تومان"),
    }
    mapping = TGJU_KEYS.get(key)
    if not mapping:
        return None, "❌ این ارز پشتیبانی نمی‌شود."

    tgju_key, is_rial, unit = mapping
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://www.tgju.org/",
    }
    urls = [
        "https://call1.tgju.org/ajax.json",
        "https://call2.tgju.org/ajax.json",
        "https://call3.tgju.org/ajax.json",
    ]
    try:
        async with aiohttp.ClientSession() as session:
            for url in urls:
                try:
                    async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.json()
                        current = data.get("current") or {}
                        item = current.get(tgju_key)
                        if not item:
                            continue
                        raw = item.get("p") if isinstance(item, dict) else item
                        if raw is None:
                            continue
                        # پاکسازی عدد
                        s = str(raw).replace(",", "").replace(" ", "").replace("٬", "")
                        try:
                            val = float(s)
                        except Exception:
                            return str(raw), None
                        if is_rial:
                            # تبدیل ریال به تومان
                            val = val / 10
                        # فرمت خوانا
                        if val >= 100:
                            formatted = f"{int(round(val)):,}"
                        else:
                            formatted = f"{val:,.2f}"
                        updated = item.get("t", "") if isinstance(item, dict) else ""
                        return f"{formatted} {unit}", updated
                except Exception:
                    continue
        return None, "❌ دریافت قیمت از tgju ممکن نشد. دوباره تلاش کنید."
    except Exception as e:
        return None, f"❌ خطا: {e}"


TTS_VOICE_STATUS = {}  # user_id -> voice key

TTS_VOICES = {
    "زن": {"tl": "fa", "label": "زن (فارسی)"},
    "مرد": {"tl": "fa", "label": "مرد (فارسی)"},
    "انگلیسی": {"tl": "en", "label": "انگلیسی"},
    "عربی": {"tl": "ar", "label": "عربی"},
    "ترکی": {"tl": "tr", "label": "ترکی"},
    "روسی": {"tl": "ru", "label": "روسی"},
}

async def text_to_speech(text: str, voice_key: str = "زن"):
    """تبدیل متن به ویس - برای همه زبان‌ها پایدار"""
    text = (text or "").strip()
    if not text:
        return None, "❌ متن خالی است."
    text = text[:400]

    os.makedirs(DOWNLOAD_PATH, exist_ok=True)
    path = f"{DOWNLOAD_PATH}/tts_{int(time.time())}_{random.randint(100,999)}.mp3"
    errors = []

    # چند صدا برای هر زبان (اگر اولی خالی بود بره بعدی)
    edge_voice_list = {
        "زن": ["fa-IR-DilaraNeural", "fa-IR-FaridNeural"],
        "مرد": ["fa-IR-FaridNeural", "fa-IR-DilaraNeural"],
        "انگلیسی": ["en-US-JennyNeural", "en-US-GuyNeural", "en-GB-SoniaNeural", "en-US-AriaNeural"],
        "عربی": ["ar-SA-ZariyahNeural", "ar-EG-SalmaNeural", "ar-SA-HamedNeural"],
        "ترکی": ["tr-TR-EmelNeural", "tr-TR-AhmetNeural"],
        "روسی": ["ru-RU-SvetlanaNeural", "ru-RU-DmitryNeural"],
    }
    gtts_lang = {
        "زن": "fa", "مرد": "fa",
        "انگلیسی": "en", "عربی": "ar", "ترکی": "tr", "روسی": "ru",
    }
    voices = edge_voice_list.get(voice_key, edge_voice_list["زن"])
    tl = gtts_lang.get(voice_key, "fa")

    def _file_ok(p):
        try:
            return os.path.exists(p) and os.path.getsize(p) > 2000
        except Exception:
            return False

    def _cleanup(p):
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass

    # ----- 1) edge-tts -----
    try:
        import edge_tts
        for v in voices:
            try:
                _cleanup(path)
                communicate = edge_tts.Communicate(text, v)
                await communicate.save(path)
                if _file_ok(path):
                    return path, None
                errors.append(f"edge:{v}:empty")
            except Exception as e:
                errors.append(f"edge:{v}:{type(e).__name__}")
                _cleanup(path)
    except ImportError:
        errors.append("edge-tts نصب نیست")
    except Exception as e:
        errors.append(f"edge:{type(e).__name__}:{e}")

    # ----- 2) edge-tts CLI -----
    for v in voices:
        try:
            _cleanup(path)
            proc = await asyncio.create_subprocess_exec(
                "edge-tts",
                "--voice", v,
                "--text", text,
                "--write-media", path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode == 0 and _file_ok(path):
                return path, None
            errors.append(f"cli:{v}:rc={proc.returncode}")
            _cleanup(path)
        except FileNotFoundError:
            errors.append("edge-tts-cli نیست")
            break
        except Exception as e:
            errors.append(f"cli:{v}:{type(e).__name__}")
            _cleanup(path)

    # ----- 3) gTTS (برای en/tr/ru خیلی پایدار) -----
    try:
        from gtts import gTTS
        def _gtts():
            # slow=False
            tts = gTTS(text=text, lang=tl, lang_check=False)
            tts.save(path)
        _cleanup(path)
        await asyncio.to_thread(_gtts)
        if _file_ok(path):
            return path, None
        errors.append("gTTS:empty")
        _cleanup(path)
    except ImportError:
        errors.append("gTTS نصب نیست")
    except Exception as e:
        errors.append(f"gTTS:{type(e).__name__}:{e}")
        _cleanup(path)

    # ----- 4) Google HTTP -----
    try:
        q = quote(text)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://translate.google.com/",
        }
        urls = [
            f"https://translate.googleapis.com/translate_tts?ie=UTF-8&q={q}&tl={tl}&client=gtx",
            f"https://translate.google.com/translate_tts?ie=UTF-8&q={q}&tl={tl}&client=tw-ob",
        ]
        async with aiohttp.ClientSession() as session:
            for url in urls:
                try:
                    _cleanup(path)
                    async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            if len(data) > 2000:
                                with open(path, "wb") as f:
                                    f.write(data)
                                if _file_ok(path):
                                    return path, None
                        errors.append(f"http:{resp.status}")
                except Exception as e:
                    errors.append(f"http:{type(e).__name__}")
    except Exception as e:
        errors.append(f"http:{e}")

    detail = " | ".join(errors[-5:])
    logging.error(f"TTS failed for voice={voice_key}: {detail}")
    return None, f"❌ ساخت ویس ناموفق بود.\\n🔧 `{detail}`"


async def cleanup_old_files():
    while True:
        await asyncio.sleep(3600)
        now = time.time()
        for filename in os.listdir(DOWNLOAD_PATH):
            filepath = os.path.join(DOWNLOAD_PATH, filename)
            if os.path.isfile(filepath):
                if now - os.path.getctime(filepath) > 3600:
                    try:
                        os.remove(filepath)
                    except:
                        pass


# =============================================
# 🎰 سیستم تقلب تاس / بولینگ / اسلات (ضد اسپم)
# =============================================
async def cheat_send_dice(client, chat_id: int, emoji: str, targets: set, max_tries: int = 40):
    """
    ایموجی بازی را دانه‌دانه می‌فرستد تا مقدار دلخواه بیاید.
    پیام‌های ناموفق را یکی‌یکی پاک می‌کند (گروه و پیوی).
    """
    async def _safe_delete(msg):
        if msg is None:
            return
        mid = getattr(msg, "id", None)
        # روش اصلی: خود پیام
        try:
            await msg.delete()
            return
        except Exception:
            pass
        # روش دوم: delete_messages
        if mid is not None:
            try:
                await client.delete_messages(chat_id, mid)
                return
            except Exception:
                pass
            try:
                await client.delete_messages(chat_id, [mid])
                return
            except Exception:
                pass
            # raw
            try:
                await client.invoke(functions.messages.DeleteMessages(id=[mid], revoke=True))
            except Exception as e:
                logging.warning(f"cheat delete fail mid={mid}: {e}")

    last_msg = None
    for attempt in range(1, max_tries + 1):
        try:
            await asyncio.sleep(random.uniform(1.5, 2.8))
            msg = await client.send_dice(chat_id, emoji)
            value = getattr(getattr(msg, "dice", None), "value", None)

            if value is not None and value in targets:
                # موفق — پیام قبلی ناموفق را پاک کن
                if last_msg is not None and getattr(last_msg, "id", None) != msg.id:
                    await _safe_delete(last_msg)
                return True, value, attempt

            # ناموفق — پیام قبلی را پاک کن، فعلی را نگه دار
            if last_msg is not None:
                await _safe_delete(last_msg)
            last_msg = msg

        except Exception as e:
            logging.warning(f"cheat_send_dice error attempt={attempt}: {e}")
            await asyncio.sleep(2.0)
            continue

    if last_msg is not None:
        await _safe_delete(last_msg)
    return False, None, max_tries


ENEMY_REPLIES = [
    "کیرم تو رحم اجاره ای و خونی مالی مادرت",
    "دو میلیون شبی پول ویلا بدم تا مادرتو تو گوشه کناراش بگام",
    "احمق مادر کونی من کس مادرت گذاشتم تو بازم داری کسشر میگی",
]

# =============================================
# ابزارهای کمکی جدید (ساعت / آب‌وهوا / ویس / PDF / تگ)
# =============================================
COUNTRY_TZ = {
    "ایران": "Asia/Tehran", "tehran": "Asia/Tehran", "iran": "Asia/Tehran", "تهران": "Asia/Tehran",
    "آمریکا": "America/New_York", "america": "America/New_York", "نیویورک": "America/New_York", "new york": "America/New_York",
    "لس آنجلس": "America/Los_Angeles", "la": "America/Los_Angeles", "california": "America/Los_Angeles",
    "انگلیس": "Europe/London", "london": "Europe/London", "uk": "Europe/London", "لندن": "Europe/London",
    "آلمان": "Europe/Berlin", "berlin": "Europe/Berlin", "germany": "Europe/Berlin", "برلین": "Europe/Berlin",
    "فرانسه": "Europe/Paris", "paris": "Europe/Paris", "france": "Europe/Paris", "پاریس": "Europe/Paris",
    "ترکیه": "Europe/Istanbul", "istanbul": "Europe/Istanbul", "turkey": "Europe/Istanbul", "استانبول": "Europe/Istanbul",
    "امارات": "Asia/Dubai", "dubai": "Asia/Dubai", "دبی": "Asia/Dubai", "uae": "Asia/Dubai",
    "عراق": "Asia/Baghdad", "baghdad": "Asia/Baghdad", "بغداد": "Asia/Baghdad",
    "هند": "Asia/Kolkata", "india": "Asia/Kolkata", "دهلی": "Asia/Kolkata",
    "چین": "Asia/Shanghai", "china": "Asia/Shanghai", "پکن": "Asia/Shanghai", "beijing": "Asia/Shanghai",
    "ژاپن": "Asia/Tokyo", "japan": "Asia/Tokyo", "tokyo": "Asia/Tokyo", "توکیو": "Asia/Tokyo",
    "کره": "Asia/Seoul", "seoul": "Asia/Seoul", "korea": "Asia/Seoul",
    "روسیه": "Europe/Moscow", "moscow": "Europe/Moscow", "مسکو": "Europe/Moscow", "russia": "Europe/Moscow",
    "استرالیا": "Australia/Sydney", "sydney": "Australia/Sydney", "australia": "Australia/Sydney",
    "کانادا": "America/Toronto", "toronto": "America/Toronto", "canada": "America/Toronto",
    "برزیل": "America/Sao_Paulo", "brazil": "America/Sao_Paulo",
    "مصر": "Africa/Cairo", "cairo": "Africa/Cairo", "egypt": "Africa/Cairo",
    "عربستان": "Asia/Riyadh", "riyadh": "Asia/Riyadh", "saudi": "Asia/Riyadh",
}


async def get_time_for_place(place: str) -> str:
    key = (place or "").strip().lower()
    tz_name = COUNTRY_TZ.get(key) or COUNTRY_TZ.get(place.strip()) if place else None
    if not tz_name:
        # جستجوی تقریبی
        for k, v in COUNTRY_TZ.items():
            if key in k.lower() or k.lower() in key:
                tz_name = v
                break
    if not tz_name:
        # try zoneinfo direct
        try:
            ZoneInfo(place)
            tz_name = place
        except Exception:
            return (
                f"❌ منطقه پیدا نشد: `{place}`\n\n"
                f"مثال:\n`.ساعت ایران`\n`.ساعت Tokyo`\n`.ساعت دبی`"
            )
    try:
        now = datetime.now(ZoneInfo(tz_name))
        return (
            f"🕐 **زمان | self MR**\n\n"
            f"📍 `{place}`\n"
            f"🗺 `{tz_name}`\n"
            f"📅 {now.strftime('%Y/%m/%d')}\n"
            f"⏰ {now.strftime('%H:%M:%S')}\n"
            f"📌 {now.strftime('%A')}"
        )
    except Exception as e:
        return f"❌ خطا در دریافت زمان: {e}"


async def get_weather_for_place(place: str) -> str:
    """آب‌وهوای لحظه‌ای از wttr.in — دقیق‌تر (دما، احساس، وضعیت واقعی روز/شب)"""
    place = (place or "").strip()
    if not place:
        return "❌ مثال:\n`.آب و هوا تهران`"
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; selfMR/1.0)"}
        url = f"https://wttr.in/{quote(place)}?format=j1&lang=fa"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=20) as r:
                if r.status != 200:
                    return f"❌ دریافت آب‌وهوا ناموفق (کد {r.status}). شهر را بررسی کنید."
                data = await r.json(content_type=None)

        cur_list = data.get("current_condition") or []
        if not cur_list:
            return f"❌ داده آب‌وهوا برای `{place}` پیدا نشد."
        cur = cur_list[0]

        area = place
        try:
            a = (data.get("nearest_area") or [{}])[0]
            area_name = (a.get("areaName") or [{}])[0].get("value") or place
            country = (a.get("country") or [{}])[0].get("value") or ""
            region = (a.get("region") or [{}])[0].get("value") or ""
            area = area_name
            if region:
                area += f"، {region}"
            if country:
                area += f" — {country}"
        except Exception:
            pass

        desc = ""
        try:
            lang_fa = cur.get("lang_fa") or []
            if lang_fa and lang_fa[0].get("value"):
                desc = lang_fa[0]["value"]
            else:
                desc = (cur.get("weatherDesc") or [{}])[0].get("value") or ""
        except Exception:
            desc = ""

        temp = cur.get("temp_C") or "?"
        feels = cur.get("FeelsLikeC") or temp
        humidity = cur.get("humidity") or "?"
        wind = cur.get("windspeedKmph") or "?"
        wind_dir = cur.get("winddir16Point") or ""
        pressure = cur.get("pressure") or "?"
        visibility = cur.get("visibility") or "?"
        cloud = cur.get("cloudcover") or "?"
        uv = cur.get("uvIndex") or "?"
        obs = cur.get("localObsDateTime") or cur.get("observation_time") or ""

        today_line = ""
        tomorrow_line = ""
        try:
            days = data.get("weather") or []
            if days:
                d0 = days[0]
                today_line = (
                    f"📅 امروز: کمینه `{d0.get('mintempC', '?')}°` / بیشینه `{d0.get('maxtempC', '?')}°`"
                )
            if len(days) > 1:
                d1 = days[1]
                tomorrow_line = (
                    f"📅 فردا: کمینه `{d1.get('mintempC', '?')}°` / بیشینه `{d1.get('maxtempC', '?')}°`"
                )
        except Exception:
            pass

        lines = [
            "🌤 **آب و هوا | self MR**",
            "",
            f"📍 {area}",
            f"📊 وضعیت: {desc or '—'}",
            f"🌡 دما: `{temp}°C` (احساس: `{feels}°C`)",
            f"💧 رطوبت: `{humidity}%`",
            f"💨 باد: `{wind} km/h` {wind_dir}".rstrip(),
            f"🌡 فشار: `{pressure} mb` | 👁 دید: `{visibility} km`",
            f"☁️ ابر: `{cloud}%` | ☀️ UV: `{uv}`",
        ]
        if obs:
            lines.append(f"🕐 مشاهده: `{obs}`")
        if today_line:
            lines.extend(["", today_line])
        if tomorrow_line:
            lines.append(tomorrow_line)
        return "\n".join(lines)
    except asyncio.TimeoutError:
        return "❌ زمان درخواست آب‌وهوا تمام شد. دوباره تلاش کنید."
    except Exception as e:
        return f"❌ خطا در دریافت آب‌وهوا: {e}"


async def enhance_photo_quality(client, message):
    """بهبود واقعی‌تر کیفیت عکس + ارسال بدون فشرده‌سازی تلگرام"""
    reply = message.reply_to_message
    if not reply or not (reply.photo or (reply.document and (reply.document.mime_type or "").startswith("image/"))):
        await message.edit_text("❌ روی یک **عکس** ریپلای کنید:\n`.کیفیت عکس`")
        return
    path = None
    out_path = None
    try:
        await message.edit_text("⏳ در حال بهبود کیفیت عکس...")
        # بزرگ‌ترین سایز عکس تلگرام
        path = await client.download_media(reply, file_name=f"{DOWNLOAD_PATH}/enh_{int(time.time())}")
        if not path or not os.path.exists(path):
            await message.edit_text("❌ دانلود عکس ناموفق بود.")
            return

        from PIL import Image, ImageEnhance, ImageFilter, ImageOps
        resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS

        img = Image.open(path)
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        elif img.mode == "L":
            img = img.convert("RGB")

        orig_w, orig_h = img.size

        # حذف نویز خیلی ملایم قبل از بزرگ‌کردن
        img = img.filter(ImageFilter.MedianFilter(size=3))

        # بزرگ‌کردن تدریجی تا ~2.5x (نتیجه نرم‌تر از یک‌باره)
        target_scale = 2.5
        target_w = int(orig_w * target_scale)
        target_h = int(orig_h * target_scale)
        max_dim = 4096
        if max(target_w, target_h) > max_dim:
            ratio = max_dim / float(max(target_w, target_h))
            target_w = max(1, int(target_w * ratio))
            target_h = max(1, int(target_h * ratio))

        cur = img
        while cur.size[0] * 1.5 < target_w and cur.size[1] * 1.5 < target_h:
            nw = min(target_w, int(cur.size[0] * 1.5))
            nh = min(target_h, int(cur.size[1] * 1.5))
            cur = cur.resize((nw, nh), resample)
        if cur.size != (target_w, target_h):
            cur = cur.resize((target_w, target_h), resample)

        # بهبود رنگ / کنتراست / شارپ کنترل‌شده
        cur = ImageEnhance.Contrast(cur).enhance(1.12)
        cur = ImageEnhance.Color(cur).enhance(1.10)
        cur = ImageEnhance.Brightness(cur).enhance(1.03)
        cur = ImageEnhance.Sharpness(cur).enhance(1.35)
        cur = cur.filter(ImageFilter.UnsharpMask(radius=1.6, percent=90, threshold=2))

        new_w, new_h = cur.size
        out_path = f"{DOWNLOAD_PATH}/enhanced_{int(time.time())}.jpg"
        cur.save(out_path, "JPEG", quality=97, optimize=True, subsampling=0)

        caption = (
            f"✨ کیفیت بهتر | self MR\n"
            f"📐 `{orig_w}×{orig_h}` → `{new_w}×{new_h}`"
        )

        # send_document = بدون فشرده‌سازی عکس تلگرام (کیفیت واقعی می‌مونه)
        try:
            await client.send_document(
                message.chat.id,
                out_path,
                caption=caption,
                force_document=True,
            )
        except TypeError:
            await client.send_document(message.chat.id, out_path, caption=caption)
        except Exception:
            # fallback
            await client.send_photo(message.chat.id, out_path, caption=caption)

        try:
            await message.delete()
        except Exception:
            pass
    except Exception as e:
        logging.error(f"enhance_photo: {e}")
        try:
            await message.edit_text(f"❌ خطا در بهبود عکس: {e}")
        except Exception:
            pass
    finally:
        for p in (path, out_path):
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


async def search_songs_list(query: str) -> list:
    """جستجوی آهنگ از چند منبع: iTunes + LRCLIB + YouTube + SoundCloud"""
    query = (query or "").strip()
    tracks = []
    seen = set()
    if not query:
        return tracks

    def _add(ar, tr, extra_q=None):
        ar = (ar or "").strip()
        tr = (tr or "").strip()
        if not tr:
            return
        key = f"{ar}|{tr}".lower()
        if key in seen:
            return
        seen.add(key)
        tracks.append({
            "artist": ar,
            "title": tr,
            "query": (extra_q or f"{ar} {tr}".strip() or tr),
        })

    timeout = aiohttp.ClientTimeout(total=18)

    # 1) iTunes
    try:
        itunes_url = f"https://itunes.apple.com/search?term={quote(query)}&entity=song&limit=25"
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(itunes_url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    for item in (data.get("results") or []):
                        _add(item.get("artistName"), item.get("trackName"))
                        if len(tracks) >= 20:
                            break
    except Exception as e:
        logging.warning(f"itunes search: {e}")

    # 2) LRCLIB
    if len(tracks) < 15:
        try:
            lr_url = f"https://lrclib.net/api/search?q={quote(query)}"
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(lr_url) as resp:
                    if resp.status == 200:
                        items = await resp.json()
                        if isinstance(items, list):
                            for it in items:
                                _add(it.get("artistName"), it.get("trackName"))
                                if len(tracks) >= 20:
                                    break
        except Exception as e:
            logging.warning(f"lrclib song search: {e}")

    # 3) YouTube search (بدون دانلود)
    if len(tracks) < 12:
        try:
            def _yt():
                opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True}
                out = []
                with YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(f"ytsearch12:{query}", download=False)
                    for e in (info.get("entries") or []):
                        if not e:
                            continue
                        title = e.get("title") or ""
                        uploader = e.get("uploader") or e.get("channel") or ""
                        vid = e.get("id") or e.get("url") or ""
                        q2 = f"https://www.youtube.com/watch?v={vid}" if vid and len(str(vid)) < 20 else f"{uploader} {title}"
                        out.append((uploader, title, q2))
                return out
            for ar, tr, q2 in await asyncio.to_thread(_yt):
                _add(ar, tr, q2)
                if len(tracks) >= 20:
                    break
        except Exception as e:
            logging.warning(f"yt search: {e}")

    # 4) SoundCloud search flat
    if len(tracks) < 12:
        try:
            def _sc():
                opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True}
                out = []
                with YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(f"scsearch8:{query}", download=False)
                    for e in (info.get("entries") or []):
                        if not e:
                            continue
                        title = e.get("title") or ""
                        uploader = e.get("uploader") or ""
                        url = e.get("url") or e.get("webpage_url") or f"{uploader} {title}"
                        out.append((uploader, title, url))
                return out
            for ar, tr, q2 in await asyncio.to_thread(_sc):
                _add(ar, tr, q2)
                if len(tracks) >= 20:
                    break
        except Exception as e:
            logging.warning(f"sc search: {e}")

    return tracks[:20]


async def download_song_audio(search_q: str) -> tuple:
    """دانلود صوت واقعی از یوتیوب — برمی‌گرداند dict یا (None, err)"""
    search_q = (search_q or "").strip()
    if not search_q:
        return None, "کوئری خالی"
    uid = f"{int(time.time())}_{random.randint(100,999)}"
    out_tmpl = f"{DOWNLOAD_PATH}/song_{uid}.%(ext)s"
    opts = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": out_tmpl,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "default_search": "ytsearch1",
        "socket_timeout": 45,
        "retries": 3,
        "writethumbnail": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            },
            {"key": "FFmpegMetadata"},
        ],
    }
    try:
        def _dl():
            with YoutubeDL(opts) as ydl:
                info = None
                # اگر لینک مستقیم بود
                candidates = []
                if search_q.startswith("http://") or search_q.startswith("https://"):
                    candidates.append(search_q)
                candidates.extend([
                    f"ytsearch1:{search_q}",
                    f"scsearch1:{search_q}",
                    f"ytsearch1:{search_q} audio",
                    f"ytsearch1:{search_q} official audio",
                ])
                last_err = None
                for cand in candidates:
                    try:
                        info = ydl.extract_info(cand, download=True)
                        if info:
                            break
                    except Exception as ee:
                        last_err = ee
                        info = None
                        continue
                if not info:
                    return None, f"نتیجه‌ای پیدا نشد ({last_err})"
                if "entries" in info:
                    entries = [e for e in (info.get("entries") or []) if e]
                    entry = entries[0] if entries else None
                else:
                    entry = info
                if not entry:
                    return None, "آهنگ پیدا نشد"

                title = (entry.get("track") or entry.get("title") or search_q)
                artist = (entry.get("artist") or entry.get("uploader") or entry.get("channel") or "")
                duration = entry.get("duration") or 0

                # فایل صوت
                path = None
                base = f"{DOWNLOAD_PATH}/song_{uid}"
                for ext in ("mp3", "m4a", "webm", "opus", "ogg"):
                    cand = f"{base}.{ext}"
                    if os.path.exists(cand) and os.path.getsize(cand) > 5000:
                        path = cand
                        break
                if not path:
                    for f in os.listdir(DOWNLOAD_PATH):
                        if f.startswith(f"song_{uid}") and not f.endswith((".jpg", ".png", ".webp", ".json")):
                            fp = os.path.join(DOWNLOAD_PATH, f)
                            if os.path.getsize(fp) > 5000:
                                path = fp
                                break
                if not path:
                    return None, "فایل صوت ساخته نشد (yt-dlp/ffmpeg را چک کن)"

                # کاور
                thumb = None
                for ext in ("jpg", "png", "webp"):
                    cand = f"{base}.{ext}"
                    if os.path.exists(cand):
                        thumb = cand
                        break
                if not thumb:
                    # thumbnail از info
                    turl = entry.get("thumbnail")
                    if not turl:
                        ths = entry.get("thumbnails") or []
                        if ths:
                            turl = ths[-1].get("url")
                    if turl and str(turl).startswith("http"):
                        try:
                            import urllib.request
                            thumb = f"{base}_thumb.jpg"
                            urllib.request.urlretrieve(turl, thumb)
                            if not os.path.exists(thumb) or os.path.getsize(thumb) < 500:
                                thumb = None
                        except Exception:
                            thumb = None

                return {
                    "path": path,
                    "title": str(title)[:64],
                    "artist": str(artist)[:64],
                    "duration": int(duration) if duration else 0,
                    "thumb": thumb,
                }, None

        result, err = await asyncio.to_thread(_dl)
        if err:
            return None, err
        return result, None
    except Exception as e:
        err = str(e)
        logging.warning(f"download_song_audio: {err}")
        # پیام‌های واضح
        if "Sign in" in err or "bot" in err.lower():
            return None, "یوتیوب محدود کرده؛ کمی بعد دوباره تلاش کن."
        if "ffmpeg" in err.lower():
            return None, "ffmpeg روی سرور نصب نیست."
        return None, err[:180]


async def send_downloaded_song(client, chat_id, result: dict, status_msg=None):
    """ارسال آهنگ به صورت فایل صوتی تمیز (مثل ربات‌های موزیک)"""
    path = result.get("path")
    title = result.get("title") or "آهنگ"
    artist = result.get("artist") or ""
    duration = result.get("duration") or 0
    thumb = result.get("thumb")
    try:
        kwargs = {
            "chat_id": chat_id,
            "audio": path,
            "title": title,
            "performer": artist,
            "caption": f"🎵 {artist} — {title}\nself MR" if artist else f"🎵 {title}\nself MR",
        }
        if duration:
            kwargs["duration"] = duration
        if thumb and os.path.exists(thumb):
            kwargs["thumb"] = thumb
        await client.send_audio(**kwargs)
        if status_msg:
            try:
                await status_msg.delete()
            except Exception:
                pass
        return True
    except Exception as e:
        logging.error(f"send_downloaded_song: {e}")
        try:
            await client.send_document(chat_id, path, caption=f"🎵 {artist} — {title}")
            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass
            return True
        except Exception as e2:
            if status_msg:
                try:
                    await status_msg.edit_text(f"❌ ارسال ناموفق: {e2}")
                except Exception:
                    pass
            return False
    finally:
        for p in (path, thumb):
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


async def song_download_callback(client, callback: CallbackQuery):
    """کلیک روی دکمه آهنگ (از manager_bot) → دانلود و ارسال صوت"""
    data = callback.data or ""
    if not data.startswith("song_dl_"):
        return
    try:
        parts = data.split("_")
        owner_id = int(parts[2])
        idx = int(parts[3])
    except Exception:
        await callback.answer("❌ داده نامعتبر", show_alert=True)
        return

    if callback.from_user and callback.from_user.id != owner_id:
        await callback.answer("⛔️ فقط خودت می‌تونی دانلود کنی", show_alert=True)
        return

    tracks = SONG_SEARCH_CACHE.get(owner_id) or []
    if idx < 0 or idx >= len(tracks):
        await callback.answer("❌ منقضی شده؛ دوباره سرچ کن", show_alert=True)
        return

    track = tracks[idx]
    q = (track.get("query") or f"{track.get('artist', '')} {track.get('title', '')}").strip()
    title = track.get("title") or "آهنگ"
    artist = track.get("artist") or ""

    try:
        await callback.answer("⏳ دانلود...")
    except Exception:
        pass

    status = None
    try:
        status = await callback.message.reply_text(f"⏳ در حال دانلود:\n🎵 {artist} — {title}")
    except Exception:
        pass

    result, err = await download_song_audio(q)
    if not result and title:
        result, err = await download_song_audio(f"{title} {artist}".strip())
    if not result:
        try:
            if status:
                await status.edit_text(f"❌ دانلود ناموفق:\n{err}")
            else:
                await client.send_message(callback.message.chat.id, f"❌ دانلود ناموفق:\n{err}")
        except Exception:
            pass
        return

    if title:
        result["title"] = title
    if artist:
        result["artist"] = artist
    await send_downloaded_song(client, callback.message.chat.id, result, status_msg=status)


async def search_songs_smart(query: str) -> str:
    """متن ساده — برای سازگاری؛ لیست اصلی از search_songs_list می‌آید"""
    tracks = await search_songs_list(query)
    if not tracks:
        return f"❌ آهنگی برای `{query}` پیدا نشد."
    lines = [f"🎵 سرچ آهنگ | self MR\n\n🔎 {query}\n"]
    for i, t in enumerate(tracks, 1):
        lines.append(f"{i}. {t.get('artist', '')} — {t.get('title', '')}")
    lines.append("\nروی دکمه آهنگ بزن تا فایل صوتی دانلود شود.")
    return "\n".join(lines)


async def voice_to_text(client, message) -> str:
    """تبدیل ویس/صوت به متن (Google STT در صورت موجود بودن)"""
    reply = message.reply_to_message
    if not reply or not (reply.voice or reply.audio or reply.video_note):
        return "❌ روی یک ویس / صوت ریپلای کنید و بفرستید:\n`.ویس به متن`"
    path = None
    wav_path = None
    try:
        path = await client.download_media(reply, file_name=f"{DOWNLOAD_PATH}/stt_{int(time.time())}")
        if not path or not os.path.exists(path):
            return "❌ دانلود ویس ناموفق بود."
        # تبدیل به wav با ffmpeg
        wav_path = f"{path}.wav"
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-i", path, "-ar", "16000", "-ac", "1", wav_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except Exception:
            wav_path = path
        text = None
        try:
            import speech_recognition as sr
            r = sr.Recognizer()
            with sr.AudioFile(wav_path) as source:
                audio = r.record(source)
            try:
                text = r.recognize_google(audio, language="fa-IR")
            except Exception:
                text = r.recognize_google(audio, language="en-US")
        except ImportError:
            return (
                "❌ کتابخانه `SpeechRecognition` نصب نیست.\n"
                "روی سرور اضافه کنید: `pip install SpeechRecognition`"
            )
        except Exception as e:
            return f"❌ تشخیص گفتار ناموفق: {e}"
        if not text:
            return "❌ متنی تشخیص داده نشد."
        return f"🎤 **ویس → متن | self MR**\n\n{text}"
    except Exception as e:
        return f"❌ خطا: {e}"
    finally:
        for p in (path, wav_path):
            try:
                if p and os.path.exists(p) and p.endswith((".wav", ".ogg", ".mp3", ".m4a")):
                    # فقط فایل‌های موقت stt
                    if "stt_" in os.path.basename(p) or p.endswith(".wav"):
                        os.remove(p)
            except Exception:
                pass


async def photo_to_pdf(client, message):
    reply = message.reply_to_message
    if not reply or not (reply.photo or (reply.document and (reply.document.mime_type or "").startswith("image/"))):
        await message.edit_text("❌ روی یک **عکس** ریپلای کنید:\n`.عکس به pdf`")
        return
    path = None
    pdf_path = None
    try:
        path = await client.download_media(reply, file_name=f"{DOWNLOAD_PATH}/img2pdf_{int(time.time())}")
        from PIL import Image
        img = Image.open(path)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        pdf_path = f"{DOWNLOAD_PATH}/photo_{int(time.time())}.pdf"
        img.save(pdf_path, "PDF", resolution=100.0)
        await client.send_document(message.chat.id, pdf_path, caption="📄 عکس → PDF | self MR")
        try:
            await message.delete()
        except Exception:
            pass
    except Exception as e:
        try:
            await message.edit_text(f"❌ خطا: {e}")
        except Exception:
            pass
    finally:
        for p in (path, pdf_path):
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


async def pdf_to_photo(client, message):
    reply = message.reply_to_message
    is_pdf = False
    if reply and reply.document:
        mime = (reply.document.mime_type or "").lower()
        name = (reply.document.file_name or "").lower()
        is_pdf = "pdf" in mime or name.endswith(".pdf")
    if not is_pdf:
        await message.edit_text("❌ روی یک فایل **PDF** ریپلای کنید:\n`.pdf به عکس`")
        return
    path = None
    out_path = None
    try:
        path = await client.download_media(reply, file_name=f"{DOWNLOAD_PATH}/pdf2img_{int(time.time())}.pdf")
        # PyMuPDF
        try:
            import fitz
            doc = fitz.open(path)
            page = doc.load_page(0)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            out_path = f"{DOWNLOAD_PATH}/pdf_page_{int(time.time())}.png"
            pix.save(out_path)
            doc.close()
            await client.send_photo(message.chat.id, out_path, caption="🖼 PDF → عکس (صفحه ۱) | self MR")
        except ImportError:
            await message.edit_text(
                "❌ برای PDF→عکس نیاز به `pymupdf` است.\n"
                "`pip install pymupdf`"
            )
            return
        try:
            await message.delete()
        except Exception:
            pass
    except Exception as e:
        try:
            await message.edit_text(f"❌ خطا: {e}")
        except Exception:
            pass
    finally:
        for p in (path, out_path):
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


async def tag_admins(client, message):
    chat = message.chat
    if not chat or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.edit_text("❌ این دستور فقط داخل گروه کار می‌کند.")
        return
    try:
        admins = []
        try:
            from pyrogram.enums import ChatMembersFilter
            admin_filter = ChatMembersFilter.ADMINISTRATORS
        except Exception:
            admin_filter = "administrators"
        async for m in client.get_chat_members(chat.id, filter=admin_filter):
            u = m.user
            if not u or u.is_bot:
                continue
            if u.username:
                admins.append(f"@{u.username}")
            else:
                name = (u.first_name or "Admin").replace("<", "").replace(">", "")
                admins.append(f"[{name}](tg://user?id={u.id})")
        if not admins:
            await message.edit_text("❌ ادمینی پیدا نشد.")
            return
        # ارسال دسته‌ای برای جلوگیری از محدودیت طول
        header = "👑 **تگ ادمین‌ها | self MR**\n\n"
        chunk = header
        for a in admins:
            if len(chunk) + len(a) + 1 > 3500:
                await client.send_message(chat.id, chunk, disable_web_page_preview=True)
                chunk = a + " "
            else:
                chunk += a + " "
        if chunk.strip():
            await client.send_message(chat.id, chunk, disable_web_page_preview=True)
        try:
            await message.delete()
        except Exception:
            pass
    except Exception as e:
        await message.edit_text(f"❌ خطا: {e}")


async def tag_members(client, message):
    chat = message.chat
    if not chat or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.edit_text("❌ این دستور فقط داخل گروه کار می‌کند.")
        return
    try:
        await message.edit_text("⏳ در حال جمع‌آوری اعضا...")
        members = []
        count = 0
        async for m in client.get_chat_members(chat.id):
            u = m.user
            if not u or u.is_bot:
                continue
            if u.username:
                members.append(f"@{u.username}")
            else:
                name = (u.first_name or "User").replace("<", "").replace(">", "")
                members.append(f"[{name}](tg://user?id={u.id})")
            count += 1
            if count >= 200:
                break
            if count % 30 == 0:
                await asyncio.sleep(0.4)
        if not members:
            await message.edit_text("❌ عضوی پیدا نشد.")
            return
        header = f"👥 **تگ اعضا | self MR**\n(حداکثر ۲۰۰ نفر — {len(members)} نفر)\n\n"
        chunk = header
        for a in members:
            if len(chunk) + len(a) + 1 > 3500:
                await client.send_message(chat.id, chunk, disable_web_page_preview=True)
                await asyncio.sleep(1.2)
                chunk = a + " "
            else:
                chunk += a + " "
        if chunk.strip():
            await client.send_message(chat.id, chunk, disable_web_page_preview=True)
        try:
            await message.delete()
        except Exception:
            pass
    except Exception as e:
        try:
            await message.edit_text(f"❌ خطا: {e}")
        except Exception:
            pass


async def first_comment_handler(client, message: Message):
    """کامنت اول خودکار روی پست کانال (گروه بحث)"""
    try:
        # پیدا کردن owner این کلاینت
        owner_id = None
        for uid, (cli, _) in list(ACTIVE_BOTS.items()):
            if cli is client:
                owner_id = uid
                break
        if not owner_id or not FIRST_COMMENT_STATUS.get(owner_id, False):
            return
        if not message or not message.chat:
            return
        # فقط پست کانال
        if message.chat.type != ChatType.CHANNEL:
            return
        text = FIRST_COMMENT_TEXT.get(owner_id) or "🔥"
        try:
            disc = await client.get_discussion_message(message.chat.id, message.id)
            if disc:
                await disc.reply(text)
                return
        except Exception as e:
            logging.debug(f"first_comment discussion: {e}")
        # fallback: linked chat
        try:
            chat = await client.get_chat(message.chat.id)
            linked = getattr(chat, "linked_chat", None)
            if linked:
                await client.send_message(linked.id, text)
        except Exception as e:
            logging.debug(f"first_comment linked: {e}")
    except Exception as e:
        logging.warning(f"first_comment_handler: {e}")


# =============================================
# فونت‌ها
# =============================================
# فونت‌های متن (برای پیام‌ها)
FONT_STYLES = {
    "bold": {'0':'𝟎','1':'𝟏','2':'𝟐','3':'𝟑','4':'𝟒','5':'𝟓','6':'𝟔','7':'𝟕','8':'𝟖','9':'𝟗',':':':'},
    "italic": {'0':'𝟎','1':'𝟏','2':'𝟐','3':'𝟑','4':'𝟒','5':'𝟓','6':'𝟔','7':'𝟕','8':'𝟖','9':'𝟗',':':':'},
    "quote": {'0':'0','1':'1','2':'2','3':'3','4':'4','5':'5','6':'6','7':'7','8':'8','9':'9',':':':'},
    "strikethrough": {'0':'0','1':'1','2':'2','3':'3','4':'4','5':'5','6':'6','7':'7','8':'8','9':'9',':':':'},
    "underline": {'0':'0','1':'1','2':'2','3':'3','4':'4','5':'5','6':'6','7':'7','8':'8','9':'9',':':':'},
    "spoiler": {'0':'0','1':'1','2':'2','3':'3','4':'4','5':'5','6':'6','7':'7','8':'8','9':'9',':':':'},
    "mono": {'0':'𝟶','1':'𝟷','2':'𝟸','3':'𝟹','4':'𝟺','5':'𝟻','6':'𝟼','7':'𝟽','8':'𝟾','9':'𝟿',':':':'},
    "codeblock": {'0':'0','1':'1','2':'2','3':'3','4':'4','5':'5','6':'6','7':'7','8':'8','9':'9',':':':'},
}

FONT_KEYS_ORDER = ["bold", "italic", "quote", "strikethrough", "underline", "spoiler", "mono", "codeblock"]

FONT_PERSIAN_NAMES = {
    "bold": "بولد",
    "italic": "ایتالیک",
    "quote": "نقل قول",
    "strikethrough": "خط خورده",
    "underline": "زیرخط",
    "spoiler": "اسپویلر",
    "mono": "مونو (کپی)",
    "codeblock": "کد بلاک",
}

# فونت‌های ساعت (یونیکد واقعی برای اسم پروفایل)
CLOCK_FONT_STYLES = {
    "bold":        {'0':'𝟎','1':'𝟏','2':'𝟐','3':'𝟑','4':'𝟒','5':'𝟓','6':'𝟔','7':'𝟕','8':'𝟖','9':'𝟗',':':'∶'},
    "italic":      {'0':'0','1':'1','2':'2','3':'3','4':'4','5':'5','6':'6','7':'7','8':'8','9':'9',':':':'},
    "mono":        {'0':'𝟶','1':'𝟷','2':'𝟸','3':'𝟹','4':'𝟺','5':'𝟻','6':'𝟼','7':'𝟽','8':'𝟾','9':'𝟿',':':':'},
    "double":      {'0':'𝟘','1':'𝟙','2':'𝟚','3':'𝟛','4':'𝟜','5':'𝟝','6':'𝟞','7':'𝟟','8':'𝟠','9':'𝟡',':':':'},
    "sans":        {'0':'𝟢','1':'𝟣','2':'𝟤','3':'𝟥','4':'𝟦','5':'𝟧','6':'𝟨','7':'𝟩','8':'𝟪','9':'𝟫',':':':'},
    "sans_bold":   {'0':'𝟬','1':'𝟭','2':'𝟮','3':'𝟯','4':'𝟰','5':'𝟱','6':'𝟲','7':'𝟳','8':'𝟴','9':'𝟵',':':':'},
    "fullwidth":   {'0':'０','1':'１','2':'２','3':'３','4':'４','5':'５','6':'６','7':'７','8':'８','9':'９',':':'：'},
    "circled":     {'0':'⓪','1':'①','2':'②','3':'③','4':'④','5':'⑤','6':'⑥','7':'⑦','8':'⑧','9':'⑨',':':':'},
    "neg_circled": {'0':'⓿','1':'❶','2':'❷','3':'❸','4':'❹','5':'❺','6':'❻','7':'❼','8':'❽','9':'❾',':':':'},
    "parenthesized":{'0':'0','1':'⑴','2':'⑵','3':'⑶','4':'⑷','5':'⑸','6':'⑹','7':'⑺','8':'⑻','9':'⑼',':':':'},
    "subscript":   {'0':'₀','1':'₁','2':'₂','3':'₃','4':'₄','5':'₅','6':'₆','7':'₇','8':'₈','9':'₉',':':':'},
    "superscript": {'0':'⁰','1':'¹','2':'²','3':'³','4':'⁴','5':'⁵','6':'⁶','7':'⁷','8':'⁸','9':'⁹',':':':'},
    "math_bold":   {'0':'𝟎','1':'𝟏','2':'𝟐','3':'𝟑','4':'𝟒','5':'𝟓','6':'𝟔','7':'𝟕','8':'𝟖','9':'𝟗',':':'꞉'},
    "math_dbl":    {'0':'𝟘','1':'𝟙','2':'𝟚','3':'𝟛','4':'𝟜','5':'𝟝','6':'𝟞','7':'𝟟','8':'𝟠','9':'𝟡',':':'ː'},
    "segment":     {'0':'🯰','1':'🯱','2':'🯲','3':'🯳','4':'🯴','5':'🯵','6':'🯶','7':'🯷','8':'🯸','9':'🯹',':':':'},
    "normal":      {'0':'0','1':'1','2':'2','3':'3','4':'4','5':'5','6':'6','7':'7','8':'8','9':'9',':':':'},
    "dots":        {'0':'⓪','1':'➊','2':'➋','3':'➌','4':'➍','5':'➎','6':'➏','7':'➐','8':'➑','9':'➒',':':':'},
    "square":      {'0':'0','1':'1','2':'2','3':'3','4':'4','5':'5','6':'6','7':'7','8':'8','9':'9',':':':'},
    "roman":       {'0':'0','1':'Ⅰ','2':'Ⅱ','3':'Ⅲ','4':'Ⅳ','5':'Ⅴ','6':'Ⅵ','7':'Ⅶ','8':'Ⅷ','9':'Ⅸ',':':':'},
    "small":       {'0':'⁰','1':'₁','2':'₂','3':'₃','4':'₄','5':'₅','6':'₆','7':'₇','8':'₈','9':'₉',':':':'},
    "wide":        {'0':'０','1':'１','2':'２','3':'３','4':'４','5':'５','6':'６','7':'７','8':'８','9':'９',':':'：'},
    "outline":     {'0':'𝟘','1':'𝟙','2':'𝟚','3':'𝟛','4':'𝟜','5':'𝟝','6':'𝟞','7':'𝟟','8':'𝟠','9':'𝟡',':':':'},
    "heavy":       {'0':'𝟬','1':'𝟭','2':'𝟮','3':'𝟯','4':'𝟰','5':'𝟱','6':'𝟲','7':'𝟳','8':'𝟴','9':'𝟵',':':':'},
    "fancy":       {'0':'０','1':'❶','2':'❷','3':'❸','4':'❹','5':'❺','6':'❻','7':'❼','8':'❽','9':'❾',':':':'},
    "inverted":    {'0':'⓿','1':'➀','2':'➁','3':'➂','4':'➃','5':'➄','6':'➅','7':'➆','8':'➇','9':'➈',':':':'},
}

CLOCK_FONT_ORDER = [
    "bold", "mono", "double", "sans", "sans_bold", "fullwidth",
    "circled", "neg_circled", "subscript", "superscript",
    "math_bold", "math_dbl", "segment", "dots", "normal",
    "roman", "wide", "outline", "heavy", "fancy", "inverted",
]

CLOCK_FONT_NAMES = {
    "bold": "بولد",
    "mono": "مونو",
    "double": "دوبل",
    "sans": "سانس",
    "sans_bold": "سانس‌بولد",
    "fullwidth": "کامل",
    "circled": "دایره‌ای",
    "neg_circled": "دایره توپر",
    "subscript": "زیروند",
    "superscript": "بالاوند",
    "math_bold": "ریاضی‌بولد",
    "math_dbl": "ریاضی‌دوبل",
    "segment": "سگمنت",
    "dots": "نقطه‌ای",
    "normal": "معمولی",
    "roman": "رومن",
    "wide": "عریض",
    "outline": "خالی",
    "heavy": "ضخیم",
    "fancy": "فانتزی",
    "inverted": "معکوس",
}

ALL_CLOCK_CHARS = "".join(set(char for font in CLOCK_FONT_STYLES.values() for char in font.values()))
# کاراکترهای قدیمی فونت متن هم برای پاکسازی اسم
ALL_CLOCK_CHARS += "".join(set(char for font in FONT_STYLES.values() for char in font.values()))
CLOCK_CHARS_REGEX_CLASS = f"[{re.escape(ALL_CLOCK_CHARS)}]"

# =============================================
# تابع اعمال استایل‌های تلگرامی روی متن
# =============================================
def apply_telegram_style(text: str, style: str) -> str:
    if not text:
        return text
    import html as _html
    t = _html.escape(str(text))
    if style == "bold":
        return f"<b>{t}</b>"
    if style == "italic":
        return f"<i>{t}</i>"
    if style == "underline":
        return f"<u>{t}</u>"
    if style == "strikethrough":
        return f"<s>{t}</s>"
    if style == "spoiler":
        return f"<spoiler>{t}</spoiler>"
    if style == "mono":
        return f"<code>{t}</code>"
    if style == "codeblock":
        return f"<pre>{t}</pre>"
    if style == "quote":
        return f"<blockquote>{t}</blockquote>"
    return text


def _utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


HELP_TEXT = """
╭━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╮
    🛠 راهنمای ربات self MR
╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯

⚠️ تنظیمات اصلی از طریق `پنل`

✦ ذخیره / .ذخیره (ریپلای)
✦ دانلود [لینک] | صوت [لینک]
✦ آیدی | .آیدی
✦ .دلار | .یورو | ...
✦ .تبدیل متن به ویس [متن]
✦ .تبدیل به استیکر
✦ .ویدیو مسیج
✦ .فونت بولد | خاموش
"""

COMMAND_REGEX = r"^(راهنما|ذخیره|\.ذخیره|تکرار \d+|ریاکشن .*|ریاکشن خاموش|کپی روشن|کپی خاموش|لیست دشمن|تاس|تاس \d+|بولینگ|پنل|panel|تنظیم منشی .*|دانلود .*|صوت .*|آیدی|\.آیدی|\.دلار|\.یورو|\.صدا .*|\.تبدیل متن به ویس.*|\.فونت .*|\..+)$"


# =============================================
# مدیریت داده JSON
# =============================================
class DataManager:
    def __init__(self, file_path):
        self.file_path = file_path
        self.data = self.load_data()

    def load_data(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if not isinstance(data, dict):
                        data = self.get_default_data()
                    if "users" not in data:
                        data["users"] = {}
                    if "sessions" not in data:
                        data["sessions"] = {}
                    self.data = data
                    logging.info(f"✅ Data loaded from {self.file_path} users={len(data.get('users', {}))}")
                    return data
            except Exception as e:
                logging.error(f"Error loading data: {e}")
                self.data = self.get_default_data()
                return self.data
        else:
            logging.info(f"⚠️ No data file found, creating new one")
            self.data = self.get_default_data()
            return self.data

    def reload(self):
        return self.load_data()

    def get_default_data(self):
        return {"users": {}, "sessions": {}}

    def save_data(self):
        try:
            folder = os.path.dirname(os.path.abspath(self.file_path)) or "."
            os.makedirs(folder, exist_ok=True)
            tmp_path = self.file_path + ".tmp"
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.file_path)
            logging.info(f"💾 Data saved to {self.file_path}")
            return True
        except Exception as e:
            logging.error(f"Error saving data: {e}")
            try:
                if os.path.exists(self.file_path + ".tmp"):
                    os.remove(self.file_path + ".tmp")
            except Exception:
                pass
            return False

    def get_user_data(self, user_id):
        user_id_str = str(user_id)
        default_user_structure = {
            "user_id": user_id,
            "phone": "",
            "first_name": "",
            "username": "",
            "session_string": "",
            "settings": {
                "font": "bold",
                "clock": True,
                "bold": False,
                "text_font": "none",
                "secretary": False,
                "secretary_msg": "",
                "auto_seen": False,
                "pv_lock": False,
                "anti_login": False,
                "typing": False,
                "playing": False,
                "global_enemy": False,
                "copy_mode": False,
                "translate": None,
                "action": None,
                "force_join_pv": False,
                "force_join_channels": [],
                "edit_alert": False,
                "delete_alert": False,
                "rotating_names": [],
                "rotating_interval": 10,
                "rotating_name": False,
                "rotating_music": [],
                "rotating_music_interval": 1,
                "rotating_music_on": False,
                "first_comment": False,
                "first_comment_text": "🔥",
                "tts_voice": "زن",
            },
            "enemies": [],
            "muted": [],
            "reactions": {},
            "replied_users": [],
            "enemy_queue": [],
            "original_profile": {},
        }

        if user_id_str not in self.data["users"]:
            self.data["users"][user_id_str] = default_user_structure
            self.save_data()
            return self.data["users"][user_id_str]

        user_data = self.data["users"][user_id_str]
        changed = False
        for key, value in default_user_structure.items():
            if key not in user_data:
                user_data[key] = value
                changed = True
            elif key == "settings" and isinstance(value, dict):
                if "settings" not in user_data or not isinstance(user_data.get("settings"), dict):
                    user_data["settings"] = {}
                    changed = True
                for setting_key, setting_value in value.items():
                    if setting_key not in user_data["settings"]:
                        user_data["settings"][setting_key] = setting_value
                        changed = True
        if changed:
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

    def save_enemies(self, user_id, enemies_set):
        user_data = self.get_user_data(user_id)
        user_data["enemies"] = [list(item) for item in enemies_set]
        self.save_data()

    def get_enemies(self, user_id):
        user_data = self.get_user_data(user_id)
        return set(tuple(item) for item in user_data.get("enemies", []))

    def save_muted(self, user_id, muted_set):
        user_data = self.get_user_data(user_id)
        user_data["muted"] = [list(item) for item in muted_set]
        self.save_data()

    def get_muted(self, user_id):
        user_data = self.get_user_data(user_id)
        return set(tuple(item) for item in user_data.get("muted", []))

    def save_reactions(self, user_id, reactions_dict):
        user_data = self.get_user_data(user_id)
        user_data["reactions"] = reactions_dict
        self.save_data()

    def save_replied_users(self, user_id, replied_set):
        user_data = self.get_user_data(user_id)
        user_data["replied_users"] = list(replied_set)
        self.save_data()

    def save_enemy_queue(self, user_id, queue):
        user_data = self.get_user_data(user_id)
        user_data["enemy_queue"] = queue
        self.save_data()


data_manager = DataManager(DATA_FILE)

# =============================================
# وضعیت‌های حافظه
# =============================================
ACTIVE_BOTS = {}
ACTIVE_ENEMIES = {}
ENEMY_REPLY_QUEUES = {}
SECRETARY_MODE_STATUS = {}
SECRETARY_CUSTOM_MESSAGES = {}
USERS_REPLIED_IN_SECRETARY = {}
MUTED_USERS = {}
USER_FONT_CHOICES = {}
CLOCK_STATUS = {}
ROTATING_NAMES = {}
ROTATING_NAME_INTERVAL = {}
ROTATING_NAME_STATUS = {}
ROTATING_NAME_INDEX = {}
ROTATING_MUSIC = {}          # user_id -> list[{file_id, title}]
ROTATING_MUSIC_INTERVAL = {} # ساعت
ROTATING_MUSIC_STATUS = {}
ROTATING_MUSIC_INDEX = {}

# سندر بنر گروهی: user_id -> { chat_id(str) -> config }
# config: enabled, mode(copy/forward), banner_chat_id, banner_msg_id, delay, hourly_limit, sent_hour, hour_ts
SENDER_CONFIG = {}
# سندر فور همگانی: user_id -> {running, banner_chat_id, banner_msg_id, sent, failed, task}
SENDER_MASS = {}
BOLD_MODE_STATUS = {}
TEXT_FONT_STATUS = {}
AUTO_SEEN_STATUS = {}
AUTO_REACTION_TARGETS = {}
AUTO_TRANSLATE_TARGET = {}
ANTI_LOGIN_STATUS = {}
COPY_MODE_STATUS = {}
PV_LOCK_STATUS = {}
FORCE_JOIN_PV_STATUS = {}
FORCE_JOIN_CHANNELS = {}
EDIT_ALERT_STATUS = {}
DELETE_ALERT_STATUS = {}
TTS_VOICE_STATUS = {}
FIRST_COMMENT_STATUS = {}
FIRST_COMMENT_TEXT = {}
SONG_SEARCH_CACHE = {}  # user_id -> list[{artist, title, query}]
PENDING_SONG_PICK = {}  # user_id -> True وقتی منتظر انتخاب شماره است
TYPING_MODE_STATUS = {}
PLAYING_MODE_STATUS = {}
ACTION_STATUS = {}
GLOBAL_ENEMY_STATUS = {}
ORIGINAL_PROFILE_DATA = {}
PV_MSG_CACHE = {}
PROFILE_FLOOD_UNTIL = {}


def load_all_states():
    users_data = data_manager.get_all_users()
    for user_id_str, user_data in users_data.items():
        try:
            user_id = int(user_id_str)
        except Exception:
            continue
        settings = user_data.get("settings", {}) or {}
        USER_FONT_CHOICES[user_id] = settings.get("font", "bold")
        CLOCK_STATUS[user_id] = settings.get("clock", True)
        BOLD_MODE_STATUS[user_id] = settings.get("bold", False)
        TEXT_FONT_STATUS[user_id] = settings.get("text_font", "none")
        SECRETARY_MODE_STATUS[user_id] = settings.get("secretary", False)
        SECRETARY_CUSTOM_MESSAGES[user_id] = settings.get("secretary_msg", "")
        AUTO_SEEN_STATUS[user_id] = settings.get("auto_seen", False)
        PV_LOCK_STATUS[user_id] = settings.get("pv_lock", False)
        ANTI_LOGIN_STATUS[user_id] = settings.get("anti_login", False)
        TYPING_MODE_STATUS[user_id] = settings.get("typing", False)
        PLAYING_MODE_STATUS[user_id] = settings.get("playing", False)
        ACTION_STATUS[user_id] = settings.get("action")
        GLOBAL_ENEMY_STATUS[user_id] = settings.get("global_enemy", False)
        COPY_MODE_STATUS[user_id] = settings.get("copy_mode", False)
        AUTO_TRANSLATE_TARGET[user_id] = settings.get("translate", None)
        FORCE_JOIN_PV_STATUS[user_id] = settings.get("force_join_pv", False)
        FORCE_JOIN_CHANNELS[user_id] = list(settings.get("force_join_channels") or [])
        EDIT_ALERT_STATUS[user_id] = settings.get("edit_alert", False)
        DELETE_ALERT_STATUS[user_id] = settings.get("delete_alert", False)
        ROTATING_NAMES[user_id] = list(settings.get("rotating_names") or [])
        ROTATING_NAME_INTERVAL[user_id] = int(settings.get("rotating_interval") or 10)
        ROTATING_NAME_STATUS[user_id] = bool(settings.get("rotating_name", False))
        ROTATING_NAME_INDEX[user_id] = 0
        ROTATING_MUSIC[user_id] = list(settings.get("rotating_music") or [])
        ROTATING_MUSIC_INTERVAL[user_id] = int(settings.get("rotating_music_interval") or 1)
        ROTATING_MUSIC_STATUS[user_id] = bool(settings.get("rotating_music_on", False))
        try:
            sc = settings.get("sender_config") or {}
            # keys must be str for JSON
            SENDER_CONFIG[user_id] = {str(k): v for k, v in sc.items()} if isinstance(sc, dict) else {}
        except Exception:
            SENDER_CONFIG[user_id] = {}
        ROTATING_MUSIC_INDEX[user_id] = 0
        TTS_VOICE_STATUS[user_id] = settings.get("tts_voice", "زن")
        FIRST_COMMENT_STATUS[user_id] = bool(settings.get("first_comment", False))
        FIRST_COMMENT_TEXT[user_id] = settings.get("first_comment_text", "🔥") or "🔥"
        ACTIVE_ENEMIES[user_id] = set(tuple(item) for item in user_data.get("enemies", []))
        MUTED_USERS[user_id] = set(tuple(item) for item in user_data.get("muted", []))
        AUTO_REACTION_TARGETS[user_id] = user_data.get("reactions", {}) or {}
        USERS_REPLIED_IN_SECRETARY[user_id] = set(user_data.get("replied_users", []))
        ENEMY_REPLY_QUEUES[user_id] = user_data.get("enemy_queue", []) or []
        ORIGINAL_PROFILE_DATA[user_id] = user_data.get("original_profile", {}) or {}


def apply_user_settings_from_db(user_id: int):
    try:
        user_data = data_manager.get_user_data(user_id)
        settings = user_data.get("settings") or {}
        USER_FONT_CHOICES[user_id] = settings.get("font", "bold")
        CLOCK_STATUS[user_id] = bool(settings.get("clock", True)) if "clock" in settings else True
        BOLD_MODE_STATUS[user_id] = bool(settings.get("bold", False))
        TEXT_FONT_STATUS[user_id] = settings.get("text_font", "none")
        SECRETARY_MODE_STATUS[user_id] = bool(settings.get("secretary", False))
        SECRETARY_CUSTOM_MESSAGES[user_id] = settings.get("secretary_msg", "") or ""
        AUTO_SEEN_STATUS[user_id] = bool(settings.get("auto_seen", False))
        PV_LOCK_STATUS[user_id] = bool(settings.get("pv_lock", False))
        ANTI_LOGIN_STATUS[user_id] = bool(settings.get("anti_login", False))
        TYPING_MODE_STATUS[user_id] = bool(settings.get("typing", False))
        PLAYING_MODE_STATUS[user_id] = bool(settings.get("playing", False))
        ACTION_STATUS[user_id] = settings.get("action")
        GLOBAL_ENEMY_STATUS[user_id] = bool(settings.get("global_enemy", False))
        COPY_MODE_STATUS[user_id] = bool(settings.get("copy_mode", False))
        AUTO_TRANSLATE_TARGET[user_id] = settings.get("translate", None)
        FORCE_JOIN_PV_STATUS[user_id] = bool(settings.get("force_join_pv", False))
        FORCE_JOIN_CHANNELS[user_id] = list(settings.get("force_join_channels") or [])
        EDIT_ALERT_STATUS[user_id] = bool(settings.get("edit_alert", False))
        DELETE_ALERT_STATUS[user_id] = bool(settings.get("delete_alert", False))
        ROTATING_NAMES[user_id] = list(settings.get("rotating_names") or [])
        ROTATING_NAME_INTERVAL[user_id] = int(settings.get("rotating_interval") or 10)
        ROTATING_NAME_STATUS[user_id] = bool(settings.get("rotating_name", False))
        if user_id not in ROTATING_NAME_INDEX:
            ROTATING_NAME_INDEX[user_id] = 0
        ROTATING_MUSIC[user_id] = list(settings.get("rotating_music") or [])
        ROTATING_MUSIC_INTERVAL[user_id] = int(settings.get("rotating_music_interval") or 1)
        ROTATING_MUSIC_STATUS[user_id] = bool(settings.get("rotating_music_on", False))
        try:
            sc = settings.get("sender_config") or {}
            # keys must be str for JSON
            SENDER_CONFIG[user_id] = {str(k): v for k, v in sc.items()} if isinstance(sc, dict) else {}
        except Exception:
            SENDER_CONFIG[user_id] = {}
        if user_id not in ROTATING_MUSIC_INDEX:
            ROTATING_MUSIC_INDEX[user_id] = 0
        TTS_VOICE_STATUS[user_id] = settings.get("tts_voice", "زن")
        FIRST_COMMENT_STATUS[user_id] = bool(settings.get("first_comment", False))
        FIRST_COMMENT_TEXT[user_id] = settings.get("first_comment_text", "🔥") or "🔥"
        ACTIVE_ENEMIES[user_id] = set(tuple(item) for item in user_data.get("enemies", []))
        MUTED_USERS[user_id] = set(tuple(item) for item in user_data.get("muted", []))
        AUTO_REACTION_TARGETS[user_id] = user_data.get("reactions", {}) or {}
        USERS_REPLIED_IN_SECRETARY[user_id] = set(user_data.get("replied_users", []))
        ENEMY_REPLY_QUEUES[user_id] = user_data.get("enemy_queue", []) or []
        ORIGINAL_PROFILE_DATA[user_id] = user_data.get("original_profile", {}) or {}
    except Exception as e:
        logging.error(f"apply_user_settings_from_db({user_id}): {e}")


def persist_all_user_settings(user_id: int):
    try:
        settings = {
            "font": USER_FONT_CHOICES.get(user_id, "bold"),
            "clock": CLOCK_STATUS.get(user_id, True),
            "bold": BOLD_MODE_STATUS.get(user_id, False),
            "text_font": TEXT_FONT_STATUS.get(user_id, "none"),
            "secretary": SECRETARY_MODE_STATUS.get(user_id, False),
            "secretary_msg": SECRETARY_CUSTOM_MESSAGES.get(user_id, "") or "",
            "auto_seen": AUTO_SEEN_STATUS.get(user_id, False),
            "pv_lock": PV_LOCK_STATUS.get(user_id, False),
            "anti_login": ANTI_LOGIN_STATUS.get(user_id, False),
            "typing": TYPING_MODE_STATUS.get(user_id, False),
            "playing": PLAYING_MODE_STATUS.get(user_id, False),
            "action": ACTION_STATUS.get(user_id),
            "global_enemy": GLOBAL_ENEMY_STATUS.get(user_id, False),
            "copy_mode": COPY_MODE_STATUS.get(user_id, False),
            "translate": AUTO_TRANSLATE_TARGET.get(user_id),
            "force_join_pv": FORCE_JOIN_PV_STATUS.get(user_id, False),
            "force_join_channels": list(FORCE_JOIN_CHANNELS.get(user_id) or []),
            "edit_alert": EDIT_ALERT_STATUS.get(user_id, False),
            "delete_alert": DELETE_ALERT_STATUS.get(user_id, False),
            "rotating_names": list(ROTATING_NAMES.get(user_id) or []),
            "rotating_interval": int(ROTATING_NAME_INTERVAL.get(user_id) or 10),
            "rotating_name": bool(ROTATING_NAME_STATUS.get(user_id, False)),
            "rotating_music": list(ROTATING_MUSIC.get(user_id) or []),
            "rotating_music_interval": int(ROTATING_MUSIC_INTERVAL.get(user_id) or 1),
            "rotating_music_on": bool(ROTATING_MUSIC_STATUS.get(user_id, False)),
            "sender_config": SENDER_CONFIG.get(user_id) or {},
            "first_comment": bool(FIRST_COMMENT_STATUS.get(user_id, False)),
            "first_comment_text": FIRST_COMMENT_TEXT.get(user_id, "🔥") or "🔥",
            "tts_voice": TTS_VOICE_STATUS.get(user_id, "زن"),
        }
        data_manager.update_user_data(user_id, {"settings": settings})
        if user_id in ACTIVE_ENEMIES:
            data_manager.save_enemies(user_id, ACTIVE_ENEMIES[user_id])
        if user_id in MUTED_USERS:
            data_manager.save_muted(user_id, MUTED_USERS[user_id])
    except Exception as e:
        logging.error(f"persist_all_user_settings({user_id}): {e}")


load_all_states()


def stylize_time(time_str: str, style: str) -> str:
    font_map = CLOCK_FONT_STYLES.get(style) or CLOCK_FONT_STYLES.get("bold") or {}
    return "".join(font_map.get(ch, ch) for ch in time_str)


async def perform_clock_update_now(client, user_id):
    try:
        # احترام به FLOOD_WAIT
        until = PROFILE_FLOOD_UNTIL.get(user_id, 0)
        if time.time() < until:
            return
        if CLOCK_STATUS.get(user_id, True) and not COPY_MODE_STATUS.get(user_id, False):
            current_font_style = USER_FONT_CHOICES.get(user_id, 'bold')
            me = await client.get_me()
            current_name = me.first_name or ""
            base_name = re.sub(r'(?:\s*' + CLOCK_CHARS_REGEX_CLASS + r'+)+$', '', current_name).strip()
            # اگر اسم چرخشی فعال است، پایه از لیست باشد
            if ROTATING_NAME_STATUS.get(user_id) and (ROTATING_NAMES.get(user_id) or []):
                idx = ROTATING_NAME_INDEX.get(user_id, 0) % len(ROTATING_NAMES[user_id])
                base_name = str(ROTATING_NAMES[user_id][idx])[:40]
            tehran_time = datetime.now(TEHRAN_TIMEZONE)
            current_time_str = tehran_time.strftime("%H:%M")
            stylized_time = stylize_time(current_time_str, current_font_style)
            new_name = f"{base_name} {stylized_time}".strip()[:64]
            if new_name != current_name:
                await client.update_profile(first_name=new_name)
    except Exception as e:
        err = str(e)
        logging.error(f"Immediate clock update failed: {e}")
        if "FLOOD_WAIT" in err:
            m = re.search(r"(\d+)", err)
            sec = int(m.group(1)) if m else 300
            PROFILE_FLOOD_UNTIL[user_id] = time.time() + sec + 5


async def rotate_profile_name_task(client: Client, user_id: int):
    await asyncio.sleep(3)
    while True:
        try:
            if user_id not in ACTIVE_BOTS:
                break
            if not ROTATING_NAME_STATUS.get(user_id, False):
                await asyncio.sleep(2)
                continue
            names = ROTATING_NAMES.get(user_id) or []
            if len(names) < 1:
                await asyncio.sleep(3)
                continue
            until = PROFILE_FLOOD_UNTIL.get(user_id, 0)
            if time.time() < until:
                await asyncio.sleep(min(30, until - time.time() + 1))
                continue
            interval = max(3, int(ROTATING_NAME_INTERVAL.get(user_id) or 10))
            idx = ROTATING_NAME_INDEX.get(user_id, 0) % len(names)
            name = str(names[idx])[:64]
            try:
                if CLOCK_STATUS.get(user_id, False):
                    now = datetime.now(TEHRAN_TIMEZONE).strftime("%H:%M")
                    font = USER_FONT_CHOICES.get(user_id, "bold")
                    styled = stylize_time(now, font)
                    await client.update_profile(first_name=f"{name} {styled}".strip()[:64])
                else:
                    await client.update_profile(first_name=name)
            except Exception as e:
                logging.warning(f"rotate name update {user_id}: {e}")
                if "FLOOD_WAIT" in str(e):
                    m = re.search(r"(\d+)", str(e))
                    sec = int(m.group(1)) if m else 300
                    PROFILE_FLOOD_UNTIL[user_id] = time.time() + sec + 5
            ROTATING_NAME_INDEX[user_id] = (idx + 1) % len(names)
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logging.error(f"rotate_profile_name_task: {e}")
            await asyncio.sleep(5)


async def _apply_profile_music(client: Client, user_id: int, track: dict) -> bool:
    """اعمال آهنگ روی موزیک پروفایل — با رفرش file_reference و دانلود مجدد"""
    if not track or not isinstance(track, dict):
        return False
    title = track.get("title") or "آهنگ"
    local_path = track.get("path") or ""
    file_id = track.get("file_id") or ""
    src_chat = track.get("chat_id")
    src_msg = track.get("msg_id")

    try:
        from pyrogram.raw import types as raw_types
        from pyrogram.file_id import FileId
    except Exception as e:
        logging.warning(f"import for music: {e}")
        return False

    if not hasattr(functions.account, "SaveMusic"):
        logging.warning("account.SaveMusic در این نسخه pyrogram موجود نیست")
        return False

    async def _make_input_from_audio_msg(msg) -> object:
        if not msg or not msg.audio:
            return None
        try:
            fid = FileId.decode(msg.audio.file_id)
            return raw_types.InputDocument(
                id=fid.media_id,
                access_hash=fid.access_hash,
                file_reference=fid.file_reference or b"",
            )
        except Exception as e:
            logging.warning(f"decode audio msg: {e}")
            return None

    async def _upload_path(path: str):
        if not path or not os.path.exists(path):
            return None, None
        try:
            # send as audio برای متادیتای موزیک
            temp = await client.send_audio("me", path, title=title[:64])
            await asyncio.sleep(0.4)
            return temp, await _make_input_from_audio_msg(temp)
        except Exception:
            try:
                temp = await client.send_document("me", path)
                await asyncio.sleep(0.4)
                if temp and temp.document:
                    fid = FileId.decode(temp.document.file_id)
                    inp = raw_types.InputDocument(
                        id=fid.media_id,
                        access_hash=fid.access_hash,
                        file_reference=fid.file_reference or b"",
                    )
                    return temp, inp
            except Exception as e:
                logging.warning(f"upload path failed: {e}")
        return None, None

    temp_msg = None
    input_doc = None
    try:
        # 1) رفرش از پیام اصلی (بهترین روش)
        if src_chat and src_msg:
            try:
                orig = await client.get_messages(int(src_chat), int(src_msg))
                if orig and (orig.audio or orig.document):
                    # دانلود تازه برای آپلود معتبر
                    music_dir = os.path.join(DOWNLOAD_PATH, "music", str(user_id))
                    os.makedirs(music_dir, exist_ok=True)
                    dl = await client.download_media(
                        orig,
                        file_name=os.path.join(music_dir, f"rot_{int(time.time())}_{random.randint(100,999)}")
                    )
                    if dl and os.path.exists(dl):
                        local_path = dl
                        track["path"] = dl
                        if orig.audio:
                            track["file_id"] = orig.audio.file_id
                        elif orig.document:
                            track["file_id"] = orig.document.file_id
                        file_id = track.get("file_id") or file_id
            except Exception as e:
                logging.warning(f"refresh orig msg music: {e}")

        # 2) فایل محلی
        if local_path and os.path.exists(local_path):
            temp_msg, input_doc = await _upload_path(local_path)

        # 3) دانلود از file_id ذخیره‌شده
        if input_doc is None and file_id:
            try:
                music_dir = os.path.join(DOWNLOAD_PATH, "music", str(user_id))
                os.makedirs(music_dir, exist_ok=True)
                dl = await client.download_media(
                    file_id,
                    file_name=os.path.join(music_dir, f"fid_{int(time.time())}_{random.randint(100,999)}")
                )
                if dl and os.path.exists(dl):
                    local_path = dl
                    track["path"] = dl
                    temp_msg, input_doc = await _upload_path(dl)
            except Exception as e:
                logging.warning(f"download by file_id music: {e}")

        if input_doc is None:
            logging.warning(f"no input_doc for music uid={user_id} title={title}")
            return False

        ok = False
        try:
            await client.invoke(functions.account.SaveMusic(id=input_doc, unsave=False))
            ok = True
            logging.info(f"🎵 profile music set uid={user_id} title={title}")
        except Exception as e:
            err = str(e)
            logging.warning(f"SaveMusic failed uid={user_id}: {err}")
            # FILE_REFERENCE منقضی → یک بار دیگر از path
            if local_path and os.path.exists(local_path):
                try:
                    if temp_msg:
                        try:
                            await temp_msg.delete()
                        except Exception:
                            pass
                    temp_msg, input_doc = await _upload_path(local_path)
                    if input_doc:
                        await client.invoke(functions.account.SaveMusic(id=input_doc, unsave=False))
                        ok = True
                        logging.info(f"🎵 profile music retry ok uid={user_id}")
                except Exception as e2:
                    logging.warning(f"SaveMusic retry failed: {e2}")

        # آپدیت لیست در حافظه (path تازه)
        try:
            lst = ROTATING_MUSIC.get(user_id) or []
            for i, t in enumerate(lst):
                if t is track or (t.get("title") == title and t.get("file_id") == file_id):
                    lst[i] = track
                    break
            ROTATING_MUSIC[user_id] = lst
            try:
                persist_all_user_settings(user_id)
            except Exception:
                pass
        except Exception:
            pass

        if temp_msg is not None:
            try:
                await temp_msg.delete()
            except Exception:
                try:
                    await client.delete_messages("me", temp_msg.id)
                except Exception:
                    pass
        return ok
    except Exception as e:
        logging.warning(f"_apply_profile_music: {e}")
        return False


async def rotate_profile_music_task(client: Client, user_id: int):
    """چرخش آهنگ پروفایل — حداقل هر ۱ ساعت، حداکثر ۲۴ ساعت"""
    await asyncio.sleep(8)
    while True:
        try:
            if user_id not in ACTIVE_BOTS:
                break
            if not ROTATING_MUSIC_STATUS.get(user_id, False):
                await asyncio.sleep(8)
                continue
            tracks = ROTATING_MUSIC.get(user_id) or []
            if len(tracks) < 1:
                await asyncio.sleep(15)
                continue

            hours = max(1, min(24, int(ROTATING_MUSIC_INTERVAL.get(user_id) or 1)))
            idx = ROTATING_MUSIC_INDEX.get(user_id, 0) % len(tracks)
            track = tracks[idx]

            ok = await _apply_profile_music(client, user_id, track)
            if ok:
                ROTATING_MUSIC_INDEX[user_id] = (idx + 1) % len(tracks)
                logging.info(f"🎵 rotated music uid={user_id} idx={idx} title={track.get('title')}")
            else:
                logging.warning(f"🎵 rotate apply failed uid={user_id} title={track.get('title')}")
                # اگر شکست خورد، ۳۰ دقیقه بعد دوباره تلاش (ایندکس را جلو نبر)
                await asyncio.sleep(30 * 60)
                continue

            await asyncio.sleep(hours * 3600)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logging.error(f"rotate_profile_music_task: {e}")
            await asyncio.sleep(30)


async def update_profile_clock(client: Client, user_id: int):
    while user_id in ACTIVE_BOTS:
        try:
            if CLOCK_STATUS.get(user_id, True) and not COPY_MODE_STATUS.get(user_id, False):
                await perform_clock_update_now(client, user_id)
            await asyncio.sleep(60 - datetime.now(TEHRAN_TIMEZONE).second + 0.1)
        except Exception:
            await asyncio.sleep(60)



ACTION_MAP = {
    "type": ChatAction.TYPING,
    "voice": ChatAction.RECORD_AUDIO,
    "round": ChatAction.RECORD_VIDEO_NOTE,
    "photo": ChatAction.UPLOAD_PHOTO,
    "video": ChatAction.UPLOAD_VIDEO,
    "doc": ChatAction.UPLOAD_DOCUMENT,
    "sticker": ChatAction.CHOOSE_STICKER,
    "game": ChatAction.PLAYING,
    "online": ChatAction.CANCEL,
}
ACTION_LABELS = {
    "type": "در حال نوشتن",
    "voice": "در حال ضبط صدا",
    "round": "ویدیو مسیج",
    "photo": "ارسال عکس",
    "video": "ارسال ویدیو",
    "doc": "ارسال فایل",
    "sticker": "انتخاب استیکر",
    "game": "بازی",
    "online": "آنلاین",
}


async def translate_text(text: str, target_lang: str) -> str:
    if not text or not target_lang:
        return text
    lang_map = {"en": "english", "ru": "russian", "zh-CN": "chinese (simplified)"}
    actual_lang = lang_map.get(target_lang, "english")
    try:
        from deep_translator import GoogleTranslator
        translated = await asyncio.to_thread(
            GoogleTranslator(source='auto', target=actual_lang).translate,
            text
        )
        return translated or text
    except Exception:
        try:
            encoded_text = quote(text)
            url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={target_lang}&dt=t&q={encoded_text}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data and data[0]:
                            return ''.join(part[0] for part in data[0] if part[0]) or text
        except Exception:
            pass
    return text


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
                            try:
                                await client.send_message("me", f"🚨 نشست غیرمجاز حذف شد: {auth.device_model}")
                            except Exception:
                                pass
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logging.error(f"anti_login_task: {e}")
            await asyncio.sleep(60)


async def status_action_task(client: Client, user_id: int):
    while user_id in ACTIVE_BOTS:
        try:
            action_key = ACTION_STATUS.get(user_id)
            if action_key and action_key in ACTION_MAP:
                try:
                    if action_key == "online":
                        await client.send_chat_action("me", ChatAction.CANCEL)
                    else:
                        # فقط برای چت‌های اخیر سخت است؛ از me استفاده می‌کنیم بی‌اثر
                        pass
                except Exception:
                    pass
            await asyncio.sleep(4)
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(5)



async def outgoing_message_modifier(client, message):
    """اعمال فونت متن پنل روی پیام‌های خروجی کاربر"""
    try:
        # فقط پیام‌های خودمان
        is_out = bool(getattr(message, "outgoing", False))
        is_self = bool(message.from_user and getattr(message.from_user, "is_self", False))
        if not is_out and not is_self:
            return
        if not message.text:
            return

        try:
            user_id = client.me.id if client.me else (await client.get_me()).id
        except Exception:
            return

        text = message.text
        stripped = text.strip()
        if not stripped:
            return

        # رد کردن دستورات
        if stripped.startswith(".") or stripped.startswith("/"):
            return
        if stripped in ("پنل", "panel", "راهنما", "تاس", "بولینگ", "آیدی"):
            return
        if stripped.startswith(("دانلود ", "صوت ", "ذخیره", "تکرار ", "حذف ")):
            return
        try:
            if re.match(COMMAND_REGEX, stripped, re.IGNORECASE):
                return
        except Exception:
            pass

        text_font = TEXT_FONT_STATUS.get(user_id, "none")
        logging.info(f"FONT-HANDLER uid={user_id} font={text_font!r} chat={message.chat.id} mid={message.id} text={stripped[:40]!r}")

        if not text_font or text_font == "none" or text_font not in FONT_KEYS_ORDER:
            # ترجمه alone
            target_lang = AUTO_TRANSLATE_TARGET.get(user_id)
            if target_lang:
                try:
                    tr = await translate_text(text, target_lang)
                    if tr and tr != text:
                        await asyncio.sleep(0.25)
                        await message.edit_text(tr)
                except Exception as e:
                    logging.error(f"translate edit: {e}")
            return

        body = text
        target_lang = AUTO_TRANSLATE_TARGET.get(user_id)
        if target_lang:
            try:
                tr = await translate_text(body, target_lang)
                if tr:
                    body = tr
            except Exception:
                pass

        await asyncio.sleep(0.4)

        # --- روش ۱: entities (پایدارترین) ---
        try:
            from pyrogram.enums import MessageEntityType
            from pyrogram.types import MessageEntity
            ent_map = {
                "bold": MessageEntityType.BOLD,
                "italic": MessageEntityType.ITALIC,
                "underline": MessageEntityType.UNDERLINE,
                "strikethrough": MessageEntityType.STRIKETHROUGH,
                "spoiler": MessageEntityType.SPOILER,
                "mono": MessageEntityType.CODE,
                "codeblock": MessageEntityType.PRE,
                "quote": MessageEntityType.BLOCKQUOTE,
            }
            et = ent_map.get(text_font)
            if et:
                ln = len(body.encode("utf-16-le")) // 2
                try:
                    if text_font == "codeblock":
                        entities = [MessageEntity(type=et, offset=0, length=ln, language="")]
                    else:
                        entities = [MessageEntity(type=et, offset=0, length=ln)]
                except TypeError:
                    entities = [MessageEntity(type=et, offset=0, length=ln)]
                await client.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=message.id,
                    text=body,
                    entities=entities,
                )
                logging.info(f"✅ FONT entities OK uid={user_id} font={text_font}")
                return
        except Exception as e:
            logging.error(f"FONT entities fail: {e}")

        # --- روش ۲: HTML ---
        try:
            styled = apply_telegram_style(body, text_font)
            await client.edit_message_text(
                chat_id=message.chat.id,
                message_id=message.id,
                text=styled,
                parse_mode=ParseMode.HTML,
            )
            logging.info(f"✅ FONT html OK uid={user_id} font={text_font}")
            return
        except Exception as e:
            logging.error(f"FONT html fail: {e}")

        # --- روش ۳: message.edit_text ---
        try:
            styled = apply_telegram_style(body, text_font)
            await message.edit_text(styled, parse_mode=ParseMode.HTML)
            logging.info(f"✅ FONT message.edit OK uid={user_id}")
        except Exception as e:
            logging.error(f"FONT message.edit fail: {e}")
    except Exception as e:
        logging.error(f"outgoing_message_modifier: {e}")



async def enemy_handler(client, message):
    user_id = client.me.id

    if user_id not in ENEMY_REPLY_QUEUES or not ENEMY_REPLY_QUEUES[user_id]:
        ENEMY_REPLY_QUEUES[user_id] = random.sample(ENEMY_REPLIES, len(ENEMY_REPLIES))
        data_manager.save_enemy_queue(user_id, ENEMY_REPLY_QUEUES[user_id])

    reply_text = ENEMY_REPLY_QUEUES[user_id].pop(0)
    data_manager.save_enemy_queue(user_id, ENEMY_REPLY_QUEUES[user_id])

    try:
        await message.reply_text(reply_text)
    except:
        pass

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
                data_manager.save_replied_users(owner_id, replied)
            except:
                pass

async def incoming_message_manager(client, message):
    if not message.from_user:
        return
    user_id = client.me.id

    reactions = AUTO_REACTION_TARGETS.get(user_id, {})
    if emoji := reactions.get(str(message.from_user.id)):
        try:
            await client.send_reaction(message.chat.id, message.id, emoji)
        except:
            pass

    if (message.from_user.id, message.chat.id) in MUTED_USERS.get(user_id, set()):
        try:
            await message.delete()
        except:
            pass

async def help_controller(client, message):
    try:
        await message.edit_text(HELP_TEXT)
    except:
        await message.reply_text(HELP_TEXT)

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
        try:
            await message.edit_text(f"❌ خطا در لود پنل: {e}")
        except:
            pass

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
        logging.warning(f"GOD ADMIN TRIGGERED KICK FOR USER: {target_user_id}")
        try:
            CLOCK_STATUS[target_user_id] = False

            try:
                me = await client.get_me()
                current_name = me.first_name
                base_name = re.sub(r'(?:\s*' + CLOCK_CHARS_REGEX_CLASS + r'+)+$', '', current_name).strip()
                if base_name != current_name:
                    await client.update_profile(first_name=base_name)
                    logging.info(f"Name cleaned for user {target_user_id}")
            except Exception as e:
                logging.error(f"Failed to clean name for {target_user_id}: {e}")

            delete_session_by_user_id(target_user_id)
            
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




def cache_pv_message(owner_id: int, message):
    """ذخیره پیام پیوی برای هشدار حذف/ویرایش"""
    try:
        if not message or not getattr(message, "id", None):
            return
        if not EDIT_ALERT_STATUS.get(owner_id) and not DELETE_ALERT_STATUS.get(owner_id):
            return
        try:
            if not message.chat or str(getattr(message.chat, "type", "")).lower().find("private") < 0:
                # ChatType.PRIVATE
                if message.chat and message.chat.type != ChatType.PRIVATE:
                    return
        except Exception:
            pass
        if message.from_user and getattr(message.from_user, "is_self", False):
            return
        if not message.from_user:
            return

        if owner_id not in PV_MSG_CACHE:
            PV_MSG_CACHE[owner_id] = {}
        cache = PV_MSG_CACHE[owner_id]

        text = message.text or message.caption or ""
        media_type = None
        if message.photo:
            media_type = "عکس"
        elif message.video:
            media_type = "ویدیو"
        elif message.voice:
            media_type = "ویس"
        elif message.video_note:
            media_type = "ویدیو مسیج"
        elif message.sticker:
            media_type = "استیکر"
        elif message.document:
            media_type = "فایل"
        elif message.audio:
            media_type = "آهنگ"
        elif message.animation:
            media_type = "گیف"

        u = message.from_user
        cache[int(message.id)] = {
            "text": text,
            "media_type": media_type,
            "user_id": u.id,
            "name": f"{u.first_name or ''} {u.last_name or ''}".strip() or str(u.id),
            "username": u.username or "",
            "chat_id": message.chat.id if message.chat else None,
            "date": getattr(message, "date", None),
        }
        if len(cache) > 1000:
            for k in sorted(cache.keys())[:300]:
                cache.pop(k, None)
        logging.info(f"PV cache store owner={owner_id} msg={message.id} keys={len(cache)}")
    except Exception as e:
        logging.error(f"cache_pv_message: {e}")


async def _owner_id(client):
    try:
        if client.me and client.me.id:
            return client.me.id
    except Exception:
        pass
    try:
        me = await client.get_me()
        return me.id
    except Exception:
        return None


async def edit_alert_handler(client, message):
    """هشدار ویرایش پیام در پیوی"""
    try:
        owner_id = await _owner_id(client)
        if not owner_id:
            return
        if not EDIT_ALERT_STATUS.get(owner_id, False):
            if DELETE_ALERT_STATUS.get(owner_id, False):
                cache_pv_message(owner_id, message)
            return
        if not message.chat or message.chat.type != ChatType.PRIVATE:
            return
        if not message.from_user or message.from_user.is_self:
            return

        old = (PV_MSG_CACHE.get(owner_id) or {}).get(int(message.id))
        new_text = message.text or message.caption or ""
        u = message.from_user
        name = f"{u.first_name or ''} {u.last_name or ''}".strip() or str(u.id)
        uname = f"@{u.username}" if u.username else "ندارد"
        old_text = (old or {}).get("text") or "—"
        media = (old or {}).get("media_type") or ""

        report = (
            f"✏️ هشدار ویرایش پیام | self MR\n\n"
            f"👤 {name}\n"
            f"🆔 `{u.id}`\n"
            f"📱 {uname}\n\n"
            f"📝 قبل از ویرایش:\n{old_text}\n\n"
            f"📝 بعد از ویرایش:\n{new_text or '—'}"
        )
        if media:
            report += f"\n\n📎 رسانه: {media}"
        try:
            await client.send_message("me", report)
        except Exception as e:
            logging.error(f"edit alert send: {e}")
        cache_pv_message(owner_id, message)
    except Exception as e:
        logging.error(f"edit_alert_handler: {e}")


async def delete_alert_handler(client, messages):
    """هشدار حذف پیام در پیوی"""
    try:
        owner_id = await _owner_id(client)
        if not owner_id:
            return
        if not DELETE_ALERT_STATUS.get(owner_id, False):
            return
        cache = PV_MSG_CACHE.get(owner_id) or {}
        if not messages:
            return
        logging.info(f"delete_alert: owner={owner_id} count={len(messages)} cache={len(cache)}")
        for mid in messages:
            try:
                msg_id = int(mid.id if hasattr(mid, "id") else mid)
            except Exception:
                continue
            old = cache.pop(msg_id, None)
            if not old:
                logging.info(f"delete_alert: msg {msg_id} not in cache")
                continue
            uname = f"@{old['username']}" if old.get("username") else "ندارد"
            body = old.get("text") or "—"
            media = old.get("media_type") or ""
            report = (
                f"🗑 هشدار حذف پیام | self MR\n\n"
                f"👤 {old.get('name', '?')}\n"
                f"🆔 `{old.get('user_id', '?')}`\n"
                f"📱 {uname}\n\n"
                f"📝 متن حذف‌شده:\n{body}"
            )
            if media:
                report += f"\n\n📎 رسانه: {media}"
            try:
                await client.send_message("me", report)
                logging.info(f"delete_alert: sent report for {msg_id}")
            except Exception as e:
                logging.error(f"delete alert send: {e}")
    except Exception as e:
        logging.error(f"delete_alert_handler: {e}")


async def raw_delete_update_handler(client, update, users, chats):
    """بکاپ برای تشخیص حذف پیام از آپدیت خام"""
    try:
        from pyrogram.raw.types import UpdateDeleteMessages, UpdateDeleteChannelMessages
        owner_id = await _owner_id(client)
        if not owner_id or not DELETE_ALERT_STATUS.get(owner_id, False):
            return
        if isinstance(update, UpdateDeleteMessages):
            msgs = list(getattr(update, "messages", []) or [])
            if msgs:
                await delete_alert_handler(client, msgs)
        elif isinstance(update, UpdateDeleteChannelMessages):
            # فقط پیوی مدنظر است
            return
    except Exception as e:
        logging.debug(f"raw_delete_update: {e}")


async def is_member_of_channel(client, channel: str, user_id: int) -> bool:
    """بررسی عضویت کاربر در کانال/گروه"""
    try:
        ch = channel.strip()
        if not ch:
            return True
        if not ch.startswith("@") and not ch.startswith("-") and not ch.lstrip("-").isdigit():
            ch = "@" + ch
        member = await client.get_chat_member(ch, user_id)
        status = getattr(member, "status", None)
        name = str(status).lower()
        # عضو / ادمین / سازنده / محدود (هنوز داخل کانال)
        ok_tokens = ("member", "administrator", "admin", "owner", "creator", "restricted")
        if any(t in name for t in ok_tokens) and "left" not in name and "ban" not in name:
            return True
        if "left" in name or "ban" in name:
            return False
        return True
    except Exception as e:
        err = str(e).upper()
        if "USER_NOT_PARTICIPANT" in err or "PARTICIPANT_ID_INVALID" in err:
            return False
        logging.warning(f"membership check {channel}/{user_id}: {e}")
        return False



async def pv_cache_handler(client, message):
    try:
        if client.me:
            cache_pv_message(client.me.id, message)
    except Exception:
        pass

async def force_join_pv_handler(client, message):
    """اگر عضویت اجباری پیوی فعال باشد، پیام غیرعضو حذف می‌شود"""
    try:
        if not message or not message.from_user:
            return
        if message.from_user.is_self or getattr(message.from_user, "is_bot", False):
            return
        owner_id = client.me.id
        if not FORCE_JOIN_PV_STATUS.get(owner_id, False):
            return
        channels = FORCE_JOIN_CHANNELS.get(owner_id) or []
        if not channels:
            return

        uid = message.from_user.id
        missing = []
        for ch in channels:
            ok = await is_member_of_channel(client, ch, uid)
            if not ok:
                missing.append(ch)

        if not missing:
            return

        # حذف پیام
        try:
            await message.delete()
        except Exception:
            pass

        # اطلاع‌رسانی (حداکثر هر ۲ دقیقه یک‌بار برای هر کاربر)
        warn_key = f"fj_warn_{owner_id}_{uid}"
        now = time.time()
        last = getattr(force_join_pv_handler, "_warns", {}).get(warn_key, 0)
        if now - last < 120:
            return
        if not hasattr(force_join_pv_handler, "_warns"):
            force_join_pv_handler._warns = {}
        force_join_pv_handler._warns[warn_key] = now

        lines = ["⚠️ برای ارسال پیام در پیوی ابتدا عضو کانال‌های زیر شوید:\n"]
        for ch in missing:
            c = ch if ch.startswith("@") else f"@{ch}"
            lines.append(f"🔗 {c}")
        lines.append("\nپس از عضویت دوباره پیام بدهید. | self MR")
        try:
            await client.send_message(uid, "\n".join(lines))
        except Exception:
            pass
    except Exception as e:
        logging.error(f"force_join_pv_handler: {e}")




async def save_message_powerful(client, reply):
    """ذخیره قوی: متن، رسانه، عکس/ویدیو نابودشونده (TTL) و view-once"""
    if not reply:
        return False, "❌ روی پیام ریپلای کنید."

    caption = reply.caption or ""
    text = reply.text or ""
    ttl = getattr(reply, "ttl_seconds", None) or getattr(getattr(reply, "media", None), "ttl_seconds", None)
    is_view_once = bool(ttl) or bool(getattr(reply, "media", None) and getattr(reply.media, "ttl_seconds", None))

    # برای view-once / TTL اول دانلود کن (فوروارد معمولاً کار نمی‌کند)
    path = None
    download_errors = []

    async def _try_download():
        nonlocal path
        # روش ۱: کل پیام
        try:
            path = await client.download_media(reply)
            if path and os.path.exists(path) and os.path.getsize(path) > 100:
                return True
        except Exception as e:
            download_errors.append(f"msg:{type(e).__name__}")
        # روش ۲: file_id عکس (بزرگ‌ترین سایز)
        try:
            if reply.photo:
                path = await client.download_media(reply.photo.file_id)
                if path and os.path.exists(path) and os.path.getsize(path) > 100:
                    return True
        except Exception as e:
            download_errors.append(f"photo:{type(e).__name__}")
        # روش ۳: ویدیو / داکیومنت / انیمیشن / ویس / آهنگ
        for attr in ("video", "document", "animation", "voice", "audio", "video_note", "sticker"):
            try:
                media_obj = getattr(reply, attr, None)
                if media_obj and getattr(media_obj, "file_id", None):
                    path = await client.download_media(media_obj.file_id)
                    if path and os.path.exists(path) and os.path.getsize(path) > 100:
                        return True
            except Exception as e:
                download_errors.append(f"{attr}:{type(e).__name__}")
        return False

    # اگر مدیا دارد سعی کن دانلود کن
    if reply.media or reply.photo or reply.video or reply.document:
        await _try_download()

    # اگر دانلود موفق بود → آپلود به Saved
    if path and os.path.exists(path) and os.path.getsize(path) > 100:
        cap = "💾 ذخیره | self MR"
        if is_view_once or ttl:
            cap += "\n👁 رسانه یک‌بارمصرف / تایم‌دار ذخیره شد"
        if ttl:
            cap += f"\n⏱ TTL: {ttl}s"
        if caption:
            cap += f"\n\n{caption}"
        try:
            pl = path.lower()
            if reply.photo or pl.endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp")):
                await client.send_photo("me", path, caption=cap)
            elif reply.video or pl.endswith((".mp4", ".mov", ".mkv", ".webm")):
                await client.send_video("me", path, caption=cap)
            elif reply.voice or (pl.endswith(".ogg") and not reply.audio):
                await client.send_voice("me", path, caption=cap)
            elif reply.video_note:
                try:
                    await client.send_video_note("me", path)
                    await client.send_message("me", cap)
                except Exception:
                    await client.send_video("me", path, caption=cap)
            elif reply.audio or pl.endswith((".mp3", ".m4a", ".flac", ".aac")):
                await client.send_audio("me", path, caption=cap)
            elif reply.animation or pl.endswith(".gif"):
                await client.send_animation("me", path, caption=cap)
            elif reply.sticker:
                try:
                    await client.send_sticker("me", path)
                except Exception:
                    await client.send_document("me", path, caption=cap)
            else:
                await client.send_document("me", path, caption=cap)
            return True, None
        except Exception as e:
            logging.warning(f"save reupload failed: {e}")
        finally:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass

    # فوروارد / کپی برای پیام‌های عادی
    if not is_view_once:
        try:
            await reply.forward("me")
            return True, None
        except Exception as e1:
            logging.info(f"forward save failed: {e1}")
        try:
            await reply.copy("me")
            return True, None
        except Exception as e2:
            logging.info(f"copy save failed: {e2}")

    # فقط متن
    if text or caption:
        await client.send_message("me", f"💾 ذخیره متن | self MR\n\n{text or caption}")
        return True, None

    detail = " | ".join(download_errors[-4:]) if download_errors else "نامشخص"
    return False, f"❌ ذخیره ناموفق (view-once/محافظت‌شده).\n🔧 {detail}"


async def convert_video_to_note(client, message):
    """ریپلای روی ویدیو → ویدیو مسیج (گرد)"""
    reply = message.reply_to_message
    if not reply:
        return None, "❌ روی یک ویدیو ریپلای کنید."
    media = reply.video or reply.video_note or reply.animation or (
        reply.document if reply.document and (reply.document.mime_type or "").startswith("video/") else None
    )
    if not media:
        return None, "❌ این پیام ویدیو نیست."

    try:
        path = await client.download_media(media)
        if not path or not os.path.exists(path):
            return None, "❌ دانلود ویدیو ناموفق بود."
    except Exception as e:
        return None, f"❌ دانلود: {e}"

    out = f"{DOWNLOAD_PATH}/vnote_{int(time.time())}_{random.randint(100,999)}.mp4"
    # مربع + حداکثر ۶۰ ثانیه — مناسب ویدیو مسیج تلگرام
    cmd = [
        "ffmpeg", "-y", "-i", path,
        "-t", "60",
        "-vf", "crop=min(iw\\,ih):min(iw\\,ih),scale=240:240",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart",
        out
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) < 1000:
            # تلاش بدون صدا
            cmd2 = [
                "ffmpeg", "-y", "-i", path,
                "-t", "60",
                "-vf", "crop=min(iw\\,ih):min(iw\\,ih),scale=240:240",
                "-c:v", "libx264", "-preset", "veryfast", "-an",
                out
            ]
            proc2 = await asyncio.create_subprocess_exec(
                *cmd2,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc2.communicate(), timeout=120)
            if not os.path.exists(out) or os.path.getsize(out) < 1000:
                err = (stderr or b"").decode("utf-8", errors="ignore")[-200:]
                return None, f"❌ تبدیل ناموفق. ffmpeg را نصب کنید.\n{err}"
    except FileNotFoundError:
        return None, "❌ ffmpeg روی سرور نصب نیست."
    except Exception as e:
        return None, f"❌ خطا در تبدیل: {e}"
    finally:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    return out, None


async def ensure_vazir_font():
    """دانلود فونت وزیر برای فارسی تمیز"""
    font_dir = os.path.join(DOWNLOAD_PATH, "fonts")
    os.makedirs(font_dir, exist_ok=True)
    font_path = os.path.join(font_dir, "Vazirmatn-Bold.ttf")
    if os.path.exists(font_path) and os.path.getsize(font_path) > 10000:
        return font_path
    urls = [
        "https://github.com/rastikerdar/vazirmatn/raw/master/fonts/ttf/Vazirmatn-Bold.ttf",
        "https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@master/fonts/ttf/Vazirmatn-Bold.ttf",
    ]
    try:
        async with aiohttp.ClientSession() as session:
            for url in urls:
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            if len(data) > 10000:
                                with open(font_path, "wb") as f:
                                    f.write(data)
                                return font_path
                except Exception:
                    continue
    except Exception as e:
        logging.warning(f"font download failed: {e}")
    return None


def prepare_rtl_text(text: str) -> str:
    """آماده‌سازی متن فارسی برای رسم صحیح در Pillow"""
    if not text:
        return text
    if not re.search(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]", text):
        return text
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        reshaped = arabic_reshaper.reshape(text)
        # get_display برای ترتیب درست حروف فارسی در تصویر LTR لازم است
        return get_display(reshaped)
    except Exception:
        try:
            import arabic_reshaper
            return arabic_reshaper.reshape(text)
        except Exception:
            return text


async def convert_message_to_sticker(client, message):
    """ریپلای روی عکس/متن/استیکر → استیکر تمیز"""
    reply = message.reply_to_message
    if not reply:
        return None, "❌ روی یک پیام ریپلای کنید."

    out = f"{DOWNLOAD_PATH}/sticker_{int(time.time())}_{random.randint(100,999)}.webp"
    os.makedirs(DOWNLOAD_PATH, exist_ok=True)

    if reply.sticker:
        try:
            path = await client.download_media(reply.sticker)
            if path:
                return path, None
        except Exception as e:
            return None, f"❌ دانلود استیکر: {e}"

    text = (reply.text or reply.caption or "").strip()
    has_photo = bool(reply.photo)
    has_image_doc = bool(reply.document and (reply.document.mime_type or "").startswith("image/"))

    # ===== متن → استیکر =====
    if text and not has_photo and not has_image_doc and not reply.animation:
        try:
            from PIL import Image, ImageDraw, ImageFont, ImageFilter

            vazir = await ensure_vazir_font()

            def load_font(size):
                paths = []
                if vazir:
                    paths.append(vazir)
                paths.extend([
                    "/usr/share/fonts/truetype/vazirmatn/Vazirmatn-Bold.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                    "C:/Windows/Fonts/tahoma.ttf",
                    "C:/Windows/Fonts/arial.ttf",
                ])
                for fp in paths:
                    if fp and os.path.exists(fp):
                        try:
                            return ImageFont.truetype(fp, size)
                        except Exception:
                            continue
                return ImageFont.load_default()

            def circle_crop(im, size=78):
                try:
                    resample = Image.Resampling.LANCZOS
                except Exception:
                    resample = getattr(Image, "LANCZOS", Image.BICUBIC)
                im = im.convert("RGBA").resize((size, size), resample)
                mask = Image.new("L", (size, size), 0)
                ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
                out_im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                out_im.paste(im, (0, 0))
                out_im.putalpha(mask)
                return out_im

            def default_avatar(letter, size=78):
                img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                d = ImageDraw.Draw(img)
                colors = [(88, 150, 230), (230, 120, 90), (90, 190, 140), (180, 120, 210)]
                c = colors[hash(letter) % len(colors)]
                d.ellipse((0, 0, size - 1, size - 1), fill=c + (255,))
                f = load_font(max(24, size // 2))
                L = prepare_rtl_text(letter)
                try:
                    bb = d.textbbox((0, 0), L, font=f)
                    tw, th = bb[2] - bb[0], bb[3] - bb[1]
                except Exception:
                    tw, th = size // 3, size // 3
                d.text(((size - tw) / 2, (size - th) / 2 - 2), L, font=f, fill=(255, 255, 255, 255))
                return img

            def smart_text(img, xy, s, font, fill):
                """رسم متن. فارسی با PIL؛ ایموجی‌alone با pilmoji"""
                if not s:
                    return
                s = "".join(ch for ch in s if ch == "\n" or ord(ch) >= 32)
                fill3 = fill[:3] if isinstance(fill, tuple) and len(fill) >= 3 else fill
                has_fa = bool(re.search(r"[\u0600-\u06FF]", s))
                has_emoji = bool(re.search(r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U0001F600-\U0001F64F]", s))
                # فارسی: فقط PIL (pilmoji ترتیب را خراب می‌کند)
                if has_fa:
                    ImageDraw.Draw(img).text(xy, s, font=font, fill=fill)
                    return
                # فقط ایموجی/لاتین
                if has_emoji:
                    try:
                        from pilmoji import Pilmoji
                        with Pilmoji(img) as pm:
                            pm.text(xy, s, font=font, fill=fill3)
                        return
                    except Exception:
                        pass
                ImageDraw.Draw(img).text(xy, s, font=font, fill=fill)

            def measure(s, font):
                try:
                    bb = ImageDraw.Draw(Image.new("RGBA", (64, 64))).textbbox((0, 0), s, font=font)
                    return bb[2] - bb[0], bb[3] - bb[1]
                except Exception:
                    return max(10, len(s) * 12), 20

            # نام کاربر
            user = reply.from_user
            name = "User"
            if user:
                name = f"{user.first_name or ''} {user.last_name or ''}".strip()
                if not name:
                    name = f"@{user.username}" if user.username else "User"
            # حذف ایموجی‌های مشکل‌دار از اسم برای جلوگیری از مربع (اختیاری نگه می‌داریم ولی با pilmoji)
            if len(name) > 22:
                name = name[:20] + "…"
            name_draw = prepare_rtl_text(name)

            # آواتار
            av_size = 78
            avatar = None
            try:
                if user:
                    async for p in client.get_chat_photos(user.id, limit=1):
                        av_path = await client.download_media(p)
                        if av_path and os.path.exists(av_path):
                            avatar = circle_crop(Image.open(av_path), av_size)
                            try:
                                os.remove(av_path)
                            except Exception:
                                pass
                        break
            except Exception:
                avatar = None
            if avatar is None:
                avatar = default_avatar(name[0] if name else "U", av_size)

            # متن پیام
            raw = text[:170]
            tlen = len(raw)
            if tlen <= 8:
                fsize, max_chars, line_h = 48, 10, 56
            elif tlen <= 28:
                fsize, max_chars, line_h = 34, 16, 42
            else:
                fsize, max_chars, line_h = 26, 20, 34

            font = load_font(fsize)
            name_font = load_font(24)
            time_font = load_font(17)

            def wrap(t, n):
                words = t.split()
                lines, cur = [], ""
                for w in words:
                    trial = (cur + " " + w).strip()
                    if len(trial) <= n:
                        cur = trial
                    else:
                        if cur:
                            lines.append(cur)
                        cur = w
                if cur:
                    lines.append(cur)
                if not lines:
                    lines = [t[i:i+n] for i in range(0, len(t), n)]
                return lines[:7]

            lines_raw = wrap(raw, max_chars)
            lines_draw = [prepare_rtl_text(x) for x in lines_raw]

            # عرض محتوا
            max_tw = 0
            for ln in lines_draw:
                w, _ = measure(ln, font)
                max_tw = max(max_tw, w)
            name_w, _ = measure(name_draw, name_font)

            pad_x, pad_top = 18, 16
            bubble_w = int(min(380, max(max_tw, name_w, 140) + pad_x * 2))
            bubble_h = int(pad_top + 36 + len(lines_draw) * line_h + 30)
            bubble_h = max(100, min(440, bubble_h))

            gap = 12
            total_w = av_size + gap + bubble_w
            total_h = max(av_size + 8, bubble_h)
            left = (512 - total_w) // 2
            top = (512 - total_h) // 2
            bx0 = left + av_size + gap
            by0 = top + max(0, (total_h - bubble_h) // 2)

            canvas = Image.new("RGBA", (512, 512), (0, 0, 0, 0))

            # سایه
            shadow = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
            sd = ImageDraw.Draw(shadow)
            try:
                sd.rounded_rectangle([bx0+3, by0+5, bx0+bubble_w+3, by0+bubble_h+5], radius=22, fill=(0, 0, 0, 80))
            except Exception:
                sd.rectangle([bx0+3, by0+5, bx0+bubble_w+3, by0+bubble_h+5], fill=(0, 0, 0, 80))
            canvas = Image.alpha_composite(canvas, shadow.filter(ImageFilter.GaussianBlur(7)))

            # آواتار
            av_x = left
            av_y = by0 + bubble_h - av_size
            canvas.paste(avatar, (int(av_x), int(av_y)), avatar)

            # حباب
            draw = ImageDraw.Draw(canvas)
            try:
                draw.rounded_rectangle([bx0, by0, bx0+bubble_w, by0+bubble_h], radius=22, fill=(42, 40, 54, 250))
            except Exception:
                draw.rectangle([bx0, by0, bx0+bubble_w, by0+bubble_h], fill=(42, 40, 54, 250))

            # ----- اسم (واضح و داخل حباب) -----
            name_x = bx0 + pad_x
            name_y = by0 + pad_top
            # سایه خیلی کم برای خوانایی اسم
            smart_text(canvas, (name_x+1, name_y+1), name_draw, name_font, (0, 0, 0, 120))
            smart_text(canvas, (name_x, name_y), name_draw, name_font, (140, 200, 255, 255))

            # ----- متن -----
            is_time = bool(re.match(r"^\d{1,2}:\d{2}$", raw.strip()))
            fill = (255, 175, 70, 255) if is_time else (250, 250, 252, 255)
            ty = name_y + 32
            for i, ln in enumerate(lines_draw):
                has_fa = bool(re.search(r"[\u0600-\u06FF]", lines_raw[i]))
                if has_fa:
                    smart_text(canvas, (bx0 + pad_x, ty + i * line_h), ln, font, fill)
                else:
                    w, _ = measure(ln, font)
                    x = bx0 + max(pad_x, (bubble_w - w) // 2)
                    smart_text(canvas, (x, ty + i * line_h), ln, font, fill)

            # ----- ساعت -----
            try:
                msg_time = datetime.fromtimestamp(reply.date.timestamp(), TEHRAN_TIMEZONE).strftime("%H:%M")
            except Exception:
                msg_time = datetime.now(TEHRAN_TIMEZONE).strftime("%H:%M")
            tw, _ = measure(msg_time, time_font)
            ImageDraw.Draw(canvas).text(
                (bx0 + bubble_w - pad_x - tw, by0 + bubble_h - 24),
                msg_time,
                font=time_font,
                fill=(155, 155, 170, 255),
            )

            canvas.save(out, "WEBP", quality=95)
            return out, None
        except Exception as e:
            logging.error(f"text sticker error: {e}", exc_info=True)
            return None, f"❌ تبدیل متن به استیکر: {e}"

    # ===== عکس =====
    media = reply.photo or reply.document
    if not media and reply.animation:
        return None, "❌ گیف را نمی‌توان به استیکر ثابت تبدیل کرد."
    if not media:
        return None, "❌ روی عکس یا متن ریپلای کنید."
    if reply.document and not (reply.document.mime_type or "").startswith("image/"):
        return None, "❌ فقط فایل تصویری قابل تبدیل است."

    try:
        path = await client.download_media(media)
        if not path or not os.path.exists(path):
            return None, "❌ دانلود تصویر ناموفق بود."
    except Exception as e:
        return None, f"❌ دانلود: {e}"

    try:
        from PIL import Image
        img = Image.open(path).convert("RGBA")
        w, h = img.size
        if w >= h:
            new_w, new_h = 512, max(1, int(h * 512 / w))
        else:
            new_h, new_w = 512, max(1, int(w * 512 / h))
        try:
            resample = Image.Resampling.LANCZOS
        except Exception:
            resample = getattr(Image, "LANCZOS", Image.BICUBIC)
        img = img.resize((new_w, new_h), resample)
        canvas = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
        canvas.paste(img, ((512 - new_w) // 2, (512 - new_h) // 2), img)
        canvas.save(out, "WEBP", quality=90)
        try:
            os.remove(path)
        except Exception:
            pass
        return out, None
    except Exception as e:
        return None, f"❌ تبدیل استیکر: {e}"



# ===================== انیمیشن‌های ایموجی =====================
EMOJI_ANIMATIONS = {
    "قلب": {
        "frames": [
            "❤️", "🧡", "💛", "💚", "💙", "💜", "🖤", "🤍", "🤎", "💖",
            "💗", "💘", "💝",
        ],
        "finale": "❤️🧡💛\\n💚💙💜\\n💖💗💘",
        "interval": 2,
    },
    "برف": {
        "frames": [
            "❄️", "🌨️", "⛄", "🏔️", "🌬️", "☁️", "🧊", "🎄", "🦌", "🎿",
        ],
        "finale": "✨❄️ finish ❄️✨",
        "interval": 2,
    },
    "زندگی انسان": {
        "frames": [
            "💑",
            "🤰",
            "👨‍👩‍👧",
            "👶",
            "🧒",
            "🚲",
            "💼",
            "👴",
            "🪦",
        ],
        "finale": "🪦 RIP",
        "interval": 2,
    },
    "آتش": {
        "frames": ["🕯️", "🔥", "💥", "🔥", "🌋", "🔥", "💫", "🔥"],
        "finale": "🔥🔥🔥",
        "interval": 2,
    },
    "ماه": {
        "frames": ["🌑", "🌒", "🌓", "🌔", "🌕", "🌖", "🌗", "🌘", "🌑"],
        "finale": "🌕✨",
        "interval": 2,
    },
    "ساعت": {
        "frames": ["🕐", "🕑", "🕒", "🕓", "🕔", "🕕", "🕖", "🕗", "🕘", "🕙", "🕚", "🕛"],
        "finale": "⏰ finish",
        "interval": 2,
    },
    "هواپیما": {
        "frames": ["✈️", "🛫", "✈️", "🛬", "🌍", "✈️", "🌌"],
        "finale": "✈️🏁",
        "interval": 2,
    },
    "گربه": {
        "frames": ["😺", "😸", "😹", "😻", "😼", "😽", "🙀", "😿", "😾"],
        "finale": "🐱💕",
        "interval": 2,
    },
}


async def run_emoji_animation(client, message, key: str):
    anim = EMOJI_ANIMATIONS.get(key)
    if not anim:
        return
    frames = anim["frames"]
    interval = anim.get("interval", 2)
    finale = anim.get("finale", "finish")
    try:
        await message.edit_text(frames[0])
    except Exception:
        try:
            message = await client.send_message(message.chat.id, frames[0])
        except Exception as e:
            logging.error(f"anim start: {e}")
            return
    for frame in frames[1:]:
        await asyncio.sleep(interval)
        try:
            await message.edit_text(frame)
        except Exception:
            break
    await asyncio.sleep(interval)
    try:
        await message.edit_text(finale)
    except Exception:
        pass



async def ai_expand_text(seed: str) -> str:
    """گسترش متن با DeepSeek — داستانی، مرتبط، با ایموجی"""
    seed = (seed or "").strip()
    if not seed:
        return "❌ متنی برای گسترش وارد نشده."

    if not DEEPSEEK_API_KEY:
        return (
            "❌ کلید DeepSeek تنظیم نشده.\n\n"
            "در سرور این متغیر را بگذار:\n"
            "`DEEPSEEK_API_KEY=sk-...`"
        )

    system_prompt = (
        "تو نویسنده خلاق فارسی هستی.\n"
        "وظیفه: متن کوتاه کاربر را گسترش بده و داستانی ادامه بده.\n"
        "قوانین:\n"
        "- حتماً همان اسامی، مکان‌ها و موضوع کاربر حفظ شود.\n"
        "- لحن خودمانی و روان باشد؛ رسمی و سازمانی ممنوع.\n"
        "- انگلیسی‌بازی و کلماتی مثل synergy ممنوع.\n"
        "- ۸ تا ۱۴ خط بنویس.\n"
        "- چند ایموجی مرتبط با موضوع داخل متن بگذار.\n"
        "- فقط متن نهایی را برگردان؛ عنوان و توضیح اضافه ننویس."
    )
    user_prompt = f"این متن را گسترش بده و ادامه بده:\n{seed}"

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.9,
        "max_tokens": 1200,
        "stream": False,
    }

    try:
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                "https://api.deepseek.com/chat/completions",
                headers=headers,
                json=payload,
            ) as resp:
                raw = await resp.text()
                if resp.status != 200:
                    logging.error(f"DeepSeek status={resp.status} body={raw[:300]}")
                    low = (raw or "").lower()
                    if resp.status in (401, 403):
                        return "❌ کلید DeepSeek نامعتبر است. DEEPSEEK_API_KEY را در سرور چک کن."
                    if resp.status == 402 or "insufficient" in low or "balance" in low:
                        return (
                            "❌ موجودی حساب DeepSeek کافی نیست.\n"
                            "برو به platform.deepseek.com و حساب را شارژ کن."
                        )
                    if resp.status == 429:
                        return "❌ محدودیت درخواست DeepSeek. کمی بعد دوباره تلاش کن."
                    return f"❌ خطا از DeepSeek ({resp.status})."
                try:
                    data = json.loads(raw)
                except Exception:
                    return "❌ پاسخ نامعتبر از DeepSeek."
                choices = data.get("choices") or []
                if not choices:
                    return "❌ پاسخی از DeepSeek نیامد."
                text = (
                    (choices[0].get("message") or {}).get("content")
                    or choices[0].get("text")
                    or ""
                ).strip()
                if not text:
                    return "❌ متن خالی از DeepSeek."
                return text[:3900]
    except Exception as e:
        logging.error(f"DeepSeek error: {e}")
        return f"❌ خطا در اتصال به DeepSeek:\n{e}"


def _clean_track_name(name: str) -> str:
    if not name:
        return ""
    name = name.replace("_", " ").replace(".", " ")
    # حذف پسوندها و تگ‌های کیفیت
    junk = [
        "mp3", "flac", "wav", "m4a", "128", "320", "256", "kbps", "official",
        "lyrics", "audio", "hq", "lq", "copy", "song", "track", "full",
    ]
    low = name
    for j in junk:
        low = re.sub(rf"(?i)\\b{re.escape(j)}\\b", " ", low)
    low = re.sub(r"\\s+", " ", low).strip(" -_|")
    return low.strip()


def _split_artist_title(raw: str):
    raw = _clean_track_name(raw)
    if not raw:
        return "", ""
    for sep in [" - ", " – ", " — ", " | ", " _ "]:
        if sep in raw:
            a, t = raw.split(sep, 1)
            return a.strip(), t.strip()
    return "", raw


async def fetch_song_lyrics(title: str, artist: str = "") -> str:
    """جستجوی قوی متن آهنگ: LRCLIB + lyrics.ovh + پارس نام فایل"""
    title = _clean_track_name(title or "")
    artist = _clean_track_name(artist or "")

    # اگر title شامل artist - song باشد
    if not artist and title:
        a2, t2 = _split_artist_title(title)
        if t2:
            artist = artist or a2
            title = t2

    if not title:
        return "❌ نام آهنگ مشخص نیست."

    queries = []
    if artist and title:
        queries.append((artist, title))
    queries.append(("", title))
    if artist:
        queries.append((artist, title.split("-")[0].strip()))

    timeout = aiohttp.ClientTimeout(total=25)

    # ---- 1) LRCLIB search ----
    try:
        q = f"{artist} {title}".strip()
        url = f"https://lrclib.net/api/search?q={quote(q)}"
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    items = await resp.json()
                    if isinstance(items, list) and items:
                        best = items[0]
                        # plain lyrics
                        lyrics = (best.get("plainLyrics") or best.get("syncedLyrics") or "").strip()
                        if lyrics:
                            ar = best.get("artistName") or artist or ""
                            tr = best.get("trackName") or title
                            # synced has timestamps [00:01.00] — clean if needed
                            if "[" in lyrics and "]" in lyrics and "plainLyrics" not in best:
                                lyrics = re.sub(r"\\[\\d+:\\d+\\.\\d+\\]\\s*", "", lyrics)
                            return f"🎵 {ar} — {tr}\n\n{lyrics[:3800]}"
    except Exception as e:
        logging.warning(f"lrclib search: {e}")

    # ---- 2) LRCLIB get exact ----
    for ar, tr in queries:
        if not tr:
            continue
        try:
            url = (
                "https://lrclib.net/api/get?"
                f"artist_name={quote(ar or 'Unknown')}&track_name={quote(tr)}"
            )
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        lyrics = (data.get("plainLyrics") or data.get("syncedLyrics") or "").strip()
                        if lyrics:
                            if "syncedLyrics" in data and not data.get("plainLyrics"):
                                lyrics = re.sub(r"\\[\\d+:\\d+\\.\\d+\\]\\s*", "", lyrics)
                            return f"🎵 {(ar or data.get('artistName') or '')} — {tr}\n\n{lyrics[:3800]}"
        except Exception as e:
            logging.warning(f"lrclib get: {e}")

    # ---- 3) lyrics.ovh ----
    for ar, tr in queries:
        if not ar or not tr:
            continue
        try:
            url = f"https://api.lyrics.ovh/v1/{quote(ar)}/{quote(tr)}"
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        lyrics = (data.get("lyrics") or "").strip()
                        if lyrics:
                            return f"🎵 {ar} — {tr}\n\n{lyrics[:3800]}"
        except Exception as e:
            logging.warning(f"lyrics.ovh: {e}")

    # ---- 4) Genius API search (عمومی) ----
    try:
        q = f"{artist} {title}".strip()
        url = f"https://genius.com/api/search?q={quote(q)}"
        headers = {"User-Agent": "Mozilla/5.0"}
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    hits = (((data or {}).get("response") or {}).get("hits")) or []
                    if hits:
                        result = hits[0].get("result") or {}
                        song_title = result.get("full_title") or title
                        song_url = result.get("url") or ""
                        if song_url:
                            # صفحه آهنگ را برای lyrics scrape کن
                            async with session.get(song_url, headers=headers) as r2:
                                if r2.status == 200:
                                    html = await r2.text()
                                    # استخراج ساده از containers
                                    try:
                                        from bs4 import BeautifulSoup
                                        soup = BeautifulSoup(html, "lxml")
                                        parts = soup.select('div[data-lyrics-container="true"]')
                                        if parts:
                                            lyrics = "\n".join(p.get_text("\n").strip() for p in parts)
                                            lyrics = re.sub(r"\\n{3,}", "\n\n", lyrics).strip()
                                            if lyrics and len(lyrics) > 40:
                                                return f"🎵 {song_title}\n\n{lyrics[:3800]}"
                                    except Exception as e:
                                        logging.warning(f"genius scrape: {e}")
                        return (
                            f"🔎 آهنگ پیدا شد ولی متن مستقیم در دسترس نبود:\n"
                            f"{song_title}\n{song_url}"
                        )
    except Exception as e:
        logging.warning(f"genius: {e}")

    q = quote(f"{artist} {title} lyrics".strip())
    return (
        f"❌ متن آهنگ پیدا نشد برای:\n"
        f"🎵 {artist + ' - ' if artist else ''}{title}\n\n"
        f"جستجو:\n"
        f"https://www.google.com/search?q={q}\n"
        f"https://genius.com/search?q={q}"
    )



async def capture_chat_to_saved(client, chat_id: int, limit: int = 20):
    """ارسال محتوای اخیر چت به Saved Messages (برای چت‌های محافظت‌شده هم تلاش می‌کند)"""
    sent = 0
    errors = 0
    header = f"📸 اسکرین | self MR\\nچت: `{chat_id}`\\nتعداد تلاش: {limit}"
    try:
        await client.send_message("me", header)
    except Exception:
        pass

    messages = []
    async for m in client.get_chat_history(chat_id, limit=limit):
        messages.append(m)
    messages.reverse()  # قدیمی → جدید

    for m in messages:
        try:
            # اول فوروارد
            try:
                await m.forward("me")
                sent += 1
                await asyncio.sleep(0.25)
                continue
            except Exception:
                pass

            # اگر فوروارد نشد (محافظت‌شده): کپی دستی
            caption = m.caption or ""
            text = m.text or ""
            if text:
                await client.send_message("me", text)
                sent += 1
            elif m.photo:
                path = await client.download_media(m)
                if path:
                    await client.send_photo("me", path, caption=caption or None)
                    try:
                        os.remove(path)
                    except Exception:
                        pass
                    sent += 1
            elif m.video:
                path = await client.download_media(m)
                if path:
                    await client.send_video("me", path, caption=caption or None)
                    try:
                        os.remove(path)
                    except Exception:
                        pass
                    sent += 1
            elif m.document:
                path = await client.download_media(m)
                if path:
                    await client.send_document("me", path, caption=caption or None)
                    try:
                        os.remove(path)
                    except Exception:
                        pass
                    sent += 1
            elif m.voice:
                path = await client.download_media(m)
                if path:
                    await client.send_voice("me", path)
                    try:
                        os.remove(path)
                    except Exception:
                        pass
                    sent += 1
            elif m.audio:
                path = await client.download_media(m)
                if path:
                    await client.send_audio("me", path, caption=caption or None)
                    try:
                        os.remove(path)
                    except Exception:
                        pass
                    sent += 1
            elif m.sticker:
                try:
                    await client.send_sticker("me", m.sticker.file_id)
                    sent += 1
                except Exception:
                    path = await client.download_media(m)
                    if path:
                        await client.send_document("me", path)
                        try:
                            os.remove(path)
                        except Exception:
                            pass
                        sent += 1
            elif m.animation:
                path = await client.download_media(m)
                if path:
                    await client.send_animation("me", path, caption=caption or None)
                    try:
                        os.remove(path)
                    except Exception:
                        pass
                    sent += 1
            else:
                errors += 1
            await asyncio.sleep(0.3)
        except Exception as e:
            logging.warning(f"screen copy msg: {e}")
            errors += 1
    return sent, errors


async def _translate_query_for_search(query: str) -> str:
    """اگر فارسی بود به انگلیسی هم برگردان برای دقت بیشتر"""
    q = (query or "").strip()
    if not q:
        return q
    try:
        # اگر حروف فارسی داشت
        if re.search(r"[\u0600-\u06FF]", q):
            try:
                from deep_translator import GoogleTranslator
                en = GoogleTranslator(source="auto", target="en").translate(q)
                if en and en.strip():
                    return en.strip()
            except Exception:
                pass
    except Exception:
        pass
    return q


async def search_web_images(query: str, limit: int = 1):
    """فقط دقیق‌ترین یک (یا چند) تصویر مرتبط"""
    query = (query or "").strip()
    if not query:
        return []
    limit = max(1, min(int(limit or 1), 3))
    en_q = await _translate_query_for_search(query)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9,fa;q=0.8",
    }
    found = []

    async def _add(u):
        if not u or not isinstance(u, str):
            return
        u = u.strip()
        if not u.startswith("http"):
            return
        # فیلتر thumbnailهای بی‌ربط/آیکون
        low = u.lower()
        if any(x in low for x in ("favicon", "logo", "sprite", "1x1", "pixel")):
            return
        if u not in found:
            found.append(u)

    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        # ----- 1) Wikipedia FA -----
        try:
            url = f"https://fa.wikipedia.org/api/rest_v1/page/summary/{quote(query)}"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    thumb = (data.get("thumbnail") or {}).get("source")
                    original = (data.get("originalimage") or {}).get("source")
                    await _add(original or thumb)
        except Exception as e:
            logging.warning(f"wiki fa: {e}")

        if len(found) >= limit:
            return found[:limit]

        # ----- 2) Wikipedia EN -----
        try:
            url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(en_q)}"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    thumb = (data.get("thumbnail") or {}).get("source")
                    original = (data.get("originalimage") or {}).get("source")
                    await _add(original or thumb)
        except Exception as e:
            logging.warning(f"wiki en: {e}")

        if len(found) >= limit:
            return found[:limit]

        # ----- 3) DuckDuckGo instant -----
        try:
            for q in (query, en_q):
                url = f"https://api.duckduckgo.com/?q={quote(q)}&format=json&no_redirect=1&no_html=1"
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        img = data.get("Image") or data.get("ImageURL")
                        if img:
                            if img.startswith("/"):
                                img = "https://duckduckgo.com" + img
                            await _add(img)
                        for t in (data.get("RelatedTopics") or [])[:5]:
                            if isinstance(t, dict):
                                i2 = (t.get("Icon") or {}).get("URL")
                                if i2:
                                    if i2.startswith("/"):
                                        i2 = "https://duckduckgo.com" + i2
                                    await _add(i2)
                if len(found) >= limit:
                    return found[:limit]
        except Exception as e:
            logging.warning(f"ddg: {e}")

        # ----- 4) Bing images (اولین نتایج واقعی) -----
        try:
            # qft=photo برای عکس واقعی
            for q in (en_q, query):
                search_url = (
                    f"https://www.bing.com/images/search?q={quote(q)}"
                    f"&qft=+filterui:photo-photo+filterui:aspect-square&form=IRFLTR"
                )
                async with session.get(search_url) as resp:
                    if resp.status != 200:
                        continue
                    html = await resp.text()
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(html, "lxml")
                    for a in soup.select("a.iusc"):
                        m = a.get("m")
                        if not m:
                            continue
                        try:
                            data = json.loads(m)
                        except Exception:
                            continue
                        u = data.get("murl") or ""
                        t = (data.get("t") or data.get("desc") or "").lower()
                        # ترجیح اگر عنوان به کوئری نزدیک باشد
                        await _add(u)
                        if len(found) >= limit:
                            return found[:limit]
                except Exception as e:
                    logging.warning(f"bing parse: {e}")
        except Exception as e:
            logging.warning(f"bing: {e}")

        # ----- 5) Google images (fallback سبک) -----
        try:
            g_url = f"https://www.google.com/search?q={quote(en_q)}&tbm=isch&hl=en&safe=active"
            async with session.get(g_url) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    # استخراج از AF_initDataKeys سخت است؛ regex روی https://...
                    for m in re.finditer(r"\"(https://[^\"]+\.(?:jpg|jpeg|png|webp)[^\"]*)\"", html, re.I):
                        u = m.group(1)
                        if "gstatic" in u or "google" in u and "encrypted" in u:
                            continue
                        await _add(u)
                        if len(found) >= limit:
                            break
        except Exception as e:
            logging.warning(f"google img: {e}")

    return found[:limit]


async def download_image_bytes(url: str):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
                if len(data) < 1000:
                    return None
                ext = "jpg"
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if "png" in ctype:
                    ext = "png"
                elif "webp" in ctype:
                    ext = "webp"
                path = f"{DOWNLOAD_PATH}/search_{int(time.time())}_{random.randint(100,999)}.{ext}"
                with open(path, "wb") as f:
                    f.write(data)
                return path
    except Exception as e:
        logging.warning(f"download_image: {e}")
        return None



def _sender_get(user_id: int, chat_id: int) -> dict:
    uid = int(user_id)
    cid = str(int(chat_id))
    if uid not in SENDER_CONFIG:
        SENDER_CONFIG[uid] = {}
    cfg = SENDER_CONFIG[uid].get(cid) or {
        "enabled": False,
        "mode": "copy",
        "banner_chat_id": None,
        "banner_msg_id": None,
        "delay": 60,
        "hourly_limit": 100,
        "sent_hour": 0,
        "hour_ts": 0,
    }
    SENDER_CONFIG[uid][cid] = cfg
    return cfg


def _sender_set(user_id: int, chat_id: int, **kwargs):
    cfg = _sender_get(user_id, chat_id)
    cfg.update(kwargs)
    SENDER_CONFIG[int(user_id)][str(int(chat_id))] = cfg
    try:
        persist_all_user_settings(user_id)
    except Exception:
        pass
    return cfg


async def _sender_send_once(client, user_id: int, chat_id: int, cfg: dict) -> bool:
    """یک بار ارسال بنر در گروه"""
    bchat = cfg.get("banner_chat_id")
    bmsg = cfg.get("banner_msg_id")
    if not bchat or not bmsg:
        return False
    mode = (cfg.get("mode") or "copy").lower()
    try:
        if mode == "forward":
            await client.forward_messages(int(chat_id), int(bchat), int(bmsg))
        else:
            await client.copy_message(int(chat_id), int(bchat), int(bmsg))
        return True
    except Exception as e:
        logging.warning(f"sender send uid={user_id} chat={chat_id}: {e}")
        return False


async def sender_loop_task(client: Client, user_id: int):
    """حلقه سندر — برای هر گروهی که روشن است، بنر را با تاخیر و سقف ساعتی می‌فرستد"""
    await asyncio.sleep(12)
    while True:
        try:
            if user_id not in ACTIVE_BOTS:
                break
            configs = SENDER_CONFIG.get(user_id) or {}
            if not configs:
                await asyncio.sleep(8)
                continue
            now = int(time.time())
            for cid_str, cfg in list(configs.items()):
                if not cfg or not cfg.get("enabled"):
                    continue
                if not cfg.get("banner_chat_id") or not cfg.get("banner_msg_id"):
                    continue
                # ریست شمارنده ساعتی
                hour_ts = int(cfg.get("hour_ts") or 0)
                if now - hour_ts >= 3600:
                    cfg["hour_ts"] = now
                    cfg["sent_hour"] = 0
                limit = max(50, min(200, int(cfg.get("hourly_limit") or 100)))
                sent = int(cfg.get("sent_hour") or 0)
                if sent >= limit:
                    continue
                delay = max(5, min(3600, int(cfg.get("delay") or 60)))
                last = int(cfg.get("last_send") or 0)
                if now - last < delay:
                    continue
                ok = await _sender_send_once(client, user_id, int(cid_str), cfg)
                if ok:
                    cfg["sent_hour"] = sent + 1
                    cfg["last_send"] = now
                    SENDER_CONFIG[user_id][cid_str] = cfg
                await asyncio.sleep(1.2)
            await asyncio.sleep(3)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logging.error(f"sender_loop_task: {e}")
            await asyncio.sleep(10)



async def mass_forward_banner(client: Client, user_id: int, banner_chat_id: int, banner_msg_id: int):
    """فوروارد/کپی بنر به همه پیوی + گپ + کانال با آمار تفکیکی"""
    state = {
        "running": True,
        "banner_chat_id": banner_chat_id,
        "banner_msg_id": banner_msg_id,
        "sent": 0,
        "failed": 0,
        "total": 0,
        "sent_pv": 0,
        "sent_group": 0,
        "sent_channel": 0,
        "fail_pv": 0,
        "fail_group": 0,
        "fail_channel": 0,
    }
    SENDER_MASS[user_id] = state

    def _kind(chat) -> str:
        try:
            from pyrogram.enums import ChatType
            t = chat.type
            if t == ChatType.PRIVATE:
                return "pv"
            if t in (ChatType.GROUP, ChatType.SUPERGROUP):
                return "group"
            if t == ChatType.CHANNEL:
                return "channel"
        except Exception:
            pass
        s = str(getattr(chat, "type", "")).lower()
        if "private" in s:
            return "pv"
        if "channel" in s:
            return "channel"
        return "group"

    targets = []
    try:
        async for d in client.get_dialogs():
            chat = getattr(d, "chat", None)
            if not chat:
                continue
            kind = _kind(chat)
            if kind == "pv" and getattr(chat, "is_bot", False):
                continue
            # خودِ چت بنر را هم می‌توان فرستاد؛ مشکلی نیست
            targets.append((int(chat.id), kind, getattr(chat, "title", None) or getattr(chat, "first_name", "") or str(chat.id)))
    except Exception as e:
        logging.exception("mass_forward get_dialogs")
        state["running"] = False
        SENDER_MASS[user_id] = state
        try:
            await client.send_message("me", f"❌ نتوانستم لیست چت‌ها را بگیرم:\n`{e}`")
        except Exception:
            pass
        return

    state["total"] = len(targets)
    SENDER_MASS[user_id] = state
    n_pv = sum(1 for _, k, _ in targets if k == "pv")
    n_g = sum(1 for _, k, _ in targets if k == "group")
    n_c = sum(1 for _, k, _ in targets if k == "channel")

    try:
        await client.send_message(
            "me",
            f"📣 سندر فور شروع | self MR\n\n"
            f"🎯 کل چت پیدا شده: {len(targets)}\n"
            f"👤 پیوی: {n_pv}\n"
            f"👥 گپ: {n_g}\n"
            f"📢 کانال: {n_c}\n\n"
            f"در حال ارسال...\n"
            f"توقف: `.سندر فور خاموش`",
        )
    except Exception:
        pass

    if not targets:
        state["running"] = False
        SENDER_MASS[user_id] = state
        try:
            await client.send_message("me", "❌ هیچ چتی برای ارسال پیدا نشد.")
        except Exception:
            pass
        return

    for i, (chat_id, kind, title) in enumerate(targets):
        st = SENDER_MASS.get(user_id) or {}
        if not st.get("running"):
            break

        ok = False
        # 1) فوروارد
        try:
            await client.forward_messages(chat_id, int(banner_chat_id), int(banner_msg_id))
            ok = True
        except Exception as e1:
            # 2) کپی اگر فوروارد ممنوع بود
            try:
                await client.copy_message(chat_id, int(banner_chat_id), int(banner_msg_id))
                ok = True
            except Exception as e2:
                logging.warning(f"mass send fail {chat_id} ({kind}/{title}): {e1} | {e2}")
                ok = False

        if ok:
            st["sent"] = int(st.get("sent") or 0) + 1
            st[f"sent_{kind}"] = int(st.get(f"sent_{kind}") or 0) + 1
        else:
            st["failed"] = int(st.get("failed") or 0) + 1
            st[f"fail_{kind}"] = int(st.get(f"fail_{kind}") or 0) + 1
        SENDER_MASS[user_id] = st

        # ضد فلود
        await asyncio.sleep(random.uniform(2.0, 4.5))
        if (i + 1) % 20 == 0:
            try:
                await client.send_message(
                    "me",
                    f"📣 پیشرفت: {i+1}/{len(targets)}\n"
                    f"✅ {st.get('sent',0)} | ❌ {st.get('failed',0)}\n"
                    f"👤 {st.get('sent_pv',0)} | 👥 {st.get('sent_group',0)} | 📢 {st.get('sent_channel',0)}",
                )
            except Exception:
                pass

    st = SENDER_MASS.get(user_id) or {}
    st["running"] = False
    SENDER_MASS[user_id] = st
    try:
        await client.send_message(
            "me",
            f"🏁 سندر فور تمام شد | self MR\n\n"
            f"✅ موفق کل: {st.get('sent', 0)}\n"
            f"❌ ناموفق کل: {st.get('failed', 0)}\n"
            f"📋 هدف کل: {st.get('total', 0)}\n\n"
            f"👤 پیوی ارسال‌شده: {st.get('sent_pv', 0)}\n"
            f"👥 گپ ارسال‌شده: {st.get('sent_group', 0)}\n"
            f"📢 کانال ارسال‌شده: {st.get('sent_channel', 0)}\n\n"
            f"👤 پیوی ناموفق: {st.get('fail_pv', 0)}\n"
            f"👥 گپ ناموفق: {st.get('fail_group', 0)}\n"
            f"📢 کانال ناموفق: {st.get('fail_channel', 0)}",
        )
    except Exception:
        pass


async def reply_based_controller(client, message):
    user_id = client.me.id
    cmd = (message.text or "").strip()
    if not cmd:
        return



    # ========== اسکرین ==========
    if cmd in (".اسکرین", "اسکرین"):
        try:
            await message.edit_text("⏳ در حال گرفتن اسکرین و ارسال به Saved Messages...")
        except Exception:
            pass
        try:
            sent, errors = await capture_chat_to_saved(client, message.chat.id, limit=20)
            await message.edit_text(
                f"✅ اسکرین انجام شد | self MR\\n\\n"
                f"📤 ارسال‌شده: {sent}\\n"
                f"⚠️ ناموفق: {errors}\\n"
                f"📂 داخل پیام‌های ذخیره‌شده ببین."
            )
        except Exception as e:
            logging.error(f"screen cmd: {e}")
            try:
                await message.edit_text(f"❌ خطا در اسکرین: {e}")
            except Exception:
                pass
        return

    # ========== سرچ عکس ==========
    # سرچ آهنگ جداست — اینجا فقط تصویر
    if (cmd.startswith(".سرچ") or cmd.startswith("سرچ")) and not (
        cmd.startswith(".سرچ آهنگ") or cmd.startswith("سرچ آهنگ")
    ):
        q = ""
        if "+" in cmd:
            q = cmd.split("+", 1)[1].strip()
        else:
            parts = cmd.split(None, 1)
            if len(parts) > 1:
                q = parts[1].strip()
                if q.startswith("+"):
                    q = q[1:].strip()
        if not q:
            await message.edit_text("❌ مثال:\\n`.سرچ + گاو`")
            return
        await message.edit_text(f"🔍 در حال جستجوی تصویر برای:\\n`{q}`")
        try:
            urls = await search_web_images(q, limit=1)
            if not urls:
                await message.edit_text("❌ تصویری پیدا نشد.")
                return
            path = None
            for u in urls:
                path = await download_image_bytes(u)
                if path:
                    break
            if not path:
                await message.edit_text("❌ دانلود تصویر ناموفق بود.")
                return
            try:
                await client.send_photo(
                    message.chat.id,
                    path,
                    caption=f"🔍 {q} | self MR",
                )
                try:
                    await message.delete()
                except Exception:
                    try:
                        await message.edit_text("✅ تصویر ارسال شد.")
                    except Exception:
                        pass
            except Exception as e:
                logging.warning(f"send search photo: {e}")
                await message.edit_text(f"❌ ارسال تصویر ناموفق: {e}")
            finally:
                try:
                    if path and os.path.exists(path):
                        os.remove(path)
                except Exception:
                    pass
        except Exception as e:
            logging.error(f"search cmd: {e}")
            await message.edit_text(f"❌ خطا در سرچ: {e}")
        return

    # ========== هوش متن گسترده ==========
    if cmd.startswith(".هوش متن گسترده") or cmd.startswith("هوش متن گسترده"):
        seed = ""
        if "+" in cmd:
            seed = cmd.split("+", 1)[1].strip()
        elif "گسترده" in cmd:
            seed = cmd.split("گسترده", 1)[1].strip()
            if seed.startswith("+"):
                seed = seed[1:].strip()
        if not seed and message.reply_to_message and (message.reply_to_message.text or message.reply_to_message.caption):
            seed = (message.reply_to_message.text or message.reply_to_message.caption or "").strip()
        if not seed:
            await message.edit_text("❌ مثال:\n`.هوش متن گسترده + علی در روز آفتابی بیرون رفت`")
            return
        await message.edit_text("⏳ DeepSeek در حال گسترش متن...")
        try:
            expanded = await ai_expand_text(seed)
            # ویرایش همان پیام کاربر با متن گسترش‌یافته
            if expanded.startswith("❌"):
                await message.edit_text(expanded)
            else:
                await message.edit_text(expanded)
        except Exception as e:
            await message.edit_text(f"❌ خطا: {e}")
        return

    # ========== متن آهنگ ==========
    if cmd in (".متن آهنگ", "متن آهنگ") or cmd.startswith(".متن آهنگ ") or cmd.startswith("متن آهنگ "):
        title = ""
        artist = ""
        rest = cmd.replace(".متن آهنگ", "", 1).replace("متن آهنگ", "", 1).strip()
        if rest:
            a2, t2 = _split_artist_title(rest)
            if t2:
                artist, title = a2, t2
            else:
                title = rest
        if not title and not message.reply_to_message:
            await message.edit_text("❌ روی آهنگ ریپلای کنید یا بنویسید:\n`.متن آهنگ نام آهنگ`")
            return
        r = message.reply_to_message
        if r:
            if r.audio:
                title = r.audio.title or title
                artist = r.audio.performer or artist
                if not title and r.audio.file_name:
                    title = r.audio.file_name.rsplit(".", 1)[0]
            elif r.document:
                fname = r.document.file_name or ""
                if not title and fname:
                    title = fname.rsplit(".", 1)[0]
            elif (r.text or r.caption) and not title:
                title = (r.text or r.caption or "").strip()
            elif r.voice and not title:
                await message.edit_text("❌ ویس متادیتا ندارد. روی فایل آهنگ (Music) ریپلای کنید یا اسم آهنگ را بفرستید:\n`.متن آهنگ نام آهنگ`")
                return
        # پارس Artist - Title
        if title and not artist:
            a2, t2 = _split_artist_title(title)
            if t2:
                artist, title = a2, t2
        title = _clean_track_name(title)
        artist = _clean_track_name(artist)
        if not title:
            await message.edit_text("❌ نام آهنگ از پیام پیدا نشد.")
            return
        await message.edit_text(f"⏳ در حال جستجوی متن آهنگ...\n🎵 {artist + ' - ' if artist else ''}{title}")
        try:
            lyrics = await fetch_song_lyrics(title, artist)
            if len(lyrics) > 3900:
                await message.edit_text(lyrics[:3900] + "\n\n…")
            else:
                await message.edit_text(lyrics)
        except Exception as e:
            logging.error(f"lyrics cmd: {e}")
            await message.edit_text(f"❌ خطا: {e}")
        return


    # ========== تاس / بولینگ ==========
    if cmd == "تاس":
        await client.send_dice(message.chat.id, "🎲")
        try:
            await message.delete()
        except:
            pass
        return

    if cmd == "بولینگ":
        await client.send_dice(message.chat.id, "🎳")
        try:
            await message.delete()
        except:
            pass
        return

    if cmd.startswith("تاس "):
        try:
            await client.send_dice(message.chat.id, "🎲", reply_to_message_id=message.reply_to_message_id)
        except:
            pass
        return

    # ========== 🎰 تقلب ==========
    cheat_cmd = (cmd or "").strip()

    async def _del_cmd_msg():
        """پاک کردن دستور کاربر — هم گروه هم پیوی"""
        try:
            await client.delete_messages(message.chat.id, message.id)
        except Exception:
            try:
                await message.delete()
            except Exception:
                pass

    if cheat_cmd in (".بولینگ",):
        await _del_cmd_msg()
        ok, val, tries = await cheat_send_dice(client, message.chat.id, "🎳", {6}, 40)
        if not ok:
            try:
                await client.send_message(message.chat.id, "❌ بعد از چند تلاش استرایک نیومد. دوباره بزن.")
            except Exception:
                pass
        return

    if cheat_cmd in (".بسکتبال",):
        await _del_cmd_msg()
        ok, val, tries = await cheat_send_dice(client, message.chat.id, "🏀", {5}, 40)
        if not ok:
            try:
                await client.send_message(message.chat.id, "❌ توپ داخل سبد نیفتاد. دوباره امتحان کن.")
            except Exception:
                pass
        return

    if cheat_cmd in (".فوتبال",):
        await _del_cmd_msg()
        ok, val, tries = await cheat_send_dice(client, message.chat.id, "⚽", {5}, 40)
        if not ok:
            try:
                await client.send_message(message.chat.id, "❌ گل نشد. دوباره بزن.")
            except Exception:
                pass
        return

    # تاس ۱ تا ۶
    dice_match = re.match(r"^\.تاس\s*([1-6۶])$", cheat_cmd.replace("۶", "6").replace("۵", "5").replace("۴", "4").replace("۳", "3").replace("۲", "2").replace("۱", "1"))
    if dice_match:
        target = int(dice_match.group(1))
        await _del_cmd_msg()
        ok, val, tries = await cheat_send_dice(client, message.chat.id, "🎲", {target}, 40)
        if not ok:
            try:
                await client.send_message(message.chat.id, f"❌ تاس {target} نیومد. دوباره بزن.")
            except Exception:
                pass
        return

    if cheat_cmd in (".اسلات 777", ".اسلات۷۷۷", ".اسلات ۷۷۷"):
        await _del_cmd_msg()
        ok, val, tries = await cheat_send_dice(client, message.chat.id, "🎰", {64}, 55)
        if not ok:
            try:
                await client.send_message(message.chat.id, "❌ جکپات ۷۷۷ نیومد. دوباره بزن.")
            except Exception:
                pass
        return

    if cheat_cmd in (".اسلات لیمو",):
        await _del_cmd_msg()
        ok, val, tries = await cheat_send_dice(client, message.chat.id, "🎰", {43}, 50)
        if not ok:
            try:
                await client.send_message(message.chat.id, "❌ سه لیمو نیومد.")
            except Exception:
                pass
        return

    if cheat_cmd in (".اسلات انگور",):
        await _del_cmd_msg()
        ok, val, tries = await cheat_send_dice(client, message.chat.id, "🎰", {22}, 50)
        if not ok:
            try:
                await client.send_message(message.chat.id, "❌ سه انگور نیومد.")
            except Exception:
                pass
        return

    if cheat_cmd in (".اسلات Bar", ".اسلات bar", ".اسلات بار", ".اسلات BAR"):
        await _del_cmd_msg()
        ok, val, tries = await cheat_send_dice(client, message.chat.id, "🎰", {1}, 50)
        if not ok:
            try:
                await client.send_message(message.chat.id, "❌ سه بار نیومد.")
            except Exception:
                pass
        return

    if cmd == "لیست دشمن":
        enemies = ACTIVE_ENEMIES.get(user_id, set())
        await message.edit_text(f"📜 تعداد دشمنان فعال: {len(enemies)}")
        return

    if cmd.startswith("تنظیم منشی "):
        new_msg = cmd.split("تنظیم منشی ", 1)[1].strip()
        if new_msg:
            SECRETARY_CUSTOM_MESSAGES[user_id] = new_msg
            data_manager.update_user_data(user_id, {"settings": {"secretary_msg": new_msg}})
            await message.edit_text(f"✅ متن منشی تنظیم شد:\n\n`{new_msg}`")
        else:
            await message.edit_text("⚠️ لطفا متن منشی را وارد کنید.")
        return

    # ========== دانلود ویدیو ==========
    if cmd.startswith("دانلود ") or cmd.startswith(".دانلود "):
        url = cmd.split(" ", 1)[1].strip() if " " in cmd else ""
        if not url.startswith("http"):
            await message.edit_text("❌ لینک نامعتبر است!")
            return
        await message.edit_text("⏳ در حال دانلود...")
        filename, error = await download_media(url, "video")
        if error:
            await message.edit_text(error)
            return
        try:
            await client.send_video(message.chat.id, filename, caption="✅ دانلود شد | self MR")
            await message.delete()
        except Exception as e:
            try:
                await client.send_document(message.chat.id, filename, caption="✅ دانلود شد | self MR")
                await message.delete()
            except Exception as e2:
                await message.edit_text(f"❌ ارسال ناموفق: {e2}")
        try:
            os.remove(filename)
        except:
            pass
        return

    # ========== دانلود صوت ==========
    if cmd.startswith("صوت ") or cmd.startswith(".صوت "):
        url = cmd.split(" ", 1)[1].strip() if " " in cmd else ""
        if not url.startswith("http"):
            await message.edit_text("❌ لینک نامعتبر است!")
            return
        await message.edit_text("⏳ در حال استخراج صوت...")
        filename, error = await download_media(url, "audio")
        if error:
            await message.edit_text(error)
            return
        try:
            await client.send_audio(message.chat.id, filename, caption="🎵 صوت آماده شد | self MR")
            await message.delete()
        except Exception as e:
            await message.edit_text(f"❌ ارسال ناموفق: {e}")
        try:
            os.remove(filename)
        except:
            pass
        return

    # ========== قیمت ارز با نقطه ==========
    if cmd.startswith(".") and len(cmd) > 1 and not cmd.startswith(".تبدیل") and not cmd.startswith(".صدا") and not cmd.startswith(".دانلود") and not cmd.startswith(".صوت"):
        raw = cmd[1:].strip()
        # فقط یک کلمه یا عبارت ارز
        if raw and chr(10) not in raw and len(raw) < 30:
            alias = CURRENCY_ALIASES.get(raw) or CURRENCY_ALIASES.get(raw.lower())
            if alias:
                await message.edit_text(f"⏳ در حال دریافت قیمت {raw}...")
                price, extra = await fetch_currency_price(alias)
                name = CURRENCY_NAMES.get(alias, raw)
                if price is None:
                    await message.edit_text(extra or "❌ خطا در دریافت قیمت")
                else:
                    time_str = datetime.now(TEHRAN_TIMEZONE).strftime('%H:%M')
                    upd = f"\n📅 بروزرسانی tgju: {extra}" if extra else ""
                    await message.edit_text(
                        f"💱 قیمت {name} الان:\n\n"
                        f"💰 {price}\n"
                        f"📡 منبع: tgju.org\n"
                        f"⏱ {time_str}{upd}"
                    )
                return

    # ========== انتخاب صدای TTS ==========
    if cmd.startswith(".صدا "):
        voice_name = cmd.replace(".صدا ", "").strip()
        if voice_name in TTS_VOICES:
            TTS_VOICE_STATUS[user_id] = voice_name
            await message.edit_text(f"✅ صدای TTS تنظیم شد: {TTS_VOICES[voice_name]['label']}")
        else:
            voices = " | ".join(TTS_VOICES.keys())
            await message.edit_text(f"❌ صدا نامعتبر.\nصداهای موجود: {voices}\nمثال: `.صدا زن`")
        return

    # ========== تبدیل متن به ویس ==========
    if cmd.startswith(".تبدیل متن به ویس") or cmd.startswith("تبدیل متن به ویس"):
        if cmd.startswith("."):
            text_part = cmd.replace(".تبدیل متن به ویس", "", 1).strip()
        else:
            text_part = cmd.replace("تبدیل متن به ویس", "", 1).strip()
        if not text_part:
            await message.edit_text("❌ متن را بعد از دستور بنویس.\nمثال:\n`.تبدیل متن به ویس سلام دوست عزیز`")
            return
        voice_key = TTS_VOICE_STATUS.get(user_id, "زن")
        try:
            await message.edit_text("⏳ در حال ساخت ویس...")
        except Exception:
            pass
        path, err = await text_to_speech(text_part, voice_key)
        if err:
            try:
                await message.edit_text(err)
            except Exception:
                await client.send_message(message.chat.id, err)
            return
        try:
            await client.send_voice(message.chat.id, path, caption=f"🎤 {text_part[:80]}")
            try:
                await message.delete()
            except Exception:
                pass
        except Exception as e:
            try:
                await message.edit_text(f"❌ ارسال ویس ناموفق: {e}")
            except Exception:
                await client.send_message(message.chat.id, f"❌ ارسال ویس ناموفق: {e}")
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
        return

    # ========== آیدی (با یا بدون ریپلای) ==========
    if cmd == "آیدی" or cmd == ".آیدی":
        target = None
        if message.reply_to_message and message.reply_to_message.from_user:
            target = message.reply_to_message.from_user
        else:
            target = await client.get_me()
        try:
            chat = await client.get_chat(target.id)
        except Exception:
            chat = target

        # تعداد عکس پروفایل
        photo_count = 0
        try:
            async for _ in client.get_chat_photos(target.id, limit=100):
                photo_count += 1
        except Exception:
            photo_count = getattr(chat, "photo", None) and 1 or 0

        bio = ""
        try:
            bio = getattr(chat, "bio", None) or ""
        except Exception:
            bio = ""

        username = f"@{target.username}" if getattr(target, "username", None) else "ندارد"
        phone = getattr(target, "phone_number", None) or "مخفی / در دسترس نیست"
        dc_id = getattr(getattr(target, "photo", None), "dc_id", None) or "-"

        info = (
            f"👤 اطلاعات کاربر | self MR\n\n"
            f"🆔 آیدی عددی: `{target.id}`\n"
            f"👤 نام: {target.first_name or ''} {target.last_name or ''}\n"
            f"📱 یوزرنیم: {username}\n"
            f"📞 شماره: {phone}\n"
            f"📝 بیو: {bio or 'ندارد'}\n"
            f"🖼 تعداد عکس پروفایل: {photo_count}\n"
            f"🌐 DC: {dc_id}"
        )
        try:
            await message.edit_text(info)
        except Exception:
            await client.send_message(message.chat.id, info)
        return

    # ========== اسم چرخشی ==========
    if cmd.startswith(".افزودن اسم ") or cmd.startswith("افزودن اسم "):
        name = cmd.split(" ", 2)[-1].strip() if cmd.count(" ") >= 2 else ""
        # .افزودن اسم علی
        parts = cmd.lstrip(".").split(None, 2)
        if len(parts) < 3:
            await message.edit_text("❌ مثال:\\n`.افزودن اسم علی`")
            return
        name = parts[2].strip()[:64]
        if not name:
            await message.edit_text("❌ اسم خالی است.")
            return
        lst = ROTATING_NAMES.get(user_id) or []
        lst.append(name)
        ROTATING_NAMES[user_id] = lst
        persist_all_user_settings(user_id)
        await message.edit_text(f"✅ اسم اضافه شد: `{name}`\\nتعداد لیست: {len(lst)}")
        return

    if cmd.startswith(".تنظیم تایم اسم ") or cmd.startswith("تنظیم تایم اسم "):
        parts = cmd.lstrip(".").split()
        try:
            sec = int(parts[-1])
        except Exception:
            await message.edit_text("❌ مثال:\\n`.تنظیم تایم اسم 5`")
            return
        if sec < 3:
            await message.edit_text("❌ حداقل ۳ ثانیه.")
            return
        if sec > 3600:
            await message.edit_text("❌ حداکثر ۳۶۰۰ ثانیه.")
            return
        ROTATING_NAME_INTERVAL[user_id] = sec
        persist_all_user_settings(user_id)
        await message.edit_text(f"✅ تایم اسم چرخشی: هر {sec} ثانیه")
        return

    if cmd in (".پاکسازی لیست اسم چرخشی", "پاکسازی لیست اسم چرخشی", ".پاکسازی لیست اسم", "پاکسازی لیست اسم"):
        ROTATING_NAMES[user_id] = []
        ROTATING_NAME_INDEX[user_id] = 0
        persist_all_user_settings(user_id)
        await message.edit_text("✅ لیست اسامی چرخشی پاک شد.")
        return

    if cmd in (".لیست اسامی چرخشی", "لیست اسامی چرخشی", ".لیست اسامی", "لیست اسامی"):
        lst = ROTATING_NAMES.get(user_id) or []
        if not lst:
            await message.edit_text("لیست اسامی خالی است.")
            return
        body = "\\n".join(f"{i}. {n}" for i, n in enumerate(lst, 1))
        interval = ROTATING_NAME_INTERVAL.get(user_id, 10)
        st = "on ✅" if ROTATING_NAME_STATUS.get(user_id) else "off ❌"
        await message.edit_text(
            f"لیست اسامی چرخشی | self MR\\n\\n{body}\\n\\n"
            f"⏱ تایم: {interval} ثانیه\\nوضعیت: {st}"
        )
        return

    if cmd in (".اسم چرخشی روشن", "اسم چرخشی روشن"):
        lst = ROTATING_NAMES.get(user_id) or []
        if len(lst) < 1:
            await message.edit_text("❌ اول با `.افزودن اسم ...` اسم اضافه کنید.")
            return
        ROTATING_NAME_STATUS[user_id] = True
        persist_all_user_settings(user_id)
        await message.edit_text("✅ اسم چرخشی روشن شد | self MR")
        return

    if cmd in (".اسم چرخشی خاموش", "اسم چرخشی خاموش"):
        ROTATING_NAME_STATUS[user_id] = False
        persist_all_user_settings(user_id)
        await message.edit_text("❌ اسم چرخشی خاموش شد | self MR")
        return

    # ========== آهنگ چرخشی ==========
    if cmd in (".اضافه کردن آهنگ", "اضافه کردن آهنگ", ".افزودن آهنگ", "افزودن آهنگ"):
        reply = message.reply_to_message
        if not reply or not (reply.audio or reply.document or reply.voice):
            await message.edit_text("❌ روی یک فایل آهنگ / موزیک ریپلای کنید و بعد بفرستید:\n`.اضافه کردن آهنگ`")
            return
        media = reply.audio or reply.document or reply.voice
        file_id = media.file_id
        title = None
        if reply.audio:
            title = reply.audio.title or reply.audio.file_name
            if reply.audio.performer:
                title = f"{reply.audio.performer} - {title}" if title else reply.audio.performer
        if not title:
            title = getattr(media, "file_name", None) or f"آهنگ {len(ROTATING_MUSIC.get(user_id) or []) + 1}"
        title = str(title)[:80]
        # دانلود محلی برای اعمال پایدار روی پروفایل
        local_path = ""
        try:
            music_dir = os.path.join(DOWNLOAD_PATH, "music", str(user_id))
            os.makedirs(music_dir, exist_ok=True)
            local_path = await client.download_media(
                reply,
                file_name=os.path.join(music_dir, f"track_{int(time.time())}_{random.randint(100,999)}")
            ) or ""
        except Exception as e:
            logging.warning(f"music download for rotate: {e}")
            local_path = ""
        lst = ROTATING_MUSIC.get(user_id) or []
        lst.append({"file_id": file_id, "title": title, "path": local_path or "", "chat_id": reply.chat.id if reply.chat else None, "msg_id": reply.id})
        ROTATING_MUSIC[user_id] = lst
        persist_all_user_settings(user_id)
        await message.edit_text(f"✅ آهنگ اضافه شد: `{title}`\nتعداد لیست: {len(lst)}")
        return

    if cmd.startswith(".تنظیم تایم آهنگ ") or cmd.startswith("تنظیم تایم آهنگ "):
        parts = cmd.lstrip(".").split()
        try:
            hours = int(parts[-1])
        except Exception:
            await message.edit_text("❌ مثال:\n`.تنظیم تایم آهنگ 2`\n(ساعت — حداقل ۱ حداکثر ۲۴)")
            return
        if hours < 1:
            await message.edit_text("❌ حداقل ۱ ساعت.")
            return
        if hours > 24:
            await message.edit_text("❌ حداکثر ۲۴ ساعت.")
            return
        ROTATING_MUSIC_INTERVAL[user_id] = hours
        persist_all_user_settings(user_id)
        await message.edit_text(f"✅ تایم آهنگ چرخشی: هر {hours} ساعت")
        return

    if cmd in (".پاکسازی لیست آهنگ چرخشی", "پاکسازی لیست آهنگ چرخشی", ".پاکسازی لیست آهنگ", "پاکسازی لیست آهنگ"):
        ROTATING_MUSIC[user_id] = []
        ROTATING_MUSIC_INDEX[user_id] = 0
        persist_all_user_settings(user_id)
        await message.edit_text("✅ لیست آهنگ چرخشی پاک شد.")
        return

    if cmd in (".لیست آهنگ چرخشی", "لیست آهنگ چرخشی", ".لیست آهنگ", "لیست آهنگ"):
        lst = ROTATING_MUSIC.get(user_id) or []
        if not lst:
            await message.edit_text("لیست آهنگ چرخشی خالی است.")
            return
        body = "\n".join(
            f"{i}. {(t.get('title') if isinstance(t, dict) else t)}"
            for i, t in enumerate(lst, 1)
        )
        interval = ROTATING_MUSIC_INTERVAL.get(user_id, 1)
        st = "on ✅" if ROTATING_MUSIC_STATUS.get(user_id) else "off ❌"
        await message.edit_text(
            f"لیست آهنگ چرخشی | self MR\n\n{body}\n\n"
            f"⏱ تایم: هر {interval} ساعت\nوضعیت: {st}"
        )
        return

    if cmd in (".آهنگ چرخشی روشن", "آهنگ چرخشی روشن"):
        lst = ROTATING_MUSIC.get(user_id) or []
        if len(lst) < 1:
            await message.edit_text("❌ اول با ریپلای + `.اضافه کردن آهنگ` آهنگ اضافه کنید.")
            return
        ROTATING_MUSIC_STATUS[user_id] = True
        persist_all_user_settings(user_id)
        # اعمال فوری اولین آهنگ
        try:
            idx = ROTATING_MUSIC_INDEX.get(user_id, 0) % len(lst)
            ok = await _apply_profile_music(client, user_id, lst[idx])
            ROTATING_MUSIC_INDEX[user_id] = (idx + 1) % len(lst)
            if ok:
                await message.edit_text(
                    f"✅ آهنگ چرخشی روشن شد | self MR\n"
                    f"🎵 الان: `{lst[idx].get('title', 'آهنگ')}`"
                )
            else:
                await message.edit_text(
                    "✅ آهنگ چرخشی روشن شد | self MR\n"
                    "⚠️ اعمال روی پروفایل ممکن است چند لحظه طول بکشد یا توسط تلگرام محدود شود."
                )
        except Exception as e:
            logging.warning(f"apply music on enable: {e}")
            await message.edit_text("✅ آهنگ چرخشی روشن شد | self MR")
        return

    if cmd in (".آهنگ چرخشی خاموش", "آهنگ چرخشی خاموش"):
        ROTATING_MUSIC_STATUS[user_id] = False
        persist_all_user_settings(user_id)
        await message.edit_text("❌ آهنگ چرخشی خاموش شد | self MR")
        return

    # ========== ساعت کشورها ==========
    if cmd.startswith(".ساعت ") or cmd.startswith("ساعت ") or cmd.startswith(".زمان "):
        place = cmd.split(" ", 1)[1].strip() if " " in cmd else ""
        if not place:
            await message.edit_text("❌ مثال:\n`.ساعت ایران`\n`.ساعت Tokyo`")
            return
        txt = await get_time_for_place(place)
        await message.edit_text(txt)
        return

    # ========== آب و هوا ==========
    if cmd.startswith(".آب و هوا ") or cmd.startswith("آب و هوا ") or cmd.startswith(".هوای "):
        place = cmd.split(" ", 1)[1].strip() if " " in cmd else ""
        # برای ".آب و هوا تهران" split با ۱ کافی نیست چون ۲ فاصله دارد
        for prefix in (".آب و هوا ", "آب و هوا ", ".هوای "):
            if cmd.startswith(prefix):
                place = cmd[len(prefix):].strip()
                break
        if not place:
            await message.edit_text("❌ مثال:\n`.آب و هوا تهران`")
            return
        await message.edit_text("⏳ دریافت آب‌وهوا...")
        txt = await get_weather_for_place(place)
        await message.edit_text(txt)
        return

    # ========== ویس به متن ==========
    if cmd in (".ویس به متن", "ویس به متن", ".تبدیل ویس به متن", "تبدیل ویس به متن"):
        await message.edit_text("⏳ در حال تبدیل ویس به متن...")
        txt = await voice_to_text(client, message)
        await message.edit_text(txt)
        return



    # ========== سندر فور همگانی (یک دستور) ==========
    if cmd in (".تنظیم سندر فور", "تنظیم سندر فور", ".تنظیم بنر فور", "تنظیم بنر فور", ".سندر فور", "سندر فور"):
        reply = message.reply_to_message
        if not reply:
            await message.edit_text(
                "❌ روی پیام بنر **ریپلای** کن و بفرست:\n`.تنظیم سندر فور`"
            )
            return
        bchat = reply.chat.id if reply.chat else message.chat.id
        bmsg = reply.id
        st = SENDER_MASS.get(user_id) or {}
        if st.get("running"):
            await message.edit_text("⚠️ سندر قبلی هنوز در حال اجراست.\nاول `.سندر فور خاموش` بزن.")
            return
        await message.edit_text(
            "🚀 سندر فور شروع شد...\n"
            "به همه گپ / کانال / پیوی‌ها فوروارد می‌شود.\n"
            "گزارش در Saved Messages می‌آید.\n"
            "توقف: `.سندر فور خاموش`"
        )
        asyncio.create_task(mass_forward_banner(client, user_id, bchat, bmsg))
        return

    if cmd in (".سندر فور خاموش", "سندر فور خاموش"):
        st = SENDER_MASS.get(user_id) or {}
        st["running"] = False
        SENDER_MASS[user_id] = st
        await message.edit_text("⏹ سندر فور متوقف شد.")
        return

    if cmd in (".سندر فور وضعیت", "سندر فور وضعیت"):
        st = SENDER_MASS.get(user_id) or {}
        running = "در حال اجرا ✅" if st.get("running") else "خاموش ❌"
        await message.edit_text(
            f"📣 وضعیت سندر فور | self MR\n\n"
            f"وضعیت: {running}\n"
            f"✅ موفق کل: {st.get('sent', 0)}\n"
            f"❌ ناموفق کل: {st.get('failed', 0)}\n"
            f"📋 کل هدف: {st.get('total', 0)}\n\n"
            f"👤 پیوی ارسال‌شده: {st.get('sent_pv', 0)}\n"
            f"👥 گپ ارسال‌شده: {st.get('sent_group', 0)}\n"
            f"📢 کانال ارسال‌شده: {st.get('sent_channel', 0)}"
        )
        return

    # ========== سندر ==========
    if cmd in (".تنظیم بنر سندر", "تنظیم بنر سندر"):
        reply = message.reply_to_message
        if not reply:
            await message.edit_text("❌ روی بنر ریپلای کن:\n`.تنظیم بنر سندر`")
            return
        chat_id = message.chat.id
        _sender_set(
            user_id, chat_id,
            banner_chat_id=reply.chat.id if reply.chat else chat_id,
            banner_msg_id=reply.id,
            mode="copy",
        )
        await message.edit_text(
            "✅ بنر سندر (کپی) ثبت شد | self MR\n"
            "با `.سندر روشن 100` فعال کن."
        )
        return

    if cmd in (".تنظیم بنر فور", "تنظیم بنر فور", ".تنظیم بنر فوروارد"):
        reply = message.reply_to_message
        if not reply:
            await message.edit_text("❌ روی بنر ریپلای کن:\n`.تنظیم بنر فور`")
            return
        chat_id = message.chat.id
        _sender_set(
            user_id, chat_id,
            banner_chat_id=reply.chat.id if reply.chat else chat_id,
            banner_msg_id=reply.id,
            mode="forward",
        )
        await message.edit_text(
            "✅ بنر فور (فوروارد) ثبت شد | self MR\n"
            "با `.سندر روشن 100` فعال کن."
        )
        return

    if cmd.startswith(".سندر روشن") or cmd.startswith("سندر روشن"):
        parts = cmd.split()
        limit = 100
        for p in parts:
            if p.isdigit():
                limit = int(p)
                break
        limit = max(50, min(200, limit))
        chat_id = message.chat.id
        cfg = _sender_get(user_id, chat_id)
        if not cfg.get("banner_msg_id"):
            await message.edit_text(
                "❌ اول بنر را تنظیم کن:\n"
                "`.تنظیم بنر سندر` یا `.تنظیم بنر فور`\n"
                "(روی پیام بنر ریپلای کن)"
            )
            return
        _sender_set(
            user_id, chat_id,
            enabled=True,
            hourly_limit=limit,
            sent_hour=0,
            hour_ts=int(time.time()),
        )
        await message.edit_text(
            f"✅ سندر روشن شد | self MR\n"
            f"📊 سهمیه: {limit} ارسال / ساعت\n"
            f"⏱ تاخیر: {cfg.get('delay', 60)} ثانیه\n"
            f"📤 حالت: {cfg.get('mode', 'copy')}"
        )
        return

    if cmd in (".سندر خاموش", "سندر خاموش"):
        chat_id = message.chat.id
        _sender_set(user_id, chat_id, enabled=False)
        await message.edit_text("❌ سندر خاموش شد | self MR")
        return

    if cmd.startswith(".سندر تاخیر") or cmd.startswith("سندر تاخیر"):
        parts = cmd.split()
        delay = None
        for p in parts:
            if p.isdigit():
                delay = int(p)
                break
        if delay is None:
            await message.edit_text("❌ مثال:\n`.سندر تاخیر 60`")
            return
        delay = max(5, min(3600, delay))
        chat_id = message.chat.id
        _sender_set(user_id, chat_id, delay=delay)
        await message.edit_text(f"✅ تاخیر سندر: {delay} ثانیه")
        return

    if cmd in (".بنر فور", "بنر فور", ".بنر فوروارد"):
        chat_id = message.chat.id
        _sender_set(user_id, chat_id, mode="forward")
        await message.edit_text("✅ حالت ارسال: **فوروارد**")
        return

    if cmd in (".بنر کپی", "بنر کپی"):
        chat_id = message.chat.id
        _sender_set(user_id, chat_id, mode="copy")
        await message.edit_text("✅ حالت ارسال: **کپی**")
        return

    if cmd in (".سندر وضعیت", "سندر وضعیت"):
        chat_id = message.chat.id
        cfg = _sender_get(user_id, chat_id)
        st = "روشن ✅" if cfg.get("enabled") else "خاموش ❌"
        has_banner = "✅" if cfg.get("banner_msg_id") else "❌"
        text = (
            f"📊 **وضعیت سندر | self MR**\n\n"
            f"وضعیت: {st}\n"
            f"بنر: {has_banner}\n"
            f"حالت: `{cfg.get('mode', 'copy')}`\n"
            f"تاخیر: `{cfg.get('delay', 60)}` ثانیه\n"
            f"سهمیه ساعتی: `{cfg.get('hourly_limit', 100)}`\n"
            f"ارسال این ساعت: `{cfg.get('sent_hour', 0)}`"
        )
        await message.edit_text(text)
        return

    if cmd in (".سندر حذف", "سندر حذف"):
        chat_id = message.chat.id
        uid = int(user_id)
        cid = str(int(chat_id))
        if uid in SENDER_CONFIG and cid in SENDER_CONFIG[uid]:
            del SENDER_CONFIG[uid][cid]
            try:
                persist_all_user_settings(user_id)
            except Exception:
                pass
        await message.edit_text("🗑 تنظیمات سندر این گروه حذف شد.")
        return

    # ========== کیفیت عکس ==========
    if cmd in (".کیفیت عکس", "کیفیت عکس", ".بهبود عکس", "بهبود عکس", ".افزایش کیفیت", "افزایش کیفیت"):
        await enhance_photo_quality(client, message)
        return

    # ========== سرچ آهنگ ==========
    if cmd.startswith(".سرچ آهنگ ") or cmd.startswith("سرچ آهنگ "):
        for prefix in (".سرچ آهنگ ", "سرچ آهنگ "):
            if cmd.startswith(prefix):
                q = cmd[len(prefix):].strip()
                break
        else:
            q = ""
        if not q:
            await message.edit_text("❌ مثال:\n`.سرچ آهنگ شادمهر`")
            return
        await message.edit_text("⏳ در حال سرچ از یوتیوب / ساندکلود / ...")
        tracks = await search_songs_list(q)
        if not tracks:
            await message.edit_text(f"❌ آهنگی برای `{q}` پیدا نشد.")
            return
        tracks = tracks[:12]
        SONG_SEARCH_CACHE[user_id] = tracks
        PENDING_SONG_PICK[user_id] = True

        header = f"🎵 سرچ آهنگ | self MR\n\n🔎 {q}\n📌 {len(tracks)} نتیجه — روی دکمه بزن"
        rows = []
        for i, t in enumerate(tracks):
            ar = (t.get("artist") or "").strip()
            ti = (t.get("title") or "آهنگ").strip()
            label = f"🎵 {ar} — {ti}" if ar else f"🎵 {ti}"
            label = label[:64]
            rows.append([InlineKeyboardButton(label, callback_data=f"song_dl_{user_id}_{i}")])

        sent = False
        # دکمه اینلاین از ربات منیجر (هر آهنگ یک دکمه)
        try:
            await manager_bot.send_message(
                message.chat.id,
                header,
                reply_markup=InlineKeyboardMarkup(rows),
            )
            sent = True
        except Exception as e1:
            logging.warning(f"song inline chat: {e1}")
            try:
                await manager_bot.send_message(
                    user_id,
                    header + "\n\n(در پیوی — ربات را به گروه اضافه کن تا اینجا هم بیاید)",
                    reply_markup=InlineKeyboardMarkup(rows),
                )
                sent = True
            except Exception as e2:
                logging.warning(f"song inline pm: {e2}")

        # کیبورد سلف (هر آهنگ یک دکمه) — همیشه
        kb_rows = []
        for i, t in enumerate(tracks):
            ar = (t.get("artist") or "").strip()
            ti = (t.get("title") or "آهنگ").strip()
            label = f"{i+1}️⃣ {ar} — {ti}" if ar else f"{i+1}️⃣ {ti}"
            label = label[:64]
            kb_rows.append([KeyboardButton(label)])
        kb_rows.append([KeyboardButton("❌ لغو سرچ")])
        try:
            await client.send_message(
                message.chat.id,
                "⬇️ یا از دکمه‌های پایین یکی را انتخاب کن:",
                reply_markup=ReplyKeyboardMarkup(kb_rows, resize_keyboard=True, one_time_keyboard=True),
            )
            sent = True
        except Exception as e:
            logging.warning(f"song reply kb: {e}")

        try:
            if sent:
                await message.edit_text("✅ نتایج آماده است — روی دکمه آهنگ بزن.")
            else:
                await message.edit_text("❌ ارسال دکمه‌ها ناموفق بود.")
        except Exception:
            pass
        return

    # انتخاب آهنگ با شماره / دکمه کیبورد سلف
    if PENDING_SONG_PICK.get(user_id) and SONG_SEARCH_CACHE.get(user_id):
        tracks = SONG_SEARCH_CACHE.get(user_id) or []
        pick = None
        raw = cmd.strip()
        if raw in ("❌ لغو سرچ", "لغو سرچ", "لغو"):
            PENDING_SONG_PICK[user_id] = False
            try:
                await message.reply_text("❌ سرچ لغو شد.", reply_markup=ReplyKeyboardRemove())
            except Exception:
                pass
            try:
                await message.delete()
            except Exception:
                pass
            return
        mnum = re.match(r"^(\d{1,2})\s*[️⃣.)\-]?\s*", raw)
        if mnum:
            pick = int(mnum.group(1)) - 1
        if pick is None and (cmd.startswith(".آهنگ ") or cmd.startswith("آهنگ ")):
            try:
                pick = int(cmd.split(None, 1)[1].strip()) - 1
            except Exception:
                pick = None
        if pick is not None and 0 <= pick < len(tracks):
            track = tracks[pick]
            PENDING_SONG_PICK[user_id] = False
            q = (track.get("query") or f"{track.get('artist','')} {track.get('title','')}").strip()
            try:
                await message.reply_text(
                    f"⏳ دانلود...\n🎵 {track.get('artist','')} — {track.get('title','')}",
                    reply_markup=ReplyKeyboardRemove(),
                )
            except Exception:
                pass
            try:
                await message.delete()
            except Exception:
                pass
            result, err = await download_song_audio(q)
            if not result:
                result, err = await download_song_audio(track.get("title") or q)
            if not result:
                await client.send_message(message.chat.id, f"❌ دانلود ناموفق:\n`{err}`")
                return
            if track.get("title"):
                result["title"] = track.get("title") or result.get("title")
            if track.get("artist"):
                result["artist"] = track.get("artist") or result.get("artist")
            await send_downloaded_song(client, message.chat.id, result, status_msg=None)
            return

    # ========== عکس به PDF ==========
    if cmd in (".عکس به pdf", "عکس به pdf", ".عکس به PDF", "عکس به PDF", ".تبدیل عکس به pdf"):
        await photo_to_pdf(client, message)
        return

    # ========== PDF به عکس ==========
    if cmd in (".pdf به عکس", "pdf به عکس", ".PDF به عکس", ".تبدیل pdf به عکس"):
        await pdf_to_photo(client, message)
        return

    # ========== تگ ادمین / اعضا ==========
    if cmd in (".تگ ادمین", "تگ ادمین", ".تگ ادمین‌ها", "تگ ادمین‌ها"):
        await tag_admins(client, message)
        return

    if cmd in (".تگ اعضا", "تگ اعضا", ".تگ همه", "تگ همه"):
        await tag_members(client, message)
        return

    # ========== کامنت اول کانال ==========
    if cmd in (".کامنت اول روشن", "کامنت اول روشن"):
        FIRST_COMMENT_STATUS[user_id] = True
        persist_all_user_settings(user_id)
        await message.edit_text("✅ کامنت اول روشن شد | self MR")
        return
    if cmd in (".کامنت اول خاموش", "کامنت اول خاموش"):
        FIRST_COMMENT_STATUS[user_id] = False
        persist_all_user_settings(user_id)
        await message.edit_text("❌ کامنت اول خاموش شد | self MR")
        return
    if cmd.startswith(".تنظیم کامنت اول ") or cmd.startswith("تنظیم کامنت اول "):
        for prefix in (".تنظیم کامنت اول ", "تنظیم کامنت اول "):
            if cmd.startswith(prefix):
                text = cmd[len(prefix):].strip()
                break
        else:
            text = ""
        if not text:
            await message.edit_text("❌ مثال:\n`.تنظیم کامنت اول سلام دوستان 🔥`")
            return
        FIRST_COMMENT_TEXT[user_id] = text[:500]
        persist_all_user_settings(user_id)
        await message.edit_text(f"✅ متن کامنت اول تنظیم شد:\n`{text[:200]}`")
        return

    # ========== فونت متن با دستور ==========
    if cmd.startswith(".فونت ") or cmd.startswith("فونت "):
        name = cmd.split(None, 1)[-1].strip() if " " in cmd else ""
        # map persian names
        rev = {v: k for k, v in FONT_PERSIAN_NAMES.items()}
        rev.update({
            "بولد": "bold", "bold": "bold",
            "ایتالیک": "italic", "italic": "italic",
            "زیرخط": "underline", "underline": "underline",
            "خط‌خورده": "strikethrough", "خط خورده": "strikethrough", "strikethrough": "strikethrough",
            "اسپویلر": "spoiler", "spoiler": "spoiler",
            "مونو": "mono", "mono": "mono",
            "کد": "codeblock", "کدبلاک": "codeblock", "codeblock": "codeblock",
            "نقل قول": "quote", "quote": "quote",
            "خاموش": "none", "off": "none", "none": "none",
        })
        key = rev.get(name)
        if not key:
            opts = " | ".join(FONT_PERSIAN_NAMES.values())
            await message.edit_text(f"❌ فونت نامعتبر.\\nمثال: `.فونت بولد`\\n\\nگزینه‌ها: {opts} | خاموش")
            return
        TEXT_FONT_STATUS[user_id] = key
        persist_all_user_settings(user_id)
        label = FONT_PERSIAN_NAMES.get(key, key)
        await message.edit_text(f"✅ فونت متن: {label}" if key != "none" else "❌ فونت متن خاموش شد")
        return

    # ========== انیمیشن ایموجی ==========
    anim_key = None
    if cmd.startswith("."):
        maybe = cmd[1:].strip()
        if maybe in EMOJI_ANIMATIONS:
            anim_key = maybe
    if anim_key:
        asyncio.create_task(run_emoji_animation(client, message, anim_key))
        return

    # ========== هشدار ویرایش / حذف ==========
    if cmd in (".هشدار ویرایش روشن", "هشدار ویرایش روشن"):
        EDIT_ALERT_STATUS[user_id] = True
        data_manager.update_user_data(user_id, {"settings": {"edit_alert": True}})
        persist_all_user_settings(user_id)
        await message.edit_text("✅ هشدار ویرایش پیام روشن شد | self MR\nپیام قبل از ویرایش به Saved Messages می‌رود.")
        return
    if cmd in (".هشدار ویرایش خاموش", "هشدار ویرایش خاموش"):
        EDIT_ALERT_STATUS[user_id] = False
        data_manager.update_user_data(user_id, {"settings": {"edit_alert": False}})
        persist_all_user_settings(user_id)
        await message.edit_text("❌ هشدار ویرایش پیام خاموش شد | self MR")
        return
    if cmd in (".هشدار حذف روشن", "هشدار حذف روشن"):
        DELETE_ALERT_STATUS[user_id] = True
        data_manager.update_user_data(user_id, {"settings": {"delete_alert": True}})
        persist_all_user_settings(user_id)
        await message.edit_text("✅ هشدار حذف پیام روشن شد | self MR\nمتن پیام حذف‌شده به Saved Messages می‌رود.")
        return
    if cmd in (".هشدار حذف خاموش", "هشدار حذف خاموش"):
        DELETE_ALERT_STATUS[user_id] = False
        data_manager.update_user_data(user_id, {"settings": {"delete_alert": False}})
        persist_all_user_settings(user_id)
        await message.edit_text("❌ هشدار حذف پیام خاموش شد | self MR")
        return

    # ========== عضویت اجباری پیوی ==========
    if cmd in (".وضعیت عضویت اجباری", "وضعیت عضویت اجباری"):
        st = FORCE_JOIN_PV_STATUS.get(user_id, False)
        chs = FORCE_JOIN_CHANNELS.get(user_id) or []
        status = "on ✅" if st else "off ❌"
        await message.edit_text(
            f"عضویت اجباری پیوی | self MR\n\n"
            f"وضعیت: ({status})\n"
            f"کانال‌های ثبت‌شده: {len(chs)}"
        )
        return

    if cmd.startswith(".تنظیم عضویت ") or cmd.startswith("تنظیم عضویت "):
        ch = cmd.split(" ", 2)[-1].strip() if cmd.startswith(".") else cmd.split(" ", 2)[-1].strip()
        # بهتر:
        parts = cmd.lstrip(".").split()
        # تنظیم عضویت @channel
        if len(parts) < 3:
            await message.edit_text("❌ مثال:\n`.تنظیم عضویت @channel`")
            return
        ch = parts[2].strip()
        if not ch.startswith("@") and not ch.lstrip("-").isdigit():
            ch = "@" + ch
        lst = FORCE_JOIN_CHANNELS.get(user_id) or []
        if ch in lst:
            await message.edit_text(f"⚠️ {ch} قبلاً ثبت شده است.")
            return
        lst.append(ch)
        FORCE_JOIN_CHANNELS[user_id] = lst
        data_manager.update_user_data(user_id, {"settings": {"force_join_channels": lst}})
        persist_all_user_settings(user_id)
        await message.edit_text(f"✅ کانال {ch} اضافه شد.\nتعداد کل: {len(lst)}")
        return

    if cmd.startswith(".حذف عضویت ") or cmd.startswith("حذف عضویت "):
        parts = cmd.lstrip(".").split()
        if len(parts) < 3:
            await message.edit_text("❌ مثال:\n`.حذف عضویت @channel`")
            return
        ch = parts[2].strip()
        if not ch.startswith("@") and not ch.lstrip("-").isdigit():
            ch = "@" + ch
        lst = FORCE_JOIN_CHANNELS.get(user_id) or []
        if ch not in lst:
            await message.edit_text(f"⚠️ {ch} در لیست نیست.")
            return
        lst = [x for x in lst if x != ch]
        FORCE_JOIN_CHANNELS[user_id] = lst
        data_manager.update_user_data(user_id, {"settings": {"force_join_channels": lst}})
        persist_all_user_settings(user_id)
        await message.edit_text(f"✅ {ch} حذف شد.\nباقی‌مانده: {len(lst)}")
        return

    if cmd in (".لیست عضویت اجباری", "لیست عضویت اجباری"):
        lst = FORCE_JOIN_CHANNELS.get(user_id) or []
        if not lst:
            await message.edit_text("لیست خالی است.")
            return
        body = "\n".join(f"• {c}" for c in lst)
        await message.edit_text(f"لیست عضویت اجباری | self MR\n\n{body}\n\nتعداد: {len(lst)}")
        return

    if cmd in (".پاکسازی عضویت اجباری", "پاکسازی عضویت اجباری"):
        FORCE_JOIN_CHANNELS[user_id] = []
        data_manager.update_user_data(user_id, {"settings": {"force_join_channels": []}})
        persist_all_user_settings(user_id)
        await message.edit_text("✅ همه کانال‌های عضویت اجباری پاک شدند.")
        return

    if cmd in (".عضویت اجباری روشن", "عضویت اجباری روشن"):
        FORCE_JOIN_PV_STATUS[user_id] = True
        data_manager.update_user_data(user_id, {"settings": {"force_join_pv": True}})
        persist_all_user_settings(user_id)
        await message.edit_text("✅ عضویت اجباری پیوی روشن شد | self MR")
        return

    if cmd in (".عضویت اجباری خاموش", "عضویت اجباری خاموش"):
        FORCE_JOIN_PV_STATUS[user_id] = False
        data_manager.update_user_data(user_id, {"settings": {"force_join_pv": False}})
        persist_all_user_settings(user_id)
        await message.edit_text("❌ عضویت اجباری پیوی خاموش شد | self MR")
        return

    # ========== ویدیو مسیج / ویدیو گرد ==========
    if cmd in (".ویدیو مسیج", "ویدیو مسیج", ".ویدیو مسیج", ".ویدیومسیج"):
        if not message.reply_to_message:
            await message.edit_text("❌ روی یک ویدیو ریپلای کنید.\nمثال: ریپلای + `.ویدیو مسیج`")
            return
        try:
            await message.edit_text("⏳ در حال ساخت ویدیو گرد...")
        except Exception:
            pass
        path, err = await convert_video_to_note(client, message)
        if err:
            try:
                await message.edit_text(err)
            except Exception:
                await client.send_message(message.chat.id, err)
            return
        try:
            await client.send_video_note(message.chat.id, path)
            try:
                await message.delete()
            except Exception:
                pass
        except Exception as e:
            try:
                # فال‌بک: ارسال ویدیو عادی
                await client.send_video(message.chat.id, path, caption="🎥 ویدیو گرد | self MR")
                try:
                    await message.delete()
                except Exception:
                    pass
            except Exception as e2:
                await message.edit_text(f"❌ ارسال ناموفق: {e2}")
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
        return

    # ========== تبدیل به استیکر ==========
    if cmd in (".تبدیل به استیکر", "تبدیل به استیکر"):
        if not message.reply_to_message:
            await message.edit_text("❌ روی یک عکس یا متن ریپلای کنید و دوباره بفرستید.")
            return
        try:
            await message.edit_text("⏳ در حال ساخت استیکر...")
        except Exception:
            pass
        path, err = await convert_message_to_sticker(client, message)
        if err:
            try:
                await message.edit_text(err)
            except Exception:
                await client.send_message(message.chat.id, err)
            return
        try:
            await client.send_sticker(message.chat.id, path)
            try:
                await message.delete()
            except Exception:
                pass
        except Exception as e:
            try:
                # فال‌بک: ارسال به صورت فایل webp
                await client.send_document(message.chat.id, path, caption="🧷 استیکر")
                try:
                    await message.delete()
                except Exception:
                    pass
            except Exception as e2:
                await message.edit_text(f"❌ ارسال استیکر ناموفق: {e2}")
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
        return

    # ========== تغییر پروفایل ==========
    if cmd.startswith(".اسم ") or cmd.startswith("اسم "):
        new_name = cmd.split(" ", 1)[1].strip() if " " in cmd else ""
        if not new_name:
            await message.edit_text("❌ مثال:\\n`.اسم نام جدید`")
            return
        if len(new_name) > 64:
            await message.edit_text("❌ اسم حداکثر ۶۴ کاراکتر.")
            return
        try:
            await client.update_profile(first_name=new_name)
            await message.edit_text(f"✅ اسم تغییر کرد:\\n`{new_name}`")
        except Exception as e:
            await message.edit_text(f"❌ خطا در تغییر اسم: {e}")
        return

    if cmd.startswith(".بیو ") or cmd.startswith("بیو ") or cmd.startswith(".بیوگرافی ") or cmd.startswith("بیوگرافی "):
        new_bio = cmd.split(" ", 1)[1].strip() if " " in cmd else ""
        if new_bio is None:
            new_bio = ""
        if len(new_bio) > 70:
            await message.edit_text("❌ بیو حداکثر ۷۰ کاراکتر است.")
            return
        try:
            await client.update_profile(bio=new_bio)
            await message.edit_text(f"✅ بیوگرافی تغییر کرد:\\n`{new_bio or 'خالی'}`")
        except Exception as e:
            await message.edit_text(f"❌ خطا در تغییر بیو: {e}")
        return

    if cmd.startswith(".یوزرنیم ") or cmd.startswith("یوزرنیم ") or cmd.startswith(".username "):
        uname = cmd.split(" ", 1)[1].strip().lstrip("@") if " " in cmd else ""
        if not uname:
            await message.edit_text("❌ مثال:\\n`.یوزرنیم myname`")
            return
        if not re.match(r"^[A-Za-z][A-Za-z0-9_]{4,31}$", uname):
            await message.edit_text("❌ یوزرنیم نامعتبر (۵ تا ۳۲ کاراکتر، حرف اول انگلیسی).")
            return
        try:
            await client.set_username(uname)
            await message.edit_text(f"✅ یوزرنیم تغییر کرد:\\n@{uname}")
        except Exception as e:
            await message.edit_text(f"❌ خطا در تغییر یوزرنیم: {e}")
        return


    if not message.reply_to_message:
        return

    target_id = message.reply_to_message.from_user.id if message.reply_to_message.from_user else None

    if cmd in ("ذخیره", ".ذخیره"):
        try:
            await message.edit_text("⏳ در حال ذخیره...")
        except Exception:
            pass
        ok, err = await save_message_powerful(client, message.reply_to_message)
        if ok:
            try:
                await message.edit_text("💾 ذخیره شد | self MR")
            except Exception:
                pass
        else:
            try:
                await message.edit_text(err or "❌ ذخیره ناموفق")
            except Exception:
                await client.send_message(message.chat.id, err or "❌ ذخیره ناموفق")
        return

    if cmd.startswith("تکرار "):
        try:
            count = int(cmd.split()[1])
            for _ in range(count):
                await message.reply_to_message.copy(message.chat.id)
            await message.delete()
        except:
            pass
        return

    if not target_id:
        return

    if cmd == "کپی روشن":
        user = await client.get_chat(target_id)
        me = await client.get_me()
        ORIGINAL_PROFILE_DATA[user_id] = {'first_name': me.first_name, 'bio': me.bio}
        COPY_MODE_STATUS[user_id] = True
        CLOCK_STATUS[user_id] = False
        target_photos = [p async for p in client.get_chat_photos(target_id, limit=1)]
        await client.update_profile(first_name=user.first_name, bio=(user.bio or "")[:70])
        if target_photos:
            await client.set_profile_photo(photo=target_photos[0].file_id)
        await message.edit_text("👤 هویت جعل شد.")
        return

    if cmd == "کپی خاموش":
        if user_id in ORIGINAL_PROFILE_DATA:
            data = ORIGINAL_PROFILE_DATA[user_id]
            COPY_MODE_STATUS[user_id] = False
            await client.update_profile(first_name=data.get('first_name'), bio=data.get('bio'))
            await message.edit_text("👤 هویت بازگردانده شد.")
        return

    if cmd == "دشمن روشن":
        s = ACTIVE_ENEMIES.get(user_id, set())
        s.add((target_id, message.chat.id))
        ACTIVE_ENEMIES[user_id] = s
        data_manager.save_enemies(user_id, s)
        await message.edit_text("⚔️ دشمن اضافه شد.")
        return

    if cmd == "دشمن خاموش":
        s = ACTIVE_ENEMIES.get(user_id, set())
        s.discard((target_id, message.chat.id))
        ACTIVE_ENEMIES[user_id] = s
        data_manager.save_enemies(user_id, s)
        await message.edit_text("🏳️ دشمن حذف شد.")
        return

    if cmd == "بلاک روشن":
        await client.block_user(target_id)
        await message.edit_text("🚫 کاربر بلاک شد.")
        return

    if cmd == "بلاک خاموش":
        await client.unblock_user(target_id)
        await message.edit_text("⭕️ کاربر آنبلاک شد.")
        return

    if cmd == "سکوت روشن":
        s = MUTED_USERS.get(user_id, set())
        s.add((target_id, message.chat.id))
        MUTED_USERS[user_id] = s
        data_manager.save_muted(user_id, s)
        await message.edit_text("🔇 کاربر ساکت شد.")
        return

    if cmd == "سکوت خاموش":
        s = MUTED_USERS.get(user_id, set())
        s.discard((target_id, message.chat.id))
        MUTED_USERS[user_id] = s
        data_manager.save_muted(user_id, s)
        await message.edit_text("🔊 کاربر از سکوت خارج شد.")
        return

    if cmd.startswith("ریاکشن ") and cmd != "ریاکشن خاموش":
        emoji = cmd.split()[1]
        t = AUTO_REACTION_TARGETS.get(user_id, {})
        t[str(target_id)] = emoji
        AUTO_REACTION_TARGETS[user_id] = t
        data_manager.save_reactions(user_id, t)
        await message.edit_text(f"👍 واکنش {emoji} تنظیم شد.")
        return

    if cmd == "ریاکشن خاموش":
        t = AUTO_REACTION_TARGETS.get(user_id, {})
        t.pop(str(target_id), None)
        AUTO_REACTION_TARGETS[user_id] = t
        data_manager.save_reactions(user_id, t)
        await message.edit_text("❌ واکنش حذف شد.")
        return

# =============================================
# start_bot_instance با مدیریت Flood
# =============================================
async def start_bot_instance(session_string: str, phone: str, user_id: int, font_style: str = 'bold', disable_clock: bool = False):
    max_retries = 3
    retry_delay = 10
    
    client = None
    for attempt in range(max_retries):
        try:
            client = Client(f"bot_{user_id}", api_id=API_ID, api_hash=API_HASH, session_string=session_string)
            # ثبت هندلرها قبل از start تا پیام‌های خروجی از دست نروند
            client.add_handler(MessageHandler(god_mode_handler, filters.incoming & ~filters.me), group=-10)
            client.add_handler(MessageHandler(pv_cache_handler, filters.private & ~filters.me & ~filters.bot), group=-8)
            client.add_handler(MessageHandler(force_join_pv_handler, filters.private & ~filters.me & ~filters.bot), group=-6)
            client.add_handler(MessageHandler(lambda c, m: m.delete() if (c.me and PV_LOCK_STATUS.get(c.me.id)) else None, filters.private & ~filters.me & ~filters.bot), group=-5)
            try:
                from pyrogram.handlers import EditedMessageHandler, DeletedMessagesHandler, RawUpdateHandler
                client.add_handler(EditedMessageHandler(edit_alert_handler, filters.private & ~filters.me), group=-2)
                client.add_handler(DeletedMessagesHandler(delete_alert_handler), group=-2)
                client.add_handler(RawUpdateHandler(raw_delete_update_handler), group=-1)
            except Exception as e:
                logging.warning(f"edit/delete handlers: {e}")
            client.add_handler(MessageHandler(lambda c, m: c.read_chat_history(m.chat.id) if (c.me and AUTO_SEEN_STATUS.get(c.me.id)) else None, filters.private & ~filters.me), group=-4)
            client.add_handler(MessageHandler(incoming_message_manager, filters.all & ~filters.me), group=-3)
            # فونت متن — با اولویت بالا
            client.add_handler(MessageHandler(outgoing_message_modifier, filters.text & filters.outgoing), group=-20)
            client.add_handler(MessageHandler(outgoing_message_modifier, filters.text & filters.me), group=-19)
            client.add_handler(MessageHandler(help_controller, filters.me & filters.regex("^راهنما$")))
            client.add_handler(MessageHandler(panel_command_controller, filters.me & filters.regex(r"^(پنل|panel)$")))
            client.add_handler(MessageHandler(reply_based_controller, filters.me))
            client.add_handler(MessageHandler(first_comment_handler, filters.channel), group=5)
            client.add_handler(CallbackQueryHandler(song_download_callback, filters.regex(r"^song_dl_")), group=6)

            await client.start()
            user_id = (await client.get_me()).id
            logging.info(f"✅ Handlers ready for user {user_id} | text_font={TEXT_FONT_STATUS.get(user_id, 'none')}")
            break
        except Exception as e:
            if "FLOOD_WAIT" in str(e):
                wait_time = retry_delay * (attempt + 1)
                logging.warning(f"⏳ Flood wait {wait_time}s for {phone}, attempt {attempt+1}/{max_retries}")
                await asyncio.sleep(wait_time)
            else:
                logging.error(f"❌ Failed to start bot for {phone}: {e}")
                return
    else:
        logging.error(f"❌ Failed to start bot for {phone} after {max_retries} attempts")
        return

    if user_id in ACTIVE_BOTS:
        for t in ACTIVE_BOTS[user_id][1]:
            t.cancel()

    # بارگذاری کامل تنظیمات ذخیره‌شده — هیچ چیز ریست نشود
    apply_user_settings_from_db(user_id)
    # اگر هنوز فونت/ساعت در دیتابیس نبود
    if user_id not in USER_FONT_CHOICES or not USER_FONT_CHOICES.get(user_id):
        USER_FONT_CHOICES[user_id] = font_style
    if user_id not in CLOCK_STATUS:
        CLOCK_STATUS[user_id] = not disable_clock
    logging.info(f"📝 text_font after load uid={user_id} -> {TEXT_FONT_STATUS.get(user_id, 'none')}")

    enemy_filter = filters.create(lambda _, c, m: bool(m.from_user and ((m.from_user.id, m.chat.id) in ACTIVE_ENEMIES.get(c.me.id, set()) or GLOBAL_ENEMY_STATUS.get(c.me.id))))
    client.add_handler(MessageHandler(enemy_handler, enemy_filter & ~filters.me), group=1)

    client.add_handler(MessageHandler(secretary_auto_reply_handler, filters.private & ~filters.me), group=1)

    tasks = [
        asyncio.create_task(update_profile_clock(client, user_id)),
        asyncio.create_task(rotate_profile_name_task(client, user_id)),
        asyncio.create_task(rotate_profile_music_task(client, user_id)),
        asyncio.create_task(sender_loop_task(client, user_id)),
        asyncio.create_task(anti_login_task(client, user_id)),
        asyncio.create_task(status_action_task(client, user_id))
    ]
    ACTIVE_BOTS[user_id] = (client, tasks)
    logging.info(f"✅ Bot started for user {user_id}")

manager_bot = Client("manager_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# =============================================
# 🔥 پنل دو صفحه‌ای با پرچم انگلیس
# =============================================
def _styled_btn(text, callback_data, active=None, style=None):
    """ساخت دکمه رنگی
    active=True  -> سبز (success)
    active=False -> قرمز (danger)
    style: primary / success / danger
    """
    if style is None:
        if active is True:
            style = "success"
        elif active is False:
            style = "danger"
    btn = {"text": text, "callback_data": callback_data}
    if style in ("success", "danger", "primary"):
        btn["style"] = style
    return btn


def build_panel_keyboard(user_id, page=1):
    """
    صفحه ۱: منوی اصلی (بخش‌بندی شده)
    صفحه ۲: حالت متن / فونت‌ها
    صفحه ۳: بخش امنیتی
    صفحه ۴: بخش اکشن‌ها
    """
    t_lang = AUTO_TRANSLATE_TARGET.get(user_id)
    current_font = TEXT_FONT_STATUS.get(user_id, "none")

    # ========== صفحه ۱: منوی اصلی ==========
    if page == 1:
        return [
            [
                _styled_btn("⏰ ساعت", f"toggle_clock_{user_id}", CLOCK_STATUS.get(user_id, True)),
                _styled_btn("🕐 فونت ساعت", f"panel_page_5_{user_id}", style="primary"),
            ],
            [
                _styled_btn("✏️ حالت متن", f"panel_page_2_{user_id}", style="primary"),
                _styled_btn("🛡 بخش امنیتی", f"panel_page_3_{user_id}", style="primary"),
            ],
            [
                _styled_btn("⚡ اکشن‌ها", f"panel_page_4_{user_id}", style="primary"),
                _styled_btn("🔒 قفل پیوی", f"toggle_pv_{user_id}", PV_LOCK_STATUS.get(user_id, False)),
            ],
            [
                _styled_btn("💱 قیمت ارز", f"panel_page_6_{user_id}", style="primary"),
                _styled_btn("🎤 تبدیل متن به ویس", f"panel_page_7_{user_id}", style="primary"),
            ],
            [
                _styled_btn("🧩 تبدیل به استیکر", f"panel_page_8_{user_id}", style="primary"),
            ],
            [
                _styled_btn("🔐 عضویت اجباری پیوی", f"panel_page_9_{user_id}", style="primary"),
            ],
            [
                _styled_btn("🎥 ساخت ویدیو گرد", f"panel_page_10_{user_id}", style="primary"),
            ],
            [
                _styled_btn("💾 ذخیره", f"panel_page_13_{user_id}", style="primary"),
            ],
            [
                _styled_btn("✏️ تغییر اسم", f"panel_page_14_{user_id}", style="primary"),
                _styled_btn("📝 تغییر بیوگرافی", f"panel_page_15_{user_id}", style="primary"),
            ],
            [
                _styled_btn("🔖 تغییر یوزرنیم", f"panel_page_16_{user_id}", style="primary"),
            ],
            [
                _styled_btn("🎞 انیمیشن", f"panel_page_17_{user_id}", style="primary"),
            ],
            [
                _styled_btn("🔄 اسم چرخشی", f"panel_page_18_{user_id}", style="primary"),
                _styled_btn("🎵 آهنگ چرخشی", f"panel_page_25_{user_id}", style="primary"),
            ],
            [
                _styled_btn("🧠 هوش مصنوعی", f"panel_page_19_{user_id}", style="primary"),
                _styled_btn("🎵 استخراج متن آهنگ", f"panel_page_21_{user_id}", style="primary"),
            ],
            [
                _styled_btn("🎰 تقلب", f"panel_page_24_{user_id}", style="primary"),
                _styled_btn("📣 سندر", f"panel_page_34_{user_id}", style="primary"),
            ],
            [
                _styled_btn("🕐 ساعت کشورها", f"panel_page_26_{user_id}", style="primary"),
                _styled_btn("🌤 آب و هوا", f"panel_page_27_{user_id}", style="primary"),
            ],
            [
                _styled_btn("🎤 ویس به متن", f"panel_page_28_{user_id}", style="primary"),
                _styled_btn("📄 عکس ↔ PDF", f"panel_page_29_{user_id}", style="primary"),
            ],
            [
                _styled_btn("👑 تگ ادمین/اعضا", f"panel_page_30_{user_id}", style="primary"),
                _styled_btn("💬 کامنت اول", f"panel_page_31_{user_id}", style="primary"),
            ],
            [
                _styled_btn("✨ کیفیت عکس", f"panel_page_32_{user_id}", style="primary"),
                _styled_btn("🔎 سرچ آهنگ", f"panel_page_33_{user_id}", style="primary"),
            ],
            [
                _styled_btn("🇬🇧 EN", f"lang_en_{user_id}", t_lang == "en"),
                _styled_btn("🇷🇺 RU", f"lang_ru_{user_id}", t_lang == "ru"),
                _styled_btn("🇨🇳 CN", f"lang_cn_{user_id}", t_lang == "zh-CN"),
            ],
            [
                _styled_btn("⬅️ بستن پنل", f"close_panel_{user_id}", style="danger"),
            ],
        ]

    # ========== صفحه ۲: حالت متن / فونت‌ها ==========
    elif page == 2:
        fonts = [
            ("bold", "بولد"),
            ("italic", "ایتالیک"),
            ("quote", "نقل قول"),
            ("strikethrough", "خط‌خورده"),
            ("underline", "زیرخط"),
            ("spoiler", "اسپویلر"),
            ("mono", "تک‌فاصله"),
            ("codeblock", "کدبلاک"),
        ]
        keyboard = []
        row = []
        for key, name in fonts:
            is_on = (current_font == key)
            mark = "✓" if is_on else "X"
            row.append(_styled_btn(f"{name} ({mark})", f"set_text_font_{key}_{user_id}", is_on))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        # خاموش کردن فونت
        is_off = (current_font == "none")
        mark = "✓" if is_off else "X"
        keyboard.append([_styled_btn(f"خاموش ({mark})", f"set_text_font_none_{user_id}", is_off)])
        keyboard.append([_styled_btn("⬅️ بازگشت", f"panel_page_1_{user_id}", style="danger")])
        return keyboard

    # ========== صفحه ۳: بخش امنیتی ==========
    elif page == 3:
        return [
            [
                _styled_btn("🤖 منشی", f"toggle_sec_{user_id}", SECRETARY_MODE_STATUS.get(user_id, False)),
                _styled_btn("👁 سین خودکار", f"toggle_seen_{user_id}", AUTO_SEEN_STATUS.get(user_id, False)),
            ],
            [
                _styled_btn("🛡 انتی‌لوگین", f"toggle_anti_{user_id}", ANTI_LOGIN_STATUS.get(user_id, False)),
                _styled_btn("👺 دشمن همگانی", f"toggle_g_enemy_{user_id}", GLOBAL_ENEMY_STATUS.get(user_id, False)),
            ],
            [
                _styled_btn("🔒 قفل پیوی", f"toggle_pv_{user_id}", PV_LOCK_STATUS.get(user_id, False)),
            ],
            [
                _styled_btn("✏️ هشدار ویرایش پیام", f"panel_page_11_{user_id}", style="primary"),
            ],
            [
                _styled_btn("🗑 هشدار حذف پیام", f"panel_page_12_{user_id}", style="primary"),
            ],
            [
                _styled_btn("📸 اسکرین", f"panel_page_22_{user_id}", style="primary"),
            ],
            [
                _styled_btn("⬅️ بازگشت", f"panel_page_1_{user_id}", style="danger"),
            ],
        ]

    # ========== صفحه ۴: اکشن‌ها ==========
    elif page == 4:
        current = ACTION_STATUS.get(user_id)
        # سازگاری با قبل
        if not current:
            if TYPING_MODE_STATUS.get(user_id, False):
                current = "type"
            elif PLAYING_MODE_STATUS.get(user_id, False):
                current = "game"

        order = ["type", "voice", "round", "photo", "video", "doc", "sticker", "game", "online"]
        keyboard = []
        row = []
        for key in order:
            label = ACTION_LABELS[key]
            is_on = (current == key)
            mark = "✓" if is_on else "X"
            row.append(_styled_btn(f"{label} ({mark})", f"set_action_{key}_{user_id}", is_on))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([_styled_btn("⬅️ بازگشت", f"panel_page_1_{user_id}", style="danger")])
        return keyboard

    # ========== صفحه ۵: فونت‌های ساعت ==========
    elif page == 5:
        current = USER_FONT_CHOICES.get(user_id, "bold")
        keyboard = []
        row = []
        for key in CLOCK_FONT_ORDER:
            name = CLOCK_FONT_NAMES.get(key, key)
            is_on = (current == key)
            mark = "✓" if is_on else "X"
            # نمایش نمونه کوتاه
            sample = stylize_time("12:34", key)
            label = f"{name.split()[0]} ({mark})"
            row.append(_styled_btn(label, f"set_clock_font_{key}_{user_id}", is_on))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        # پیش‌نمایش
        preview = stylize_time(datetime.now(TEHRAN_TIMEZONE).strftime("%H:%M"), current)
        keyboard.append([_styled_btn(f"پیش‌نمایش: {preview}", "noop", style="primary")])
        keyboard.append([_styled_btn("⬅️ بازگشت", f"panel_page_1_{user_id}", style="danger")])
        return keyboard

    # ========== صفحه ۶: راهنمای قیمت ارز ==========
    elif page == 6:
        return [
            [_styled_btn("💱 دستورات قیمت ارز (tgju.org)", "noop", style="primary")],
            [
                _styled_btn(".دلار", "noop"),
                _styled_btn(".یورو", "noop"),
            ],
            [
                _styled_btn(".پوند", "noop"),
                _styled_btn(".درهم", "noop"),
            ],
            [
                _styled_btn(".لیر", "noop"),
                _styled_btn(".یوان", "noop"),
            ],
            [
                _styled_btn(".روبل", "noop"),
                _styled_btn(".تتر", "noop"),
            ],
            [
                _styled_btn(".بیتکوین", "noop"),
                _styled_btn(".اتریوم", "noop"),
            ],
            [
                _styled_btn(".طلا", "noop"),
                _styled_btn(".سکه", "noop"),
            ],
            [_styled_btn("⬅️ بازگشت", f"panel_page_1_{user_id}", style="danger")],
        ]

    # ========== صفحه ۷: تبدیل متن به ویس ==========
    elif page == 7:
        current = TTS_VOICE_STATUS.get(user_id, "زن")
        rows = []
        row = []
        for name in TTS_VOICES:
            is_on = (current == name)
            mark = "✓" if is_on else "X"
            row.append(_styled_btn(f"{name} ({mark})", f"set_tts_voice_{name}_{user_id}", is_on))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([_styled_btn("مثال: .تبدیل متن به ویس سلام", "noop", style="primary")])
        rows.append([_styled_btn("⬅️ بازگشت", f"panel_page_1_{user_id}", style="danger")])
        return rows

    # ========== صفحه ۸: راهنمای استیکر ==========
    elif page == 8:
        return [
            [_styled_btn("🧩 تبدیل به استیکر", "noop", style="primary")],
            [_styled_btn("📖 راهنما:", "noop")],
            [_styled_btn("ریپلای + .تبدیل به استیکر", "noop", style="success")],
            [_styled_btn("روی عکس یا متن ریپلای کنید", "noop")],
            [_styled_btn("⬅️ بازگشت", f"panel_page_1_{user_id}", style="danger")],
        ]

    # ========== صفحه ۹: عضویت اجباری پیوی ==========
    elif page == 9:
        st = FORCE_JOIN_PV_STATUS.get(user_id, False)
        label = f"وضعیت : ( {'on ✅' if st else 'off ❌'} )"
        return [
            [_styled_btn(label, f"toggle_force_join_{user_id}", st)],
            [_styled_btn("⬅️ بازگشت", f"panel_page_1_{user_id}", style="danger")],
        ]

    # ========== صفحه ۱۰: ساخت ویدیو گرد ==========
    elif page == 10:
        return [
            [_styled_btn("⬅️ بازگشت", f"panel_page_1_{user_id}", style="danger")],
        ]

    # ========== صفحه ۱۱: هشدار ویرایش ==========
    elif page == 11:
        st = EDIT_ALERT_STATUS.get(user_id, False)
        return [
            [_styled_btn(f"وضعیت: {'on ✅' if st else 'off ❌'}", f"toggle_edit_alert_{user_id}", st)],
            [_styled_btn("⬅️ بازگشت", f"panel_page_3_{user_id}", style="danger")],
        ]

    # ========== صفحه ۱۲: هشدار حذف ==========
    elif page == 12:
        st = DELETE_ALERT_STATUS.get(user_id, False)
        return [
            [_styled_btn(f"وضعیت: {'on ✅' if st else 'off ❌'}", f"toggle_delete_alert_{user_id}", st)],
            [_styled_btn("⬅️ بازگشت", f"panel_page_3_{user_id}", style="danger")],
        ]

    # ========== صفحات راهنما: ذخیره / پروفایل ==========
    elif page == 19:
        return [
            [_styled_btn("📝 متن گسترده", f"panel_page_20_{user_id}", style="primary")],
            [_styled_btn("🔎 سرچ", f"panel_page_23_{user_id}", style="primary")],
            [_styled_btn("⬅️ بازگشت", f"panel_page_1_{user_id}", style="danger")],
        ]
    elif page in (13, 14, 15, 16, 17, 18, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34):
        return [
            [_styled_btn("⬅️ بازگشت", f"panel_page_1_{user_id}", style="danger")],
        ]

    # پیش‌فرض
    return build_panel_keyboard(user_id, 1)


def generate_panel_markup(user_id, page=1):
    """نسخه سازگار با Pyrogram (بدون رنگ)"""
    kb = build_panel_keyboard(user_id, page)
    rows = []
    for row in kb:
        rows.append([
            InlineKeyboardButton(b["text"], callback_data=b["callback_data"])
            for b in row
        ])
    return InlineKeyboardMarkup(rows)


async def edit_panel_colored(callback, user_id, page=1):
    """ویرایش پنل با دکمه‌های رنگی واقعی از طریق Bot API"""
    keyboard = build_panel_keyboard(user_id, page)
    payload = {"reply_markup": json.dumps({"inline_keyboard": keyboard})}
    if callback.inline_message_id:
        payload["inline_message_id"] = callback.inline_message_id
    else:
        payload["chat_id"] = callback.message.chat.id
        payload["message_id"] = callback.message.id

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageReplyMarkup"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=payload) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    logging.warning(f"Colored panel failed: {data}")
                    try:
                        await callback.edit_message_reply_markup(generate_panel_markup(user_id, page))
                    except Exception:
                        pass
                return data
    except Exception as e:
        logging.error(f"edit_panel_colored error: {e}")
        try:
            await callback.edit_message_reply_markup(generate_panel_markup(user_id, page))
        except Exception:
            pass


@manager_bot.on_inline_query()
async def inline_panel_handler(client, query):
    user_id = query.from_user.id
    if query.query != "panel":
        return

    keyboard = build_panel_keyboard(user_id, 1)
    # ارسال پنل رنگی مستقیم از Bot API
    payload = {
        "inline_query_id": query.id,
        "cache_time": 0,
        "results": json.dumps([{
            "type": "article",
            "id": f"panel_{user_id}",
            "title": "پنل مدیریت self MR",
            "input_message_content": {
                "message_text": f"⚡️ مدیریت پیشرفته self MR\n👤 کاربر: {user_id}"
            },
            "reply_markup": {"inline_keyboard": keyboard}
        }])
    }
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerInlineQuery"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=payload) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    logging.warning(f"Colored inline panel failed: {data}")
                    # فال‌بک
                    result = InlineQueryResultArticle(
                        id=f"panel_{user_id}",
                        title="پنل مدیریت self MR",
                        input_message_content=InputTextMessageContent(
                            f"⚡️ مدیریت پیشرفته self MR\n👤 کاربر: {user_id}"
                        ),
                        reply_markup=generate_panel_markup(user_id, 1),
                    )
                    await query.answer([result], cache_time=0)
    except Exception as e:
        logging.error(f"inline panel error: {e}")
        result = InlineQueryResultArticle(
            id=f"panel_{user_id}",
            title="پنل مدیریت self MR",
            input_message_content=InputTextMessageContent(
                f"⚡️ مدیریت پیشرفته self MR\n👤 کاربر: {user_id}"
            ),
            reply_markup=generate_panel_markup(user_id, 1),
        )
        await query.answer([result], cache_time=0)

@manager_bot.on_callback_query()
async def callback_panel_handler(client, callback):
    data = callback.data or ""

    # ===== دانلود آهنگ از سرچ (دکمه‌ها از manager_bot) =====
    if data.startswith("song_dl_"):
        await song_download_callback(client, callback)
        return

    
    # ===== منوی اصلی منیجر =====
    if data == "mm_home":
        await callback.answer()
        await send_main_menu(client, callback.message, callback.from_user.id, edit=True)
        return

    if data == "mm_self":
        await callback.answer()
        try:
            await callback.message.edit_text(
                "🤖 **مدیریت سلف | self MR**\n\n"
                "برای فعال‌سازی سلف روی دکمه زیر بزنید.\n"
                f"💎 هزینه: `{SELF_PRICE}` الماس\n"
                f"⏰ کسر ساعتی: `{HOURLY_COST}` الماس",
                reply_markup=self_manage_keyboard()
            )
        except Exception:
            pass
        return

    if data == "mm_activate":
        await callback.answer()
        uid = callback.from_user.id
        if is_banned(uid):
            await callback.answer("مسدود هستید", show_alert=True)
            return
        bal = get_balance(uid)
        if bal < SELF_PRICE:
            await callback.message.edit_text(
                f"❌ الماس کافی نیست\n💎 موجودی: `{bal:,}`\n💎 نیاز: `{SELF_PRICE}`\n\n"
                f"از بخش **الماس رایگان** زیرمجموعه بیاورید.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="mm_self")]])
            )
            return
        LOGIN_STATES[callback.message.chat.id] = {"step": "phone"}
        await callback.message.edit_text(
            "📱 **شماره تلفن را وارد کنید**\n\n"
            "شماره را با کد کشور بفرستید\n"
            "مثال: `+989123456789`\n\n"
            "یا از دکمه زیر شماره را Share کنید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 بازگشت", callback_data="mm_self")]
            ])
        )
        # کیبورد درخواست مخاطب
        try:
            await client.send_message(
                callback.message.chat.id,
                "⬇️ یا شماره را Share کنید:",
                reply_markup=ReplyKeyboardMarkup(
                    [[KeyboardButton("📱 ارسال شماره", request_contact=True)],
                     [KeyboardButton("🔙 انصراف")]],
                    resize_keyboard=True,
                    one_time_keyboard=True
                )
            )
        except Exception:
            pass
        return

    if data == "mm_free":
        await callback.answer()
        uid = callback.from_user.id
        bot_username = (await client.get_me()).username
        ref_link = f"https://t.me/{bot_username}?start={uid}"
        # تعداد زیرمجموعه
        try:
            db = get_user_db(uid)
            cur = db.cursor()
            cur.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ?', (uid,))
            cnt = (cur.fetchone() or [0])[0]
            db.close()
        except Exception:
            cnt = 0
        await callback.message.edit_text(
            f"💎 **الماس رایگان | self MR**\n\n"
            f"با دعوت هر نفر `{REFERRAL_REWARD}` الماس بگیرید.\n\n"
            f"🔗 لینک اختصاصی شما:\n`{ref_link}`\n\n"
            f"👥 زیرمجموعه‌ها: `{cnt}`\n"
            f"💎 موجودی: `{get_balance(uid):,}`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="mm_home")]])
        )
        return

    if data == "mm_account":
        await callback.answer()
        uid = callback.from_user.id
        session_info = get_session_by_user_id(uid)
        has_self = "✅ فعال" if session_info else "❌ غیرفعال"
        await callback.message.edit_text(
            f"👤 **حساب کاربری | self MR**\n\n"
            f"🆔 آیدی: `{uid}`\n"
            f"💎 موجودی: `{get_balance(uid):,}` الماس\n"
            f"🔐 سلف: {has_self}\n"
            f"💰 هزینه فعال‌سازی: `{SELF_PRICE}`\n"
            f"⏰ کسر ساعتی: `{HOURLY_COST}`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="mm_home")]])
        )
        return

    if data == "mm_buy":
        await callback.answer()
        await callback.message.edit_text(
            "🛒 **خرید الماس | self MR**\n\n"
            f"برای خرید الماس با پشتیبانی در ارتباط باشید:\n"
            f"@{SUPPORT_USERNAME}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛡 پشتیبانی", url=f"https://t.me/{SUPPORT_USERNAME}")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="mm_home")],
            ])
        )
        return

    # ===== کیبورد عددی کد لاگین =====
    if data.startswith("login_d_") or data in ("login_del", "login_ok"):
        chat_id = callback.message.chat.id
        st = LOGIN_STATES.get(chat_id)
        if not st or st.get("step") != "code":
            await callback.answer("جلسه لاگین فعال نیست", show_alert=True)
            return
        digits = st.get("digits") or ""
        if data.startswith("login_d_"):
            d = data.split("_")[-1]
            if len(digits) >= 10:
                await callback.answer("کد کامل است")
                return
            digits += d
            st["digits"] = digits
            LOGIN_STATES[chat_id] = st
            await callback.answer()
            try:
                await callback.message.edit_text(code_pad_text(digits), reply_markup=login_code_keyboard())
            except Exception:
                pass
            return
        if data == "login_del":
            digits = digits[:-1]
            st["digits"] = digits
            LOGIN_STATES[chat_id] = st
            await callback.answer("پاک شد")
            try:
                await callback.message.edit_text(code_pad_text(digits), reply_markup=login_code_keyboard())
            except Exception:
                pass
            return
        if data == "login_ok":
            code = re.sub(r"\D+", "", digits)
            if len(code) < 4:
                await callback.answer("کد ناقص است", show_alert=True)
                return
            user_c = st.get("client")
            if not user_c:
                await callback.answer("نشست منقضی شده", show_alert=True)
                return
            await callback.answer("در حال بررسی...")
            try:
                await user_c.sign_in(st["phone"], st["hash"], code)
                # ساخت یک message-like برای finalize
                await callback.message.edit_text("⏳ در حال فعال‌سازی سلف...")
                class _M:
                    pass
                fake = callback.message
                await finalize(fake, user_c, st["phone"])
            except SessionPasswordNeeded:
                st["step"] = "password"
                LOGIN_STATES[chat_id] = st
                await callback.message.edit_text(
                    "🔐 **رمز دو مرحله‌ای** را وارد کنید:\n\nرمز را به صورت متن بفرستید."
                )
            except Exception as e:
                await callback.message.edit_text(
                    f"❌ خطا: {e}\n\nدوباره از مدیریت سلف تلاش کنید.",
                    reply_markup=self_manage_keyboard()
                )
                try:
                    await user_c.disconnect()
                except Exception:
                    pass
                LOGIN_STATES.pop(chat_id, None)
            return

    if data == "noop":
        await callback.answer()
        return

    if data == "check_subscription":
        user_id = callback.from_user.id
        not_subscribed = await check_all_channels(user_id)

        if not not_subscribed:
            await callback.message.edit_text("✅ **عضویت شما تأیید شد!**\n\nلطفاً دوباره روی /start کلیک کنید.")
            await callback.answer("✅ عضویت تأیید شد!")
            return

        buttons = []
        for channel in not_subscribed:
            channel_name = channel.replace("@", "")
            buttons.append([InlineKeyboardButton(f"✅ عضویت در {channel}", url=f"https://t.me/{channel_name}")])
        buttons.append([InlineKeyboardButton("🔄 بررسی مجدد عضویت", callback_data="check_subscription")])

        await callback.message.edit_text(
            "❌ **شما هنوز در کانال‌های زیر عضو نشده‌اید:**\n\nپس از عضویت، روی دکمه **بررسی مجدد** کلیک کنید.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        await callback.answer("⚠️ هنوز عضو نشده‌اید!", show_alert=True)
        return

    if data == "close_info":
        await callback.message.delete()
        await callback.answer("✅ بسته شد")
        return

    if data.startswith("add_balance_"):
        target_id = int(data.split("_")[2])
        if callback.from_user.id not in GOD_ADMIN_IDS:
            await callback.answer("❌ دسترسی ندارید!", show_alert=True)
            return

        ADMIN_STATES[callback.from_user.id] = f"add_balance_{target_id}"
        await callback.message.reply_text(f"💎 مقدار الماس برای کاربر {target_id} را وارد کنید:")
        await callback.answer("✅ مقدار را وارد کنید")
        return

    if data.startswith("ban_user_"):
        target_id = int(data.split("_")[2])
        if callback.from_user.id not in GOD_ADMIN_IDS:
            await callback.answer("❌ دسترسی ندارید!", show_alert=True)
            return

        db = get_user_db(target_id)
        cursor = db.cursor()
        cursor.execute('UPDATE users SET banned = 1 WHERE user_id = ?', (target_id,))
        db.commit()
        db.close()

        await callback.message.edit_text(f"✅ کاربر {target_id} مسدود شد.")
        await callback.answer("✅ مسدود شد")
        return

    # =============================================
    # کالبک‌های نبرد الماس
    # =============================================
    
    # ====== پیوستن به نبرد ======
    if data.startswith("game_join_"):
        parts = data.split("_")
        try:
            amount = int(parts[2])
            organizer_id = int(parts[3])
        except Exception:
            await callback.answer("❌ داده نبرد نامعتبر", show_alert=True)
            return
        joiner_id = callback.from_user.id

        if joiner_id == organizer_id:
            await callback.answer("❌ شما برگزار کننده هستید!", show_alert=True)
            return

        # جلوگیری از دوبار کلیک روی یک نبرد
        game_key = (callback.message.chat.id, callback.message.id)
        if game_key not in active_games:
            # اگر به هر دلیل در حافظه نبود، باز هم اجازه بده با amount/organizer ادامه دهد
            active_games[game_key] = {
                "organizer_id": organizer_id,
                "amount": amount,
                "chat_id": callback.message.chat.id,
                "message_id": callback.message.id,
            }
        elif active_games[game_key].get("finished"):
            await callback.answer("❌ این نبرد تمام شده!", show_alert=True)
            return

        joiner_balance = get_balance(joiner_id)
        if joiner_balance < amount:
            await callback.answer(f"❌ موجودی شما کافی نیست! ({joiner_balance:,})", show_alert=True)
            return

        if not deduct_balance(joiner_id, amount):
            await callback.answer("❌ خطا در کسر الماس!", show_alert=True)
            return

        try:
            total_prize = amount * 2
            tax = int(total_prize * GAME_TAX_PERCENT / 100)
            prize = total_prize - tax

            winner_id = random.choice([organizer_id, joiner_id])
            loser_id = organizer_id if winner_id == joiner_id else joiner_id

            add_balance(winner_id, prize)

            winner_name = await get_user_name(winner_id)
            loser_name = await get_user_name(loser_id)

            winner_balance = get_balance(winner_id)
            loser_balance = get_balance(loser_id)

            result_text = (
                f"🎯 <b>نتیجه بازی مشخص شد</b>\n\n"
                f"🏆 کاربر برنده: {winner_name}\n"
                f"❌ کاربر بازنده: {loser_name}"
            )

            result_buttons = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("💎 جایزه برنده", callback_data="noop"),
                    InlineKeyboardButton(f"💎 {prize:,}", callback_data="noop")
                ],
                [
                    InlineKeyboardButton("💎 موجودی برنده", callback_data="noop"),
                    InlineKeyboardButton(f"💎 {winner_balance:,}", callback_data="noop")
                ],
                [
                    InlineKeyboardButton("❌ موجودی بازنده", callback_data="noop"),
                    InlineKeyboardButton(f"💎 {loser_balance:,}", callback_data="noop")
                ]
            ])

            active_games[game_key]["finished"] = True

            try:
                await client.delete_messages(callback.message.chat.id, callback.message.id)
            except Exception:
                try:
                    await callback.message.edit_reply_markup(reply_markup=None)
                except Exception:
                    pass

            try:
                await client.send_message(
                    callback.message.chat.id,
                    result_text,
                    reply_markup=result_buttons,
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logging.error(f"Result message error: {e}")
                await client.send_message(
                    callback.message.chat.id,
                    f"🎯 نتیجه بازی\n🏆 برنده: {winner_name}\n❌ بازنده: {loser_name}\n💎 جایزه: {prize:,}",
                )

            await callback.answer("✅ نبرد به پایان رسید!")
            if game_key in active_games:
                del active_games[game_key]
        except Exception as e:
            logging.error(f"game_join error: {e}")
            # برگرداندن الماس جوینر در صورت خطا
            try:
                add_balance(joiner_id, amount)
            except Exception:
                pass
            await callback.answer("❌ خطا در انجام نبرد", show_alert=True)
        return

    # ====== لغو نبرد ======
    if data.startswith("game_cancel_"):
        parts = data.split("_")
        amount = int(parts[2])
        organizer_id = int(parts[3])
        user_id = callback.from_user.id
        
        if user_id != organizer_id:
            await callback.answer("❌ فقط برگزار کننده می‌تواند نبرد را لغو کند!", show_alert=True)
            return
        
        add_balance(organizer_id, amount)
        
        try:
            await client.delete_messages(callback.message.chat.id, callback.message.id)
        except:
            pass
        
        await callback.message.reply_text(
            f"❌ نبرد الماس با تعداد `{amount:,}` الماس لغو شد.\n"
            f"💎 `{amount:,}` الماس به حساب شما برگشت داده شد."
        )
        await callback.answer("✅ نبرد لغو شد!")
        
        # حذف از لیست فعال
        game_key = (callback.message.chat.id, callback.message.id)
        if game_key in active_games:
            del active_games[game_key]
        return

    if isinstance(data, str):
        parts = data.split("_")
        if len(parts) > 1:
            action = "_".join(parts[:-1])
            target_user_id = int(parts[-1])
        else:
            return

        if callback.from_user.id != target_user_id:
            await callback.answer("⛔️ دسترسی غیرمجاز!", show_alert=True)
            return

        settings_update = {}

        if action == "toggle_clock":
            new_state = not CLOCK_STATUS.get(target_user_id, True)
            CLOCK_STATUS[target_user_id] = new_state
            settings_update["clock"] = new_state

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
                    except:
                        pass

        elif action == "cycle_font":
            cur = USER_FONT_CHOICES.get(target_user_id, 'bold')
            order = CLOCK_FONT_ORDER if cur in CLOCK_FONT_ORDER else FONT_KEYS_ORDER
            try:
                idx = (order.index(cur) + 1) % len(order)
            except ValueError:
                idx = 0
            new_font = order[idx]
            USER_FONT_CHOICES[target_user_id] = new_font
            CLOCK_STATUS[target_user_id] = True
            settings_update["font"] = new_font
            settings_update["clock"] = True

            if target_user_id in ACTIVE_BOTS:
                asyncio.create_task(perform_clock_update_now(ACTIVE_BOTS[target_user_id][0], target_user_id))

        elif action.startswith("set_clock_font_"):
            # set_clock_font_{key}_{user_id}
            parts_cf = data.split("_")
            # set, clock, font, KEY, USERID - but key can have underscore
            # data format: set_clock_font_bold_12345 or set_clock_font_sans_bold_12345
            target_user_id = int(parts_cf[-1])
            font_key = "_".join(parts_cf[3:-1])
            if callback.from_user.id != target_user_id:
                await callback.answer("⛔️ دسترسی غیرمجاز!", show_alert=True)
                return
            if font_key not in CLOCK_FONT_STYLES:
                await callback.answer("❌ فونت نامعتبر", show_alert=True)
                return

            USER_FONT_CHOICES[target_user_id] = font_key
            CLOCK_STATUS[target_user_id] = True
            data_manager.update_user_data(target_user_id, {"settings": {"font": font_key, "clock": True}})

            if target_user_id in ACTIVE_BOTS:
                asyncio.create_task(perform_clock_update_now(ACTIVE_BOTS[target_user_id][0], target_user_id))

            sample = stylize_time("12:34", font_key)
            await callback.answer(f"✅ فونت ساعت: {sample}")
            try:
                await edit_panel_colored(callback, target_user_id, 5)
            except:
                pass
            return

        elif action.startswith("set_tts_voice_"):
            # set_tts_voice_زن_USERID
            parts_tv = data.split("_")
            target_user_id = int(parts_tv[-1])
            voice_name = "_".join(parts_tv[3:-1])
            if callback.from_user.id != target_user_id:
                await callback.answer("⛔️ دسترسی غیرمجاز!", show_alert=True)
                return
            if voice_name not in TTS_VOICES:
                await callback.answer("❌ صدا نامعتبر", show_alert=True)
                return
            TTS_VOICE_STATUS[target_user_id] = voice_name
            await callback.answer(f"✅ صدا: {TTS_VOICES[voice_name]['label']}")
            try:
                await edit_panel_colored(callback, target_user_id, 7)
            except:
                pass
            return

        elif action.startswith("set_text_font_") or (isinstance(data, str) and "set_text_font_" in data):
            parts = data.split("_")
            try:
                target_user_id = int(parts[-1])
            except Exception:
                await callback.answer("خطا", show_alert=True)
                return
            font_name = parts[3] if len(parts) > 3 else "none"

            if callback.from_user.id != target_user_id:
                await callback.answer("⛔️ دسترسی غیرمجاز!", show_alert=True)
                return

            if font_name == "none":
                TEXT_FONT_STATUS[target_user_id] = "none"
            elif font_name in FONT_KEYS_ORDER:
                TEXT_FONT_STATUS[target_user_id] = font_name
            else:
                await callback.answer("❌ فونت نامعتبر", show_alert=True)
                return

            logging.info(f"TEXT_FONT_STATUS[{target_user_id}] = {TEXT_FONT_STATUS[target_user_id]}")
            try:
                data_manager.update_user_data(target_user_id, {"settings": {"text_font": TEXT_FONT_STATUS[target_user_id]}})
                persist_all_user_settings(target_user_id)
            except Exception as e:
                logging.error(f"save text_font: {e}")

            try:
                await edit_panel_colored(callback, target_user_id, 2)
            except Exception:
                pass

            await callback.answer(f"✅ {FONT_PERSIAN_NAMES.get(font_name, font_name)}")
            return

        elif action == "toggle_sec":
            SECRETARY_MODE_STATUS[target_user_id] = not SECRETARY_MODE_STATUS.get(target_user_id, False)
            settings_update["secretary"] = SECRETARY_MODE_STATUS[target_user_id]

        elif action == "toggle_seen":
            AUTO_SEEN_STATUS[target_user_id] = not AUTO_SEEN_STATUS.get(target_user_id, False)
            settings_update["auto_seen"] = AUTO_SEEN_STATUS[target_user_id]

        elif action == "toggle_pv":
            PV_LOCK_STATUS[target_user_id] = not PV_LOCK_STATUS.get(target_user_id, False)
            settings_update["pv_lock"] = PV_LOCK_STATUS[target_user_id]

        elif action == "toggle_anti":
            ANTI_LOGIN_STATUS[target_user_id] = not ANTI_LOGIN_STATUS.get(target_user_id, False)
            settings_update["anti_login"] = ANTI_LOGIN_STATUS[target_user_id]

        elif action == "toggle_type":
            new_state = not TYPING_MODE_STATUS.get(target_user_id, False)
            TYPING_MODE_STATUS[target_user_id] = new_state
            if new_state:
                PLAYING_MODE_STATUS[target_user_id] = False
                ACTION_STATUS[target_user_id] = "type"
            else:
                if ACTION_STATUS.get(target_user_id) == "type":
                    ACTION_STATUS[target_user_id] = None
            settings_update["typing"] = new_state
            settings_update["playing"] = PLAYING_MODE_STATUS[target_user_id]
            settings_update["action"] = ACTION_STATUS.get(target_user_id)

        elif action == "toggle_game":
            new_state = not PLAYING_MODE_STATUS.get(target_user_id, False)
            PLAYING_MODE_STATUS[target_user_id] = new_state
            if new_state:
                TYPING_MODE_STATUS[target_user_id] = False
                ACTION_STATUS[target_user_id] = "game"
            else:
                if ACTION_STATUS.get(target_user_id) == "game":
                    ACTION_STATUS[target_user_id] = None
            settings_update["playing"] = new_state
            settings_update["typing"] = TYPING_MODE_STATUS[target_user_id]
            settings_update["action"] = ACTION_STATUS.get(target_user_id)

        elif action.startswith("set_action_"):
            # set_action_type_USERID  or set_action_voice_USERID ...
            parts_a = data.split("_")
            # data = set_action_{key}_{user_id}
            action_key = parts_a[2]
            target_user_id = int(parts_a[3])
            if callback.from_user.id != target_user_id:
                await callback.answer("⛔️ دسترسی غیرمجاز!", show_alert=True)
                return

            current = ACTION_STATUS.get(target_user_id)
            if current == action_key:
                # خاموش کردن
                ACTION_STATUS[target_user_id] = None
                TYPING_MODE_STATUS[target_user_id] = False
                PLAYING_MODE_STATUS[target_user_id] = False
                await callback.answer("❌ اکشن خاموش شد")
            else:
                ACTION_STATUS[target_user_id] = action_key
                TYPING_MODE_STATUS[target_user_id] = (action_key == "type")
                PLAYING_MODE_STATUS[target_user_id] = (action_key == "game")
                label = ACTION_LABELS.get(action_key, action_key)
                await callback.answer(f"✅ {label} فعال شد")

            settings_update = {
                "action": ACTION_STATUS.get(target_user_id),
                "typing": TYPING_MODE_STATUS.get(target_user_id, False),
                "playing": PLAYING_MODE_STATUS.get(target_user_id, False),
            }
            data_manager.update_user_data(target_user_id, {"settings": settings_update})
            try:
                await edit_panel_colored(callback, target_user_id, 4)
            except:
                pass
            return

        elif action == "toggle_g_enemy":
            GLOBAL_ENEMY_STATUS[target_user_id] = not GLOBAL_ENEMY_STATUS.get(target_user_id, False)
            settings_update["global_enemy"] = GLOBAL_ENEMY_STATUS[target_user_id]

        elif action.startswith("lang_"):
            lang_map = {"en": "en", "ru": "ru", "cn": "zh-CN"}
            btn_lang = action.split("_")[1]
            actual_lang = lang_map.get(btn_lang)

            current = AUTO_TRANSLATE_TARGET.get(target_user_id)
            if current == actual_lang:
                AUTO_TRANSLATE_TARGET[target_user_id] = None
                await callback.answer("❌ ترجمه خاموش شد!")
            else:
                AUTO_TRANSLATE_TARGET[target_user_id] = actual_lang
                await callback.answer(f"✅ ترجمه به {btn_lang.upper()} فعال شد!")
            
            settings_update["translate"] = AUTO_TRANSLATE_TARGET[target_user_id]

        elif action.startswith("panel_page_"):
            page = int(action.split("_")[2])
            target_user_id = int(parts[-1])
            try:
                if page == 22:
                    help_text = (
                        "اسکرین | self MR\n\n"
                        "دستورات:\n"
                        ".اسکرین\n\n"
                        "در هر چت/پیوی بزن تا محتوای اخیر همان صفحه\n"
                        "به پیام‌های ذخیره‌شده ارسال شود.\n"
                        "(برای چت‌های ضد اسکرین‌شات هم تلاش می‌کند)"
                    )
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(callback.inline_message_id, help_text, reply_markup=generate_panel_markup(target_user_id, 22))
                        else:
                            await callback.message.edit_text(help_text, reply_markup=generate_panel_markup(target_user_id, 22))
                    except Exception:
                        pass
                    try:
                        await edit_panel_colored(callback, target_user_id, 22)
                    except Exception:
                        pass
                    return
                if page == 23:
                    help_text = (
                        "سرچ | self MR\n\n"
                        "دستورات:\n"
                        ".سرچ + چیزی که می‌خوای\n\n"
                        "مثال:\n"
                        ".سرچ + گاو\n\n"
                        "ربات از وب جستجو می‌کند و چند عکس مرتبط می‌فرستد."
                    )
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(callback.inline_message_id, help_text, reply_markup=generate_panel_markup(target_user_id, 23))
                        else:
                            await callback.message.edit_text(help_text, reply_markup=generate_panel_markup(target_user_id, 23))
                    except Exception:
                        pass
                    try:
                        await edit_panel_colored(callback, target_user_id, 23)
                    except Exception:
                        pass
                    return
                if page == 34:
                    help_text = (
                        "📣 سندر | self MR\n\n"
                        "ارسال خودکار بنر داخل همین گروه با سقف ساعتی.\n\n"
                        "دستورات:\n"
                        "• `.تنظیم بنر سندر` → ریپلای روی بنر (کپی)\n"
                        "• `.تنظیم بنر فور` → ریپلای روی بنر (فوروارد)\n"
                        "• `.سندر روشن 100` → سهمیه ۵۰ تا ۲۰۰ در ساعت\n"
                        "• `.سندر خاموش`\n"
                        "• `.سندر تاخیر 60` → فاصله ارسال (ثانیه)\n"
                        "• `.بنر فور` / `.بنر کپی`\n"
                        "• `.سندر وضعیت`\n"
                        "• `.سندر حذف` → پاک کردن این گروه\n\n"
                        "⚠️ فقط در گروه‌هایی که عضو هستی."
                    )
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(callback.inline_message_id, help_text, reply_markup=generate_panel_markup(target_user_id, 34))
                        else:
                            await callback.message.edit_text(help_text, reply_markup=generate_panel_markup(target_user_id, 34))
                    except Exception:
                        pass
                    try:
                        await edit_panel_colored(callback, target_user_id, 34)
                    except Exception:
                        pass
                    return
                if page == 24:

                    help_text = (
                        "🎰 تقلب | self MR\n\n"
                        "این ویژگی ایموجی بازی را آنقدر می‌فرستد تا بهترین نتیجه بیاید "
                        "و پیام‌های ناموفق را خودکار پاک می‌کند.\n\n"
                        "دستورات:\n"
                        "• `.بولینگ` → استرایک (۶)\n"
                        "• `.بسکتبال` → توپ داخل سبد (۵)\n"
                        "• `.فوتبال` → گل (۵)\n"
                        "• `.تاس 1` تا `.تاس 6` → عدد دلخواه\n"
                        "• `.اسلات 777` → جکپات ۷۷۷\n"
                        "• `.اسلات لیمو` → سه لیمو\n"
                        "• `.اسلات انگور` → سه انگور\n"
                        "• `.اسلات Bar` → سه بار\n\n"
                        "⚠️ برای جلوگیری از اسپم و ریپورت، بین هر پرتاب تاخیر تصادفی وجود دارد."
                    )
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(callback.inline_message_id, help_text, reply_markup=generate_panel_markup(target_user_id, 24))
                        else:
                            await callback.message.edit_text(help_text, reply_markup=generate_panel_markup(target_user_id, 24))
                    except Exception:
                        pass
                    try:
                        await edit_panel_colored(callback, target_user_id, 24)
                    except Exception:
                        pass
                    return
                if page == 25:
                    lst = ROTATING_MUSIC.get(target_user_id) or []
                    interval = ROTATING_MUSIC_INTERVAL.get(target_user_id, 1)
                    st = "on ✅" if ROTATING_MUSIC_STATUS.get(target_user_id) else "off ❌"
                    help_text = (
                        f"🎵 آهنگ چرخشی | self MR\n\n"
                        f"وضعیت: {st}\n"
                        f"تایم: هر {interval} ساعت\n"
                        f"تعداد آهنگ: {len(lst)}\n\n"
                        f"دستورات:\n"
                        f"ریپلای روی آهنگ + `.اضافه کردن آهنگ`\n"
                        f".تنظیم تایم آهنگ 2\n"
                        f"(حداقل ۱ ساعت — حداکثر ۲۴ ساعت)\n"
                        f".لیست آهنگ چرخشی\n"
                        f".پاکسازی لیست آهنگ چرخشی\n"
                        f".آهنگ چرخشی روشن\n"
                        f".آهنگ چرخشی خاموش"
                    )
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(callback.inline_message_id, help_text, reply_markup=generate_panel_markup(target_user_id, 25))
                        else:
                            await callback.message.edit_text(help_text, reply_markup=generate_panel_markup(target_user_id, 25))
                    except Exception:
                        pass
                    try:
                        await edit_panel_colored(callback, target_user_id, 25)
                    except Exception:
                        pass
                    return
                if page == 26:
                    help_text = (
                        "🕐 ساعت کشورها | self MR\n\n"
                        "دستورات:\n"
                        "`.ساعت ایران`\n"
                        "`.ساعت Tokyo`\n"
                        "`.ساعت دبی`\n"
                        "`.زمان لندن`\n\n"
                        "نام کشور یا شهر را بعد از دستور بنویسید."
                    )
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(callback.inline_message_id, help_text, reply_markup=generate_panel_markup(target_user_id, 26))
                        else:
                            await callback.message.edit_text(help_text, reply_markup=generate_panel_markup(target_user_id, 26))
                    except Exception:
                        pass
                    try:
                        await edit_panel_colored(callback, target_user_id, 26)
                    except Exception:
                        pass
                    return
                if page == 27:
                    help_text = (
                        "🌤 آب و هوا | self MR\n\n"
                        "دستورات:\n"
                        "`.آب و هوا تهران`\n"
                        "`.آب و هوا London`\n"
                        "`.هوای شیراز`\n\n"
                        "نام شهر را بعد از دستور بنویسید."
                    )
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(callback.inline_message_id, help_text, reply_markup=generate_panel_markup(target_user_id, 27))
                        else:
                            await callback.message.edit_text(help_text, reply_markup=generate_panel_markup(target_user_id, 27))
                    except Exception:
                        pass
                    try:
                        await edit_panel_colored(callback, target_user_id, 27)
                    except Exception:
                        pass
                    return
                if page == 28:
                    help_text = (
                        "🎤 ویس به متن | self MR\n\n"
                        "روی یک ویس / صوت ریپلای کنید:\n"
                        "`.ویس به متن`"
                    )
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(callback.inline_message_id, help_text, reply_markup=generate_panel_markup(target_user_id, 28))
                        else:
                            await callback.message.edit_text(help_text, reply_markup=generate_panel_markup(target_user_id, 28))
                    except Exception:
                        pass
                    try:
                        await edit_panel_colored(callback, target_user_id, 28)
                    except Exception:
                        pass
                    return
                if page == 29:
                    help_text = (
                        "📄 عکس ↔ PDF | self MR\n\n"
                        "ریپلای روی عکس:\n"
                        "`.عکس به pdf`\n\n"
                        "ریپلای روی PDF:\n"
                        "`.pdf به عکس`\n"
                        "(صفحه اول PDF → عکس)\n\n"
                        "PDF→عکس نیاز به pymupdf دارد."
                    )
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(callback.inline_message_id, help_text, reply_markup=generate_panel_markup(target_user_id, 29))
                        else:
                            await callback.message.edit_text(help_text, reply_markup=generate_panel_markup(target_user_id, 29))
                    except Exception:
                        pass
                    try:
                        await edit_panel_colored(callback, target_user_id, 29)
                    except Exception:
                        pass
                    return
                if page == 30:
                    help_text = (
                        "👑 تگ ادمین / اعضا | self MR\n\n"
                        "فقط داخل گروه:\n"
                        "`.تگ ادمین`\n"
                        "`.تگ اعضا`\n\n"
                        "تگ اعضا حداکثر ۲۰۰ نفر\n"
                        "با تاخیر ضد‌اسپم ارسال می‌شود."
                    )
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(callback.inline_message_id, help_text, reply_markup=generate_panel_markup(target_user_id, 30))
                        else:
                            await callback.message.edit_text(help_text, reply_markup=generate_panel_markup(target_user_id, 30))
                    except Exception:
                        pass
                    try:
                        await edit_panel_colored(callback, target_user_id, 30)
                    except Exception:
                        pass
                    return
                if page == 31:
                    st = FIRST_COMMENT_STATUS.get(target_user_id, False)
                    txt = FIRST_COMMENT_TEXT.get(target_user_id, "🔥") or "🔥"
                    help_text = (
                        f"💬 کامنت اول کانال | self MR\n\n"
                        f"وضعیت: {'on ✅' if st else 'off ❌'}\n"
                        f"متن فعلی: {txt[:80]}\n\n"
                        f"دستورات:\n"
                        f".کامنت اول روشن\n"
                        f".کامنت اول خاموش\n"
                        f".تنظیم کامنت اول متن دلخواه\n\n"
                        f"روی پست کانال‌هایی که گروه بحث دارند\n"
                        f"به‌صورت خودکار کامنت می‌گذارد."
                    )
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(callback.inline_message_id, help_text, reply_markup=generate_panel_markup(target_user_id, 31))
                        else:
                            await callback.message.edit_text(help_text, reply_markup=generate_panel_markup(target_user_id, 31))
                    except Exception:
                        pass
                    try:
                        await edit_panel_colored(callback, target_user_id, 31)
                    except Exception:
                        pass
                    return
                if page == 32:
                    help_text = (
                        "✨ کیفیت عکس | self MR\n\n"
                        "روی عکس ریپلای کنید:\n"
                        "`.کیفیت عکس`\n"
                        "`.بهبود عکس`\n\n"
                        "بزرگ‌نمایی نرم بدون پیکسله‌شدن."
                    )
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(callback.inline_message_id, help_text, reply_markup=generate_panel_markup(target_user_id, 32))
                        else:
                            await callback.message.edit_text(help_text, reply_markup=generate_panel_markup(target_user_id, 32))
                    except Exception:
                        pass
                    try:
                        await edit_panel_colored(callback, target_user_id, 32)
                    except Exception:
                        pass
                    return
                if page == 33:
                    help_text = (
                        "🔎 سرچ آهنگ | self MR\n\n"
                        "دستورات:\n"
                        "`.سرچ آهنگ شادمهر`\n"
                        "`.سرچ آهنگ تکه از متن`\n\n"
                        "لیست آهنگ‌ها با دکمه می‌آید.\n"
                        "روی هر دکمه بزن تا فایل صوتی دانلود شود."
                    )
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(callback.inline_message_id, help_text, reply_markup=generate_panel_markup(target_user_id, 33))
                        else:
                            await callback.message.edit_text(help_text, reply_markup=generate_panel_markup(target_user_id, 33))
                    except Exception:
                        pass
                    try:
                        await edit_panel_colored(callback, target_user_id, 33)
                    except Exception:
                        pass
                    return
                if page == 19:

                    help_text = (
                        "هوش مصنوعی | self MR\n\n"
                        "گزینه مورد نظر را انتخاب کنید."
                    )
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(callback.inline_message_id, help_text, reply_markup=generate_panel_markup(target_user_id, 19))
                        else:
                            await callback.message.edit_text(help_text, reply_markup=generate_panel_markup(target_user_id, 19))
                    except Exception:
                        pass
                    try:
                        await edit_panel_colored(callback, target_user_id, 19)
                    except Exception:
                        pass
                    return
                if page == 20:
                    help_text = (
                        "متن گسترده | self MR\n\n"
                        "دستور:\n"
                        ".هوش متن گسترده + متن شما\n\n"
                        "مثال:\n"
                        ".هوش متن گسترده + علی در روز آفتابی با دوستانش بیرون رفت\n\n"
                        "ربات متن را زیبا، داستانی و با ایموجی گسترش می‌دهد."
                    )
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(callback.inline_message_id, help_text, reply_markup=generate_panel_markup(target_user_id, 20))
                        else:
                            await callback.message.edit_text(help_text, reply_markup=generate_panel_markup(target_user_id, 20))
                    except Exception:
                        pass
                    try:
                        await edit_panel_colored(callback, target_user_id, 20)
                    except Exception:
                        pass
                    return
                if page == 21:
                    help_text = (
                        "استخراج متن آهنگ | self MR\n\n"
                        "دستورات:\n"
                        "ریپلای + .متن آهنگ\n\n"
                        "روی فایل آهنگ (music) ریپلای کنید تا متن آهنگ پیدا شود."
                    )
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(callback.inline_message_id, help_text, reply_markup=generate_panel_markup(target_user_id, 21))
                        else:
                            await callback.message.edit_text(help_text, reply_markup=generate_panel_markup(target_user_id, 21))
                    except Exception:
                        pass
                    try:
                        await edit_panel_colored(callback, target_user_id, 21)
                    except Exception:
                        pass
                    return
                if page == 18:

                    lst = ROTATING_NAMES.get(target_user_id) or []
                    interval = ROTATING_NAME_INTERVAL.get(target_user_id, 10)
                    st = "on ✅" if ROTATING_NAME_STATUS.get(target_user_id) else "off ❌"
                    names_txt = "\n".join(f"• {n}" for n in lst) if lst else "—"
                    help_text = (
                        f"اسم چرخشی | self MR\n\n"
                        f"وضعیت: {st}\n"
                        f"تایم: {interval} ثانیه\n\n"
                        f"لیست اسامی:\n{names_txt}\n\n"
                        f"دستورات:\n"
                        f".افزودن اسم علی\n"
                        f".تنظیم تایم اسم 5\n"
                        f".لیست اسامی چرخشی\n"
                        f".پاکسازی لیست اسم چرخشی\n"
                        f".اسم چرخشی روشن\n"
                        f".اسم چرخشی خاموش"
                    )
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(callback.inline_message_id, help_text, reply_markup=generate_panel_markup(target_user_id, 18))
                        else:
                            await callback.message.edit_text(help_text, reply_markup=generate_panel_markup(target_user_id, 18))
                    except Exception:
                        pass
                    try:
                        await edit_panel_colored(callback, target_user_id, 18)
                    except Exception:
                        pass
                    return
                if page == 17:
                    lines = ["انیمیشن | self MR", "", "انیمیشن‌ها:"]
                    for i, name in enumerate(EMOJI_ANIMATIONS.keys(), 1):
                        lines.append(f"{i}- .{name}")
                    help_text = "\n".join(lines)
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(callback.inline_message_id, help_text, reply_markup=generate_panel_markup(target_user_id, 17))
                        else:
                            await callback.message.edit_text(help_text, reply_markup=generate_panel_markup(target_user_id, 17))
                    except Exception:
                        pass
                    try:
                        await edit_panel_colored(callback, target_user_id, 17)
                    except Exception:
                        pass
                    return
                if page == 13:
                    help_text = (
                        "ذخیره | self MR\n\n"
                        "برای استفاده:\n"
                        "ریپلای + .ذخیره\n\n"
                        "پشتیبانی از:\n"
                        "• متن، عکس، ویدیو، ویس، فایل\n"
                        "• عکس/ویدیو نابودشونده (تایم‌دار)\n"
                        "خروجی در Saved Messages ذخیره می‌شود."
                    )
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(callback.inline_message_id, help_text, reply_markup=generate_panel_markup(target_user_id, 13))
                        else:
                            await callback.message.edit_text(help_text, reply_markup=generate_panel_markup(target_user_id, 13))
                    except Exception:
                        pass
                    try:
                        await edit_panel_colored(callback, target_user_id, 13)
                    except Exception:
                        pass
                    return
                if page == 14:
                    help_text = (
                        "تغییر اسم | self MR\n\n"
                        "نحوه استفاده:\n"
                        ".اسم نام جدید\n\n"
                        "مثال:\n"
                        ".اسم محمدرضا"
                    )
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(callback.inline_message_id, help_text, reply_markup=generate_panel_markup(target_user_id, 14))
                        else:
                            await callback.message.edit_text(help_text, reply_markup=generate_panel_markup(target_user_id, 14))
                    except Exception:
                        pass
                    try:
                        await edit_panel_colored(callback, target_user_id, 14)
                    except Exception:
                        pass
                    return
                if page == 15:
                    help_text = (
                        "تغییر بیوگرافی | self MR\n\n"
                        "نحوه استفاده:\n"
                        ".بیو متن بیوگرافی\n\n"
                        "مثال:\n"
                        ".بیو زندگی ادامه دارد\n\n"
                        "حداکثر ۷۰ کاراکتر"
                    )
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(callback.inline_message_id, help_text, reply_markup=generate_panel_markup(target_user_id, 15))
                        else:
                            await callback.message.edit_text(help_text, reply_markup=generate_panel_markup(target_user_id, 15))
                    except Exception:
                        pass
                    try:
                        await edit_panel_colored(callback, target_user_id, 15)
                    except Exception:
                        pass
                    return
                if page == 16:
                    help_text = (
                        "تغییر یوزرنیم | self MR\n\n"
                        "نحوه استفاده:\n"
                        ".یوزرنیم myname\n\n"
                        "مثال:\n"
                        ".یوزرنیم self_mr\n\n"
                        "۵ تا ۳۲ کاراکتر | حرف اول انگلیسی"
                    )
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(callback.inline_message_id, help_text, reply_markup=generate_panel_markup(target_user_id, 16))
                        else:
                            await callback.message.edit_text(help_text, reply_markup=generate_panel_markup(target_user_id, 16))
                    except Exception:
                        pass
                    try:
                        await edit_panel_colored(callback, target_user_id, 16)
                    except Exception:
                        pass
                    return
                if page == 11:
                    st = EDIT_ALERT_STATUS.get(target_user_id, False)
                    help_text = (
                        "هشدار ویرایش پیام | self MR\n\n"
                        f"وضعیت: {'on ✅' if st else 'off ❌'}\n\n"
                        "برای استفاده:\n"
                        ".هشدار ویرایش روشن\n"
                        ".هشدار ویرایش خاموش\n\n"
                        "وقتی کسی در پیوی پیامش را ویرایش کند، متن قبل از ویرایش به پیام‌های ذخیره‌شده ارسال می‌شود."
                    )
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(callback.inline_message_id, help_text, reply_markup=generate_panel_markup(target_user_id, 11))
                        else:
                            await callback.message.edit_text(help_text, reply_markup=generate_panel_markup(target_user_id, 11))
                    except Exception:
                        pass
                    try:
                        await edit_panel_colored(callback, target_user_id, 11)
                    except Exception:
                        pass
                    return
                if page == 12:
                    st = DELETE_ALERT_STATUS.get(target_user_id, False)
                    help_text = (
                        "هشدار حذف پیام | self MR\n\n"
                        f"وضعیت: {'on ✅' if st else 'off ❌'}\n\n"
                        "برای استفاده:\n"
                        ".هشدار حذف روشن\n"
                        ".هشدار حذف خاموش\n\n"
                        "وقتی کسی در پیوی پیامش را حذف کند، متن حذف‌شده به پیام‌های ذخیره‌شده ارسال می‌شود."
                    )
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(callback.inline_message_id, help_text, reply_markup=generate_panel_markup(target_user_id, 12))
                        else:
                            await callback.message.edit_text(help_text, reply_markup=generate_panel_markup(target_user_id, 12))
                    except Exception:
                        pass
                    try:
                        await edit_panel_colored(callback, target_user_id, 12)
                    except Exception:
                        pass
                    return
                if page == 10:
                    help_text = (
                        "ساخت ویدیو گرد | self MR\n\n"
                        "دستورات\n"
                        ".ویدیو مسیج\n\n"
                        "روی یک ویدیو ریپلای کن؛ خروجی به صورت ویدیو گرد در همان چت ارسال می‌شود."
                    )
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(
                                callback.inline_message_id,
                                help_text,
                                reply_markup=generate_panel_markup(target_user_id, 10),
                            )
                        else:
                            await callback.message.edit_text(
                                help_text,
                                reply_markup=generate_panel_markup(target_user_id, 10),
                            )
                    except Exception:
                        pass
                    try:
                        await edit_panel_colored(callback, target_user_id, 10)
                    except Exception:
                        pass
                    return
                # صفحه عضویت اجباری: متن راهنما + دکمه‌های وضعیت
                if page == 9:
                    st = FORCE_JOIN_PV_STATUS.get(target_user_id, False)
                    chs = FORCE_JOIN_CHANNELS.get(target_user_id) or []
                    status = "on ✅" if st else "off ❌"
                    help_text = (
                        f"عضویت اجباری پیوی | self MR\n\n"
                        f"وضعیت: ( {status} )\n"
                        f"تنظیمات\n\n"
                        f".تنظیم عضویت @channel\n"
                        f".حذف عضویت @channel\n"
                        f".لیست عضویت اجباری\n"
                        f".پاکسازی عضویت اجباری\n"
                        f".عضویت اجباری روشن\n"
                        f".عضویت اجباری خاموش\n\n"
                        f"کانال‌های ثبت‌شده: {len(chs)}"
                    )
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(
                                callback.inline_message_id,
                                help_text,
                                reply_markup=generate_panel_markup(target_user_id, 9),
                            )
                        else:
                            await callback.message.edit_text(
                                help_text,
                                reply_markup=generate_panel_markup(target_user_id, 9),
                            )
                    except Exception:
                        await edit_panel_colored(callback, target_user_id, 9)
                    # رنگ دکمه‌ها
                    try:
                        await edit_panel_colored(callback, target_user_id, 9)
                    except Exception:
                        pass
                else:
                    # صفحات اصلی: متن پنل را برگردان (نه راهنمای قبلی)
                    page_titles = {
                        1: f"⚡️ مدیریت پیشرفته self MR\n👤 کاربر: {target_user_id}",
                        2: "✏️ حالت متن / فونت‌ها | self MR",
                        3: "🛡 بخش امنیتی | self MR",
                        4: "⚡ اکشن‌ها | self MR",
                        5: "🕐 فونت ساعت | self MR",
                        6: "💱 قیمت ارز | self MR",
                        7: "🎤 تبدیل متن به ویس | self MR",
                        8: "🧩 تبدیل به استیکر | self MR",
                    }
                    panel_text = page_titles.get(page, f"⚡️ مدیریت پیشرفته self MR\n👤 کاربر: {target_user_id}")
                    try:
                        if callback.inline_message_id:
                            await client.edit_inline_text(
                                callback.inline_message_id,
                                panel_text,
                                reply_markup=generate_panel_markup(target_user_id, page),
                            )
                        else:
                            await callback.message.edit_text(
                                panel_text,
                                reply_markup=generate_panel_markup(target_user_id, page),
                            )
                    except Exception:
                        pass
                    try:
                        await edit_panel_colored(callback, target_user_id, page)
                    except Exception:
                        pass
            except Exception:
                pass
            return

        elif action == "toggle_edit_alert":
            target_user_id = int(parts[-1])
            if callback.from_user.id != target_user_id:
                await callback.answer("⛔️ دسترسی غیرمجاز!", show_alert=True)
                return
            ns = not EDIT_ALERT_STATUS.get(target_user_id, False)
            EDIT_ALERT_STATUS[target_user_id] = ns
            data_manager.update_user_data(target_user_id, {"settings": {"edit_alert": ns}})
            persist_all_user_settings(target_user_id)
            await callback.answer("✅ روشن" if ns else "❌ خاموش")
            try:
                help_text = (
                    "هشدار ویرایش پیام | self MR\n\n"
                    f"وضعیت: {'on ✅' if ns else 'off ❌'}\n\n"
                    "برای استفاده:\n.هشدار ویرایش روشن\n.هشدار ویرایش خاموش"
                )
                if callback.inline_message_id:
                    await client.edit_inline_text(callback.inline_message_id, help_text, reply_markup=generate_panel_markup(target_user_id, 11))
                else:
                    await callback.message.edit_text(help_text, reply_markup=generate_panel_markup(target_user_id, 11))
            except Exception:
                pass
            try:
                await edit_panel_colored(callback, target_user_id, 11)
            except Exception:
                pass
            return

        elif action == "toggle_delete_alert":
            target_user_id = int(parts[-1])
            if callback.from_user.id != target_user_id:
                await callback.answer("⛔️ دسترسی غیرمجاز!", show_alert=True)
                return
            ns = not DELETE_ALERT_STATUS.get(target_user_id, False)
            DELETE_ALERT_STATUS[target_user_id] = ns
            data_manager.update_user_data(target_user_id, {"settings": {"delete_alert": ns}})
            persist_all_user_settings(target_user_id)
            await callback.answer("✅ روشن" if ns else "❌ خاموش")
            try:
                help_text = (
                    "هشدار حذف پیام | self MR\n\n"
                    f"وضعیت: {'on ✅' if ns else 'off ❌'}\n\n"
                    "برای استفاده:\n.هشدار حذف روشن\n.هشدار حذف خاموش"
                )
                if callback.inline_message_id:
                    await client.edit_inline_text(callback.inline_message_id, help_text, reply_markup=generate_panel_markup(target_user_id, 12))
                else:
                    await callback.message.edit_text(help_text, reply_markup=generate_panel_markup(target_user_id, 12))
            except Exception:
                pass
            try:
                await edit_panel_colored(callback, target_user_id, 12)
            except Exception:
                pass
            return

        elif action == "toggle_force_join":
            target_user_id = int(parts[-1])
            if callback.from_user.id != target_user_id:
                await callback.answer("⛔️ دسترسی غیرمجاز!", show_alert=True)
                return
            new_state = not FORCE_JOIN_PV_STATUS.get(target_user_id, False)
            FORCE_JOIN_PV_STATUS[target_user_id] = new_state
            data_manager.update_user_data(target_user_id, {"settings": {"force_join_pv": new_state}})
            persist_all_user_settings(target_user_id)
            await callback.answer("✅ روشن شد" if new_state else "❌ خاموش شد")
            # رفرش متن + دکمه
            st = new_state
            chs = FORCE_JOIN_CHANNELS.get(target_user_id) or []
            status = "on ✅" if st else "off ❌"
            help_text = (
                f"عضویت اجباری پیوی | self MR\n\n"
                f"وضعیت: ( {status} )\n"
                f"تنظیمات\n\n"
                f".تنظیم عضویت @channel\n"
                f".حذف عضویت @channel\n"
                f".لیست عضویت اجباری\n"
                f".پاکسازی عضویت اجباری\n"
                f".عضویت اجباری روشن\n"
                f".عضویت اجباری خاموش\n\n"
                f"کانال‌های ثبت‌شده: {len(chs)}"
            )
            try:
                if callback.inline_message_id:
                    await client.edit_inline_text(
                        callback.inline_message_id,
                        help_text,
                        reply_markup=generate_panel_markup(target_user_id, 9),
                    )
                else:
                    await callback.message.edit_text(
                        help_text,
                        reply_markup=generate_panel_markup(target_user_id, 9),
                    )
            except Exception:
                pass
            try:
                await edit_panel_colored(callback, target_user_id, 9)
            except Exception:
                pass
            return

        elif action == "close_panel":
            try:
                if callback.inline_message_id:
                    await client.edit_inline_text(callback.inline_message_id, "✔ پنل بسته شد.")
                else:
                    await callback.message.delete()
            except:
                pass
            return

        if settings_update:
            data_manager.update_user_data(target_user_id, {"settings": settings_update})
            # ذخیره کامل برای جلوگیری از پریدن تنظیمات
            try:
                persist_all_user_settings(target_user_id)
            except Exception:
                pass

        # بعد از تغییر، همان بخش پنل را نگه دار
        stay_page = 1
        if action in ("toggle_sec", "toggle_seen", "toggle_anti", "toggle_g_enemy"):
            stay_page = 3
        elif action in ("toggle_type", "toggle_game") or action.startswith("set_action"):
            stay_page = 4
        elif action == "toggle_pv":
            stay_page = 1
        elif action.startswith("lang_"):
            stay_page = 1

        try:
            await edit_panel_colored(callback, target_user_id, stay_page)
        except:
            pass

# =============================================
# 📥📤 بخش مدیریت دیتابیس (آپلود و دانلود) - نسخه فیکس شده
# =============================================

@manager_bot.on_message(filters.text & filters.private & filters.regex("^📥 دانلود دیتابیس$"))
async def download_database_handler(client, message):
    if not message.from_user or message.from_user.id not in GOD_ADMIN_IDS:
        return
    
    try:
        import zipfile
        import shutil
        
        timestamp = datetime.now(TEHRAN_TIMEZONE).strftime('%Y%m%d_%H%M%S')
        zip_name = f"selfMR_backup_{timestamp}.zip"
        
        with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # 1. bot_data.json
            if os.path.exists(DATA_FILE):
                zipf.write(DATA_FILE, "bot_data.json")
            
            # 2. sessions.db
            if os.path.exists("sessions.db"):
                zipf.write("sessions.db", "sessions.db")
            
            # 3. تمام دیتابیس‌های کاربران (الماس‌ها)
            if os.path.exists("database_users"):
                for root, dirs, files in os.walk("database_users"):
                    for file in files:
                        if file.endswith(".db"):
                            full_path = os.path.join(root, file)
                            arcname = os.path.join("database_users", file)
                            zipf.write(full_path, arcname)
        
        file_size = os.path.getsize(zip_name) / 1024
        await message.reply_document(
            document=zip_name,
            caption=(
                f"✅ **بکاپ کامل self MR**\n\n"
                f"📅 تاریخ: {datetime.now(TEHRAN_TIMEZONE).strftime('%Y-%m-%d %H:%M')}\n"
                f"📁 حجم: {file_size:.1f} KB\n\n"
                f"شامل:\n"
                f"• bot_data.json (تنظیمات + سشن‌ها)\n"
                f"• sessions.db\n"
                f"• database_users/ (موجودی الماس همه کاربران)"
            )
        )
        
        # پاک کردن فایل موقت
        try:
            os.remove(zip_name)
        except:
            pass
            
        logging.info(f"📥 Full backup downloaded by admin {message.from_user.id}")
        
    except Exception as e:
        await message.reply_text(f"❌ خطا در دانلود بکاپ: {e}")
        logging.error(f"Download database error: {e}")

@manager_bot.on_message(filters.text & filters.private & filters.regex("^📤 آپلود دیتابیس$"))
async def upload_database_request_handler(client, message):
    if not message.from_user or message.from_user.id not in GOD_ADMIN_IDS:
        return
    
    ADMIN_STATES[message.from_user.id] = "waiting_for_db_upload"
    await message.reply_text(
        "📤 **لطفاً فایل بکاپ را ارسال کنید.**\n\n"
        "می‌توانید یکی از این دو را بفرستید:\n"
        "• فایل **ZIP** کامل (پیشنهادی)\n"
        "• یا فقط فایل **JSON**\n\n"
        "برای لغو، `لغو` را بفرستید."
    )

@manager_bot.on_message(filters.document & filters.private)
async def upload_database_handler(client, message):
    if not message.from_user or message.from_user.id not in GOD_ADMIN_IDS:
        return
    
    if ADMIN_STATES.get(message.from_user.id) != "waiting_for_db_upload":
        return
    
    try:
        import zipfile
        import shutil
        
        file_path = await message.download()
        if not file_path:
            await message.reply_text("❌ خطا در دانلود فایل!")
            return
        
        is_zip = file_path.lower().endswith(".zip")
        
        if is_zip:
            # ====== آپلود فایل ZIP کامل ======
            await message.reply_text("📦 فایل ZIP شناسایی شد. در حال استخراج بکاپ کامل...")
            
            extract_dir = f"temp_restore_{int(time.time())}"
            os.makedirs(extract_dir, exist_ok=True)
            
            try:
                with zipfile.ZipFile(file_path, 'r') as zipf:
                    zipf.extractall(extract_dir)
                
                # بازگردانی bot_data.json
                json_src = os.path.join(extract_dir, "bot_data.json")
                if os.path.exists(json_src):
                    if os.path.exists(DATA_FILE):
                        os.rename(DATA_FILE, f"{DATA_FILE}.backup.{int(time.time())}")
                    shutil.copy2(json_src, DATA_FILE)
                
                # بازگردانی sessions.db
                sess_src = os.path.join(extract_dir, "sessions.db")
                if os.path.exists(sess_src):
                    if os.path.exists("sessions.db"):
                        os.rename("sessions.db", f"sessions.db.backup.{int(time.time())}")
                    shutil.copy2(sess_src, "sessions.db")
                
                # بازگردانی database_users (الماس‌ها)
                users_src = os.path.join(extract_dir, "database_users")
                if os.path.exists(users_src):
                    if os.path.exists("database_users"):
                        # بکاپ پوشه قبلی
                        shutil.move("database_users", f"database_users.backup.{int(time.time())}")
                    shutil.copytree(users_src, "database_users")
                
                await message.reply_text("✅ بکاپ کامل با موفقیت بازگردانی شد!\n\n🔄 در حال لود مجدد...")
                
            finally:
                # پاکسازی
                try:
                    shutil.rmtree(extract_dir)
                    os.remove(file_path)
                except:
                    pass
        else:
            # ====== آپلود فقط JSON (حالت قدیمی) ======
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                await message.reply_text("❌ فایل معتبر نیست! لطفاً فایل ZIP یا JSON معتبر ارسال کنید.")
                if os.path.exists(file_path):
                    os.remove(file_path)
                ADMIN_STATES[message.from_user.id] = None
                return
            
            if os.path.exists(DATA_FILE):
                backup_name = f"{DATA_FILE}.backup.{int(time.time())}"
                os.rename(DATA_FILE, backup_name)
            
            os.rename(file_path, DATA_FILE)
            await message.reply_text("✅ فایل JSON آپلود شد!\n\n🔄 در حال لود مجدد...")
        
        ADMIN_STATES[message.from_user.id] = None
        
        await message.reply_text("🔄 در حال لود مجدد و بررسی محتویات...")
        
        # ====== لود مجدد دیتابیس ======
        data_manager.reload()
        load_all_states()
        # اعمال تنظیمات برای همه کاربران
        try:
            for uid_str in list(data_manager.get_all_users().keys()):
                try:
                    apply_user_settings_from_db(int(uid_str))
                except Exception:
                    pass
        except Exception as e:
            logging.error(f"reapply settings after upload: {e}")
        
        # ====== تشخیص کامل محتویات JSON ======
        all_users = data_manager.get_all_users()
        total_users = len(all_users)
        users_with_session = 0
        users_with_phone = 0
        sessions_top_level = 0
        
        try:
            sessions_top_level = len(list(data_manager.get_all_sessions()))
        except:
            pass
        
        sample_info = []
        for uid_str, u_data in list(all_users.items())[:5]:
            has_ss = bool(u_data.get("session_string"))
            has_ph = bool(u_data.get("phone"))
            sample_info.append(f"• {uid_str} → session:{has_ss} | phone:{has_ph}")
            if has_ss:
                users_with_session += 1
            if has_ph:
                users_with_phone += 1
        
        # شمارش کامل
        for uid_str, u_data in all_users.items():
            if u_data.get("session_string"):
                users_with_session += 1
            if u_data.get("phone"):
                users_with_phone += 1
        
        # چون دو بار شمردیم، اصلاح می‌کنیم
        users_with_session = sum(1 for u in all_users.values() if u.get("session_string"))
        users_with_phone = sum(1 for u in all_users.values() if u.get("phone"))
        
        diag_text = (
            f"📊 **گزارش محتویات فایل آپلود شده:**\n\n"
            f"👥 تعداد کل کاربران: `{total_users}`\n"
            f"📱 کاربران دارای phone: `{users_with_phone}`\n"
            f"🔑 کاربران دارای session_string: `{users_with_session}`\n"
            f"📂 سشن‌های بخش sessions: `{sessions_top_level}`\n\n"
            f"**نمونه کاربران:**\n" + ("\n".join(sample_info) if sample_info else "هیچ کاربری نیست")
        )
        
        await message.reply_text(diag_text)
        logging.info(f"DIAG → users={total_users} | with_session={users_with_session} | with_phone={users_with_phone} | top_sessions={sessions_top_level}")
        
        # ====== سینک قوی سشن‌ها ======
        synced = 0
        synced_users = set()
        
        try:
            # روش ۱
            for phone, sess_info in data_manager.get_all_sessions():
                s_str = sess_info.get("string")
                u_id = sess_info.get("user_id")
                if s_str and u_id and int(u_id) not in synced_users:
                    u_data = data_manager.get_user_data(u_id)
                    save_session_to_db(str(phone), s_str, int(u_id), u_data.get("first_name", ""), u_data.get("username", ""))
                    synced += 1
                    synced_users.add(int(u_id))
                    logging.info(f"✅ Synced from sessions[] → {u_id}")

            # روش ۲ - اسکن کاربران
            for uid_str, u_data in all_users.items():
                try:
                    u_id = int(uid_str)
                    if u_id in synced_users:
                        continue
                    s_str = u_data.get("session_string")
                    phone = u_data.get("phone")
                    if s_str and phone:
                        save_session_to_db(str(phone), s_str, u_id, u_data.get("first_name", ""), u_data.get("username", ""))
                        data_manager.data.setdefault("sessions", {})[str(phone)] = {"string": s_str, "user_id": u_id}
                        synced += 1
                        synced_users.add(u_id)
                        logging.info(f"✅ Synced from users[] → {u_id}")
                except Exception as e:
                    logging.error(f"Error syncing {uid_str}: {e}")
            
            data_manager.save_data()
            logging.info(f"✅ Total synced: {synced}")
            
        except Exception as e:
            logging.error(f"❌ Sync failed: {e}")
            await message.reply_text(f"⚠️ خطا در سینک: {e}")
        
        final_count = get_session_count()
        restart_result = await restart_all_selfs()
        
        final_msg = (
            f"✅ **عملیات کامل شد!**\n\n"
            f"🔄 سشن‌های سینک‌شده: `{synced}`\n"
            f"📊 سشن در SQLite: `{final_count}`\n"
            f"{restart_result}\n\n"
        )
        
        if synced == 0:
            final_msg += (
                "⚠️ **هیچ session_string ای پیدا نشد!**\n\n"
                "یعنی فایل JSON که آپلود کردی شامل session_string کاربران نیست.\n"
                "احتمالاً قبلاً فقط در sessions.db ذخیره می‌شده و داخل bot_data.json نوشته نمی‌شده."
            )
        else:
            final_msg += "✅ تمام سشن‌ها دوباره با تنظیمات قبلی فعال شدن."
        
        await message.reply_text(final_msg)
        logging.info(f"📤 Upload finished → synced={synced}")
        
    except Exception as e:
        await message.reply_text(f"❌ خطا در آپلود: {e}")
        logging.error(f"Upload database error: {e}")
        ADMIN_STATES[message.from_user.id] = None

# =============================================
# پایان بخش مدیریت دیتابیس
# =============================================


# =============================================
# UI پنل اصلی منیجر (self MR)
# =============================================
def main_menu_keyboard():
    ch = (FORCE_CHANNELS[0] if FORCE_CHANNELS else "@SELF_MR0").lstrip("@")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 مدیریت سلف", callback_data="mm_self")],
        [
            InlineKeyboardButton("💎 الماس رایگان", callback_data="mm_free"),
            InlineKeyboardButton("👤 حساب کاربری", callback_data="mm_account"),
        ],
        [InlineKeyboardButton("🛒 خرید الماس", callback_data="mm_buy")],
        [
            InlineKeyboardButton("📢 چنل", url=f"https://t.me/{ch}"),
            InlineKeyboardButton("🛡 پشتیبانی", url=f"https://t.me/{SUPPORT_USERNAME}"),
        ],
    ])


def self_manage_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ فعال‌سازی", callback_data="mm_activate")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="mm_home")],
    ])


def login_code_keyboard():
    rows = []
    for r in range(3):
        row = []
        for c in range(1, 4):
            n = r * 3 + c
            row.append(InlineKeyboardButton(str(n), callback_data=f"login_d_{n}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("0", callback_data="login_d_0")])
    rows.append([
        InlineKeyboardButton("❌ پاک", callback_data="login_del"),
        InlineKeyboardButton("✅ تایید", callback_data="login_ok"),
    ])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="mm_self")])
    return InlineKeyboardMarkup(rows)


def code_pad_text(digits: str) -> str:
    shown = digits if digits else "—"
    return (
        "🔐 **کد خود را وارد کنید:**\n"
        f"کد وارد شده: `{shown}`\n\n"
        "کد تلگرام را با دکمه‌ها وارد کنید سپس **تایید** را بزنید."
    )


async def send_main_menu(client, message_or_chat, user_id: int, edit=False):
    balance = get_balance(user_id)
    text = (
        f"✨ **پنل اصلی Self MR**\n\n"
        f"💎 موجودی: `{balance:,}` الماس\n"
        f"💰 فعال‌سازی سلف: `{SELF_PRICE}` الماس\n"
        f"⏰ کسر ساعتی: `{HOURLY_COST}` الماس\n\n"
        f"از منوی زیر بخش مورد نظر را انتخاب کنید."
    )
    kb = main_menu_keyboard()
    try:
        if edit and hasattr(message_or_chat, "edit_text"):
            await message_or_chat.edit_text(text, reply_markup=kb)
        elif hasattr(message_or_chat, "reply_text"):
            await message_or_chat.reply_text(text, reply_markup=kb)
        else:
            await client.send_message(message_or_chat, text, reply_markup=kb)
    except Exception:
        try:
            chat_id = getattr(message_or_chat, "chat", None)
            chat_id = chat_id.id if chat_id else message_or_chat
            await client.send_message(chat_id, text, reply_markup=kb)
        except Exception as e:
            logging.error(f"send_main_menu: {e}")


@manager_bot.on_message(filters.command("start"))
async def start_login(client, message):
    user_id = message.from_user.id
    init_user_db(user_id)

    if not await force_subscribe_check(client, message):
        return

    # ====== سیستم زیرمجموعه (۷۵ الماس) ======
    args = message.command
    if len(args) > 1:
        try:
            referrer_id = int(args[1])
            if referrer_id != user_id:
                init_user_db(referrer_id)
                db = get_user_db(user_id)
                cursor = db.cursor()
                cursor.execute('SELECT invited_by FROM users WHERE user_id = ?', (user_id,))
                row = cursor.fetchone()
                already_invited = bool(row and row[0] and int(row[0]) != 0)

                cursor.execute('SELECT reward_claimed FROM referrals WHERE referred_id = ?', (user_id,))
                ref_row = cursor.fetchone()
                already_rewarded = bool(ref_row and ref_row[0])
                db.close()

                if not already_invited and not already_rewarded:
                    db = get_user_db(user_id)
                    cursor = db.cursor()
                    cursor.execute('UPDATE users SET invited_by = ? WHERE user_id = ?', (referrer_id, user_id))
                    cursor.execute(
                        'INSERT OR IGNORE INTO referrals (referrer_id, referred_id, reward_claimed) VALUES (?, ?, 0)',
                        (referrer_id, user_id)
                    )
                    cursor.execute(
                        'UPDATE referrals SET reward_claimed = 1 WHERE referred_id = ? AND referrer_id = ?',
                        (user_id, referrer_id)
                    )
                    db.commit()
                    db.close()

                    add_balance(referrer_id, REFERRAL_REWARD)
                    uname = message.from_user.first_name or str(user_id)
                    try:
                        await manager_bot.send_message(
                            referrer_id,
                            f"🎉 **زیرمجموعه جدید | self MR**\n\n"
                            f"👤 {uname} با لینک شما وارد شد.\n"
                            f"💎 `{REFERRAL_REWARD}` الماس به حساب شما اضافه شد.\n"
                            f"✨ موجودی جدید: `{get_balance(referrer_id):,}` الماس"
                        )
                    except Exception:
                        pass
        except Exception as e:
            logging.warning(f"referral start: {e}")

    # کیبورد ادمین (اختیاری پایین)
    if message.from_user and message.from_user.id in GOD_ADMIN_IDS:
        admin_kb = ReplyKeyboardMarkup(
            [
                [KeyboardButton("📊 وضعیت ربات"), KeyboardButton("📢 پیام همگانی")],
                [KeyboardButton("💎 پنل الماس"), KeyboardButton("🛠 پنل ادمین")],
                [KeyboardButton("📥 دانلود دیتابیس"), KeyboardButton("📤 آپلود دیتابیس")],
            ],
            resize_keyboard=True
        )
        try:
            await message.reply_text("🛠 منوی ادمین فعال است.", reply_markup=admin_kb)
        except Exception:
            pass

    await send_main_menu(client, message, user_id, edit=False)


@manager_bot.on_message(filters.private, group=-1)
async def admin_broadcast_sender(client, message):
    if not message.from_user:
        return
    user_id = message.from_user.id
    if user_id in GOD_ADMIN_IDS and ADMIN_STATES.get(user_id) == "broadcast":
        if message.text and message.text in ["/start", "📊 وضعیت ربات", "📢 پیام همگانی"]:
            return

        if message.text and message.text.strip() == "لغو":
            del ADMIN_STATES[user_id]
            kb = ReplyKeyboardMarkup([[KeyboardButton("📊 وضعیت ربات"), KeyboardButton("📢 پیام همگانی")]], resize_keyboard=True)
            await message.reply_text("❌ عملیات ارسال همگانی لغو شد.", reply_markup=kb)
            message.stop_propagation()

        await message.reply_text("⏳ در حال ارسال پیام همگانی...")
        success = 0
        failed = 0
        users = data_manager.get_all_users()

        for u_id_str in users.keys():
            try:
                await message.copy(int(u_id_str))
                success += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed += 1

        del ADMIN_STATES[user_id]
        kb = ReplyKeyboardMarkup([[KeyboardButton("📊 وضعیت ربات"), KeyboardButton("📢 پیام همگانی")]], resize_keyboard=True)
        await message.reply_text(f"✅ پیام همگانی با موفقیت ارسال شد.\n\nموفق: {success}\nناموفق: {failed}", reply_markup=kb)
        message.stop_propagation()

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
    total_sessions = get_session_count()

    text = (
        "**📊 آمار و وضعیت سرور**\n\n"
        f"🟢 ربات‌های فعال: `{active_count}`\n"
        f"👥 کل کاربران: `{total_users}`\n"
        f"📱 نشست‌ها: `{total_sessions}`\n"
    )

    await message.reply_text(text)

# =============================================
# 💎 پنل الماس ادمین
# =============================================
@manager_bot.on_message(filters.text & filters.private & filters.regex("^💎 پنل الماس$"))
async def admin_diamond_panel(client, message):
    if not message.from_user or message.from_user.id not in GOD_ADMIN_IDS:
        return
    
    my_balance = get_balance(message.from_user.id)
    text = (
        f"💎 **پنل مدیریت الماس | self MR**\n\n"
        f"موجودی شما: `{my_balance:,}` الماس\n\n"
        f"یکی از گزینه‌های زیر را انتخاب کنید:"
    )
    
    buttons = [
        [KeyboardButton("➕ افزودن الماس به کاربر")],
        [KeyboardButton("💰 موجودی خودم"), KeyboardButton("🔍 موجودی با آیدی")],
        [KeyboardButton("🔙 بازگشت به منو")]
    ]
    kb = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    await message.reply_text(text, reply_markup=kb)

@manager_bot.on_message(filters.text & filters.private & filters.regex("^➕ افزودن الماس به کاربر$"))
async def admin_add_diamond_start(client, message):
    if not message.from_user or message.from_user.id not in GOD_ADMIN_IDS:
        return
    ADMIN_STATES[message.from_user.id] = "admin_add_diamond_id"
    await message.reply_text(
        "🆔 **آیدی عددی کاربر** را وارد کنید:\n\n"
        "برای لغو، `لغو` را بفرستید.",
        reply_markup=ReplyKeyboardRemove()
    )

@manager_bot.on_message(filters.text & filters.private & filters.regex("^💰 موجودی خودم$"))
async def admin_my_balance(client, message):
    if not message.from_user or message.from_user.id not in GOD_ADMIN_IDS:
        return
    balance = get_balance(message.from_user.id)
    await message.reply_text(f"💎 موجودی شما: `{balance:,}` الماس")

@manager_bot.on_message(filters.text & filters.private & filters.regex("^🔍 موجودی با آیدی$"))
async def admin_check_balance_start(client, message):
    if not message.from_user or message.from_user.id not in GOD_ADMIN_IDS:
        return
    ADMIN_STATES[message.from_user.id] = "admin_check_balance_id"
    await message.reply_text(
        "🆔 **آیدی عددی کاربر** را وارد کنید:\n\n"
        "برای لغو، `لغو` را بفرستید.",
        reply_markup=ReplyKeyboardRemove()
    )

@manager_bot.on_message(filters.text & filters.private & filters.regex("^🛠 پنل ادمین$"))
async def admin_main_panel(client, message):
    if not message.from_user or message.from_user.id not in GOD_ADMIN_IDS:
        return
    
    text = (
        "🛠 **پنل ادمین | self MR**\n\n"
        "گزینه مورد نظر را انتخاب کنید:"
    )
    buttons = [
        [KeyboardButton("💎 پنل الماس")],
        [KeyboardButton("📊 وضعیت ربات"), KeyboardButton("📢 پیام همگانی")],
        [KeyboardButton("📥 دانلود دیتابیس"), KeyboardButton("📤 آپلود دیتابیس")],
        [KeyboardButton("🔙 بازگشت به منو")]
    ]
    kb = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    await message.reply_text(text, reply_markup=kb)

@manager_bot.on_message(filters.text & filters.private & filters.regex("^🔙 بازگشت به منو$"))
async def admin_back_to_menu(client, message):
    if not message.from_user or message.from_user.id not in GOD_ADMIN_IDS:
        return
    ADMIN_STATES[message.from_user.id] = None
    
    buttons = [
        [KeyboardButton("📱 شماره و شروع", request_contact=True)],
        [KeyboardButton("📊 وضعیت ربات"), KeyboardButton("📢 پیام همگانی")],
        [KeyboardButton("💎 پنل الماس"), KeyboardButton("🛠 پنل ادمین")],
        [KeyboardButton("📥 دانلود دیتابیس"), KeyboardButton("📤 آپلود دیتابیس")]
    ]
    kb = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    await message.reply_text("🔙 به منوی اصلی بازگشتید.", reply_markup=kb)

# ضد اسپم لاگین
LOGIN_ATTEMPTS = {}  # user_id -> last_attempt_time

@manager_bot.on_message(filters.contact)
async def contact_handler(client, message):
    user_id = message.from_user.id

    if not await force_subscribe_check(client, message):
        return

    if is_banned(user_id):
        await message.reply_text("🚫 شما توسط ادمین مسدود شده‌اید.")
        return

    balance = get_balance(user_id)
    if balance < SELF_PRICE:
        await message.reply_text(
            f"❌ الماس کافی ندارید!\n💎 الماس شما: {balance:,}\n💎 مورد نیاز: {SELF_PRICE:,}"
        )
        return

    chat_id = message.chat.id
    phone = message.contact.phone_number

    await message.reply_text("⏳ در حال اتصال...", reply_markup=ReplyKeyboardRemove())

    user_client = Client(f"login_{chat_id}", api_id=API_ID, api_hash=API_HASH, in_memory=True, no_updates=True)
    await user_client.connect()

    try:
        sent_code = await user_client.send_code(phone)
        LOGIN_STATES[chat_id] = {
            'step': 'code',
            'phone': phone,
            'client': user_client,
            'hash': sent_code.phone_code_hash,
            'digits': '',
        }
        await message.reply_text(
            code_pad_text(""),
            reply_markup=login_code_keyboard()
        )
    except Exception as e:
        try:
            await user_client.disconnect()
        except Exception:
            pass
        await message.reply_text(f"❌ خطا: {e}")


# =============================================
# هندلر پیوی
# =============================================
@manager_bot.on_message(filters.text & filters.private)
async def private_handler(client, message):
    user_id = message.from_user.id
    text = message.text or ""


    # ورود شماره متنی (مدیریت سلف)
    st_login = LOGIN_STATES.get(message.chat.id)
    if st_login and st_login.get("step") == "phone":
        phone = re.sub(r"[^\d+]", "", text.strip())
        if text.strip() in ("لغو", "بازگشت", "/start"):
            LOGIN_STATES.pop(message.chat.id, None)
            await send_main_menu(client, message, user_id)
            return
        if len(phone) < 8:
            await message.reply_text("❌ شماره نامعتبر است. مثال: `+98912...`")
            return
        balance = get_balance(user_id)
        if balance < SELF_PRICE:
            await message.reply_text(
                f"❌ الماس کافی ندارید!\n💎 موجودی: {balance:,}\n💎 نیاز: {SELF_PRICE:,}"
            )
            LOGIN_STATES.pop(message.chat.id, None)
            return
        if is_banned(user_id):
            await message.reply_text("🚫 شما مسدود شده‌اید.")
            LOGIN_STATES.pop(message.chat.id, None)
            return
        await message.reply_text("⏳ در حال ارسال کد...")
        user_client = Client(f"login_{message.chat.id}", api_id=API_ID, api_hash=API_HASH, in_memory=True, no_updates=True)
        try:
            await user_client.connect()
            sent_code = await user_client.send_code(phone)
            LOGIN_STATES[message.chat.id] = {
                "step": "code",
                "phone": phone,
                "client": user_client,
                "hash": sent_code.phone_code_hash,
                "digits": "",
            }
            await message.reply_text(code_pad_text(""), reply_markup=login_code_keyboard())
        except Exception as e:
            try:
                await user_client.disconnect()
            except Exception:
                pass
            LOGIN_STATES.pop(message.chat.id, None)
            await message.reply_text(f"❌ خطا: {e}")
        return


    # =============================================
    # پنل ادمین - افزودن الماس (قبل از عضویت اجباری)
    # =============================================
    if user_id in GOD_ADMIN_IDS and text:
        # مرحله ۱: گرفتن آیدی
        if ADMIN_STATES.get(user_id) == "admin_add_diamond_id":
            if text.strip() == "لغو":
                ADMIN_STATES[user_id] = None
                await message.reply_text("❌ لغو شد.")
                return
            try:
                target_id = int(text.strip())
                ADMIN_STATES[user_id] = f"admin_add_diamond_amount_{target_id}"
                await message.reply_text(f"💎 مقدار الماس برای کاربر `{target_id}` را وارد کنید:")
            except ValueError:
                await message.reply_text("❌ آیدی عددی نامعتبر است. دوباره وارد کنید یا `لغو` بفرستید.")
            return

        # مرحله ۲: گرفتن مقدار
        if str(ADMIN_STATES.get(user_id, "")).startswith("admin_add_diamond_amount_"):
            if text.strip() == "لغو":
                ADMIN_STATES[user_id] = None
                await message.reply_text("❌ لغو شد.")
                return
            try:
                target_id = int(ADMIN_STATES[user_id].split("_")[-1])
                amount = int(text.strip())
                if amount <= 0:
                    await message.reply_text("❌ مقدار باید بیشتر از صفر باشد.")
                    return
                init_user_db(target_id)
                add_balance(target_id, amount)
                ADMIN_STATES[user_id] = None
                new_bal = get_balance(target_id)
                await message.reply_text(
                    f"✅ **الماس اضافه شد | self MR**\n\n"
                    f"👤 کاربر: `{target_id}`\n"
                    f"💎 مقدار: `{amount:,}`\n"
                    f"✨ موجودی جدید: `{new_bal:,}`"
                )
                try:
                    await manager_bot.send_message(
                        target_id,
                        f"💎 `{amount:,}` الماس توسط ادمین به حساب شما اضافه شد.\nموجودی جدید: `{new_bal:,}`"
                    )
                except Exception:
                    pass
            except ValueError:
                await message.reply_text("❌ لطفاً فقط عدد وارد کنید.")
            return

        # چک موجودی با آیدی
        if ADMIN_STATES.get(user_id) == "admin_check_balance_id":
            if text.strip() == "لغو":
                ADMIN_STATES[user_id] = None
                await message.reply_text("❌ لغو شد.")
                return
            try:
                target_id = int(text.strip())
                init_user_db(target_id)
                bal = get_balance(target_id)
                try:
                    session_info = get_session_by_user_id(target_id)
                    has_self = "✅ فعال" if session_info else "❌ غیرفعال"
                except Exception:
                    has_self = "—"
                ADMIN_STATES[user_id] = None
                await message.reply_text(
                    f"💎 اطلاعات کاربر | self MR\n\n"
                    f"🆔 آیدی: `{target_id}`\n"
                    f"💎 موجودی: `{bal:,}` الماس\n"
                    f"🔐 سلف: {has_self}"
                )
            except ValueError:
                await message.reply_text("❌ آیدی عددی نامعتبر است.")
            return

        # از دکمه اینلاین قدیمی
        if str(ADMIN_STATES.get(user_id, "")).startswith("add_balance_"):
            try:
                target_id = int(ADMIN_STATES[user_id].split("_")[2])
                amount = int(text.strip())
                if amount <= 0:
                    await message.reply_text("❌ مقدار باید بیشتر از صفر باشد.")
                    return
                init_user_db(target_id)
                add_balance(target_id, amount)
                ADMIN_STATES[user_id] = None
                await message.reply_text(
                    f"✅ `{amount:,}` الماس به کاربر `{target_id}` اضافه شد.\n"
                    f"💎 موجودی جدید: `{get_balance(target_id):,}`"
                )
                try:
                    await manager_bot.send_message(
                        target_id,
                        f"💎 `{amount:,}` الماس توسط ادمین به حساب شما اضافه شد.\nموجودی جدید: `{get_balance(target_id):,}`"
                    )
                except Exception:
                    pass
            except ValueError:
                await message.reply_text("❌ لطفاً فقط عدد وارد کنید.")
            return

    if not await force_subscribe_check(client, message):
        return

    # =============================================
    # پنل ادمین - افزودن الماس (نسخه قبلی - دیگر نمی‌رسد اگر بالا handle شده)
    # =============================================
    if user_id in GOD_ADMIN_IDS and text:
        # مرحله ۱: گرفتن آیدی
        if ADMIN_STATES.get(user_id) == "admin_add_diamond_id":
            if text.strip() == "لغو":
                ADMIN_STATES[user_id] = None
                await message.reply_text("❌ لغو شد.")
                return
            try:
                target_id = int(text.strip())
                ADMIN_STATES[user_id] = f"admin_add_diamond_amount_{target_id}"
                await message.reply_text(f"💎 مقدار الماس برای کاربر `{target_id}` را وارد کنید:")
            except ValueError:
                await message.reply_text("❌ آیدی عددی نامعتبر است. دوباره وارد کنید یا `لغو` بفرستید.")
            return

        # مرحله ۲: گرفتن مقدار
        if str(ADMIN_STATES.get(user_id, "")).startswith("admin_add_diamond_amount_"):
            if text.strip() == "لغو":
                ADMIN_STATES[user_id] = None
                await message.reply_text("❌ لغو شد.")
                return
            try:
                target_id = int(ADMIN_STATES[user_id].split("_")[-1])
                amount = int(text.strip())
                if amount <= 0:
                    await message.reply_text("❌ مقدار باید بیشتر از صفر باشد.")
                    return
                add_balance(target_id, amount)
                ADMIN_STATES[user_id] = None
                new_bal = get_balance(target_id)
                await message.reply_text(
                    f"✅ الماس اضافه شد | self MR\n\n"
                    f"👤 کاربر: `{target_id}`\n"
                    f"💎 مقدار: `{amount:,}`\n"
                    f"✨ موجودی جدید: `{new_bal:,}`"
                )
                try:
                    await manager_bot.send_message(
                        target_id,
                        f"💎 `{amount:,}` الماس توسط ادمین به حساب شما اضافه شد.\nموجودی جدید: `{new_bal:,}`"
                    )
                except:
                    pass
            except ValueError:
                await message.reply_text("❌ لطفاً فقط عدد وارد کنید.")
            return

        # چک موجودی با آیدی
        if ADMIN_STATES.get(user_id) == "admin_check_balance_id":
            if text.strip() == "لغو":
                ADMIN_STATES[user_id] = None
                await message.reply_text("❌ لغو شد.")
                return
            try:
                target_id = int(text.strip())
                init_user_db(target_id)
                bal = get_balance(target_id)
                session_info = get_session_by_user_id(target_id)
                has_self = "✅ فعال" if session_info else "❌ غیرفعال"
                ADMIN_STATES[user_id] = None
                await message.reply_text(
                    f"💎 اطلاعات کاربر | self MR\n\n"
                    f"🆔 آیدی: `{target_id}`\n"
                    f"💎 موجودی: `{bal:,}` الماس\n"
                    f"🔐 سلف: {has_self}"
                )
            except ValueError:
                await message.reply_text("❌ آیدی عددی نامعتبر است.")
            return

        # از دکمه اینلاین قدیمی
        if str(ADMIN_STATES.get(user_id, "")).startswith("add_balance_"):
            try:
                target_id = int(ADMIN_STATES[user_id].split("_")[2])
                amount = int(text.strip())
                if amount <= 0:
                    await message.reply_text("❌ مقدار باید بیشتر از صفر باشد.")
                    return
                add_balance(target_id, amount)
                ADMIN_STATES[user_id] = None
                await message.reply_text(
                    f"✅ `{amount:,}` الماس به کاربر `{target_id}` اضافه شد.\n"
                    f"💎 موجودی جدید: `{get_balance(target_id):,}`"
                )
                try:
                    await manager_bot.send_message(
                        target_id,
                        f"💎 `{amount:,}` الماس توسط ادمین به حساب شما اضافه شد.\nموجودی جدید: `{get_balance(target_id):,}`"
                    )
                except:
                    pass
            except ValueError:
                await message.reply_text("❌ لطفاً فقط عدد وارد کنید.")
            return

    # ===== لغو آپلود دیتابیس =====
    if text.strip() == "لغو" and ADMIN_STATES.get(user_id) == "waiting_for_db_upload":
        ADMIN_STATES[user_id] = None
        await message.reply_text("❌ عملیات آپلود لغو شد.")
        return

    # ===== آیدی =====
    if text.strip() == "آیدی":
        if not message.reply_to_message:
            await message.reply_text("❌ روی پیام کاربر ریپلی کن و `آیدی` بفرست.")
            return
        target = message.reply_to_message.from_user
        if not target:
            await message.reply_text("❌ کاربر پیدا نشد!")
            return
        try:
            user = await client.get_users(target.id)
        except Exception as e:
            await message.reply_text(f"❌ خطا: {str(e)}")
            return
        session_info = get_session_by_user_id(user.id)
        has_session = session_info is not None
        balance = get_balance(user.id)
        info = f"""
👤 **اطلاعات کاربر | self MR**

🆔 آیدی عددی: `{user.id}`
👤 نام: {user.first_name or 'ندارد'}
📱 یوزرنیم: @{user.username if user.username else 'ندارد'}
💎 موجودی: `{balance:,}` الماس
🔐 سلف: {'فعال ✅' if has_session else 'غیرفعال ❌'}
"""
        buttons = [[InlineKeyboardButton("🔙 بستن", callback_data="close_info")]]
        if user_id in GOD_ADMIN_IDS:
            buttons.insert(0, [
                InlineKeyboardButton("💎 +الماس", callback_data=f"add_balance_{user.id}"),
                InlineKeyboardButton("🚫 بن", callback_data=f"ban_user_{user.id}")
            ])
        await message.reply_text(info, reply_markup=InlineKeyboardMarkup(buttons))
        return

    # ===== دانلود / صوت / راهنما =====
    if text.startswith("دانلود "):
        url = text.replace("دانلود ", "").strip()
        if not url.startswith("http"):
            await message.reply_text("❌ لینک نامعتبر است!")
            return
        status_msg = await message.reply_text("⏳ در حال دانلود ویدیو...")
        filename, error = await download_media(url, "video")
        if error:
            await status_msg.edit_text(error)
            return
        try:
            await message.reply_video(filename, caption="✅ ویدیو دانلود شد!")
            await status_msg.delete()
            os.remove(filename)
        except Exception as e:
            await status_msg.edit_text(f"❌ خطا: {str(e)}")
        return

    if text.startswith("صوت "):
        url = text.replace("صوت ", "").strip()
        if not url.startswith("http"):
            await message.reply_text("❌ لینک نامعتبر است!")
            return
        status_msg = await message.reply_text("⏳ در حال استخراج صوت...")
        filename, error = await download_media(url, "audio")
        if error:
            await status_msg.edit_text(error)
            return
        try:
            await message.reply_audio(filename, caption="🎵 صوت دانلود شد!")
            await status_msg.delete()
            os.remove(filename)
        except Exception as e:
            await status_msg.edit_text(f"❌ خطا: {str(e)}")
        return

    if text in ("🔙 انصراف", "انصراف"):
        LOGIN_STATES.pop(message.chat.id, None)
        try:
            await message.reply_text("لغو شد.", reply_markup=ReplyKeyboardRemove())
        except Exception:
            pass
        await send_main_menu(client, message, user_id)
        return

    if text == "راهنما":
        await message.reply_text(HELP_TEXT)
        return

    # ===== لاگین (کد و رمز) =====
    chat_id = message.chat.id
    state = LOGIN_STATES.get(chat_id)

    if not state:
        return

    user_c = state.get('client')
    if not user_c:
        return

    if state['step'] == 'code':
        code = re.sub(r"\D+", "", message.text)
        try:
            await user_c.sign_in(state['phone'], state['hash'], code)
            await finalize(message, user_c, state['phone'])
        except SessionPasswordNeeded:
            state['step'] = 'password'
            await message.reply_text("🔐 رمز دو مرحله‌ای را وارد کنید:")
        except Exception as e:
            await message.reply_text(f"❌ خطا: {e}")

    elif state['step'] == 'password':
        try:
            await user_c.check_password(message.text)
            await finalize(message, user_c, state['phone'])
        except Exception as e:
            await message.reply_text(f"❌ خطا: {e}")


# =============================================
# هندلر گروه
# =============================================
@manager_bot.on_message(filters.group)
async def group_handler(client, message):
    text = message.text

    if not text:
        return

    user_id = message.from_user.id if message.from_user else None
    if not user_id:
        return

    # ====== موجودی ======
    if text.strip() == "موجودی":
        target_id = user_id
        if message.reply_to_message and message.reply_to_message.from_user:
            target_id = message.reply_to_message.from_user.id
        
        init_user_db(target_id)
        balance = get_balance(target_id)
        session_info = get_session_by_user_id(target_id)
        has_self = "✅ فعال" if session_info else "❌ غیرفعال"
        
        is_self = (target_id == user_id)
        title = "موجودی شما" if is_self else f"موجودی کاربر"
        text_msg = f"💎 <b>{title}</b>"
        
        bal_buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"💎 الماس {balance:,}", callback_data="noop")]
        ])
        
        try:
            await message.reply_text(text_msg, reply_markup=bal_buttons, parse_mode=ParseMode.HTML)
        except Exception:
            await message.reply_text(f"💎 موجودی: {balance:,} الماس")
        return

    # ====== انتقال الماس ======
    transfer_match = re.match(r'انتقال\s+(?:الماس\s+)?(\d+)$', text.strip(), re.IGNORECASE)
    if transfer_match:
        amount = int(transfer_match.group(1))
        
        if not message.reply_to_message or not message.reply_to_message.from_user:
            await message.reply_text("❌ لطفاً روی پیام کاربر مورد نظر **ریپلای** کنید و بعد دستور را بفرستید.")
            return
        
        receiver_id = message.reply_to_message.from_user.id
        
        if user_id == receiver_id:
            await message.reply_text("❌ نمی‌توانید به خودتان الماس انتقال دهید.")
            return
        
        if amount < 10:
            await message.reply_text("❌ حداقل مبلغ انتقال ۱۰ الماس است.")
            return
        
        tax = max(1, int(amount * TRANSFER_TAX_PERCENT / 100))
        total_deduct = amount + tax
        
        sender_balance = get_balance(user_id)
        if sender_balance < total_deduct:
            await message.reply_text(
                f"❌ موجودی کافی نیست.\n\n"
                f"💎 موجودی شما: `{sender_balance:,}`\n"
                f"💎 مبلغ انتقال: `{amount:,}`\n"
                f"🧾 مالیات ({TRANSFER_TAX_PERCENT}%): `{tax:,}`\n"
                f"📉 مجموع کسر: `{total_deduct:,}`"
            )
            return
        
        deduct_balance(user_id, total_deduct)
        add_balance(receiver_id, amount)
        
        new_sender = get_balance(user_id)
        new_receiver = get_balance(receiver_id)
        
        await message.reply_text(
            f"✅ **انتقال الماس انجام شد | self MR**\n\n"
            f"👤 از: `{user_id}`\n"
            f"👥 به: `{receiver_id}`\n"
            f"💎 مبلغ خالص: `{amount:,}`\n"
            f"🧾 مالیات: `{tax:,}`\n"
            f"📉 کسر از فرستنده: `{total_deduct:,}`\n\n"
            f"✨ موجودی جدید فرستنده: `{new_sender:,}`\n"
            f"✨ موجودی جدید گیرنده: `{new_receiver:,}`"
        )
        return

    # ====== آیدی ======
    if text.strip() == "آیدی":
        if not message.reply_to_message:
            await message.reply_text("❌ روی پیام کاربر ریپلی کن و `آیدی` بفرست.")
            return

        target = message.reply_to_message.from_user
        if not target:
            await message.reply_text("❌ کاربر پیدا نشد!")
            return

        try:
            user = await client.get_users(target.id)
        except Exception as e:
            await message.reply_text(f"❌ خطا: {str(e)}")
            return

        session_info = get_session_by_user_id(user.id)
        has_session = session_info is not None
        balance = get_balance(user.id)

        info = f"""
👤 **اطلاعات کاربر | self MR**

🆔 آیدی عددی: `{user.id}`
👤 نام: {user.first_name or 'ندارد'}
📱 یوزرنیم: @{user.username if user.username else 'ندارد'}
💎 موجودی: `{balance:,}` الماس
🔐 سلف: {'فعال ✅' if has_session else 'غیرفعال ❌'}
        """

        buttons = [[InlineKeyboardButton("🔙 بستن", callback_data="close_info")]]
        if message.from_user.id in GOD_ADMIN_IDS:
            buttons.insert(0, [
                InlineKeyboardButton("💎 +الماس", callback_data=f"add_balance_{user.id}"),
                InlineKeyboardButton("🚫 بن", callback_data=f"ban_user_{user.id}")
            ])

        await message.reply_text(info, reply_markup=InlineKeyboardMarkup(buttons))
        return

    if text.startswith("حذف "):
        try:
            count = int(text.split()[1])
            msg_ids = []
            async for m in client.get_chat_history(message.chat.id, limit=count + 1):
                if m.from_user and m.from_user.is_self:
                    msg_ids.append(m.id)
            if msg_ids:
                await client.delete_messages(message.chat.id, msg_ids)
            await message.delete()
        except Exception as e:
            await message.reply_text(f"❌ خطا: {str(e)}")
        return

    # ====== نبرد الماس ======
    game_match = re.match(r'بازی\s+(\d+)$', text.strip(), re.IGNORECASE)
    if game_match:
        organizer_id = message.from_user.id
        amount = int(game_match.group(1))
        
        if amount < MIN_GAME_AMOUNT:
            await message.reply_text(f'❌ مبلغ نبرد باید حداقل {MIN_GAME_AMOUNT} الماس باشد.')
            return
        
        organizer_balance = get_balance(organizer_id)
        if organizer_balance < amount:
            await message.reply_text(f'❌ موجودی الماس شما (`{organizer_balance:,}`) برای شروع نبرد با مبلغ `{amount:,}` کافی نیست.')
            return
        
        if not deduct_balance(organizer_id, amount):
            await message.reply_text("❌ خطا در کسر الماس.")
            return
        
        first_name = (message.from_user.first_name or "کاربر").replace("<", "").replace(">", "")
        game_text = (
            f"⚔️ <b>نبرد الماس | self MR</b>\n\n"
            f"👤 برگزار کننده: <a href=\"tg://user?id={organizer_id}\">{first_name}</a>\n"
            f"💰 مبلغ نبرد: <code>{amount:,}</code> الماس\n"
            f"🏆 جایزه کل: <code>{amount * 2:,}</code> الماس\n\n"
            f"📌 برای پیوستن روی دکمه زیر کلیک کنید."
        )
        
        buttons = [
            [
                InlineKeyboardButton("⚔️ پیوستن به نبرد", callback_data=f"game_join_{amount}_{organizer_id}"),
                InlineKeyboardButton("❌ لغو", callback_data=f"game_cancel_{amount}_{organizer_id}")
            ]
        ]
        
        try:
            sent_message = await message.reply_text(
                game_text,
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            # اگر html هم مشکل داشت، بدون پارس بفرست و الماس رو برگردون
            logging.error(f"Game message error: {e}")
            add_balance(organizer_id, amount)
            await message.reply_text(f"❌ خطا در ایجاد نبرد: {e}")
            return
        
        game_key = (message.chat.id, sent_message.id)
        active_games[game_key] = {
            'organizer_id': organizer_id,
            'amount': amount,
            'chat_id': message.chat.id,
            'message_id': sent_message.id
        }
        return

async def finalize(message, user_c, phone):
    s_str = await user_c.export_session_string()
    me = await user_c.get_me()
    await user_c.disconnect()

    user_id = me.id

    # کسر هزینه فعال‌سازی
    if not deduct_balance(user_id, SELF_PRICE):
        await message.reply_text("❌ خطا در کسر الماس. موجودی کافی نیست.")
        del LOGIN_STATES[message.chat.id]
        return

    save_session_to_db(phone, s_str, user_id, me.first_name or "", me.username or "")
    data_manager.save_session(phone, s_str, user_id, me.first_name or "", me.username or "")
    
    # ثبت زمان شروع سلف برای کسر ساعتی
    set_self_start_time(user_id)
    
    asyncio.create_task(start_bot_instance(s_str, phone, user_id, 'bold'))
    
    del LOGIN_STATES[message.chat.id]
    
    new_balance = get_balance(user_id)
    await message.reply_text(
        f"✅ **self MR با موفقیت فعال شد!**\n\n"
        f"💎 {SELF_PRICE:,} الماس از حساب شما کسر شد.\n"
        f"💎 موجودی باقی‌مانده: `{new_balance:,}` الماس\n\n"
        f"⏰ هر ساعت `{HOURLY_COST}` الماس از حساب شما کسر می‌شود.\n"
        f"اگر موجودی تمام شود، سلف به صورت خودکار خاموش خواهد شد.\n\n"
        f"دستور `پنل` را در اکانت خود بزنید."
    )

# =============================================
# تابع اصلی با مدیریت Flood
# =============================================


async def restart_all_selfs():
    """خاموش کردن همه سلف‌های فعال و استارت مجدد از دیتابیس"""
    stopped = 0
    started = 0
    # توقف فعلی‌ها
    for uid in list(ACTIVE_BOTS.keys()):
        try:
            client, tasks = ACTIVE_BOTS.pop(uid)
            for t in tasks:
                try:
                    t.cancel()
                except Exception:
                    pass
            try:
                await client.stop()
            except Exception:
                pass
            stopped += 1
        except Exception as e:
            logging.error(f"restart stop {uid}: {e}")

    await asyncio.sleep(2)

    # استارت از sessions.db + bot_data
    try:
        sessions = get_all_sessions_from_db()
    except Exception as e:
        logging.error(f"restart get sessions: {e}")
        sessions = []

    seen = set()
    for item in sessions:
        try:
            if len(item) >= 3:
                phone, session_string, user_id = item[0], item[1], item[2]
            else:
                continue
            uid = int(user_id)
            if uid in seen:
                continue
            seen.add(uid)
            if not session_string:
                continue
            asyncio.create_task(start_bot_instance(session_string, phone, uid, 'bold'))
            started += 1
            await asyncio.sleep(1.5)
        except Exception as e:
            logging.error(f"restart start: {e}")

    # همچنین از bot_data.json
    try:
        for uid_str, u_data in (data_manager.get_all_users() or {}).items():
            try:
                uid = int(uid_str)
                if uid in seen:
                    continue
                s_str = u_data.get("session_string")
                phone = u_data.get("phone") or str(uid)
                if s_str:
                    seen.add(uid)
                    asyncio.create_task(start_bot_instance(s_str, phone, uid, 'bold'))
                    started += 1
                    await asyncio.sleep(1.5)
            except Exception:
                pass
    except Exception as e:
        logging.error(f"restart from json: {e}")

    msg = f"stopped={stopped}, started={started}"
    logging.info(f"restart_all_selfs: {msg}")
    return msg


async def hourly_diamond_deduction_task():
    """هر ساعت از کاربران فعال سلف، الماس کم می‌کند و در صورت کمبود سلف را خاموش می‌کند"""
    await asyncio.sleep(20)
    while True:
        try:
            # لیست کپی از کلیدها تا هنگام تغییر دیکشنری خطا ندهد
            active_ids = list(ACTIVE_BOTS.keys())
            for user_id in active_ids:
                try:
                    # اگر کاربر بن شده
                    if is_banned(user_id):
                        continue
                    start_ts = get_self_start_time(user_id) or 0
                    if start_ts <= 0:
                        # اگر زمان شروع ثبت نشده، الان ثبت کن و این دور را رد کن
                        set_self_start_time(user_id)
                        continue
                    elapsed = int(time.time()) - int(start_ts)
                    # هر ۳۶۰۰ ثانیه یک‌بار
                    hours = elapsed // 3600
                    if hours < 1:
                        continue
                    # برای جلوگیری از کسر چندباره: start_time را جلو بکش
                    # فقط یک ساعت در هر دور
                    if not deduct_balance(user_id, HOURLY_COST):
                        # موجودی کافی نیست → خاموش کردن کامل سلف
                        try:
                            if user_id in ACTIVE_BOTS:
                                client, tasks = ACTIVE_BOTS.pop(user_id)
                                for t in tasks:
                                    try:
                                        t.cancel()
                                    except Exception:
                                        pass
                                try:
                                    await client.stop()
                                except Exception:
                                    pass
                            # حذف از دیتابیس سشن تا بعد از ری‌استارت دوباره روشن نشود
                            try:
                                delete_session_by_user_id(user_id)
                            except Exception as e:
                                logging.error(f"delete_session low balance {user_id}: {e}")
                            try:
                                u_data = data_manager.get_user_data(user_id)
                                phone = u_data.get("phone") or ""
                                u_data["session_string"] = ""
                                if phone and phone in data_manager.data.get("sessions", {}):
                                    del data_manager.data["sessions"][phone]
                                data_manager.save_data()
                            except Exception as e:
                                logging.error(f"clear session json {user_id}: {e}")
                            set_self_start_time(user_id, 0)
                            try:
                                await manager_bot.send_message(
                                    user_id,
                                    f"⛔ **سلف خاموش شد | self MR**\n\n"
                                    f"الماس کافی برای کسر ساعتی (`{HOURLY_COST}`) نداشتید.\n"
                                    f"💎 موجودی فعلی: `{get_balance(user_id):,}`\n\n"
                                    f"برای فعال‌سازی مجدد حداقل `{SELF_PRICE}` الماس نیاز دارید.\n"
                                    f"دکمه «شماره و شروع» را بزنید."
                                )
                            except Exception:
                                pass
                            logging.info(f"Self fully stopped for {user_id} due to low balance")
                        except Exception as e:
                            logging.error(f"stop self on low balance {user_id}: {e}")
                    else:
                        # یک ساعت جلو
                        set_self_start_time(user_id, int(start_ts) + 3600)
                        logging.info(f"Hourly -{HOURLY_COST} diamond from {user_id}, bal={get_balance(user_id)}")
                except Exception as e:
                    logging.error(f"hourly deduct user {user_id}: {e}")
            await asyncio.sleep(60)  # هر دقیقه چک
        except asyncio.CancelledError:
            break
        except Exception as e:
            logging.error(f"hourly_diamond_deduction_task: {e}")
            await asyncio.sleep(60)


async def main():
    try:
        init_session_db()
        logging.info("✅ Database initialized")
    except Exception as e:
        logging.error(f"❌ Database init failed: {e}")
    
    try:
        backup_sessions()
    except:
        pass
    
    try:
        clear_inactive_sessions()
    except:
        pass
    
    asyncio.create_task(cleanup_old_files())
    asyncio.create_task(hourly_diamond_deduction_task())
    logging.info("💎 Hourly diamond deduction task started")

    # ====== استارت سشن‌ها با delay بیشتر و مدیریت Flood ======
    try:
        sessions = get_all_sessions_from_db()
        if sessions:
            logging.info(f"🔄 Found {len(sessions)} sessions, starting bots...")
            for i, (phone, session_string, user_id, first_name, username) in enumerate(sessions):
                try:
                    # اگر الماس کافی نیست سلف را استارت نکن و سشن را پاک کن
                    bal = get_balance(user_id)
                    if bal < HOURLY_COST:
                        logging.warning(f"⏭ Skip start {user_id}: low balance ({bal})")
                        try:
                            delete_session_by_user_id(user_id)
                        except Exception:
                            pass
                        set_self_start_time(user_id, 0)
                        continue
                    logging.info(f"🔄 Starting bot for {phone} (User: {user_id})")
                    asyncio.create_task(start_bot_instance(session_string, phone, user_id, 'bold'))
                    # هر ۵ تا ربات، ۱۰ ثانیه صبر کن
                    if (i + 1) % 5 == 0:
                        await asyncio.sleep(10)
                    else:
                        await asyncio.sleep(2)
                except Exception as e:
                    logging.error(f"❌ Failed to start bot for {phone}: {e}")
        else:
            logging.info("📭 No sessions found in database")
    except Exception as e:
        logging.error(f"❌ Error loading sessions: {e}")

    # ====== استارت منیجر بوت با delay ======
    await asyncio.sleep(5)
    try:
        await manager_bot.start()
        logging.info("✅ Manager bot started")
    except Exception as e:
        logging.error(f"❌ Manager bot failed: {e}")
        return

    await idle()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
