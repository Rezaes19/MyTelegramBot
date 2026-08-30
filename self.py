import os
import random
import psutil
import json
import pytz
import aiocron
import asyncio
import aiofiles
import aiohttp
import numpy
from datetime import datetime, timedelta
from telethon.sync import TelegramClient, events, types
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.account import UpdateStatusRequest, GetAuthorizationsRequest, UpdateProfileRequest
from telethon.tl.functions.messages import SendScreenshotNotificationRequest, SendReactionRequest
from telethon.tl.functions.phone import CreateGroupCallRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest, DeletePhotosRequest
from gtts import gTTS
from googletrans import Translator
from google_play_scraper import search
import matplotlib.pyplot as plt

# =============================================
# نصب خودکار پکیج‌ها در صورت نیاز
# =============================================
try:
    import telethon
except ModuleNotFoundError:
    os.system('pip install --upgrade pip && pip install -U telethon psutil aiohttp asyncio aiocron aiofiles pytz googletrans==4.0.0-rc1 gtts google_play_scraper numpy matplotlib')
    os.sys.exit('✅ Packages installed!')

# =============================================
# تنظیمات اصلی
# =============================================
API_ID = 34996139
API_HASH = "a1f3db16cae2919cfb05e61d1e968b8d"
HELPER_BOT = "VIPMR_Helper_Bot"  # ربات کمکی برای پنل

# =============================================
# توابع دیتابیس
# =============================================
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

# =============================================
# ایجاد فایل دیتا در صورت نبود
# =============================================
loop = asyncio.get_event_loop()

if not os.path.exists('data.json'):
    data = {
        'timename': 'off', 'timebio': 'off', 'timeprofile': 'off', 'timecrash': 'off',
        'bot': 'on', 'hashtag': 'off', 'bold': 'off', 'italic': 'off', 'delete': 'off',
        'code': 'off', 'underline': 'off', 'reverse': 'off', 'part': 'off', 'mention': 'off',
        'spoiler': 'off', 'comment': 'on', 'text': 'سلام! من ربات VIP MR هستم ❤️',
        'typing': 'off', 'game': 'off', 'voice': 'off', 'video': 'off', 'sticker': 'off',
        'crash': [], 'enemy': []
    }
    loop.run_until_complete(put('data.json', data))

# =============================================
# اتصال به تلگرام (لاگین دستی با شماره)
# =============================================
print("📱 لطفاً شماره خود را وارد کنید:")
bot = TelegramClient('self', API_ID, API_HASH, loop=loop)
bot.start()

# =============================================
# تابع ساخت ساعت روی عکس
# =============================================
async def makeClock(h, m, s, read, write):
    image = plt.imread(read)
    fig = plt.figure(figsize=(4, 4), dpi=300, facecolor=[0.2, 0.2, 0.2])
    ax_image = fig.add_axes([0, 0, 1, 1])
    ax_image.axis('off')
    ax_image.imshow(image)
    axc = fig.add_axes([0.062, 0.062, 0.88, 0.88], projection='polar')
    axc.cla()
    seconds = numpy.multiply(numpy.ones(5), s * 2 * numpy.pi / 60)
    minutes = numpy.multiply(numpy.ones(5), m * 2 * numpy.pi / 60) + (seconds / 60)
    hours = numpy.multiply(numpy.ones(5), h * 2 * numpy.pi / 12) + (minutes / 12)
    axc.axis('off')
    axc.set_theta_zero_location('N')
    axc.set_theta_direction(-1)
    axc.plot(hours, numpy.linspace(0.00, 0.70, 5), c='c', linewidth=2.0)
    axc.plot(minutes, numpy.linspace(0.00, 0.85, 5), c='b', linewidth=1.5)
    axc.plot(seconds, numpy.linspace(0.00, 1.00, 5), c='r', linewidth=1.0)
    axc.plot(minutes, numpy.linspace(0.73, 0.83, 5), c='w', linewidth=1.0)
    axc.plot(hours, numpy.linspace(0.60, 0.68, 5), c='w', linewidth=1.5)
    axc.plot(seconds, numpy.linspace(0.80, 0.98, 5), c='w', linewidth=0.5)
    axc.set_rmax(1)
    plt.savefig(write)
    return write

