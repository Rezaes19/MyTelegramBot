import subprocess
import sys
import os

# ====== نصب خودکار telethon در زمان اجرا ======
def install_telethon():
    try:
        import telethon
        print("✅ telethon already installed")
        return True
    except ImportError:
        print("📦 Installing telethon...")
        try:
            # نصب با pip
            subprocess.check_call([sys.executable, "-m", "pip", "install", "telethon==1.34.0", "--no-cache-dir"])
            print("✅ telethon installed successfully")
            return True
        except Exception as e:
            print(f"❌ Failed to install telethon: {e}")
            return False

# نصب قبل از هر چیزی
if not install_telethon():
    print("❌ Cannot continue without telethon")
    sys.exit(1)

# حالا می‌توانیم import کنیم
import asyncio
import sqlite3
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError, UserNotParticipantError, PeerIdInvalidError, RPCError
import re
import random
import time
import glob
import json
from datetime import datetime, timedelta
import locale

try:
    locale.setlocale(locale.LC_ALL, 'fa_IR.UTF-8')
except:
    try:
        locale.setlocale(locale.LC_ALL, 'fa_IR')
    except:
        pass

# ====== تنظیمات ربات ======
API_ID = 34996139
API_HASH = 'a1f3db16cae2919cfb05e61d1e968b8d'
BOT_TOKEN = '8858887304:AAELneONarg-zYTRBAWocRV9NO9xRzodFFg'

# ====== لیست ادمین‌ها ======
ADMINS = [6691993264, 7831049189]  # اصلاح شد

GROUP_INSTALL_TARGET_ID = 7831049189
SELF_PRICE = 1440

active_games = {}
BOT_IMAGE_PATH = '1782502761872.jpg'

# ====== بقیه کد شما ======
if not os.path.exists('database_users'):
    os.makedirs('database_users')

def get_user_db(user_id):
    return sqlite3.connect(f'database_users/user_{user_id}.db')

def init_user_db(user_id):
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('PRAGMA foreign_keys = ON')
    cursor.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 0, banned INTEGER DEFAULT 0, invited_by INTEGER DEFAULT 0, self_start_time INTEGER DEFAULT 0)')
    try:
        cursor.execute('ALTER TABLE users ADD COLUMN self_start_time INTEGER DEFAULT 0')
    except: pass
    cursor.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
    cursor.execute('CREATE TABLE IF NOT EXISTS self_sessions (session_string TEXT, sub_type INTEGER, is_active INTEGER DEFAULT 1, start_time INTEGER DEFAULT 0)')
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

def save_self_session(user_id, session_string, sub_type):
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('UPDATE self_sessions SET is_active = 0')
    cursor.execute('INSERT INTO self_sessions (session_string, sub_type, is_active, start_time) VALUES (?, ?, 1, ?)', (session_string, sub_type, int(time.time())))
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
    except:
        return False

def stop_self_py(user_id):
    try:
        subprocess.run(['pkill', '-f', f'self.py.*{user_id}'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except:
        return True

def get_all_active_sessions():
    sessions = []
    for db_file in glob.glob('database_users/user_*.db'):
        try:
            match = re.search(r'user_(\d+)\.db', db_file)
            if match:
                user_id = int(match.group(1))
                db = sqlite3.connect(db_file)
                cursor = db.cursor()
                cursor.execute('SELECT session_string, sub_type FROM self_sessions WHERE is_active = 1')
                result = cursor.fetchone()
                db.close()
                if result:
                    sessions.append((user_id, result[0], result[1]))
        except:
            continue
    return sessions

async def restart_all_selfs():
    sessions = get_all_active_sessions()
    restart_count = 0
    for user_id, session_string, sub_type in sessions:
        stop_self_py(user_id)
        await asyncio.sleep(0.5)
        if run_self_py(session_string, sub_type, user_id):
            restart_count += 1
    return restart_count

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
        time_info = f"\n⏱ آمار سلف: {days} روز و {hours} ساعت"
    else:
        time_info = ""
    return f"👤 **اطلاعات حساب شما**\n\n🆔 **آیدی عددی :** `{user_id}`\n\n💎 **موجودی :** `{balance:,}` الماس\n\n🔐 **وضعیت سلف :** `{has_active_self}`{time_info}"

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
            await bot.delete_messages(chat_id, message_id)
            await bot.send_message(organizer_id, f'❌ نبرد الماس با تعداد {amount:,} الماس در گروه به دلیل عدم حضور حریف در طول ۵ دقیقه لغو شد. تعداد {amount:,} الماس به حساب شما برگشت داده شد.')
        except:
            pass
        del active_games[game_key]

async def handle_game_cancel(chat_id, message_id, organizer_id, event_to_edit):
    game_key = (chat_id, message_id)
    if game_key in active_games:
        active_games[game_key]['timer'].cancel()
        amount = active_games[game_key]['amount']
        db = get_user_db(organizer_id)
        cursor = db.cursor()
        cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, organizer_id))
        db.commit()
        db.close()
        try:
            await bot.delete_messages(chat_id, message_id)
            await bot.send_message(organizer_id, f'❌ نبرد الماس با تعداد {amount:,} الماس لغو شد. تعداد {amount:,} الماس به حساب شما برگشت داده شد.')
        except:
            try:
                await event_to_edit.edit('❌ نبرد الماس با موفقیت لغو و تعداد الماس بسته شده به حساب شما بازگشت داده شد.')
            except:
                pass
        del active_games[game_key]
        return True
    return False

