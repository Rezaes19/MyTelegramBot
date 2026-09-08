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
from pyrogram.handlers import MessageHandler
from pyrogram.enums import ChatType, ChatAction, ParseMode
from pyrogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton,
    InlineQueryResultArticle, InputTextMessageContent
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

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN not found in environment variables!")

GOD_ADMIN_IDS = [6691993264]

# =============================================
# کانال‌های عضویت اجباری
# =============================================
FORCE_CHANNELS = [
    "@SELF_MR0"
]

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
REFERRAL_REWARD = 25     # پاداش زیرمجموعه
MIN_GAME_AMOUNT = 20     # حداقل مبلغ نبرد
TRANSFER_TAX_PERCENT = 10
GAME_TAX_PERCENT = 5

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

ENEMY_REPLIES = [
    "کیرم تو رحم اجاره ای و خونی مالی مادرت",
    "دو میلیون شبی پول ویلا بدم تا مادرتو تو گوشه کناراش بگام",
    "احمق مادر کونی من کس مادرت گذاشتم تو بازم داری کسشر میگی",
]

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
    """اعمال استایل متن با تگ HTML تلگرام"""
    if not text:
        return text
    import html as _html
    t = _html.escape(str(text))
    styles = {
        "bold": f"<b>{t}</b>",
        "italic": f"<i>{t}</i>",
        "underline": f"<u>{t}</u>",
        "strikethrough": f"<s>{t}</s>",
        "spoiler": f"<spoiler>{t}</spoiler>",
        "mono": f"<code>{t}</code>",
        "codeblock": f"<pre>{t}</pre>",
        "quote": f"<blockquote>{t}</blockquote>",
    }
    return styles.get(style, text)


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
        TTS_VOICE_STATUS[user_id] = settings.get("tts_voice", "زن")
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
        TTS_VOICE_STATUS[user_id] = settings.get("tts_voice", "زن")
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
    """اعمال فونت متن + ترجمه روی پیام‌های خروجی سلف"""
    try:
        try:
            user_id = client.me.id if client.me else (await client.get_me()).id
        except Exception:
            return
        if not message or not message.text:
            return
        text = message.text.strip()
        if not text:
            return
        if text.startswith(".") or text.startswith("/"):
            return
        try:
            if re.match(COMMAND_REGEX, text, re.IGNORECASE):
                return
        except Exception:
            pass
        if text in ("پنل", "panel", "راهنما", "تاس", "بولینگ", "آیدی") or text.startswith(("دانلود ", "صوت ", "ذخیره", "تکرار ")):
            return

        original_text = message.text
        modified_text = original_text
        used_html = False

        target_lang = AUTO_TRANSLATE_TARGET.get(user_id)
        if target_lang:
            try:
                translated = await translate_text(modified_text, target_lang)
                if translated and translated != modified_text:
                    modified_text = translated
            except Exception as e:
                logging.error(f"translate error: {e}")

        text_font = TEXT_FONT_STATUS.get(user_id) or TEXT_FONT_STATUS.get(str(user_id)) or "none"
        logging.info(f"font-check uid={user_id} font={text_font!r} text={original_text[:40]!r}")
        if text_font and text_font != "none" and text_font in FONT_KEYS_ORDER:
            modified_text = apply_telegram_style(modified_text, text_font)
            used_html = True

        if not used_html and modified_text == original_text:
            return

        await asyncio.sleep(0.25)
        try:
            if used_html:
                await client.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=message.id,
                    text=modified_text,
                    parse_mode=ParseMode.HTML,
                )
            else:
                await client.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=message.id,
                    text=modified_text,
                )
            logging.info(f"font-applied uid={user_id} font={text_font}")
        except Exception as e:
            logging.error(f"font edit failed uid={user_id}: {e}")
            try:
                if used_html:
                    await message.edit_text(modified_text, parse_mode=ParseMode.HTML)
                else:
                    await message.edit_text(modified_text)
            except Exception as e2:
                logging.error(f"font edit fallback failed: {e2}")
    except Exception as e:
        logging.error(f"outgoing_message_modifier error: {e}")


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
    """ذخیره قوی: متن، رسانه، و عکس/ویدیو نابودشونده (TTL)"""
    if not reply:
        return False, "❌ روی پیام ریپلای کنید."

    # ۱) تلاش فوروارد معمولی
    try:
        await reply.forward("me")
        return True, None
    except Exception as e1:
        logging.info(f"forward save failed: {e1}")

    # ۲) کپی محتوا
    try:
        await reply.copy("me")
        return True, None
    except Exception as e2:
        logging.info(f"copy save failed: {e2}")

    # ۳) دانلود و آپلود مجدد (برای TTL / view-once / محدودیت فوروارد)
    caption = reply.caption or ""
    text = reply.text or ""
    try:
        # متن خالی بدون رسانه
        if text and not reply.media:
            await client.send_message("me", f"💾 ذخیره شد | self MR\n\n{text}")
            return True, None

        if not reply.media and not text:
            await client.send_message("me", "💾 پیام بدون محتوای قابل ذخیره.")
            return True, None

        path = None
        try:
            path = await client.download_media(reply)
        except Exception as e3:
            # بعضی مدیاهای تایم‌دار فقط یک‌بار قابل خواندن‌اند
            if text or caption:
                await client.send_message("me", f"💾 ذخیره متن | self MR\n\n{text or caption}")
                return True, None
            return False, f"❌ دانلود ممکن نشد (احتمالاً منقضی شده): {e3}"

        if not path or not os.path.exists(path):
            if text or caption:
                await client.send_message("me", f"💾 ذخیره متن | self MR\n\n{text or caption}")
                return True, None
            return False, "❌ فایل دانلود نشد."

        cap = f"💾 ذخیره | self MR"
        if caption:
            cap += f"\n\n{caption}"
        # TTL info
        ttl = getattr(reply, "ttl_seconds", None) or getattr(getattr(reply, "media", None), "ttl_seconds", None)
        if ttl:
            cap += f"\n⏱ رسانه تایم‌دار بود ({ttl}s)"

        try:
            if reply.photo or (path.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))):
                await client.send_photo("me", path, caption=cap)
            elif reply.video or path.lower().endswith((".mp4", ".mov", ".mkv")):
                await client.send_video("me", path, caption=cap)
            elif reply.voice or path.lower().endswith(".ogg"):
                await client.send_voice("me", path, caption=cap)
            elif reply.video_note:
                try:
                    await client.send_video_note("me", path)
                    if caption or ttl:
                        await client.send_message("me", cap)
                except Exception:
                    await client.send_video("me", path, caption=cap)
            elif reply.audio or path.lower().endswith((".mp3", ".m4a")):
                await client.send_audio("me", path, caption=cap)
            elif reply.animation or path.lower().endswith(".gif"):
                await client.send_animation("me", path, caption=cap)
            elif reply.sticker:
                try:
                    await client.send_sticker("me", path)
                except Exception:
                    await client.send_document("me", path, caption=cap)
            else:
                await client.send_document("me", path, caption=cap)
        finally:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
        return True, None
    except Exception as e:
        return False, f"❌ ذخیره ناموفق: {e}"


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