# =============================================
# کرون جاب - آپدیت ساعت هر دقیقه
# =============================================
@aiocron.crontab('*/1 * * * *')
async def clock():
    await bot(UpdateStatusRequest(offline=False))
    js = await get('data.json')
    if js['timename'] == 'off' and js['timebio'] == 'off' and js['timeprofile'] == 'off' and js['timecrash'] == 'off':
        return
    
    now = datetime.now(pytz.timezone('Asia/Tehran')).strftime('%H:%M:%S')
    h, m, s = list(map(int, now.split(':')))
    time = f'【 {h}:{m} 】'
    rand = ['⓪➀➁➂➃➄➅➆➇➈', '𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗']
    fonts = time.translate(time.maketrans('0123456789', random.choice(rand)))
    
    if js['timecrash'] == 'on':
        if h == m:
            for from_id in js['crash']:
                await bot.send_message(from_id, f'💖 عاشقتم {fonts}')
    
    if js['timename'] == 'on':
        await bot(UpdateProfileRequest(last_name=fonts))
    
    if js['timebio'] == 'on':
        await bot(UpdateProfileRequest(about=f'❦ VIP MR Self Bot ❦ {fonts}'))
    
    if js['timeprofile'] == 'on':
        build = await makeClock(h, m, s, 'clock.jpg', 'oclock.jpg')
        photo = await bot.upload_file(build)
        photos = await bot.get_profile_photos('me')
        if photos:
            if datetime.now(pytz.timezone('UTC')) - photos[0].date < timedelta(minutes=10):
                await bot(DeletePhotosRequest(id=[types.InputPhoto(
                    id=photos[0].id,
                    access_hash=photos[0].access_hash,
                    file_reference=photos[0].file_reference
                )]))
        await bot(UploadProfilePhotoRequest(file=photo, fallback=True))

# =============================================
# تابع گرفتن آیدی کاربر
# =============================================
async def get_user_id(event):
    if event.is_reply:
        getMessage = await event.get_reply_message()
        return getMessage.sender.id
    elif len(event.raw_text.split(' ')) == 2:
        try:
            user = int(event.raw_text.split(' ')[1])
        except:
            user = str(event.raw_text.split(' ')[1])
        try:
            entity = await bot.get_input_entity(user)
            return entity.user_id
        except:
            return None
    elif event.is_private:
        return event.chat_id
    return None

# =============================================
# حالت‌های نوشتن
# =============================================
@bot.on(events.NewMessage(outgoing=True))
async def mode(event):
    js = await get('data.json')
    text = event.raw_text
    if not text:
        return
    
    try:
        if js['hashtag'] == 'on':
            new = text.replace(' ', '_')
            await event.edit(f'#{new}')
        elif js['bold'] == 'on':
            await event.edit(f'<b>{text}</b>', parse_mode='HTML')
        elif js['italic'] == 'on':
            await event.edit(f'<i>{text}</i>', parse_mode='HTML')
        elif js['delete'] == 'on':
            await event.edit(f'<del>{text}</del>', parse_mode='HTML')
        elif js['code'] == 'on':
            await event.edit(f'<code>{text}</code>', parse_mode='HTML')
        elif js['underline'] == 'on':
            await event.edit(f'<u>{text}</u>', parse_mode='HTML')
        elif js['reverse'] == 'on':
            await event.edit(text[::-1])
        elif js['part'] == 'on':
            if len(text) > 1:
                new = ''
                for add in text:
                    new += add
                    if add != ' ':
                        await event.edit(new)
        elif js['mention'] == 'on':
            if event.is_reply:
                try:
                    getMessage = await event.get_reply_message()
                    get_id = getMessage.sender.id
                    await event.edit(f'<a href="tg://openmessage?user_id={get_id}">{text}</a>', parse_mode='HTML')
                except Exception as e:
                    await bot.send_message('me', f'❌ خطا: {e}')
    except Exception as e:
        print(e)