# ایجاد دیتابیس برای همه ادمین‌ها
for admin_id in ADMINS:
    init_user_db(admin_id)

bot = TelegramClient('bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

user_clients = {}
user_purchase_amount = {}

async def get_user_display(user_id):
    try:
        entity = await bot.get_entity(user_id)
        if hasattr(entity, 'username') and entity.username:
            return f"@{entity.username}"
        else:
            name = entity.first_name or "کاربر"
            return name[:18] + "..." if len(name) > 20 else name
    except:
        return "کاربر"

async def code_timer(user_id):
    await asyncio.sleep(60)
    if user_id in user_clients and user_clients[user_id].get('step') == 'code':
        await bot.send_message(user_id, '⏰ زمان کد ورود به پایان رسید.')
        try:
            client = user_clients[user_id].get('client')
            if client:
                await client.disconnect()
        except:
            pass
        finally:
            if user_id in user_clients:
                del user_clients[user_id]

async def handle_login_success(user_id, sub_type):
    client = user_clients[user_id]['client']
    session_string = client.session.save()
    if not session_string or session_string.strip() == '':
        await bot.send_message(user_id, '❌ خطا: سشن استرینگ ایجاد نشده یا نامعتبر است.')
        try:
            await client.disconnect()
        except:
            pass
        finally:
            if user_id in user_clients:
                del user_clients[user_id]
        return
    success = run_self_py(session_string, sub_type, user_id)
    if success:
        save_self_session(user_id, session_string, sub_type)
        db = get_user_db(user_id)
        cursor = db.cursor()
        cursor.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (SELF_PRICE, user_id))
        db.commit()
        db.close()
        data_db_path = f'database_users/data_{user_id}.db'
        if not os.path.exists(data_db_path):
            conn = sqlite3.connect(data_db_path)
            cursor = conn.cursor()
            cursor.execute('''CREATE TABLE IF NOT EXISTS SELF(time json, time_int_name json, time_int_bio json, mode json, action json, gpt varchar(3), answer varchar(3), lockpv json, enemy_list json, mute_list json, answer_list json, insult_list json, lang varchar(10))''')
            cursor.execute("INSERT INTO SELF (time) VALUES (?)", (json.dumps({'time_name':'on','time_bio':'off'}),))
            conn.commit()
            conn.close()
        await bot.send_message(user_id, f'✅ سلف با موفقیت فعال شد!\n💎 {SELF_PRICE:,} الماس از حساب شما کسر شد.')
    else:
        await bot.send_message(user_id, '❌ خطا در راه اندازی سلف. لطفاً به مالک ( @L0MB0 ) گزارش دهید.')
    try:
        await client.disconnect()
    except:
        pass
    if user_id in user_clients:
        del user_clients[user_id]

# ====== بقیه هندلرها ======
@bot.on(events.NewMessage)
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
            entity = await bot.get_entity(chat_id)
            if entity.megagroup or entity.gigagroup:
                await event.reply(f'✅ ربات سلف الماس در گروه نصب شد.')
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
        message = f"🎖️ **موجودی الماس**"
        buttons = [[Button.inline(f'💎 {balance:,}', f'balance_show_{target_user_id}')]]
        if os.path.exists(BOT_IMAGE_PATH):
            await bot.send_file(event.chat_id, BOT_IMAGE_PATH, caption=message, buttons=buttons, parse_mode='md', reply_to=event.id)
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
        game_text = f"⚔️ **نبرد الماس**\n\n👤 **برگزار کننده :** {organizer_mention}\n💰 **مبلغ نبرد :** {amount:,} الماس\n🏆 **جایزه کل :** {amount * 2:,} الماس\n\n📌 جهت پیوستن به نبرد الماس لطفا روی دکمه زیر کلیک کنید."
        buttons = [[Button.inline('⚔️ پیوستن به نبرد', f'game_join_{amount}_{organizer_id}'.encode())], [Button.inline('❌ لغو نبرد', f'game_cancel_{amount}_{organizer_id}'.encode())]]
        if os.path.exists(BOT_IMAGE_PATH):
            sent_message = await bot.send_file(event.chat_id, BOT_IMAGE_PATH, caption=game_text, buttons=buttons, parse_mode='md', reply_to=event.id)
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
        transfer_message = f"✅ **انتقال الماس انجام شد.**\n\n👤 **از:** `{sender_id}`\n👥 **به:** `{receiver_id}`\n💎 **مبلغ انتقال (خالص):** {amount:,}\n🧾 **مالیات (۱۰%):** {tax:,}\n📉 **مجموع کسر از فرستنده:** {total_deduct:,}\n✨ **موجودی جدید فرستنده:** {new_sender_balance:,}\n✨ **موجودی جدید گیرنده:** {new_receiver_balance:,}"
        await event.reply(transfer_message, parse_mode='md')
        return

