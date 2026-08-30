try:
    import os, random, json, pytz, asyncio, aiofiles, aiohttp, logging
    from telethon.sync import TelegramClient, events, types
    from telethon.tl.functions.users import GetFullUserRequest
    from telethon.tl.functions.account import UpdateStatusRequest, GetAuthorizationsRequest
    from telethon.tl.functions.messages import SendScreenshotNotificationRequest, SendReactionRequest
    from telethon.tl.functions.phone import CreateGroupCallRequest
    from datetime import datetime, timedelta
except ModuleNotFoundError:
    os.system('pip install --upgrade pip && pip install -U telethon && pip install psutil && pip install aiohttp && pip install asyncio && pip install aiofiles && pip install pytz && clear')
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

# =============================================
# تنظیمات با توکن ربات (مثل کد خودت)
# =============================================
API_ID = 34996139
API_HASH = "a1f3db16cae2919cfb05e61d1e968b8d"
BOT_TOKEN = "8763155587:AAFyqwUzGx8VuQlfFWhknqfzmjyxM7zinyg"

helperbot = 'SelfRMUu_bot'  # یوزرنیم ربات هلپر خودت

# ایجاد کلاینت با توکن ربات
bot = TelegramClient('self_bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

logging.info("✅ ربات با توکن اجرا شد!")

# =============================================
# تابع دریافت آیدی کاربر (با ریپلی یا مستقیم)
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
# هندلر پیام‌های خروجی (مودهای ادیت متن)
# =============================================
@bot.on(events.NewMessage(outgoing=True))
async def mode(event):
    js = await get('data.json')
    text = event.raw_text
    if text:
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
                await event.edit(text[::-1], parse_mode='HTML')
            elif js['part'] == 'on':
                if len(text) > 1:
                    new = ''
                    for add in text:
                        new += add
                        if add != ' ':
                            await event.edit(new, parse_mode='HTML')
            elif js['mention'] == 'on':
                if event.is_reply:
                    try:
                        getMessage = await event.get_reply_message()
                        get_id = getMessage.sender.id
                        await event.edit(f'<a href=\'tg://openmessage?user_id={get_id}\'>{text}</a>', parse_mode='HTML')
                    except Exception as e:
                        await bot.send_message('me', f'ERROR :\n\n{e}')
        except Exception as e:
            print(e)

# =============================================
# هندلر پیام‌های دریافتی (دشمن، کراش، کامنت)
# =============================================
@bot.on(events.NewMessage())
async def updateMessage(event):
    js = await get('data.json')
    fromid = event.sender_id
    if fromid in js['enemy'] and event.is_private:
        await event.delete()
    elif fromid in js['crash'] and event.is_group:
        try:
            await bot(SendReactionRequest(peer=event.chat_id, msg_id=event.message.id, reaction=[types.ReactionEmoji(emoticon='❤️')]))
        except:
            emoticons = ['🤍', '🖤', '💜', '💙', '💚', '💛', '🧡', '❤️', '🤎', '💖']
            await event.reply(random.choice(emoticons))
        await event.forward_to('me')
    elif js['comment'] == 'on' and event.fwd_from:
        if event.fwd_from.saved_from_peer:
            if event.from_id:
                await event.reply(js['text'])
                print(event)

# =============================================
# هندلر ورود به گروه و امتیاز
# =============================================
@bot.on(events.ChatAction)
async def chatAction(event):
    if event.user_joined:
        if event.action_message.out:
            await event.reply('ɪ\'ᴍ ᴡᴇʟᴄᴏᴍᴇᴅ !')
        else:
            await event.reply('ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴛʜᴇ ɢʀᴏᴜᴘ !')
    elif event.new_score:
        if event.action_message.out:
            await event.reply('😜 رکورد جدیدی رو زدم !')
        else:
            await event.reply('😉 رکورد جدید زدی ولی رکوردت به من نمیرسه !')

# =============================================
# هندلر ادیت پیام در پیوی
# =============================================
@bot.on(events.MessageEdited(outgoing=False, func=lambda e: e.is_private))
async def messageEdited(event):
    if event.message and not event.reactions:
        time = datetime.now(pytz.timezone('Asia/Tehran')).strftime('✐ %H:%M:%S ✎')
        await bot.send_message(event.chat_id, f'<a href=\'tg://openmessage?user_id={event.sender_id}\'>😅 پیامت رو در ساعت {time} ادیت زدی</a>', parse_mode='HTML', reply_to=event.message.id)

# =============================================
# هندلر اکشن‌ها (تایپ، بازی، ...)
# =============================================
@bot.on(events.NewMessage())
async def sendAction(event):
    js = await get('data.json')
    for type in ['typing', 'game', 'voice', 'video', 'sticker']:
        if js[type] == 'on':
            async with bot.action(event.chat_id, type):
                await asyncio.sleep(2)

# =============================================
# دستورات متنی (ربات، راهنما، پنل، دوز، ...)
# =============================================
@bot.on(events.NewMessage(pattern=r'(robot|ربات)', outgoing=True))
async def roBot(event):
    await event.edit('ᴛʜᴇ ʀᴏʙᴏᴛ ɪs ᴏɴ !')

@bot.on(events.NewMessage(pattern=r'(help|راهنما)', outgoing=True))
async def help(event):
    js = await get('data.json')
    help_text = f"""
нelp мeɴυ :

⟩••• ʜᴀsʜᴛᴀɢ : {js['hashtag']}
⟩••• ʙᴏʟᴅ : {js['bold']}
⟩••• ɪᴛᴀʟɪᴄ : {js['italic']}
⟩••• ᴅᴇʟᴇᴛᴇ : {js['delete']}
⟩••• ᴄᴏᴅᴇ : {js['code']}
⟩••• ᴜɴᴅᴇʀʟɪɴᴇ : {js['underline']}
⟩••• ʀᴇᴠᴇʀsᴇ : {js['reverse']}
⟩••• ᴘᴀʀᴛ : {js['part']}
⟩••• ᴍᴇɴᴛɪᴏɴ : {js['mention']}
⟩••• sᴘᴏɪʟᴇʀ : {js['spoiler']}
⟩••• coммeɴт : {js['comment']}
⟩••• тeхт coммeɴт : {js['text']}

⟩••• ᴛʏᴘɪɴɢ : {js['typing']}
⟩••• ɢᴀᴍᴇ : {js['game']}
⟩••• ᴠᴏɪᴄᴇ : {js['voice']}
⟩••• ᴠɪᴅᴇᴏ : {js['video']}
⟩••• sᴛɪᴄᴋᴇʀ : {js['sticker']}

دستورات:
⟩••• hashtag (oɴ|oғғ)
⟩••• bold (oɴ|oғғ)
⟩••• italic (oɴ|oғғ)
⟩••• delete (oɴ|oғғ)
⟩••• code (oɴ|oғғ)
⟩••• underline (oɴ|oғғ)
⟩••• reverse (oɴ|oғғ)
⟩••• part (oɴ|oғғ)
⟩••• mention (oɴ|oғғ)
⟩••• spoiler (oɴ|oғғ)

⟩••• typing (oɴ|oғғ)
⟩••• game (oɴ|oғғ)
⟩••• voice (oɴ|oғғ)
⟩••• video (oɴ|oғғ)
⟩••• sticker (oɴ|oғғ)

⟩••• .comment (oɴ|oғғ)
⟩••• .commentText (тeхт)

⟩••• .addenemy (ιd)
⟩••• .delenemy (ιd)
⟩••• listenemy
⟩••• .addcrash (ιd)
⟩••• .delcrash (ιd)
⟩••• listcrash

⟩••• fun (тeхт)
⟩••• heart
⟩••• tagall
⟩••• tagadmins
⟩••• info (ιd)(reply)
⟩••• status
⟩••• .clean (ιɴт)
"""
    await bot.send_message(event.chat_id, help_text, reply_to=event.message.id)

@bot.on(events.NewMessage(pattern=r'(panel|پنل)', outgoing=True))
async def panel(event):
    await event.edit('⟩••• ᴏᴘᴇɴɪɴɢ ᴛʜᴇ ᴘᴀɴᴇʟ !')
    results = await bot.inline_query(helperbot, 'panel')
    await results[0].click(event.chat_id)

@bot.on(events.NewMessage(pattern=r'(xo|دوز)', outgoing=True))
async def xo(event):
    await event.edit('⟩••• ᴏᴘᴇɴɪɴɢ ᴛʜᴇ xᴏ !')
    results = await bot.inline_query(helperbot, 'xo')
    await results[0].click(event.chat_id)

@bot.on(events.NewMessage(pattern=r'(dice|تاس) (1|2|3|4|5|6)', outgoing=True))
async def dice(event):
    input_str = event.pattern_match.group(2)
    await event.delete()
    send = await bot.send_file(event.chat_id, types.InputMediaDice('🎲'))
    while send.media.value != int(input_str):
        await bot.delete_messages(event.chat_id, send.id)
        send = await bot.send_file(event.chat_id, types.InputMediaDice('🎲'))

@bot.on(events.NewMessage(pattern=r'(fun|فان) (.*)', outgoing=True))
async def fun(event):
    input_str = event.pattern_match.group(2)
    if input_str in 'love':
        emoticons = ['🤍', '🖤', '💜', '💙', '💚', '💛', '🧡', '❤️', '🤎', '💖']
    elif input_str in 'oclock':
        emoticons = ['🕐', '🕑', '🕒', '🕓', '🕔', '🕕', '🕖', '🕗', '🕘', '🕙', '🕚', '🕛', '🕜', '🕝', '🕞', '🕟', '🕠', '🕡', '🕢', '🕣', '🕤', '🕥', '🕦', '🕧']
    elif input_str in 'star':
        emoticons = ['💥', '⚡️', '✨', '🌟', '⭐️', '💫']
    elif input_str in 'snow':
        emoticons = ['❄️', '☃️', '⛄️']
    random.shuffle(emoticons)
    for emoji in emoticons:
        await asyncio.sleep(1)
        await event.edit(emoji)

@bot.on(events.NewMessage(pattern=r'(heart|قلب)', outgoing=True))
async def heart(event):
    for x in range(1, 4):
        for i in range(1, 11):
            await event.edit('➣ ' + str(x) + ' ❦' * i + ' | ' + str(10 * i) + '%')

@bot.on(events.NewMessage(pattern=r'(clean|حذف) (\d+)', outgoing=True))
async def clean(event):
    input_str = event.pattern_match.group(2)
    async for message in bot.iter_messages(event.chat_id, limit=int(input_str)):
        await bot.delete_messages(event.chat_id, message.id)
    await bot.send_message(event.chat_id, f'{input_str} мeѕѕαɢeѕ were deleтe . . . !')

# =============================================
# مدیریت لیست کراش و دشمن
# =============================================
@bot.on(events.NewMessage(pattern=r'(addcrash|افزودن کراش)', outgoing=True))
async def addCrash(event):
    get_id = await get_user_id(event)
    if not get_id:
        return await event.edit('⟩••• ᴄᴀɴ ɴᴏᴛ ғɪɴᴅ ᴛʜɪs ᴜsᴇʀ !')
    js = await get('data.json')
    if get_id in js['crash']:
        await event.edit(f'• [ᴜsᴇʀ](tg://user?id={get_id}) ᴡᴀs ɪɴ crαѕн ʟɪsᴛ !')
    else:
        js['crash'].append(get_id)
        await put('data.json', js)
        await event.edit(f'• [ᴜsᴇʀ](tg://user?id={get_id}) ɴᴏᴡ ɪɴ crαѕн ʟɪsᴛ !')

@bot.on(events.NewMessage(pattern=r'(delcrash|حذف کراش)', outgoing=True))
async def delCrash(event):
    get_id = await get_user_id(event)
    if not get_id:
        return await event.edit('⟩••• ᴄᴀɴ ɴᴏᴛ ғɪɴᴅ ᴛʜɪs ᴜsᴇʀ !')
    js = await get('data.json')
    if get_id in js['crash']:
        js['crash'].remove(get_id)
        await put('data.json', js)
        await event.edit(f'• [ᴜsᴇʀ](tg://user?id={get_id}) ᴅᴇʟᴇᴛᴇᴅ ғʀᴏᴍ crαѕн ʟɪsᴛ !')
    else:
        await event.edit(f'• [ᴜsᴇʀ](tg://user?id={get_id}) ɪs ɴᴏᴛ ɪɴ ᴛʜᴇ crαѕн ʟɪsᴛ !')

@bot.on(events.NewMessage(pattern=r'(listcrash|لیست کراش)', outgoing=True))
async def listCrash(event):
    txt = 'crαѕн ʟɪsᴛ :\n'
    js = await get('data.json')
    for i in js['crash']:
        txt += f'\n• [{i}](tg://user?id={i})'
    await event.edit(txt)

@bot.on(events.NewMessage(pattern=r'(addenemy|افزودن انمی)', outgoing=True))
async def addEnemy(event):
    get_id = await get_user_id(event)
    if not get_id:
        return await event.edit('⟩••• ᴄᴀɴ ɴᴏᴛ ғɪɴᴅ ᴛʜɪs ᴜsᴇʀ !')
    js = await get('data.json')
    if get_id in js['enemy']:
        await event.edit(f'• [ᴜsᴇʀ](tg://user?id={get_id}) ᴡᴀs ɪɴ ᴇɴᴇᴍʏ ʟɪsᴛ !')
    else:
        js['enemy'].append(get_id)
        await put('data.json', js)
        await event.edit(f'• [ᴜsᴇʀ](tg://user?id={get_id}) ɴᴏᴡ ɪɴ ᴇɴᴇᴍʏ ʟɪsᴛ !')

@bot.on(events.NewMessage(pattern=r'(delenemy|حذف انمی)', outgoing=True))
async def delEnemy(event):
    get_id = await get_user_id(event)
    if not get_id:
        return await event.edit('⟩••• ᴄᴀɴ ɴᴏᴛ ғɪɴᴅ ᴛʜɪs ᴜsᴇʀ !')
    js = await get('data.json')
    if get_id in js['enemy']:
        js['enemy'].remove(get_id)
        await put('data.json', js)
        await event.edit(f'• [ᴜsᴇʀ](tg://user?id={get_id}) ᴅᴇʟᴇᴛᴇᴅ ғʀᴏᴍ ᴇɴᴇᴍʏ ʟɪsᴛ !')
    else:
        await event.edit(f'• [ᴜsᴇʀ](tg://user?id={get_id}) ɪs ɴᴏᴛ ɪɴ ᴛʜᴇ ᴇɴᴇᴍʏ ʟɪsᴛ !')

@bot.on(events.NewMessage(pattern=r'(listenemy|لیست انمی)', outgoing=True))
async def listEnemy(event):
    txt = 'ᴇɴᴇᴍʏ ʟɪsᴛ :\n'
    js = await get('data.json')
    for i in js['enemy']:
        txt += f'\n• [{i}](tg://user?id={i})'
    await event.edit(txt)

# =============================================
# دستورات نقطه‌دار
# =============================================
@bot.on(events.NewMessage(pattern=r'\.comment (on|off)', outgoing=True))
async def comment(event):
    input_str = event.pattern_match.group(1)
    js = await get('data.json')
    js['comment'] = str(input_str)
    await put('data.json', js)
    await event.edit(f'⟩••• ᴛʜᴇ coммeɴт ɴᴏᴡ ɪs {input_str}')

@bot.on(events.NewMessage(pattern=r'\.commentText (.*)', outgoing=True))
async def commentText(event):
    input_str = event.pattern_match.group(1)
    js = await get('data.json')
    js['text'] = str(input_str)
    await put('data.json', js)
    await event.edit(f'⟩••• ᴛʜᴇ coммeɴт тeхт ɴᴏᴡ ɪs {input_str}')

# =============================================
# تگ کردن
# =============================================
@bot.on(events.NewMessage(pattern=r'(tagall|تگ)', outgoing=True, func=lambda e: e.is_group))
async def tagAll(event):
    mentions = '✅ آخرین افراد آنلاین گروه'
    chat = await event.get_input_chat()
    async for x in bot.iter_participants(chat, 100):
        mentions += f'\n [{x.first_name}](tg://user?id={x.id})'
    await event.reply(mentions)
    await event.delete()

@bot.on(events.NewMessage(pattern=r'(tagadmins|تگ ادمین ها)', outgoing=True, func=lambda e: e.is_group))
async def tagAdmins(event):
    mentions = '⚡️ تگ کردن ادمین ها'
    chat = await event.get_input_chat()
    async for x in bot.iter_participants(chat, filter=types.ChannelParticipantsAdmins):
        mentions += f'\n [{x.first_name}](tg://user?id={x.id})'
    await event.reply(mentions)
    await event.delete()

# =============================================
# گزارش به ادمین
# =============================================
@bot.on(events.NewMessage(pattern=r'(report|گزارش)', func=lambda e: e.is_group and e.is_reply))
async def report(event):
    mentions = 'ʏᴏᴜʀ ʀᴇᴘᴏʀᴛ ʜᴀs ʙᴇᴇɴ sᴜᴄᴄᴇssғᴜʟʟʏ sᴜʙᴍɪᴛᴛᴇᴅ !'
    chat = await event.get_input_chat()
    async for x in bot.iter_participants(chat, filter=types.ChannelParticipantsAdmins):
        mentions += u'[\u2066]' + f'(tg://user?id={x.id})'
    await event.reply(mentions)

# =============================================
# اطلاعات کاربر
# =============================================
@bot.on(events.NewMessage(pattern=r'(info|اطلاعات)', outgoing=True))
async def info(event):
    get_id = await get_user_id(event)
    if not get_id:
        return await event.edit('⟩••• ᴄᴀɴ ɴᴏᴛ ғɪɴᴅ ᴛʜɪs ᴜsᴇʀ !')
    full = await bot(GetFullUserRequest(get_id))
    first_name = full.users[0].first_name
    last_name = full.users[0].last_name
    username = full.users[0].username
    phone = full.users[0].phone
    about = full.full_user.about
    photos = await bot.get_profile_photos(get_id)
    time = datetime.now(pytz.timezone('Asia/Tehran')).strftime('ᴛɪᴍᴇ : %H:%M:%S')
    txt = f'υѕer ιd : {get_id}\nғιrѕт ɴαмe : {first_name}\nlαѕт ɴαмe : {last_name}\nυѕerɴαмe : {username}\npнoɴe : {phone}\nвιo : {about}\n{time}'
    if photos:
        await event.delete()
        await bot.send_message(event.chat_id, txt, file=photos[0])
    else:
        await event.edit(txt)

# =============================================
# وضعیت کلی
# =============================================
@bot.on(events.NewMessage(pattern=r'(status|وضعیت)', outgoing=True))
async def status(event):
    private_chats = 0
    bots = 0
    groups = 0
    broadcast_channels = 0
    admin_in_groups = 0
    creator_in_groups = 0
    admin_in_broadcast_channels = 0
    creator_in_channels = 0
    unread_mentions = 0
    unread = 0
    largest_group_member_count = 0
    largest_group_with_admin = 0
    async for dialog in bot.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, types.Channel):
            if entity.broadcast:
                broadcast_channels += 1
                if entity.creator or entity.admin_rights:
                    admin_in_broadcast_channels += 1
                if entity.creator:
                    creator_in_channels += 1
            elif entity.megagroup:
                groups += 1
                if entity.creator or entity.admin_rights:
                    admin_in_groups += 1
                if entity.creator:
                    creator_in_groups += 1
        elif isinstance(entity, types.User):
            private_chats += 1
            if entity.bot:
                bots += 1
        elif isinstance(entity, types.Chat):
            groups += 1
            if entity.creator or entity.admin_rights:
                admin_in_groups += 1
            if entity.creator:
                creator_in_groups += 1
        unread_mentions += dialog.unread_mentions_count
        unread += dialog.unread_count
    txt = f'ѕтαтυѕ !'
    txt += f'\nᴘʀɪᴠᴀᴛᴇ ᴄʜᴀᴛs : {private_chats}'
    txt += f'\nʙᴏᴛs : {bots}'
    txt += f'\nɢʀᴏᴜᴘs : {groups}'
    txt += f'\nʙʀᴏᴀᴅᴄᴀsᴛ ᴄʜᴀɴɴᴇʟs : {broadcast_channels}'
    txt += f'\nᴀᴅᴍɪɴ ɪɴ ɢʀᴏᴜᴘs : {admin_in_groups}'
    txt += f'\nᴄʀᴇᴀᴛᴏʀ ɪɴ ɢʀᴏᴜᴘs : {creator_in_groups}'
    txt += f'\nᴀᴅᴍɪɴ ɪɴ ʙʀᴏᴀᴅᴄᴀsᴛ ᴄʜᴀɴɴᴇʟs : {admin_in_broadcast_channels}'
    txt += f'\nᴄʀᴇᴀᴛᴏʀ ɪɴ ᴄʜᴀɴɴᴇʟs : {creator_in_channels}'
    txt += f'\nᴜɴʀᴇᴀᴅ ᴍᴇɴᴛɪᴏɴs : {unread_mentions}'
    txt += f'\nᴜɴʀᴇᴀᴅ : {unread}'
    txt += f'\nʟᴀʀɢᴇsᴛ ɢʀᴏᴜᴘ ᴍᴇᴍʙᴇʀ ᴄᴏᴜɴᴛ : {largest_group_member_count}'
    txt += f'\nʟᴀʀɢᴇsᴛ ɢʀᴏᴜᴘ ᴡɪᴛʜ ᴀᴅᴍɪɴ : {largest_group_with_admin}'
    await event.edit(txt)