# =============================================
# مدیریت پیام‌های دریافتی
# =============================================
@bot.on(events.NewMessage())
async def updateMessage(event):
    js = await get('data.json')
    fromid = event.sender_id
    
    if not fromid:
        return
    
    if fromid in js['enemy'] and event.is_private:
        await event.delete()
    elif fromid in js['crash'] and event.is_group:
        try:
            await bot(SendReactionRequest(
                peer=event.chat_id,
                msg_id=event.message.id,
                reaction=[types.ReactionEmoji(emoticon='❤️')]
            ))
        except:
            emoticons = ['🤍', '🖤', '💜', '💙', '💚', '💛', '🧡', '❤️', '🤎', '💖']
            await event.reply(random.choice(emoticons))
        await event.forward_to('me')
    elif js['comment'] == 'on' and event.fwd_from:
        if event.fwd_from.saved_from_peer:
            if event.from_id:
                await event.reply(js['text'])

# =============================================
# ورود به گروه
# =============================================
@bot.on(events.ChatAction)
async def chatAction(event):
    if event.user_joined:
        if event.action_message.out:
            await event.reply('🤖 من به گروه خوش آمدیدم!')
        else:
            await event.reply('👋 به گروه خوش آمدید!')

# =============================================
# ادیت پیام
# =============================================
@bot.on(events.MessageEdited(outgoing=False, func=lambda e: e.is_private))
async def messageEdited(event):
    if event.message and not event.reactions:
        time = datetime.now(pytz.timezone('Asia/Tehran')).strftime('✐ %H:%M:%S ✎')
        await bot.send_message(
            event.chat_id,
            f'<a href="tg://openmessage?user_id={event.sender_id}">😅 پیامت رو ساعت {time} ادیت زدی</a>',
            parse_mode='HTML',
            reply_to=event.message.id
        )

# =============================================
# اکشن‌ها (تایپ، بازی، وویس...)
# =============================================
@bot.on(events.NewMessage())
async def sendAction(event):
    js = await get('data.json')
    for action_type in ['typing', 'game', 'voice', 'video', 'sticker']:
        if js.get(action_type) == 'on':
            async with bot.action(event.chat_id, action_type):
                await asyncio.sleep(2)

# =============================================
# دستورات متنی
# =============================================

# راهنما
@bot.on(events.NewMessage(pattern=r'(help|راهنما)', outgoing=True))
async def help(event):
    memoryUse = psutil.Process(os.getpid()).memory_info()[0] / 1073741824
    memoryPercent = psutil.virtual_memory()[2]
    cpuPercent = psutil.cpu_percent(3)
    me = await bot.get_me()
    name = me.first_name
    js = await get('data.json')
    
    help_text = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
    🤖 راهنمای ربات VIP MR
╰━━━━━━━━━━━━━━━━━━━━━━━╯

👤 نام: {name}

✧━━━━━━━━━━━━━━━━━━━━━━━✧
⏰ تنظیمات ساعت

✦ timename: {js['timename']}
✦ timebio: {js['timebio']}
✦ timeprofile: {js['timeprofile']}
✦ timecrash: {js['timecrash']}

✧━━━━━━━━━━━━━━━━━━━━━━━✧
📝 حالت‌های نوشتن

✦ hashtag: {js['hashtag']}
✦ bold: {js['bold']}
✦ italic: {js['italic']}
✦ delete: {js['delete']}
✦ code: {js['code']}
✦ underline: {js['underline']}
✦ reverse: {js['reverse']}
✦ part: {js['part']}
✦ mention: {js['mention']}