@bot.on(events.CallbackQuery)
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
        message = f"🎖️ **موجودی الماس**"
        buttons = [[Button.inline(f'💎 {balance:,}', f'balance_show_{user_id}')]]
        await event.edit(message, buttons=buttons, parse_mode='md')
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
        result_text = f"◈ ━━━ 𝐕𝐈𝐏 𝐌𝐦𝐝 ━━━ ◈\n𝐕𝐈𝐏 | نتیجه بازی :\n𝐕𝐈𝐏 | برنده : {winner_name}\n𝐕𝐈𝐏 | بازنده : {loser_name}\n𝐕𝐈𝐏 | جایزه: {prize:,} الماس\n𝐕𝐈𝐏 | مالیات: {tax:,} الماس\n◈ ━━━ 𝐕𝐈𝐏 𝐌𝐦𝐝 ━━━ ◈"
        try:
            await bot.delete_messages(event.chat_id, event.message_id)
        except:
            pass
        if os.path.exists(BOT_IMAGE_PATH):
            await bot.send_file(event.chat_id, BOT_IMAGE_PATH, caption=result_text, parse_mode='md')
        else:
            await bot.send_message(event.chat_id, result_text, parse_mode='md')
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
                await bot.delete_messages(event.chat_id, event.message_id)
                await bot.send_message(organizer_id, f'❌ نبرد الماس با تعداد {amount:,} الماس لغو شد. تعداد {amount:,} الماس به حساب شما برگشت داده شد.')
            except:
                pass
            del active_games[game_key]
            await event.answer("✅ نبرد لغو شد!")
        else:
            await event.answer("❌ این نبرد قبلاً به پایان رسیده یا لغو شده است!", alert=True)
        return

