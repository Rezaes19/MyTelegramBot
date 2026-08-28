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
from datetime import datetime
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError,
    PhoneCodeExpiredError, FloodWaitError
)

# =============================================
# تنظیمات
# =============================================
API_ID = 34996139
API_HASH = 'a1f3db16cae2919cfb05e61d1e968b8d'
BOT_TOKEN = '8858887304:AAELneONarg-zYTRBAWocRV9NO9xRzodFFg'

ADMINS = [6691993264, 7831049189]
SELF_PRICE = 1440
BOT_IMAGE_PATH = '1782502761872.jpg'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================
# دیتابیس
# =============================================
if not os.path.exists('database_users'):
    os.makedirs('database_users')

def get_user_db(user_id):
    return sqlite3.connect(f'database_users/user_{user_id}.db')

def init_user_db(user_id):
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, 
        balance INTEGER DEFAULT 0, 
        banned INTEGER DEFAULT 0
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS self_sessions (
        session_string TEXT, 
        is_active INTEGER DEFAULT 1
    )''')
    cursor.execute('INSERT OR IGNORE INTO users (user_id, balance, banned) VALUES (?, 0, 0)', (user_id,))
    db.commit()
    db.close()

def get_balance(user_id):
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    db.close()
    return result[0] if result else 0

def add_balance(user_id, amount):
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    db.commit()
    db.close()

def remove_balance(user_id, amount):
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (amount, user_id))
    db.commit()
    db.close()

def save_session(user_id, session_string):
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('UPDATE self_sessions SET is_active = 0')
    cursor.execute('INSERT INTO self_sessions (session_string, is_active) VALUES (?, 1)', (session_string,))
    db.commit()
    db.close()

def get_session(user_id):
    db = get_user_db(user_id)
    cursor = db.cursor()
    cursor.execute('SELECT session_string FROM self_sessions WHERE is_active = 1')
    result = cursor.fetchone()
    db.close()
    return result[0] if result else None

def run_self_py(session_string, user_id):
    try:
        command = [sys.executable, 'self.py', session_string, str(user_id)]
        subprocess.Popen(command, start_new_session=True)
        return True
    except:
        return False

# =============================================
# متغیرهای سراسری
# =============================================
login_states = {}  # {user_id: {'phone': '+98...', 'client': client, 'hash': '...'}}
user_clients = {}  # {user_id: {'step': 'phone'}}
active_games = {}
user_purchase = {}  # {user_id: '0'}

# =============================================
# شروع ربات
# =============================================
bot = TelegramClient('bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# =============================================
# توابع کمکی
# =============================================
async def safe_edit(event, text, buttons=None):
    try:
        if buttons:
            await event.edit(text, buttons=buttons, parse_mode='md')
        else:
            await event.edit(text, parse_mode='md')
    except Exception as e:
        if "MessageNotModifiedError" not in str(e):
            logger.error(f"Edit error: {e}")

async def get_user_name(user_id):
    try:
        entity = await bot.get_entity(user_id)
        return entity.first_name or "کاربر"
    except:
        return "کاربر"

# =============================================
# منوی اصلی
# =============================================
async def main_menu(event, user_id):
    buttons = [
        [Button.inline('💎 خرید سلف', b'buy_self')],
        [Button.inline('👤 حساب کاربری', b'account'), Button.inline('⚙️ مدیریت سلف', b'manage_self')],
        [Button.inline('👥 زیرمجموعه گیری', b'referral')]
    ]
    if user_id in ADMINS:
        buttons.append([Button.inline('🛠 پنل مدیریت', b'admin_panel')])
    
    if os.path.exists(BOT_IMAGE_PATH):
        await bot.send_file(user_id, BOT_IMAGE_PATH, caption='به سلف ساز VIP MR خوش آمدید', buttons=buttons)
    else:
        await event.reply('به سلف ساز VIP MR خوش آمدید', buttons=buttons)

# =============================================
# هندلر NewMessage
# =============================================
@bot.on(events.NewMessage)
async def handle_messages(event):
    user_id = event.sender_id
    text = event.text
    
    if not text:
        return
    
    # ====== دستور /start ======
    if text == "/start":
        init_user_db(user_id)
        
        # چک کن قبلاً لاگین کرده
        session = get_session(user_id)
        if session:
            await main_menu(event, user_id)
            return
        
        # درخواست شماره
        await event.reply('📱 لطفاً شماره تلفن خود را وارد کنید:\n\n`+989123456789`')
        user_clients[user_id] = {'step': 'phone'}
        return
    
    # ====== مرحله 1: دریافت شماره ======
    if user_id in user_clients and user_clients[user_id].get('step') == 'phone':
        phone = text.strip()
        if not phone.startswith('+'):
            await event.reply('⚠️ شماره باید با + شروع شود.\nمثال: `+989123456789`')
            return
        
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        try:
            await client.connect()
            sent_code = await client.send_code_request(phone)
            login_states[user_id] = {
                'phone': phone,
                'client': client,
                'hash': sent_code.phone_code_hash,
                'code_sent_at': time.time()
            }
            await event.reply('✅ کد ارسال شد.\nکد را وارد کنید:\n`1 2 3 4 5`')
            del user_clients[user_id]
        except Exception as e:
            await event.reply(f'❌ خطا: {str(e)}')
            try:
                await client.disconnect()
            except:
                pass
        return
    
    # ====== مرحله 2: دریافت کد ======
    if user_id in login_states and login_states[user_id].get('phone'):
        state = login_states[user_id]
        client = state['client']
        phone = state['phone']
        code_hash = state['hash']
        
        # چک منقضی نشده (2 دقیقه)
        if time.time() - state.get('code_sent_at', 0) > 120:
            await event.reply('⏰ کد منقضی شد. دوباره تلاش کنید.')
            try:
                await client.disconnect()
            except:
                pass
            del login_states[user_id]
            user_clients[user_id] = {'step': 'phone'}
            await event.reply('📱 شماره خود را وارد کنید:')
            return
        
        code = re.sub(r"\D+", "", text)
        if len(code) != 5:
            await event.reply('⚠️ کد ۵ رقمی وارد کنید:\n`1 2 3 4 5`')
            return
        
        try:
            await client.sign_in(phone, code_hash, code)
            session_string = client.session.save()
            
            if session_string:
                save_session(user_id, session_string)
                run_self_py(session_string, user_id)
                remove_balance(user_id, SELF_PRICE)
                await event.reply(f'✅ سلف فعال شد!\n💎 {SELF_PRICE:,} الماس کسر شد.')
                await main_menu(event, user_id)
            else:
                await event.reply('❌ خطا در ایجاد سشن')
                
        except PhoneCodeInvalidError:
            await event.reply('❌ کد اشتباه است. دوباره تلاش کنید:')
        except PhoneCodeExpiredError:
            await event.reply('⏰ کد منقضی شد. دوباره شماره بفرستید.')
            del login_states[user_id]
            user_clients[user_id] = {'step': 'phone'}
            await event.reply('📱 شماره خود را وارد کنید:')
        except SessionPasswordNeededError:
            await event.reply('🔐 رمز دو مرحله‌ای را وارد کنید:')
            login_states[user_id]['step'] = 'password'
        except Exception as e:
            await event.reply(f'❌ خطا: {str(e)}')
        finally:
            try:
                await client.disconnect()
            except:
                pass
            if user_id in login_states:
                del login_states[user_id]
        return
    
    # ====== رمز دو مرحله‌ای ======
    if user_id in login_states and login_states[user_id].get('step') == 'password':
        state = login_states[user_id]
        client = state['client']
        
        try:
            await client.sign_in(password=text)
            session_string = client.session.save()
            if session_string:
                save_session(user_id, session_string)
                run_self_py(session_string, user_id)
                remove_balance(user_id, SELF_PRICE)
                await event.reply(f'✅ سلف فعال شد!\n💎 {SELF_PRICE:,} الماس کسر شد.')
                await main_menu(event, user_id)
            else:
                await event.reply('❌ خطا')
        except Exception as e:
            await event.reply(f'❌ رمز اشتباه: {str(e)}')
        finally:
            try:
                await client.disconnect()
            except:
                pass
            del login_states[user_id]
        return
    
    # ====== دستورات گروهی ======
    if event.is_group or event.is_channel:
        # موجودی
        if text.strip() == 'موجودی':
            target_id = user_id
            if event.is_reply:
                reply = await event.get_reply_message()
                if reply and reply.sender_id:
                    target_id = reply.sender_id
            balance = get_balance(target_id)
            await event.reply(f'💎 موجودی: {balance:,} الماس')
            return
        
        # بازی
        game_match = re.match(r'بازی\s+(\d+)$', text.strip())
        if game_match:
            amount = int(game_match.group(1))
            if amount < 20:
                await event.reply('❌ حداقل ۲۰ الماس')
                return
            
            if get_balance(user_id) < amount:
                await event.reply(f'❌ موجودی کافی نیست')
                return
            
            remove_balance(user_id, amount)
            name = await get_user_name(user_id)
            msg = f"⚔️ **نبرد الماس VIP MR**\n\n👤 {name}\n💰 {amount:,} الماس"
            buttons = [[Button.inline('⚔️ پیوستن', f'join_{amount}_{user_id}')]]
            sent = await event.reply(msg, buttons=buttons)
            
            game_key = (event.chat_id, sent.id)
            active_games[game_key] = {
                'organizer': user_id,
                'amount': amount,
                'msg_id': sent.id
            }
            return
        
        # انتقال
        transfer_match = re.match(r'انتقال\s+الماس\s+(\d+)$', text.strip())
        if transfer_match:
            if not event.is_reply:
                await event.reply('❌ روی پیام کاربر ریپلی کنید')
                return
            
            amount = int(transfer_match.group(1))
            reply = await event.get_reply_message()
            if not reply or not reply.sender_id:
                await event.reply('❌ کاربر پیدا نشد')
                return
            
            receiver = reply.sender_id
            if user_id == receiver:
                await event.reply('❌ نمی‌توانید به خودتان بدهید')
                return
            
            if amount < 10:
                await event.reply('❌ حداقل ۱۰ الماس')
                return
            
            if get_balance(user_id) < amount:
                await event.reply('❌ موجودی کافی نیست')
                return
            
            remove_balance(user_id, amount)
            add_balance(receiver, amount)
            await event.reply(f'✅ {amount:,} الماس انتقال یافت')
            return

# =============================================
# هندلر CallbackQuery
# =============================================
@bot.on(events.CallbackQuery)
async def handle_callback(event):
    user_id = event.sender_id
    data = event.data.decode()
    
    # ====== موجودی ======
    if data.startswith("balance_"):
        uid = int(data.split("_")[1])
        balance = get_balance(uid)
        await event.answer(f'💎 موجودی: {balance:,} الماس', alert=True)
        return
    
    # ====== خرید سلف ======
    if data == "buy_self":
        balance = get_balance(user_id)
        if balance < SELF_PRICE:
            await event.answer(f'❌ الماس کافی نیست!\n💎 {balance:,} / {SELF_PRICE:,}', alert=True)
            return
        
        await safe_edit(event, '📱 شماره خود را وارد کنید:\n\n`+989123456789`')
        user_clients[user_id] = {'step': 'phone'}
        return
    
    # ====== حساب کاربری ======
    if data == "account":
        balance = get_balance(user_id)
        session = get_session(user_id)
        status = "فعال ✅" if session else "غیرفعال ❌"
        text = f"👤 **حساب کاربری**\n\n🆔 {user_id}\n💎 {balance:,} الماس\n🔐 سلف: {status}"
        buttons = [[Button.inline('🔙 برگشت', b'back')]]
        await safe_edit(event, text, buttons)
        return
    
    # ====== مدیریت سلف ======
    if data == "manage_self":
        session = get_session(user_id)
        if not session:
            await event.answer('❌ سلف فعال نیست!', alert=True)
            return
        
        buttons = [
            [Button.inline('🔓 غیرفعال‌سازی', b'disable_self')],
            [Button.inline('🔙 برگشت', b'back')]
        ]
        await safe_edit(event, '⚙️ **مدیریت سلف**\n\nسلف شما فعال است.', buttons)
        return
    
    # ====== غیرفعال‌سازی سلف ======
    if data == "disable_self":
        save_session(user_id, "")  # غیرفعال
        await safe_edit(event, '✅ سلف غیرفعال شد.')
        await event.answer('✅ غیرفعال شد')
        return
    
    # ====== زیرمجموعه گیری ======
    if data == "referral":
        bot_username = (await bot.get_me()).username
        link = f"https://t.me/{bot_username}?start={user_id}"
        text = f"👥 **زیرمجموعه گیری**\n\nلینک دعوت:\n`{link}`"
        buttons = [[Button.inline('🔙 برگشت', b'back')]]
        await safe_edit(event, text, buttons)
        return
    
    # ====== برگشت ======
    if data == "back":
        await main_menu(event, user_id)
        return
    
    # ====== پیوستن به بازی ======
    if data.startswith("join_"):
        parts = data.split("_")
        amount = int(parts[1])
        organizer = int(parts[2])
        
        if user_id == organizer:
            await event.answer("❌ خودت هستی!", alert=True)
            return
        
        if get_balance(user_id) < amount:
            await event.answer(f"❌ موجودی کافی نیست!", alert=True)
            return
        
        remove_balance(user_id, amount)
        
        # انتخاب برنده
        winner = random.choice([organizer, user_id])
        prize = amount * 2
        tax = int(prize * 0.05)
        prize -= tax
        
        add_balance(winner, prize)
        
        # حذف پیام بازی
        try:
            await bot.delete_messages(event.chat_id, event.message_id)
        except:
            pass
        
        # نتیجه
        winner_name = await get_user_name(winner)
        loser_name = await get_user_name(organizer if winner == user_id else user_id)
        
        result = f"◈ ━━━ 𝐕𝐈𝐏 𝐌𝐑 ━━━ ◈\n"
        result += f"𝐕𝐈𝐏 | برنده: {winner_name}\n"
        result += f"𝐕𝐈𝐏 | بازنده: {loser_name}\n"
        result += f"𝐕𝐈𝐏 | جایزه: {prize:,} الماس\n"
        result += f"◈ ━━━ 𝐕𝐈𝐏 𝐌𝐑 ━━━ ◈"
        
        await bot.send_message(event.chat_id, result, parse_mode='md')
        await event.answer("✅ بازی تمام شد!")
        
        # پاک کردن از active_games
        for key in list(active_games.keys()):
            if key[1] == event.message_id:
                del active_games[key]
                break
        return
    
    # ====== پنل مدیریت ======
    if data == "admin_panel":
        if user_id not in ADMINS:
            await event.answer("❌ دسترسی ندارید!", alert=True)
            return
        
        buttons = [
            [Button.inline('➕ اضافه الماس', b'add_balance')],
            [Button.inline('🚫 مسدود کردن', b'ban_user')],
            [Button.inline('🔙 برگشت', b'back')]
        ]
        await safe_edit(event, '🛠 **پنل مدیریت**', buttons)
        return
    
    # ====== اضافه الماس ======
    if data == "add_balance":
        if user_id not in ADMINS:
            await event.answer("❌ دسترسی ندارید!", alert=True)
            return
        
        await safe_edit(event, '➕ آیدی کاربر را وارد کنید:')
        user_clients[user_id] = {'step': 'add_balance_user'}
        return
    
    # ====== مسدود کردن ======
    if data == "ban_user":
        if user_id not in ADMINS:
            await event.answer("❌ دسترسی ندارید!", alert=True)
            return
        
        await safe_edit(event, '🚫 آیدی کاربر را وارد کنید:')
        user_clients[user_id] = {'step': 'ban_user'}
        return

# =============================================
# مدیریت ورودی ادمین‌ها (از طریق پیام)
# =============================================
@bot.on(events.NewMessage)
async def admin_input_handler(event):
    user_id = event.sender_id
    text = event.text
    
    if user_id not in ADMINS:
        return
    
    if user_id not in user_clients:
        return
    
    step = user_clients[user_id].get('step')
    
    if step == 'add_balance_user':
        try:
            target = int(text.strip())
            user_clients[user_id]['target'] = target
            user_clients[user_id]['step'] = 'add_balance_amount'
            await event.reply('💎 مقدار الماس را وارد کنید:')
        except ValueError:
            await event.reply('❌ آیدی نامعتبر')
    
    elif step == 'add_balance_amount':
        try:
            amount = int(text.strip())
            target = user_clients[user_id].get('target')
            add_balance(target, amount)
            await event.reply(f'✅ {amount:,} الماس به کاربر {target} اضافه شد.')
            del user_clients[user_id]
            await main_menu(event, user_id)
        except ValueError:
            await event.reply('❌ مقدار نامعتبر')
    
    elif step == 'ban_user':
        try:
            target = int(text.strip())
            init_user_db(target)
            db = get_user_db(target)
            cursor = db.cursor()
            cursor.execute('UPDATE users SET banned = 1 WHERE user_id = ?', (target,))
            db.commit()
            db.close()
            await event.reply(f'✅ کاربر {target} مسدود شد.')
            del user_clients[user_id]
            await main_menu(event, user_id)
        except ValueError:
            await event.reply('❌ آیدی نامعتبر')

# =============================================
# توقف خودکار بازی بعد از ۵ دقیقه
# =============================================
async def game_timeout():
    while True:
        await asyncio.sleep(60)
        now = time.time()
        for key, game in list(active_games.items()):
            if now - game.get('time', 0) > 300:
                chat_id, msg_id = key
                try:
                    await bot.delete_messages(chat_id, msg_id)
                except:
                    pass
                # برگشت الماس
                add_balance(game['organizer'], game['amount'])
                del active_games[key]

# =============================================
# تابع اصلی
# =============================================
async def main():
    # اجرای تایمر بازی
    asyncio.create_task(game_timeout())
    
    # شروع ربات
    await bot.start()
    logger.info("✅ Bot started")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except Exception as e:
        logger.error(f"Error: {e}")