✧━━━━━━━━━━━━━━━━━━━━━━━✧
🎮 اکشن‌ها

✦ typing: {js['typing']}
✦ game: {js['game']}
✦ voice: {js['voice']}
✦ video: {js['video']}
✦ sticker: {js['sticker']}

✧━━━━━━━━━━━━━━━━━━━━━━━✧
📊 آمار سرور

💾 رم مصرفی: {memoryUse:.2f} GB
📊 رم: {memoryPercent}%
⚡️ CPU: {cpuPercent}%

✧━━━━━━━━━━━━━━━━━━━━━━━✧
"""
    await bot.send_message(event.chat_id, help_text, reply_to=event.message.id)

# پنل
@bot.on(events.NewMessage(pattern=r'(panel|پنل)', outgoing=True))
async def panel(event):
    await event.edit('⏳ در حال باز کردن پنل...')
    if HELPER_BOT:
        try:
            results = await bot.inline_query(HELPER_BOT, 'panel')
            if results:
                await results[0].click(event.chat_id)
        except:
            await event.edit('❌ ربات کمکی در دسترس نیست!')

# تاس
@bot.on(events.NewMessage(pattern=r'(dice|تاس) (1|2|3|4|5|6)', outgoing=True))
async def dice(event):
    input_str = event.pattern_match.group(2)
    await event.delete()
    send = await bot.send_file(event.chat_id, types.InputMediaDice('🎲'))
    while send.media.value != int(input_str):
        await bot.delete_messages(event.chat_id, send.id)
        send = await bot.send_file(event.chat_id, types.InputMediaDice('🎲'))

# پاک کردن پیام‌ها
@bot.on(events.NewMessage(pattern=r'(clean|حذف) (\d+)', outgoing=True))
async def clean(event):
    count = int(event.pattern_match.group(2))
    async for message in bot.iter_messages(event.chat_id, limit=count):
        await bot.delete_messages(event.chat_id, message.id)
    await bot.send_message(event.chat_id, f'✅ {count} پیام حذف شد!')

# =============================================
# مدیریت دشمن
# =============================================
@bot.on(events.NewMessage(pattern=r'(addenemy|افزودن دشمن)', outgoing=True))
async def addEnemy(event):
    user_id = await get_user_id(event)
    if not user_id:
        return await event.edit('❌ کاربر پیدا نشد!')
    
    js = await get('data.json')
    if user_id in js['enemy']:
        await event.edit(f'• [کاربر](tg://user?id={user_id}) قبلاً در لیست دشمنان است!')
    else:
        js['enemy'].append(user_id)
        await put('data.json', js)
        await event.edit(f'• [کاربر](tg://user?id={user_id}) به لیست دشمنان اضافه شد!')

@bot.on(events.NewMessage(pattern=r'(delenemy|حذف دشمن)', outgoing=True))
async def delEnemy(event):
    user_id = await get_user_id(event)
    if not user_id:
        return await event.edit('❌ کاربر پیدا نشد!')
    
    js = await get('data.json')
    if user_id in js['enemy']:
        js['enemy'].remove(user_id)
        await put('data.json', js)
        await event.edit(f'• [کاربر](tg://user?id={user_id}) از لیست دشمنان حذف شد!')
    else:
        await event.edit(f'• [کاربر](tg://user?id={user_id}) در لیست دشمنان نیست!')

@bot.on(events.NewMessage(pattern=r'(listenemy|لیست دشمن)', outgoing=True))
async def listEnemy(event):
    js = await get('data.json')
    if not js['enemy']:
        await event.edit('📭 لیست دشمنان خالی است!')
        return
    
    txt = '⚔️ لیست دشمنان:\n'
    for i in js['enemy']:
        txt += f'\n• [{i}](tg://user?id={i})'
    await event.edit(txt)

# =============================================
# مدیریت کراش
# =============================================
@bot.on(events.NewMessage(pattern=r'(addcrash|افزودن کراش)', outgoing=True))
async def addCrash(event):
    user_id = await get_user_id(event)
    if not user_id:
        return await event.edit('❌ کاربر پیدا نشد!')
    
    js = await get('data.json')
    if user_id in js['crash']:
        await event.edit(f'• [کاربر](tg://user?id={user_id}) قبلاً در لیست کراش است!')
    else:
        js['crash'].append(user_id)
        await put('data.json', js)
        await event.edit(f'• [کاربر](tg://user?id={user_id}) به لیست کراش اضافه شد!')

@bot.on(events.NewMessage(pattern=r'(delcrash|حذف کراش)', outgoing=True))
async def delCrash(event):
    user_id = await get_user_id(event)
    if not user_id:
        return await event.edit('❌ کاربر پیدا نشد!')
    
    js = await get('data.json')
    if user_id in js['crash']:
        js['crash'].remove(user_id)
        await put('data.json', js)
        await event.edit(f'• [کاربر](tg://user?id={user_id}) از لیست کراش حذف شد!')
    else:
        await event.edit(f'• [کاربر](tg://user?id={user_id}) در لیست کراش نیست!')

@bot.on(events.NewMessage(pattern=r'(listcrash|لیست کراش)', outgoing=True))
async def listCrash(event):
    js = await get('data.json')
    if not js['crash']:
        await event.edit('📭 لیست کراش خالی است!')
        return
    
    txt = '💖 لیست کراش:\n'
    for i in js['crash']:
        txt += f'\n• [{i}](tg://user?id={i})'
    await event.edit(txt)

# =============================================
# تنظیمات ساعت
# =============================================
@bot.on(events.NewMessage(pattern=r'\.timename (on|off)', outgoing=True))
async def timeName(event):
    val = event.pattern_match.group(1)
    js = await get('data.json')
    js['timename'] = val
    await put('data.json', js)
    await event.edit(f'✅ ساعت روی اسم: {val}')

@bot.on(events.NewMessage(pattern=r'\.timebio (on|off)', outgoing=True))
async def timeBio(event):
    val = event.pattern_match.group(1)
    js = await get('data.json')
    js['timebio'] = val
    await put('data.json', js)
    await event.edit(f'✅ ساعت روی بیو: {val}')

@bot.on(events.NewMessage(pattern=r'\.timeprofile (on|off)', outgoing=True))
async def timeProfile(event):
    val = event.pattern_match.group(1)
    js = await get('data.json')
    js['timeprofile'] = val
    await put('data.json', js)
    await event.edit(f'✅ ساعت روی پروفایل: {val}')

@bot.on(events.NewMessage(pattern=r'\.timecrash (on|off)', outgoing=True))
async def timeCrash(event):
    val = event.pattern_match.group(1)
    js = await get('data.json')
    js['timecrash'] = val
    await put('data.json', js)
    await event.edit(f'✅ ساعت کراش: {val}')

# =============================================
# تنظیمات حالت‌های نوشتن
# =============================================
@bot.on(events.NewMessage(pattern=r'(hashtag|bold|italic|delete|code|underline|reverse|part|mention|spoiler) (on|off)', outgoing=True))
async def editMode(event):
    match = event.raw_text.split(' ')
    js = await get('data.json')
    js[match[0]] = match[1]
    await put('data.json', js)
    await event.edit(f'✅ حالت {match[0]}: {match[1]}')

# =============================================
# تنظیمات اکشن‌ها
# =============================================
@bot.on(events.NewMessage(pattern=r'(typing|game|voice|video|sticker) (on|off)', outgoing=True))
async def editAction(event):
    match = event.raw_text.split(' ')
    js = await get('data.json')
    js[match[0]] = match[1]
    await put('data.json', js)
    await event.edit(f'✅ اکشن {match[0]}: {match[1]}')

# =============================================
# اطلاعات کاربر
# =============================================
@bot.on(events.NewMessage(pattern=r'(info|اطلاعات)', outgoing=True))
async def info(event):
    user_id = await get_user_id(event)
    if not user_id:
        return await event.edit('❌ کاربر پیدا نشد!')
    
    try:
        full = await bot(GetFullUserRequest(user_id))
        user = full.users[0]
        
        info_text = f"""