async def show_self_menu(event, user_id):
    session_data = get_self_session(user_id)
    if not session_data:
        db = get_user_db(user_id)
        cursor = db.cursor()
        cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        balance = result[0] if result else 0
        db.close()
        if balance < SELF_PRICE:
            await event.reply(f'❌ موجودی شما برای فعال‌سازی سلف کافی نیست.\n\n💎 موجودی: {balance:,}\n💎 هزینه سلف: {SELF_PRICE:,}')
            return
        await event.reply('📱 لطفاً شماره تلفن خود را به صورت زیر وارد کنید:\n\n`+989123456789`')
        user_clients[user_id] = {'step': 'phone'}
        return
    session_string, sub_type, start_time = session_data
    elapsed_time = int(time.time()) - start_time
    days = elapsed_time // 86400
    hours = (elapsed_time % 86400) // 3600
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    balance = result[0] if result else 0
    db.close()
    remaining_hours = balance // 2
    data_db_path = f'database_users/data_{user_id}.db'
    time_status = "غیرفعال ❌"
    if os.path.exists(data_db_path):
        try:
            conn = sqlite3.connect(data_db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT time FROM SELF')
            result = cursor.fetchone()
            conn.close()
            if result:
                time_data = json.loads(result[0])
                if time_data.get('time_name') == 'on':
                    time_status = "فعال ✅"
        except:
            pass
    status_text = f"⚙️ **مدیریت سلف**\n\n⏱ **مدت زمان فعال بودن:** {days} روز و {hours} ساعت\n💎 **موجودی الماس:** {balance:,}\n⏳ **زمان باقی مانده:** {remaining_hours} ساعت\n🕐 **ساعت در کنار اسم:** {time_status}\n\n📌 **تنظیمات:**"
    buttons = [[Button.inline('🕐 فعال/غیرفعال ساعت کنار اسم', b'toggle_time_name')], [Button.inline('🔓 غیرفعال‌سازی سلف', b'disable_self')], [Button.inline('🔙 برگشت', b'back')]]
    try:
        await event.edit(status_text, buttons=buttons, parse_mode='md')
        await event.answer()
    except Exception as e:
        print(f"Error editing manage self: {e}")

@bot.on(events.CallbackQuery(data=b'toggle_time_name'))
async def toggle_time_name(event):
    user_id = event.sender_id
    data_db_path = f'database_users/data_{user_id}.db'
    if not os.path.exists(data_db_path):
        await event.answer('❌ دیتابیس سلف پیدا نشد!', alert=True)
        return
    try:
        conn = sqlite3.connect(data_db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT time FROM SELF')
        result = cursor.fetchone()
        if result:
            time_data = json.loads(result[0])
            current_status = time_data.get('time_name', 'off')
            new_status = 'off' if current_status == 'on' else 'on'
            time_data['time_name'] = new_status
            cursor.execute('UPDATE SELF SET time = ?', (json.dumps(time_data),))
            conn.commit()
            conn.close()
            status_text = "فعال ✅" if new_status == 'on' else "غیرفعال ❌"
            await event.answer(f'🕐 ساعت کنار اسم: {status_text}', alert=False)
            session_data = get_self_session(user_id)
            if session_data:
                session_string, sub_type, _ = session_data
                stop_self_py(user_id)
                await asyncio.sleep(1)
                run_self_py(session_string, sub_type, user_id)
            await show_self_menu(event, user_id)
        else:
            conn.close()
            await event.answer('❌ خطا در تنظیمات!', alert=True)
    except Exception as e:
        print(f"Error toggling time name: {e}")
        await event.answer('❌ خطا در تغییر تنظیمات!', alert=True)

@bot.on(events.CallbackQuery(data=b'disable_self'))
async def disable_self(event):
    user_id = event.sender_id
    deactivate_self_session(user_id)
    stop_self_py(user_id)
    try:
        await event.edit('✅ سلف با موفقیت خاموش شد.')
        await event.answer('✅ سلف خاموش شد.')
    except Exception as e:
        print(f"Error editing disable self: {e}")
    await back(event)

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
        buttons = [[Button.inline('💎 خرید سلف', b'buy_self')], [Button.inline('👤 حساب کاربری', b'user_account'), Button.inline('⚙️ مدیریت سلف', b'manage_self')], [Button.inline('👥 زیرمجموعه گیری', b'referral_system')]]
        if user_id in ADMINS:
            buttons.append([Button.inline('🛠 پنل مدیریت', b'admin_panel')])
        if os.path.exists(BOT_IMAGE_PATH):
            await bot.send_file(user_id, BOT_IMAGE_PATH, caption='به سلف ساز خوش آمدید', buttons=buttons)
        else:
            await event.reply('به سلف ساز خوش آمدید', buttons=buttons)
        return
    if user_id in user_clients and user_clients[user_id].get('step') == 'receipt':
        if event.photo:
            receipt_path = None
            try:
                receipt_path = await event.download_media()
                sender = event.sender
                user_info = f"آیدی: {user_id}\nنام: {sender.first_name}\nیوزرنیم: @{sender.username if sender.username else 'ندارد'}"
                amount = user_clients[user_id]['amount']
                black_amount = user_clients[user_id]['black_amount']
                buttons = [[Button.inline('تایید پرداخت', f'confirm_{user_id}_{amount}_{black_amount}'.encode())], [Button.inline('رد پرداخت', f'reject_{user_id}_{amount}'.encode())]]
                invoice_text = f"""فاکتور خرید موجودی\n\n{user_info}\n\nتعداد الماس: {black_amount:,}\nمبلغ: {amount:,} تومان\nتاریخ: {event.date.strftime('%Y/%m/%d %H:%M')}\n\nرسید پرداخت:"""
                await bot.send_message(ADMINS[0], invoice_text, file=receipt_path, buttons=buttons)
                await event.reply('فاکتور شما برای مالک ارسال شد. منتظر تأیید باشید.')
            except Exception as e:
                print(f"Error sending receipt: {e}")
                await event.reply('خطا در ارسال فاکتور. لطفاً با پشتیبانی تماس بگیرید.')
            finally:
                if receipt_path and os.path.exists(receipt_path):
                    os.remove(receipt_path)
                if user_id in user_clients:
                    del user_clients[user_id]
        else:
            await event.reply('لطفاً عکس فیش واریزی را ارسال نمایید.')
        return
    if user_id not in user_clients:
        return
    step = user_clients[user_id].get('step')
    if step == 'phone':
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
        user_clients[user_id].update({'client': client, 'phone': phone, 'step': 'code', 'timer': asyncio.create_task(code_timer(user_id))})
        await event.reply('کد ورود را به فرمت 1.3.8.8.3.1 وارد کنید:')
    elif step == 'code':
        code = text.replace('.', '')
        client = user_clients[user_id]['client']
        if 'timer' in user_clients[user_id]:
            user_clients[user_id]['timer'].cancel()
        try:
            await client.sign_in(user_clients[user_id]['phone'], code)
            await handle_login_success(user_id, user_clients[user_id]['sub_type'])
        except SessionPasswordNeededError:
            user_clients[user_id]['step'] = 'password'
            await event.reply('رمز دو مرحله ای را وارد کنید:')
        except PhoneCodeInvalidError:
            await event.reply('کد وارد شده اشتباه میباشد ، #لطفا مجدد تلاش کنید.')
            if 'client' in user_clients[user_id]:
                try:
                    await user_clients[user_id]['client'].disconnect()
                except:
                    pass
            del user_clients[user_id]
        except Exception as e:
            await event.reply(f'خطا: {e}')
            try:
                await client.disconnect()
            except:
                pass
            del user_clients[user_id]
    elif step == 'password':
        password = text
        client = user_clients[user_id]['client']
        try:
            await client.sign_in(password=password)
            await handle_login_success(user_id, user_clients[user_id]['sub_type'])
        except Exception as e:
            await event.reply(f'رمز اشتباه است: {e}')
            try:
                await client.disconnect()
            except:
                pass
            del user_clients[user_id]
    elif user_id in ADMINS:
        if step == 'add_balance_user':
            try:
                target_id = int(text.strip())
                user_clients[user_id]['target_id'] = target_id
                user_clients[user_id]['step'] = 'add_balance_amount'
                await event.reply('💎 لطفاً مقدار الماس مورد نظر را وارد کنید:')
            except ValueError:
                await event.reply('❌ آیدی عددی نامعتبر است. لطفاً مجدد تلاش کنید.')
                user_clients[user_id]['step'] = 'add_balance_user'
        elif step == 'add_balance_amount':
            try:
                amount = int(text.strip())
                if amount <= 0:
                    await event.reply('❌ مقدار باید بیشتر از صفر باشد.')
                    return
                target_id = user_clients[user_id]['target_id']
                init_user_db(target_id)
                db = get_user_db(target_id)
                cursor = db.cursor()
                cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, target_id))
                db.commit()
                db.close()
                await event.reply(f'✅ {amount:,} الماس با موفقیت به کاربر {target_id} اضافه شد.')
                del user_clients[user_id]
                await send_admin_panel(event, user_id)
            except ValueError:
                await event.reply('❌ مقدار نامعتبر است. لطفاً یک عدد وارد کنید.')
        elif step == 'ban_user':
            try:
                target_id = int(text.strip())
                init_user_db(target_id)
                db = get_user_db(target_id)
                cursor = db.cursor()
                cursor.execute('UPDATE users SET banned = 1 WHERE user_id = ?', (target_id,))
                db.commit()
                db.close()
                await event.reply(f'✅ کاربر {target_id} با موفقیت مسدود شد.')
                del user_clients[user_id]
                await send_admin_panel(event, user_id)
            except ValueError:
                await event.reply('❌ آیدی عددی نامعتبر است. لطفاً مجدد تلاش کنید.')
                user_clients[user_id]['step'] = 'ban_user'