async def reply_based_controller(client, message):
    user_id = client.me.id
    cmd = (message.text or "").strip()
    if not cmd:
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
            await client.start()
            user_id = (await client.get_me()).id
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
    client.add_handler(MessageHandler(lambda c, m: c.read_chat_history(m.chat.id) if AUTO_SEEN_STATUS.get(c.me.id) else None, filters.private & ~filters.me), group=-4)
    client.add_handler(MessageHandler(incoming_message_manager, filters.all & ~filters.me), group=-3)
    client.add_handler(MessageHandler(outgoing_message_modifier, filters.text & filters.outgoing), group=-1)
    client.add_handler(MessageHandler(help_controller, filters.me & filters.regex("^راهنما$")))
    client.add_handler(MessageHandler(panel_command_controller, filters.me & filters.regex(r"^(پنل|panel)$")))
    client.add_handler(MessageHandler(reply_based_controller, filters.me))

    enemy_filter = filters.create(lambda _, c, m: bool(m.from_user and ((m.from_user.id, m.chat.id) in ACTIVE_ENEMIES.get(c.me.id, set()) or GLOBAL_ENEMY_STATUS.get(c.me.id))))
    client.add_handler(MessageHandler(enemy_handler, enemy_filter & ~filters.me), group=1)

    client.add_handler(MessageHandler(secretary_auto_reply_handler, filters.private & ~filters.me), group=1)

    tasks = [
        asyncio.create_task(update_profile_clock(client, user_id)),
        asyncio.create_task(rotate_profile_name_task(client, user_id)),
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
    elif page in (13, 14, 15, 16, 17, 18):
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
    data = callback.data

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
        amount = int(parts[2])
        organizer_id = int(parts[3])
        joiner_id = callback.from_user.id
        
        if joiner_id == organizer_id:
            await callback.answer("❌ شما برگزار کننده هستید!", show_alert=True)
            return
        
        joiner_balance = get_balance(joiner_id)
        if joiner_balance < amount:
            await callback.answer(f"❌ موجودی شما کافی نیست! ({joiner_balance:,})", show_alert=True)
            return
        
        if not deduct_balance(joiner_id, amount):
            await callback.answer("❌ خطا در کسر الماس!", show_alert=True)
            return
        
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
        
        try:
            await client.delete_messages(callback.message.chat.id, callback.message.id)
        except:
            pass
        
        try:
            await callback.message.reply_text(result_text, reply_markup=result_buttons, parse_mode=ParseMode.HTML)
        except Exception as e:
            logging.error(f"Result message error: {e}")
            await callback.message.reply_text(
                f"🎯 نتیجه بازی\n🏆 برنده: {winner_name}\n❌ بازنده: {loser_name}\n💎 جایزه: {prize:,}"
            )
        await callback.answer("✅ نبرد به پایان رسید!")
        
        game_key = (callback.message.chat.id, callback.message.id)
        if game_key in active_games:
            del active_games[game_key]
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

        elif "set_text_font_" in data:
            # data: set_text_font_bold_USERID | set_text_font_none_USERID
            parts = data.split("_")
            try:
                target_user_id = int(parts[-1])
            except Exception:
                await callback.answer("خطا", show_alert=True)
                return
            font_name = "_".join(parts[3:-1]) if len(parts) > 4 else (parts[3] if len(parts) > 3 else "none")

            if callback.from_user.id != target_user_id:
                await callback.answer("⛔️ دسترسی غیرمجاز!", show_alert=True)
                return

            if font_name == "none":
                TEXT_FONT_STATUS[target_user_id] = "none"
            elif font_name in FONT_KEYS_ORDER:
                TEXT_FONT_STATUS[target_user_id] = font_name
            else:
                logging.warning(f"invalid text font: {font_name} data={data}")
                await callback.answer("❌ فونت نامعتبر", show_alert=True)
                return

            logging.info(f"TEXT_FONT set uid={target_user_id} -> {TEXT_FONT_STATUS[target_user_id]}")
            data_manager.update_user_data(target_user_id, {"settings": {"text_font": TEXT_FONT_STATUS[target_user_id]}})
            try:
                persist_all_user_settings(target_user_id)
            except Exception:
                pass

            try:
                await edit_panel_colored(callback, target_user_id, 2)
            except Exception:
                pass

            label = FONT_PERSIAN_NAMES.get(font_name, font_name)
            await callback.answer(f"✅ فونت متن: {label}")
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
                    await edit_panel_colored(callback, target_user_id, page)
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

@manager_bot.on_message(filters.command("start"))
async def start_login(client, message):
    user_id = message.from_user.id
    init_user_db(user_id)

    if not await force_subscribe_check(client, message):
        return

    # ====== سیستم زیرمجموعه ======
    args = message.command
    if len(args) > 1:
        try:
            referrer_id = int(args[1])
            if referrer_id != user_id:
                # چک کن قبلاً ثبت نشده باشه
                db = get_user_db(user_id)
                cursor = db.cursor()
                cursor.execute('SELECT invited_by FROM users WHERE user_id = ?', (user_id,))
                row = cursor.fetchone()
                already_invited = row and row[0] and row[0] != 0
                db.close()

                if not already_invited:
                    # ثبت زیرمجموعه
                    db = get_user_db(user_id)
                    cursor = db.cursor()
                    cursor.execute('UPDATE users SET invited_by = ? WHERE user_id = ?', (referrer_id, user_id))
                    cursor.execute('INSERT OR IGNORE INTO referrals (referrer_id, referred_id, reward_claimed) VALUES (?, ?, 0)', (referrer_id, user_id))
                    db.commit()
                    db.close()

                    # پاداش به معرف
                    add_balance(referrer_id, REFERRAL_REWARD)
                    try:
                        await manager_bot.send_message(
                            referrer_id,
                            f"🎉 **زیرمجموعه جدید | self MR**\n\n"
                            f"یک نفر با لینک شما وارد شد.\n"
                            f"💎 `{REFERRAL_REWARD}` الماس به حساب شما اضافه شد.\n"
                            f"موجودی جدید: `{get_balance(referrer_id):,}` الماس"
                        )
                    except:
                        pass
        except:
            pass

    balance = get_balance(user_id)
    bot_username = (await client.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start={user_id}"

    welcome_text = (
        f"👋 **خوش آمدید به self MR**\n\n"
        f"💎 موجودی شما: `{balance:,}` الماس\n"
        f"💰 هزینه فعال‌سازی سلف: `{SELF_PRICE}` الماس\n"
        f"⏰ کسر ساعتی: `{HOURLY_COST}` الماس\n\n"
        f"🔗 **لینک دعوت شما:**\n`{ref_link}`\n"
        f"با دعوت هر نفر `{REFERRAL_REWARD}` الماس دریافت می‌کنید.\n\n"
        f"برای فعال‌سازی سلف یکی از دکمه‌های زیر را بزنید:"
    )

    buttons = [[KeyboardButton("📱 شماره و شروع", request_contact=True)]]

    if message.from_user and message.from_user.id in GOD_ADMIN_IDS:
        buttons.append([
            KeyboardButton("📊 وضعیت ربات"),
            KeyboardButton("📢 پیام همگانی")
        ])
        buttons.append([
            KeyboardButton("💎 پنل الماس"),
            KeyboardButton("🛠 پنل ادمین")
        ])
        buttons.append([
            KeyboardButton("📥 دانلود دیتابیس"),
            KeyboardButton("📤 آپلود دیتابیس")
        ])

    kb = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=False)
    await message.reply_text(welcome_text, reply_markup=kb)

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
        LOGIN_STATES[chat_id] = {'step': 'code', 'phone': phone, 'client': user_client, 'hash': sent_code.phone_code_hash}
        await message.reply_text("✅ کد را بفرستید (مثلاً `1 1 1 1 1 با فاصله`)")
    except Exception as e:
        await user_client.disconnect()
        await message.reply_text(f"❌ خطا: {e}")


# =============================================
# هندلر پیوی
# =============================================
@manager_bot.on_message(filters.text & filters.private)
async def private_handler(client, message):
    user_id = message.from_user.id
    text = message.text or ""

    if not await force_subscribe_check(client, message):
        return

    # =============================================
    # پنل ادمین - افزودن الماس
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
                        # موجودی کافی نیست → خاموش کردن سلف
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
                            try:
                                await manager_bot.send_message(
                                    user_id,
                                    f"⛔ سلف خاموش شد | self MR\n\n"
                                    f"الماس کافی برای کسر ساعتی ({HOURLY_COST}) نداشتید.\n"
                                    f"💎 موجودی: {get_balance(user_id):,}"
                                )
                            except Exception:
                                pass
                            set_self_start_time(user_id, 0)
                            logging.info(f"Self stopped for {user_id} due to low balance")
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