👤 **اطلاعات کاربر**

🆔 آیدی: `{user.id}`
👤 نام: {user.first_name or 'ندارد'}
📛 نام خانوادگی: {user.last_name or 'ندارد'}
📱 یوزرنیم: @{user.username if user.username else 'ندارد'}
📞 شماره: {user.phone if hasattr(user, 'phone') else '🔒 مخفی'}

📝 بیو: {full.full_user.about if full.full_user.about else 'ندارد'}
        """
        
        photos = await bot.get_profile_photos(user_id)
        if photos:
            await event.delete()
            await bot.send_message(event.chat_id, info_text, file=photos[0], parse_mode='md')
        else:
            await event.edit(info_text, parse_mode='md')
    except Exception as e:
        await event.edit(f'❌ خطا: {e}')

# =============================================
# وضعیت
# =============================================
@bot.on(events.NewMessage(pattern=r'(status|وضعیت)', outgoing=True))
async def status(event):
    private_chats = 0
    bots = 0
    groups = 0
    channels = 0
    
    async for dialog in bot.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, types.Channel):
            if entity.broadcast:
                channels += 1
            else:
                groups += 1
        elif isinstance(entity, types.User):
            private_chats += 1
            if entity.bot:
                bots += 1
        elif isinstance(entity, types.Chat):
            groups += 1
    
    txt = f"""