@bot.on(events.CallbackQuery(data=b'buy_self'))
async def buy_self(event):
    user_id = event.sender_id
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('SELECT banned FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    db.close()
    if result and result[0] == 1:
        await event.answer('🚫 شما توسط ادمین مسدود شده‌اید!', alert=True)
        return
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    balance = result[0] if result else 0
    db.close()
    if balance < SELF_PRICE:
        await event.answer(f'❌ الماس کافی ندارید!\n💎 الماس شما: {balance:,}\n💎 الماس مورد نیاز: {SELF_PRICE:,}', alert=True)
        return
    await event.edit(f'📱 لطفاً شماره اکانت خود را برای فعال‌سازی سلف ارسال نمایید (با + شروع شود):\n\n💎 هزینه فعال‌سازی: {SELF_PRICE:,} الماس')
    user_clients[user_id] = {'step': 'phone', 'sub_type': 0}

@bot.on(events.CallbackQuery(data=b'back'))
async def back(event):
    user_id = event.sender_id
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('SELECT banned FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    db.close()
    if result and result[0] == 1:
        await event.answer('🚫 شما توسط ادمین مسدود شده‌اید!', alert=True)
        return
    if user_id in user_clients and user_clients[user_id].get('step') in ['ban', 'unban', 'set_channel', 'set_card', 'add_balance_user', 'add_balance_amount']:
        del user_clients[user_id]
    buttons = [[Button.inline('💎 خرید سلف', b'buy_self')], [Button.inline('👤 حساب کاربری', b'user_account'), Button.inline('⚙️ مدیریت سلف', b'manage_self')], [Button.inline('👥 زیرمجموعه گیری', b'referral_system')]]
    if user_id in ADMINS:
        buttons.append([Button.inline('🛠 پنل مدیریت', b'admin_panel')])
    if os.path.exists(BOT_IMAGE_PATH):
        await bot.send_file(user_id, BOT_IMAGE_PATH, caption='به سلف ساز خوش آمدید', buttons=buttons)
    else:
        await event.edit('به سلف ساز خوش آمدید', buttons=buttons)

@bot.on(events.CallbackQuery(data=b'user_account'))
async def user_account(event):
    user_id = event.sender_id
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('SELECT banned FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    db.close()
    if result and result[0] == 1:
        await event.answer('🚫 شما توسط ادمین مسدود شده‌اید!', alert=True)
        return
    account_text = await get_user_info_for_group(user_id)
    buttons = [[Button.inline('💳 خرید موجودی', b'buy_balance_menu')], [Button.inline('🔙 برگشت', b'back')]]
    try:
        await event.edit(account_text, buttons=buttons, parse_mode='md')
    except Exception as e:
        print(f"Error editing user account: {e}")

@bot.on(events.CallbackQuery(data=b'manage_self'))
async def manage_self(event):
    user_id = event.sender_id
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('SELECT banned FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    db.close()
    if result and result[0] == 1:
        await event.answer('🚫 شما توسط ادمین مسدود شده‌اید!', alert=True)
        return
    await show_self_menu(event, user_id)

@bot.on(events.CallbackQuery(data=b'referral_system'))
async def referral_system(event):
    user_id = event.sender_id
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('SELECT banned FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    db.close()
    if result and result[0] == 1:
        await event.answer('🚫 شما توسط ادمین مسدود شده‌اید!', alert=True)
        return
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ?', (user_id,))
    total_referrals = cursor.fetchone()[0]
    db.close()
    bot_username = (await bot.get_me()).username
    referral_link = f"https://t.me/{bot_username}?start={user_id}"
    referral_text = f"👥 **سیستم زیرمجموعه گیری**\n\nبا دعوت دوستان خود به ربات، ۲۵ الماس دریافت کنید.\n\n📊 **کل دعوتی‌ها:** {total_referrals}\n🎁 **پاداش هر نفر:** ۲۵ الماس\n\n🔗 **لینک دعوت:** \n`{referral_link}`"
    buttons = [[Button.inline('🔙 برگشت', b'back')]]
    try:
        await event.edit(referral_text, buttons=buttons, parse_mode='md')
    except Exception as e:
        print(f"Error editing referral system: {e}")

@bot.on(events.CallbackQuery(data=b'buy_balance_menu'))
async def buy_balance_menu(event):
    user_id = event.sender_id
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('SELECT banned FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    db.close()
    if result and result[0] == 1:
        await event.answer('🚫 شما توسط ادمین مسدود شده‌اید!', alert=True)
        return
    if user_id not in user_purchase_amount or isinstance(user_purchase_amount.get(user_id), dict):
        user_purchase_amount[user_id] = '0'
    current_amount = user_purchase_amount.get(user_id, '0')
    try:
        black_amount = int(current_amount)
    except ValueError:
        black_amount = 0
        user_purchase_amount[user_id] = '0'
    amount = black_amount * 40
    buttons = [[Button.inline('1', b'num_1'), Button.inline('2', b'num_2'), Button.inline('3', b'num_3')], [Button.inline('4', b'num_4'), Button.inline('5', b'num_5'), Button.inline('6', b'num_6')], [Button.inline('7', b'num_7'), Button.inline('8', b'num_8'), Button.inline('9', b'num_9')], [Button.inline('0', b'num_0'), Button.inline('۰۰', b'num_00')], [Button.inline('تایید', b'confirm_amount'), Button.inline('حذف', b'clear_amount')], [Button.inline('🔙 برگشت', b'back')]]
    display_text = f"💳 **خرید موجودی**\n\nتعداد الماس: {black_amount:,}\nمبلغ: {amount:,} تومان\n\nلطفاً تعداد الماس مورد نظر را انتخاب کنید:"
    try:
        await event.edit(display_text, buttons=buttons, parse_mode='md')
    except Exception as e:
        print(f"Error editing buy balance menu: {e}")

@bot.on(events.CallbackQuery(pattern=b'num_(.+)$'))
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
    buttons = [[Button.inline('1', b'num_1'), Button.inline('2', b'num_2'), Button.inline('3', b'num_3')], [Button.inline('4', b'num_4'), Button.inline('5', b'num_5'), Button.inline('6', b'num_6')], [Button.inline('7', b'num_7'), Button.inline('8', b'num_8'), Button.inline('9', b'num_9')], [Button.inline('0', b'num_0'), Button.inline('۰۰', b'num_00')], [Button.inline('تایید', b'confirm_amount'), Button.inline('حذف', b'clear_amount')], [Button.inline('🔙 برگشت', b'back')]]
    current_amount_str = user_purchase_amount.get(user_id, '0')
    if isinstance(current_amount_str, dict):
        current_amount_str = '0'
    try:
        black_amount = int(current_amount_str)
    except ValueError:
        black_amount = 0
    amount = black_amount * 40
    display_text = f"💳 **خرید موجودی**\n\nتعداد الماس: {black_amount:,}\nمبلغ: {amount:,} تومان\n\nلطفاً تعداد الماس مورد نظر را انتخاب کنید:"
    try:
        await event.edit(display_text, buttons=buttons, parse_mode='md')
        await event.answer()
    except Exception as e:
        print(f"Error editing number input: {e}")

@bot.on(events.CallbackQuery(data=b'clear_amount'))
async def clear_amount(event):
    user_id = event.sender_id
    user_purchase_amount[user_id] = '0'
    buttons = [[Button.inline('1', b'num_1'), Button.inline('2', b'num_2'), Button.inline('3', b'num_3')], [Button.inline('4', b'num_4'), Button.inline('5', b'num_5'), Button.inline('6', b'num_6')], [Button.inline('7', b'num_7'), Button.inline('8', b'num_8'), Button.inline('9', b'num_9')], [Button.inline('0', b'num_0'), Button.inline('۰۰', b'num_00')], [Button.inline('تایید', b'confirm_amount'), Button.inline('حذف', b'clear_amount')], [Button.inline('🔙 برگشت', b'back')]]
    display_text = f"💳 **خرید موجودی**\n\nتعداد الماس: 0\nمبلغ: 0 تومان\n\nلطفاً تعداد الماس مورد نظر را انتخاب کنید:"
    try:
        await event.edit(display_text, buttons=buttons, parse_mode='md')
        await event.answer()
    except Exception as e:
        print(f"Error editing clear amount: {e}")

@bot.on(events.CallbackQuery(data=b'confirm_amount'))
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
    invoice_text = f"💳 **فاکتور خرید موجودی**\n\n**اطلاعات خریدار:**\n🆔 آیدی: {user_id}\n👤 نام: {event.sender.first_name}\n📱 یوزرنیم: @{event.sender.username if event.sender.username else 'ندارد'}\n\n💎 تعداد الماس: {black_amount:,}\n💰 مبلغ قابل پرداخت: {amount:,} تومان\n💳 شماره کارت: {card_number}\n\nلطفاً پس از پرداخت، عکس فیش واریزی را ارسال نمایید."
    buttons = [[Button.inline('پرداخت', b'proceed_payment')], [Button.inline('لغو', b'cancel_payment')]]
    user_purchase_amount[user_id] = {'black_amount': black_amount, 'amount': amount}
    try:
        await event.edit(invoice_text, buttons=buttons, parse_mode='md')
        await event.answer()
    except Exception as e:
        print(f"Error editing confirm amount: {e}")

@bot.on(events.CallbackQuery(data=b'proceed_payment'))
async def proceed_payment(event):
    user_id = event.sender_id
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('SELECT banned FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    db.close()
    if result and result[0] == 1:
        await event.answer('🚫 شما توسط ادمین مسدود شده‌اید!', alert=True)
        return
    if user_id not in user_purchase_amount or isinstance(user_purchase_amount[user_id], str):
        await event.answer('خطای داخلی: مقدار خرید نامعتبر.', alert=True)
        return
    purchase_data = user_purchase_amount[user_id]
    black_amount = purchase_data['black_amount']
    amount = purchase_data['amount']
    user_clients[user_id] = {'step': 'receipt', 'amount': amount, 'black_amount': black_amount}
    card_number = get_setting(ADMINS[0], 'card_number', 'تنظیم نشده')
    try:
        await event.edit(f'💳 لطفاً مبلغ {amount:,} تومان (معادل {black_amount:,} الماس) را به کارت {card_number} واریز کنید و عکس فیش واریزی خود را ارسال نمایید.')
        await event.answer()
    except Exception as e:
        print(f"Error editing proceed payment: {e}")
    finally:
        if user_id in user_purchase_amount and not isinstance(user_purchase_amount[user_id], str):
            del user_purchase_amount[user_id]

@bot.on(events.CallbackQuery(data=b'cancel_payment'))
async def cancel_payment(event):
    user_id = event.sender_id
    if user_id in user_purchase_amount:
        del user_purchase_amount[user_id]
    buttons = [[Button.inline('💳 خرید موجودی', b'buy_balance_menu')], [Button.inline('🔙 برگشت', b'back')]]
    try:
        await event.edit('❌ خرید لغو شد.', buttons=buttons)
        await event.answer('❌ خرید لغو شد.')
    except Exception as e:
        print(f"Error editing cancel payment: {e}")

async def send_admin_panel(event, admin_id):
    if admin_id not in ADMINS:
        return
    buttons = [[Button.inline('➕ اضافه کردن الماس', b'add_balance')], [Button.inline('🚫 مسدود کردن کاربر', b'ban_user_admin')], [Button.inline('🔙 برگشت', b'back')]]
    await event.edit('🛠 **پنل مدیریت**\n\nلطفاً یکی از گزینه‌های زیر را انتخاب کنید:', buttons=buttons, parse_mode='md')

@bot.on(events.CallbackQuery(data=b'admin_panel'))
async def admin_panel_handler(event):
    user_id = event.sender_id
    if user_id not in ADMINS:
        await event.answer('❌ شما دسترسی ندارید!', alert=True)
        return
    await send_admin_panel(event, user_id)

@bot.on(events.CallbackQuery(data=b'add_balance'))
async def add_balance_admin(event):
    user_id = event.sender_id
    if user_id not in ADMINS:
        await event.answer('❌ شما دسترسی ندارید!', alert=True)
        return
    await event.edit('➕ **اضافه کردن الماس**\n\nلطفاً آیدی عددی کاربر مورد نظر را وارد کنید:', parse_mode='md')
    user_clients[user_id] = {'step': 'add_balance_user'}

@bot.on(events.CallbackQuery(data=b'ban_user_admin'))
async def ban_user_admin(event):
    user_id = event.sender_id
    if user_id not in ADMINS:
        await event.answer('❌ شما دسترسی ندارید!', alert=True)
        return
    await event.edit('🚫 **مسدود کردن کاربر**\n\nلطفاً آیدی عددی کاربر مورد نظر را وارد کنید:', parse_mode='md')
    user_clients[user_id] = {'step': 'ban_user'}

@bot.on(events.CallbackQuery(pattern=b'confirm_(\\d+)_(\\d+)_(\\d+)'))
async def confirm(event):
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
        await bot.send_message(user_id, f'✅ پرداخت شما تأیید شد!\n💎 {black_amount:,} الماس به حساب شما اضافه شد.')
    except Exception as e:
        print(f"Error sending message to user {user_id}: {e}")
    try:
        await event.edit(f'✅ پرداخت کاربر {user_id} برای {black_amount:,} الماس تأیید شد.')
    except Exception as e:
        print(f"Error editing confirm: {e}")
    await send_admin_panel(event, event.sender_id)

@bot.on(events.CallbackQuery(pattern=b'reject_(\\d+)_(\\d+)'))
async def reject(event):
    if event.sender_id not in ADMINS:
        return
    try:
        data_parts = event.data.decode().split('_')
        user_id = int(data_parts[1])
    except:
        await event.answer('خطای داده!', alert=True)
        return
    try:
        await bot.send_message(user_id, '❌ پرداخت شما رد شد. لطفاً با پشتیبانی تماس بگیرید.')
    except Exception as e:
        print(f"Error sending message to user {user_id}: {e}")
    try:
        await event.edit(f'❌ پرداخت کاربر {user_id} رد شد.')
    except Exception as e:
        print(f"Error editing reject: {e}")
    await send_admin_panel(event, event.sender_id)

@bot.on(events.NewMessage(pattern='/panel'))
async def panel_command(event):
    user_id = event.sender_id
    if user_id not in ADMINS:
        await event.reply('❌ شما دسترسی ندارید!')
        return
    buttons = [[Button.inline('🛠 پنل مدیریت', b'admin_panel')], [Button.inline('🔙 منو اصلی', b'back')]]
    await event.reply('برای دسترسی به پنل مدیریت روی دکمه زیر کلیک کنید:', buttons=buttons)

@bot.on(events.NewMessage(pattern=r'/sioh\s+(\d+)\s+(\d+)'))
async def transfer_sioh(event):
    user_id = event.sender_id
    try:
        match = event.pattern_match
        amount = int(match.group(1))
        target_id = int(match.group(2))
        if amount <= 0:
            await event.reply('❌ مقدار باید بیشتر از صفر باشد.')
            return
        if user_id == target_id:
            await event.reply('❌ نمی توانید به خودتان الماس انتقال دهید.')
            return
        db = get_user_db(user_id)
        cursor = db.cursor()
        cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        sender_balance = result[0] if result else 0
        db.close()
        if sender_balance < amount:
            await event.reply(f'❌ الماس کافی ندارید!\n💎 الماس شما: {sender_balance:,}')
            return
        init_user_db(target_id)
        target_db = get_user_db(target_id)
        target_cursor = target_db.cursor()
        target_cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, target_id))
        target_db.commit()
        target_db.close()
        db = get_user_db(user_id)
        cursor = db.cursor()
        cursor.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (amount, user_id))
        db.commit()
        db.close()
        await event.reply(f'✅ انتقال موفق!\n💎 {amount:,} الماس به کاربر {target_id} انتقال یافت.')
        try:
            await bot.send_message(target_id, f'✅ دریافت الماس!\n👤 کاربر {user_id} به شما {amount:,} الماس انتقال داد.')
        except:
            pass
    except Exception as e:
        await event.reply(f'❌ خطا در انتقال: {e}')

print("🤖 Bot is running...")
bot.run_until_disconnected()
