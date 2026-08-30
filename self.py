try:
    import os, random, json, pytz, asyncio, aiofiles, aiohttp, logging, re
    from telethon.sync import TelegramClient, events, types
    from telethon.sessions import StringSession
    from telethon.tl.functions.users import GetFullUserRequest
    from telethon.tl.functions.account import UpdateStatusRequest, GetAuthorizationsRequest, UpdateProfileRequest
    from telethon.tl.functions.messages import SendScreenshotNotificationRequest, SendReactionRequest
    from telethon.tl.functions.phone import CreateGroupCallRequest
    from telethon.tl.functions.photos import UploadProfilePhotoRequest, DeletePhotosRequest
    from datetime import datetime, timedelta
    from pyrogram import Client, filters
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
    import numpy as np
    import matplotlib.pyplot as plt
    from gtts import gTTS
    from googletrans import Translator
    from pytgcalls import PyTgCalls, idle
    from pytgcalls.types import MediaStream
    from google_play_scraper import search
    import psutil
    import aiocron
except ModuleNotFoundError:
    os.system('pip install --upgrade pip && pip install -U telethon && pip install psutil && pip install py-tgcalls && pip install aiohttp && pip install asyncio && pip install aiocron && pip install aiofiles && pip install pytz && pip install googletrans==4.0.0-rc1 && pip install gtts && pip install google_play_scraper && pip install numpy && pip install matplotlib && pip install pyrogram && clear')
    os.sys.exit('installed the required packages !')

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s - %(message)s')

async def get(file):
    async with aiofiles.open(file, 'r') as r:
        return json.loads(await r.read())

async def put(file, data):
    async with aiofiles.open(file, 'w') as w:
        await w.write(json.dumps(data))

def font(text):
    text = text.lower()
    return text.translate(text.maketrans('qwertyuiopasdfghjklzxcvbnm', 'ǫᴡᴇʀᴛʏᴜɪᴏᴘᴀsᴅғɢʜᴊᴋʟᴢxᴄᴠʙɴᴍ'))

async def requests(url, **kwargs):
    async with aiohttp.ClientSession() as session:
        async with session.get(url, **kwargs) as result:
            try:
                return json.loads(await result.text())
            except:
                return await result.read()

loop = asyncio.get_event_loop()

if not os.path.exists('data.json'):
    data = {
        'timename': 'off',
        'timebio': 'off',
        'timeprofile': 'off',
        'timecrash': 'off',
        'bot': 'on',
        'hashtag': 'off',
        'bold': 'off',
        'italic': 'off',
        'delete': 'off',
        'code': 'off',
        'underline': 'off',
        'reverse': 'off',
        'part': 'off',
        'mention': 'off',
        'spoiler': 'off',
        'comment': 'on',
        'text': 'first !',
        'typing': 'off',
        'game': 'off',
        'voice': 'off',
        'video': 'off',
        'sticker': 'off',
        'crash': [],
        'enemy': []
    }
    loop.run_until_complete(put('data.json', data))

if not os.path.exists('database_users'):
    os.makedirs('database_users')

# =============================================
# تنظیمات اصلی - اینجا رو ادیت کن
# =============================================
API_ID = 34996139
API_HASH = "a1f3db16cae2919cfb05e61d1e968b8d"
BOT_TOKEN = "8763155587:AAFyqwUzGx8VuQlfFWhknqfzmjyxM7zinyg"
helperbot = 'SelfRMUu_bot'