📊 **وضعیت اکانت**

💬 پیوی‌ها: {private_chats}
🤖 ربات‌ها: {bots}
👥 گروه‌ها: {groups}
📢 کانال‌ها: {channels}
    """
    await event.edit(txt, parse_mode='md')

# =============================================
# تگ همه
# =============================================
@bot.on(events.NewMessage(pattern=r'(tagall|تگ)', outgoing=True, func=lambda e: e.is_group))
async def tagAll(event):
    mentions = '📢 **همه افراد گروه:**\n'
    chat = await event.get_input_chat()
    async for x in bot.iter_participants(chat, limit=100):
        mentions += f'\n• [{x.first_name}](tg://user?id={x.id})'
    await event.reply(mentions)
    await event.delete()

# =============================================
# تگ ادمین‌ها
# =============================================
@bot.on(events.NewMessage(pattern=r'(tagadmins|تگ ادمین)', outgoing=True, func=lambda e: e.is_group))
async def tagAdmins(event):
    mentions = '👑 **ادمین‌های گروه:**\n'
    chat = await event.get_input_chat()
    async for x in bot.iter_participants(chat, filter=types.ChannelParticipantsAdmins):
        mentions += f'\n• [{x.first_name}](tg://user?id={x.id})'
    await event.reply(mentions)
    await event.delete()

# =============================================
# ری‌استارت
# =============================================
@bot.on(events.NewMessage(pattern=r'(restart|ریستارت)', outgoing=True))
async def restart(event):
    await event.edit('🔄 در حال ری‌استارت...')
    pid = os.getpid()
    filename = __file__.split('/')[-1]
    os.system(f'kill -9 {pid} && python3 {filename}')

# =============================================
# اجرای ربات
# =============================================
async def main():
    # استارت با شماره (دستی)
    await bot.start()
    print("✅ VIP MR Self Bot started!")
    print("📱 Username:", (await bot.get_me()).username)
    print("🆔 ID:", (await bot.get_me()).id)
    
    # شروع کرون جاب
    clock.start()
    
    # اجرا
    await bot.run_until_disconnected()

if __name__ == "__main__":
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("❌ Bot stopped!")
    except Exception as e:
        print(f"❌ Error: {e}")