# =============================================
# دستورات اکشن
# =============================================
@bot.on(events.NewMessage(pattern=r'(hashtag|bold|italic|delete|code|underline|reverse|part|mention|spoiler) (on|off)', outgoing=True))
async def editMode(event):
    match = event.raw_text.split(' ')
    js = await get('data.json')
    js[match[0]] = str(match[1])
    await put('data.json', js)
    mode = font(match[0])
    await event.edit(f'⟩••• ᴛʜᴇ {mode} ᴍᴏᴅᴇ ɴᴏᴡ ɪs {match[1]}')

@bot.on(events.NewMessage(pattern=r'(typing|game|voice|video|sticker) (on|off)', outgoing=True))
async def editAction(event):
    match = event.raw_text.split(' ')
    js = await get('data.json')
    js[match[0]] = str(match[1])
    await put('data.json', js)
    action = font(match[0])
    await event.edit(f'⟩••• ᴛʜᴇ {action} αcтιoɴ ɴᴏᴡ ɪs {match[1]}')

# =============================================
# ریستارت
# =============================================
@bot.on(events.NewMessage(pattern=r'(restart|ریستارت)', outgoing=True))
async def restart(event):
    await event.edit(f'⟩••• ʀᴇsᴛᴀʀᴛᴇᴅ . . . !')
    pid = os.getpid()
    filename = __file__.split('/')[-1]
    os.system(f'kill -9 {pid} && python3 {filename}')

# =============================================
# اجرا
# =============================================
logging.info("✅ سلف‌بات با توکن ربات اجرا شد!")
bot.run_until_disconnected()