manager_bot = Client("manager_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

LOGIN_STATES = {}
ACTIVE_SELF_BOTS = {}
USER_FONT_CHOICES = {}
CLOCK_STATUS = {}
BOLD_MODE_STATUS = {}
SECRETARY_MODE_STATUS = {}
SECRETARY_CUSTOM_MESSAGES = {}
AUTO_SEEN_STATUS = {}
PV_LOCK_STATUS = {}
ANTI_LOGIN_STATUS = {}
TYPING_MODE_STATUS = {}
PLAYING_MODE_STATUS = {}
GLOBAL_ENEMY_STATUS = {}
COPY_MODE_STATUS = {}
ORIGINAL_PROFILE_DATA = {}
ENEMY_REPLY_QUEUES = {}
USERS_REPLIED_IN_SECRETARY = {}
MUTED_USERS = {}
AUTO_REACTION_TARGETS = {}
AUTO_TRANSLATE_TARGET = {}

# =============================================
# لیست پاسخ‌های دشمن
# =============================================
ENEMY_REPLIES = [
    "کیرم تو رحم اجاره ای و خونی مالی مادرت",
    "دو میلیون شبی پول ویلا بدم تا مادرتو تو گوشه کناراش بگام",
    "احمق مادر کونی من کس مادرت گذاشتم تو بازم داری کسشر میگی",
]

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

SECRETARY_REPLY_MESSAGE = "سلام! در حال حاضر آفلاین هستم. در اولین فرصت پاسخ خواهم داد."

# =============================================
# توابع کمکی
# =============================================
def stylize_time(time_str: str, style: str) -> str:
    font_map = FONT_STYLES.get(style, FONT_STYLES["stylized"])
    return ''.join(font_map.get(char, char) for char in time_str)

async def translate_text(text: str, target_lang: str) -> str:
    if not text:
        return ""
    encoded_text = re.quote(text)
    url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={target_lang}&dt=t&q={encoded_text}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data[0][0][0]
    except:
        pass
    return text

async def makeClock(h, m, s, read, write):
    try:
        image = plt.imread(read)
        fig = plt.figure(figsize=(4, 4), dpi=300, facecolor=[0.2, 0.2, 0.2])
        ax_image = fig.add_axes([0, 0, 1, 1])
        ax_image.axis('off')
        ax_image.imshow(image)
        axc = fig.add_axes([0.062, 0.062, 0.88, 0.88], projection='polar')
        axc.cla()
        seconds = np.multiply(np.ones(5), s * 2 * np.pi / 60)
        minutes = np.multiply(np.ones(5), m * 2 * np.pi / 60) + (seconds / 60)
        hours = np.multiply(np.ones(5), h * 2 * np.pi / 12) + (minutes / 12)
        axc.axis('off')
        axc.set_theta_zero_location('N')
        axc.set_theta_direction(-1)
        axc.plot(hours, np.linspace(0.00, 0.70, 5), c='c', linewidth=2.0)
        axc.plot(minutes, np.linspace(0.00, 0.85, 5), c='b', linewidth=1.5)
        axc.plot(seconds, np.linspace(0.00, 1.00, 5), c='r', linewidth=1.0)
        axc.plot(minutes, np.linspace(0.73, 0.83, 5), c='w', linewidth=1.0)
        axc.plot(hours, np.linspace(0.60, 0.68, 5), c='w', linewidth=1.5)
        axc.plot(seconds, np.linspace(0.80, 0.98, 5), c='w', linewidth=0.5)
        axc.set_rmax(1)
        plt.savefig(write)
        return write
    except:
        return None

async def perform_clock_update_now(client, user_id):
    try:
        if CLOCK_STATUS.get(user_id, True) and not COPY_MODE_STATUS.get(user_id, False):
            current_font_style = USER_FONT_CHOICES.get(user_id, 'stylized')
            me = await client.get_me()
            current_name = me.first_name
            base_name = re.sub(r'(?:\s*' + CLOCK_CHARS_REGEX_CLASS + r'+)+$', '', current_name).strip()
            tehran_time = datetime.now(pytz.timezone('Asia/Tehran'))
            current_time_str = tehran_time.strftime("%H:%M")
            stylized_time = stylize_time(current_time_str, current_font_style)
            new_name = f"{base_name} {stylized_time}"
            if new_name != current_name:
                await client.update_profile(first_name=new_name)
    except Exception as e:
        logging.error(f"Clock update failed: {e}")

async def update_profile_clock(client: Client, user_id: int):
    while user_id in ACTIVE_SELF_BOTS:
        try:
            if CLOCK_STATUS.get(user_id, True) and not COPY_MODE_STATUS.get(user_id, False):
                await perform_clock_update_now(client, user_id)
            await asyncio.sleep(60 - datetime.now(pytz.timezone('Asia/Tehran')).second + 0.1)
        except Exception:
            await asyncio.sleep(60)

async def anti_login_task(client: Client, user_id: int):
    while user_id in ACTIVE_SELF_BOTS:
        try:
            if ANTI_LOGIN_STATUS.get(user_id, False):
                auths = await client.invoke(GetAuthorizationsRequest())
                current_hash = next((a.hash for a in auths.authorizations if a.current), None)
                if current_hash:
                    for auth in auths.authorizations:
                        if auth.hash != current_hash:
                            await client.invoke(UpdateStatusRequest(offline=False))
            await asyncio.sleep(60)
        except Exception:
            await asyncio.sleep(120)

# =============================================
# تابع اصلی سلف‌بات
# =============================================
async def start_self_bot(session_string, user_id, phone):
    client = Client(f"self_{user_id}", api_id=API_ID, api_hash=API_HASH, session_string=session_string)
    
    try:
        await client.start()
        me = await client.get_me()
        user_id = me.id
        logging.info(f"✅ سلف‌بات برای کاربر {user_id} فعال شد!")
        ACTIVE_SELF_BOTS[user_id] = client

        # ====== هندلر پیام‌های خروجی (مودهای ادیت متن) ======
        @client.on_message(filters.me & filters.text)
        async def outgoing_modifier(client, message):
            js = await get('data.json')
            text = message.text
            if not text or text.startswith('/') or text.startswith('.'):
                return
            if js.get('hashtag') == 'on':
                try:
                    await message.edit_text(f"#{text.replace(' ', '_')}")
                    return
                except:
                    pass
            if js.get('bold') == 'on':
                try:
                    if not text.startswith(('**', '__', '~~', '`')):
                        await message.edit_text(f"**{text}**")
                    return
                except:
                    pass
            if js.get('italic') == 'on':
                try:
                    await message.edit_text(f"<i>{text}</i>")
                    return
                except:
                    pass
            if js.get('delete') == 'on':
                try:
                    await message.edit_text(f"~~{text}~~")
                    return
                except:
                    pass
            if js.get('code') == 'on':
                try:
                    await message.edit_text(f"`{text}`")
                    return
                except:
                    pass
            if js.get('underline') == 'on':
                try:
                    await message.edit_text(f"<u>{text}</u>")
                    return
                except:
                    pass
            if js.get('reverse') == 'on':
                try:
                    await message.edit_text(text[::-1])
                    return
                except:
                    pass
            if js.get('part') == 'on' and len(text) > 1:
                try:
                    new = ''
                    for char in text:
                        new += char
                        if char != ' ':
                            await message.edit_text(new)
                            await asyncio.sleep(0.3)
                    return
                except:
                    pass
            if js.get('mention') == 'on' and message.reply_to_message:
                try:
                    target = message.reply_to_message.from_user
                    if target:
                        await message.edit_text(f'<a href="tg://openmessage?user_id={target.id}">{text}</a>')
                    return
                except:
                    pass

        # ====== هندلر پیام‌های دریافتی ======
        @client.on_message(filters.incoming & ~filters.me)
        async def incoming_handler(client, message):
            js = await get('data.json')
            from_id = message.from_user.id if message.from_user else None
            if from_id in js.get('enemy', []):
                try:
                    if message.is_private:
                        await message.delete()
                    else:
                        if from_id not in ENEMY_REPLY_QUEUES or not ENEMY_REPLY_QUEUES[from_id]:
                            ENEMY_REPLY_QUEUES[from_id] = random.sample(ENEMY_REPLIES, len(ENEMY_REPLIES))
                        reply_text = ENEMY_REPLY_QUEUES[from_id].pop(0)
                        await message.reply_text(reply_text)
                except:
                    pass
            if from_id in js.get('crash', []):
                try:
                    await client.send_reaction(message.chat.id, message.id, "❤️")
                except:
                    pass
            if message.is_private and js.get('comment') == 'on':
                try:
                    replied = USERS_REPLIED_IN_SECRETARY.get(user_id, set())
                    if from_id not in replied:
                        custom_msg = SECRETARY_CUSTOM_MESSAGES.get(user_id)
                        reply_msg = custom_msg if custom_msg else SECRETARY_REPLY_MESSAGE
                        await message.reply_text(reply_msg)
                        replied.add(from_id)
                        USERS_REPLIED_IN_SECRETARY[user_id] = replied
                except:
                    pass

        # ====== دستورات سلف ======
        @client.on_message(filters.text & filters.regex(r'^(پنل|panel)$') & filters.me)
        async def self_panel(client, message):
            js = await get('data.json')
            font_style = USER_FONT_CHOICES.get(user_id, 'stylized')
            preview = stylize_time("12:34", font_style)
            panel_text = f"""
⚡️ **پنل مدیریت سلف‌بات**

🕐 ساعت در نام: {'✅' if js.get('timename') == 'on' else '❌'}
🕐 ساعت در بیو: {'✅' if js.get('timebio') == 'on' else '❌'}
🕐 ساعت در پروفایل: {'✅' if js.get('timeprofile') == 'on' else '❌'}
🕐 کراش تایم: {'✅' if js.get('timecrash') == 'on' else '❌'}
🎨 فونت فعلی: `{font_style}` ⏰ {preview}

🔤 بولد: {'✅' if js.get('bold') == 'on' else '❌'}
🔠 هشتگ: {'✅' if js.get('hashtag') == 'on' else '❌'}
📝 ایتالیک: {'✅' if js.get('italic') == 'on' else '❌'}
📝 خط خورده: {'✅' if js.get('delete') == 'on' else '❌'}
📝 کد: {'✅' if js.get('code') == 'on' else '❌'}
📝 زیرخط: {'✅' if js.get('underline') == 'on' else '❌'}
🔄 برعکس: {'✅' if js.get('reverse') == 'on' else '❌'}
📝 پارت: {'✅' if js.get('part') == 'on' else '❌'}
📝 منشن: {'✅' if js.get('mention') == 'on' else '❌'}

📝 منشی: {'✅' if js.get('comment') == 'on' else '❌'}
📝 متن منشی: `{js.get('text', '')}`

👥 دشمنان: {len(js.get('enemy', []))}
❤️ کراش‌ها: {len(js.get('crash', []))}

⌨️ تایپ: {'✅' if js.get('typing') == 'on' else '❌'}
🎮 بازی: {'✅' if js.get('game') == 'on' else '❌'}

دستورات کامل رو با `راهنما` ببینید.
"""
            await message.reply_text(panel_text)
            await message.delete()

        @client.on_message(filters.text & filters.regex(r'^(راهنما|help)$') & filters.me)
        async def self_help(client, message):
            help_text = """
📚 **راهنمای کامل سلف‌بات**

⏰ **زمان و ساعت:**
.timename on/off - نمایش زمان در نام
.timebio on/off - نمایش زمان در بیو
.timeprofile on/off - عکس ساعت در پروفایل
.timecrash on/off - ارسال پیام عاشقانه به کراش‌ها

🔤 **مودهای ویرایش متن:**
hashtag on/off - تبدیل به هشتگ
bold on/off - پررنگ
italic on/off - کج
delete on/off - خط خورده
code on/off - کد
underline on/off - زیرخط
reverse on/off - برعکس
part on/off - نمایش تدریجی
mention on/off - منشن خودکار

🎮 **اکشن‌ها (نمایش وضعیت):**
typing on/off - در حال تایپ
game on/off - در حال بازی
voice on/off - در حال ضبط صدا
video on/off - در حال ضبط ویدیو
sticker on/off - در حال ارسال استیکر

📝 **منشی:**
.comment on/off - فعال/غیرفعال
.commentText [متن] - تنظیم متن

⚔️ **مدیریت دشمن:**
.addenemy (ریپلی) - افزودن دشمن
.delenemy (ریپلی) - حذف دشمن
listenemy - لیست دشمنان

❤️ **مدیریت کراش:**
.addcrash (ریپلی) - افزودن کراش
.delcrash (ریپلی) - حذف کراش
listcrash - لیست کراش‌ها

🎲 **سرگرمی:**
dice [1-6] - تاس
fun [love/oclock/star/snow] - انیمیشن
heart - انیمیشن قلب

📊 **اطلاعات:**
info (ریپلی) - اطلاعات کاربر
status - وضعیت کلی

🛠 **ابزارها:**
clean [تعداد] - حذف پیام‌ها
restart - ریستارت سلف‌بات
"""
            await message.reply_text(help_text)
            await message.delete()

        # ====== دستورات نقطه‌دار ======
        @client.on_message(filters.text & filters.regex(r'^\.timename (on|off)$') & filters.me)
        async def time_name(client, message):
            value = message.text.split()[1]
            js = await get('data.json')
            js['timename'] = value
            await put('data.json', js)
            await message.edit_text(f'✅ زمان در نام: {"فعال" if value == "on" else "غیرفعال"}')

        @client.on_message(filters.text & filters.regex(r'^\.timebio (on|off)$') & filters.me)
        async def time_bio(client, message):
            value = message.text.split()[1]
            js = await get('data.json')
            js['timebio'] = value
            await put('data.json', js)
            await message.edit_text(f'✅ زمان در بیو: {"فعال" if value == "on" else "غیرفعال"}')

        @client.on_message(filters.text & filters.regex(r'^\.timeprofile (on|off)$') & filters.me)
        async def time_profile(client, message):
            value = message.text.split()[1]
            js = await get('data.json')
            js['timeprofile'] = value
            await put('data.json', js)
            await message.edit_text(f'✅ عکس ساعت: {"فعال" if value == "on" else "غیرفعال"}')

        @client.on_message(filters.text & filters.regex(r'^\.timecrash (on|off)$') & filters.me)
        async def time_crash(client, message):
            value = message.text.split()[1]
            js = await get('data.json')
            js['timecrash'] = value
            await put('data.json', js)
            await message.edit_text(f'✅ کراش تایم: {"فعال" if value == "on" else "غیرفعال"}')

        @client.on_message(filters.text & filters.regex(r'^\.comment (on|off)$') & filters.me)
        async def comment(client, message):
            value = message.text.split()[1]
            js = await get('data.json')
            js['comment'] = value
            await put('data.json', js)
            await message.edit_text(f'✅ منشی: {"فعال" if value == "on" else "غیرفعال"}')

        @client.on_message(filters.text & filters.regex(r'^\.commentText (.+)$') & filters.me)
        async def comment_text(client, message):
            text = message.text.replace('.commentText', '').strip()
            if text:
                js = await get('data.json')
                js['text'] = text
                await put('data.json', js)
                await message.edit_text(f'✅ متن منشی تنظیم شد:\n`{text}`')
            else:
                await message.edit_text('❌ لطفا متن را وارد کنید!')

        @client.on_message(filters.text & filters.regex(r'^\.addenemy$') & filters.me)
        async def add_enemy(client, message):
            if message.reply_to_message:
                target = message.reply_to_message.from_user
                if target:
                    js = await get('data.json')
                    if target.id not in js['enemy']:
                        js['enemy'].append(target.id)
                        await put('data.json', js)
                        await message.edit_text(f'✅ دشمن {target.id} اضافه شد!')
                    else:
                        await message.edit_text('⚠️ کاربر در لیست دشمنان است!')
                else:
                    await message.edit_text('❌ کاربر پیدا نشد!')
            else:
                await message.edit_text('❌ روی پیام کاربر ریپلی کن!')

        @client.on_message(filters.text & filters.regex(r'^\.delenemy$') & filters.me)
        async def del_enemy(client, message):
            if message.reply_to_message:
                target = message.reply_to_message.from_user
                if target:
                    js = await get('data.json')
                    if target.id in js['enemy']:
                        js['enemy'].remove(target.id)
                        await put('data.json', js)
                        await message.edit_text(f'✅ دشمن {target.id} حذف شد!')
                    else:
                        await message.edit_text('⚠️ کاربر در لیست دشمنان نیست!')
                else:
                    await message.edit_text('❌ کاربر پیدا نشد!')
            else:
                await message.edit_text('❌ روی پیام کاربر ریپلی کن!')

        @client.on_message(filters.text & filters.regex(r'^listenemy$') & filters.me)
        async def list_enemy(client, message):
            js = await get('data.json')
            enemies = js.get('enemy', [])
            if enemies:
                text = "📜 لیست دشمنان:\n"
                for i, e in enumerate(enemies, 1):
                    text += f"{i}. `{e}`\n"
                await message.edit_text(text)
            else:
                await message.edit_text("📭 لیست دشمنان خالی است!")

        @client.on_message(filters.text & filters.regex(r'^\.addcrash$') & filters.me)
        async def add_crash(client, message):
            if message.reply_to_message:
                target = message.reply_to_message.from_user
                if target:
                    js = await get('data.json')
                    if target.id not in js['crash']:
                        js['crash'].append(target.id)
                        await put('data.json', js)
                        await message.edit_text(f'✅ کراش {target.id} اضافه شد!')
                    else:
                        await message.edit_text('⚠️ کاربر در لیست کراش‌ها است!')
                else:
                    await message.edit_text('❌ کاربر پیدا نشد!')
            else:
                await message.edit_text('❌ روی پیام کاربر ریپلی کن!')

        @client.on_message(filters.text & filters.regex(r'^\.delcrash$') & filters.me)
        async def del_crash(client, message):
            if message.reply_to_message:
                target = message.reply_to_message.from_user
                if target:
                    js = await get('data.json')
                    if target.id in js['crash']:
                        js['crash'].remove(target.id)
                        await put('data.json', js)
                        await message.edit_text(f'✅ کراش {target.id} حذف شد!')
                    else:
                        await message.edit_text('⚠️ کاربر در لیست کراش‌ها نیست!')
                else:
                    await message.edit_text('❌ کاربر پیدا نشد!')
            else:
                await message.edit_text('❌ روی پیام کاربر ریپلی کن!')

        @client.on_message(filters.text & filters.regex(r'^listcrash$') & filters.me)
        async def list_crash(client, message):
            js = await get('data.json')
            crashes = js.get('crash', [])
            if crashes:
                text = "❤️ لیست کراش‌ها:\n"
                for i, c in enumerate(crashes, 1):
                    text += f"{i}. `{c}`\n"
                await message.edit_text(text)
            else:
                await message.edit_text("📭 لیست کراش‌ها خالی است!")

        @client.on_message(filters.text & filters.regex(r'^(hashtag|bold|italic|delete|code|underline|reverse|part|mention|typing|game|voice|video|sticker) (on|off)$') & filters.me)
        async def toggle_mode(client, message):
            mode, value = message.text.split()
            js = await get('data.json')
            js[mode] = value
            await put('data.json', js)
            mode_names = {
                'hashtag': 'هشتگ', 'bold': 'بولد', 'italic': 'ایتالیک',
                'delete': 'خط خورده', 'code': 'کد', 'underline': 'زیرخط',
                'reverse': 'برعکس', 'part': 'پارت', 'mention': 'منشن',
                'typing': 'تایپ', 'game': 'بازی', 'voice': 'ویس',
                'video': 'ویدیو', 'sticker': 'استیکر'
            }
            await message.edit_text(f'✅ {mode_names.get(mode, mode)}: {"فعال" if value == "on" else "غیرفعال"}')

        @client.on_message(filters.text & filters.regex(r'^fun (love|oclock|star|snow)$') & filters.me)
        async def fun_animation(client, message):
            category = message.text.split()[1]
            emoticons = {
                'love': ['🤍', '🖤', '💜', '💙', '💚', '💛', '🧡', '❤️', '🤎', '💖'],
                'oclock': ['🕐', '🕑', '🕒', '🕓', '🕔', '🕕', '🕖', '🕗', '🕘', '🕙', '🕚', '🕛', '🕜', '🕝', '🕞', '🕟', '🕠', '🕡', '🕢', '🕣', '🕤', '🕥', '🕦', '🕧'],
                'star': ['💥', '⚡️', '✨', '🌟', '⭐️', '💫'],
                'snow': ['❄️', '☃️', '⛄️']
            }
            if category in emoticons:
                random.shuffle(emoticons[category])
                for emoji in emoticons[category][:5]:
                    await message.edit_text(emoji)
                    await asyncio.sleep(0.5)

        @client.on_message(filters.text & filters.regex(r'^heart$') & filters.me)
        async def heart_animation(client, message):
            for x in range(1, 4):
                for i in range(1, 11):
                    await message.edit_text('➣ ' + str(x) + ' ❦' * i + ' | ' + str(10 * i) + '%')
                    await asyncio.sleep(0.2)

        @client.on_message(filters.text & filters.regex(r'^dice ([1-6])$') & filters.me)
        async def dice_command(client, message):
            num = int(message.text.split()[1])
            if 1 <= num <= 6:
                await client.send_dice(message.chat.id, "🎲")
                await message.delete()
            else:
                await message.edit_text('❌ عدد باید بین ۱ تا ۶ باشد!')

        @client.on_message(filters.text & filters.regex(r'^clean (\d+)$') & filters.me)
        async def clean_messages(client, message):
            count = int(message.text.split()[1])
            async for msg in client.get_chat_history(message.chat.id, limit=count + 1):
                if msg.from_user and msg.from_user.is_self:
                    try:
                        await msg.delete()
                    except:
                        pass
            await message.delete()

        @client.on_message(filters.text & filters.regex(r'^info$') & filters.me)
        async def info_command(client, message):
            if message.reply_to_message:
                user = message.reply_to_message.from_user
                if user:
                    try:
                        full = await client.get_entity(user.id)
                        info_text = f"""
👤 **اطلاعات کاربر**

🆔 آیدی: `{user.id}`
👤 نام: {user.first_name or 'ندارد'}
📱 نام خانوادگی: {user.last_name or 'ندارد'}
📱 یوزرنیم: @{user.username if user.username else 'ندارد'}
📱 شماره: {getattr(full, 'phone', 'ندارد')}
"""
                        await message.edit_text(info_text)
                    except:
                        await message.edit_text(f'🆔 آیدی: `{user.id}`')
                else:
                    await message.edit_text('❌ کاربر پیدا نشد!')
            else:
                me = await client.get_me()
                await message.edit_text(f'🆔 آیدی خودت: `{me.id}`')

        @client.on_message(filters.text & filters.regex(r'^status$') & filters.me)
        async def status_command(client, message):
            private_chats = 0
            bots = 0
            groups = 0
            broadcast_channels = 0
            async for dialog in client.get_dialogs():
                entity = dialog.entity
                if isinstance(entity, types.Channel):
                    if entity.broadcast:
                        broadcast_channels += 1
                    elif entity.megagroup:
                        groups += 1
                elif isinstance(entity, types.User):
                    private_chats += 1
                    if entity.bot:
                        bots += 1
                elif isinstance(entity, types.Chat):
                    groups += 1
            await message.edit_text(f"""
📊 **وضعیت کلی**

👤 چت‌های خصوصی: {private_chats}
🤖 ربات‌ها: {bots}
👥 گروه‌ها: {groups}
📢 کانال‌ها: {broadcast_channels}
""")

        @client.on_message(filters.text & filters.regex(r'^restart$') & filters.me)
        async def restart_command(client, message):
            await message.edit_text('🔄 در حال ریستارت...')
            pid = os.getpid()
            filename = __file__.split('/')[-1]
            os.system(f'kill -9 {pid} && python3 {filename}')

        await manager_bot.send_message(user_id, "✅ سلف‌بات شما با موفقیت فعال شد!\n\nدستور `پنل` رو بفرست تا تنظیمات رو ببینی.")
        
    except Exception as e:
        logging.error(f"❌ خطا در فعال‌سازی سلف‌بات: {e}")
        try:
            await manager_bot.send_message(user_id, f"❌ خطا در فعال‌سازی سلف‌بات: {e}")
        except:
            pass

# =============================================
# هندلرهای ربات مدیریت
# =============================================

@manager_bot.on_message(filters.command("start"))
async def start_login(client, message):
    buttons = ReplyKeyboardMarkup([
        [KeyboardButton("📱 ارسال شماره", request_contact=True)]
    ], resize_keyboard=True)
    await message.reply_text(
        "👋 **به ربات سلف‌بات خوش آمدید!**\n\n"
        "برای فعال‌سازی سلف‌بات، لطفاً شماره تلفن خود را ارسال کنید.\n\n"
        "⚠️ توجه: این ربات به جای شما وارد اکانتتان می‌شود.",
        reply_markup=buttons
    )

@manager_bot.on_message(filters.contact)
async def contact_handler(client, message):
    user_id = message.from_user.id
    phone = message.contact.phone_number
    await message.reply_text("⏳ در حال اتصال به تلگرام...", reply_markup=ReplyKeyboardRemove())
    temp_client = Client(f"login_{user_id}", api_id=API_ID, api_hash=API_HASH, in_memory=True)
    await temp_client.start()
    try:
        sent_code = await temp_client.send_code(phone)
        LOGIN_STATES[user_id] = {
            'step': 'code',
            'phone': phone,
            'client': temp_client,
            'hash': sent_code.phone_code_hash
        }
        await message.reply_text("✅ کد تایید به شماره شما ارسال شد.\n\nلطفاً کد را وارد کنید (مثلاً: `1 1 1 1 1` با فاصله)")
    except Exception as e:
        await temp_client.disconnect()
        await message.reply_text(f"❌ خطا: {e}")

@manager_bot.on_message(filters.text & filters.private)
async def code_handler(client, message):
    user_id = message.from_user.id
    state = LOGIN_STATES.get(user_id)
    if not state:
        return
    text = message.text.strip()
    if state['step'] == 'code':
        code = re.sub(r"\s+", "", text)
        try:
            temp_client = state['client']
            await temp_client.sign_in(state['phone'], state['hash'], code)
            session_string = await temp_client.export_session_string()
            me = await temp_client.get_me()
            await temp_client.disconnect()
            del LOGIN_STATES[user_id]
            await message.reply_text("✅ **سلف‌بات با موفقیت فعال شد!**\n\n⏳ در حال راه‌اندازی...")
            asyncio.create_task(start_self_bot(session_string, user_id, state['phone']))
        except Exception as e:
            await message.reply_text(f"❌ خطا در تایید کد: {e}")
            if "password" in str(e).lower():
                state['step'] = 'password'
                await message.reply_text("🔐 رمز دو مرحله‌ای را وارد کنید:")
    elif state['step'] == 'password':
        try:
            temp_client = state['client']
            await temp_client.check_password(text)
            session_string = await temp_client.export_session_string()
            me = await temp_client.get_me()
            await temp_client.disconnect()
            del LOGIN_STATES[user_id]
            await message.reply_text("✅ **سلف‌بات با موفقیت فعال شد!**\n\n⏳ در حال راه‌اندازی...")
            asyncio.create_task(start_self_bot(session_string, user_id, state['phone']))
        except Exception as e:
            await message.reply_text(f"❌ خطا در رمز دو مرحله‌ای: {e}")

# =============================================
# اجرا
# =============================================
async def main():
    await manager_bot.start()
    logging.info("✅ ربات مدیریت با توکن اجرا شد!")
    logging.info("🚀 منتظر لاگین کاربران...")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
