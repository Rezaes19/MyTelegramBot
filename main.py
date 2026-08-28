import asyncio
import os
import sqlite3
import time
import random
import re
import subprocess
import sys
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError

# =============================================
# تنظیمات
# =============================================
API_ID = 34996139
API_HASH = 'a1f3db16cae2919cfb05e61d1e968b8d'
BOT_TOKEN = '8858887304:AAELneONarg-zYTRBAWocRV9NO9xRzodFFg'

ADMINS = [6691993264, 7831049189]
SELF_PRICE = 1440
BOT_IMAGE_PATH = '1782502761872.jpg'

if not os.path.exists('database_users'):
    os.makedirs('database_users')

# =============================================
# دیتابیس
# =============================================
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
    if session_string:
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
        subprocess.Popen([sys.executable, 'self.py', session_string, str(user_id)], start_new_session=True)
        return True
    except:
        return False

# =============================================
# متغیرها
# =============================================
login_states = {}
user_steps = {}
active_games = {}
user_purchase = {}

# =============================================
# شروع ربات
# =============================================
bot = TelegramClient('bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

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
# هندلر پیام‌ها
# =============================================
@bot.on(events.NewMessage)
async def handle_messages(event):
    user_id = event.sender_id
    text = event.text
    if not text:
        return
    
    init_user_db(user_id)
    
    # ====== /start ======
    if text == "/start":
        if get_session(user_id):
            await main_menu(event, user_id)
        else:
            await event.reply('📱 شماره خود را وارد کنید:\n`+989123456789`')
            user_steps[user_id] = 'phone'
        return
    
    # ====== دریافت شماره ======
    if user_id in user_steps and user_steps[user_id] == 'phone':
        phone = text.strip()
        if not phone.startswith('+'):
            await event.reply('⚠️ شماره باید با + شروع شود')
            return
        
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        try:
            await client.connect()
            sent = await client.send_code_request(phone)
            login_states[user_id] = {
                'phone': phone,
                'client': client,
                'hash': sent.phone_code_hash,
                'time': time.time()
            }
            await event.reply('✅ کد ارسال شد.\nکد را وارد کنید:')
            del user_steps[user_id]
        except Exception as e:
            await event.reply(f'❌ خطا: {str(e)}')
        return
    
    # ====== دریافت کد ======
    if user_id in login_states:
        state = login_states[user_id]
        client = state['client']
        
        # چک منقضی (۲ دقیقه)
        if time.time() - state.get('time', 0) > 120:
            await event.reply('⏰ کد منقضی شد. دوباره شماره بفرستید.')
            del login_states[user_id]
            user_steps[user_id] = 'phone'
            return
        
        code = re.sub(r"\D+", "", text)
        if len(code) != 5:
            await event.reply('⚠️ کد ۵ رقمی وارد کنید:')
            return
        
        try:
            await client.sign_in(state['phone'], state['hash'], code)
            session_str = client.session.save()
            save_session(user_id, session_str)
            remove_balance(user_id, SELF_PRICE)
            run_self_py(session_str, user_id)
            await event.reply(f'✅ سلف فعال شد!\n💎 {SELF_PRICE:,} الماس کسر شد.')
            await main_menu(event, user_id)
        except PhoneCodeInvalidError:
            await event.reply('❌ کد اشتباه است. دوباره تلاش کنید:')
        except PhoneCodeExpiredError:
            await event.reply('⏰ کد منقضی شد.')
            del login_states[user_id]
            user_steps[user_id] = 'phone'
        except SessionPasswordNeededError:
            await event.reply('🔐 رمز دو مرحله‌ای را وارد کنید:')
            login_states[user_id]['step'] = 'password'
        except Exception as e:
            await event.reply(f'❌ خطا: {str(e)}')
        finally:
            if user_id in login_states and login_states[user_id].get('step') != 'password':
                del login_states[user_id]
        return
    
    # ====== رمز دو مرحله‌ای ======
    if user_id in login_states and login_states[user_id].get('step') == 'password':
        state = login_states[user_id]
        client = state['client']
        try:
            await client.sign_in(password=text)
            session_str = client.session.save()
            save_session(user_id, session_str)
            remove_balance(user_id, SELF_PRICE)
            run_self_py(session_str, user_id)
            await event.reply(f'✅ سلف فعال شد!')
            await main_menu(event, user_id)
        except Exception as e:
            await event.reply(f'❌ رمز اشتباه: {str(e)}')
        finally:
            del login_states[user_id]
        return
    
    # ====== ادمین: اضافه الماس ======
    if user_id in user_steps:
        step = user_steps[user_id]
        
        if step == 'add_balance_user':
            try:
                target = int(text.strip())
                user_steps[user_id] = 'add_balance_amount'
                user_steps[f'{user_id}_target'] = target
                await event.reply('💎 مقدار الماس را وارد کنید:')
            except ValueError:
                await event.reply('❌ آیدی نامعتبر')
            return
        
        if step == 'add_balance_amount':
            try:
                amount = int(text.strip())
                target = user_steps.get(f'{user_id}_target')
                if target:
                    add_balance(target, amount)
                    await event.reply(f'✅ {amount:,} الماس اضافه شد.')
                    del user_steps[user_id]
                    if f'{user_id}_target' in user_steps:
                        del user_steps[f'{user_id}_target']
                    await main_menu(event, user_id)
            except ValueError:
                await event.reply('❌ مقدار نامعتبر')
            return
        
        if step == 'ban_user':
            try:
                target = int(text.strip())
                db = get_user_db(target)
                cursor = db.cursor()
                cursor.execute('UPDATE users SET banned = 1 WHERE user_id = ?', (target,))
                db.commit()
                db.close()
                await event.reply(f'✅ کاربر {target} مسدود شد.')
                del user_steps[user_id]
                await main_menu(event, user_id)
            except ValueError:
                await event.reply('❌ آیدی نامعتبر')
            return
    
    # ====== دستورات گروهی ======
    if event.is_group:
        if text.strip() == 'موجودی':
            target = user_id
            if event.is_reply:
                reply = await event.get_reply_message()
                if reply and reply.sender_id:
                    target = reply.sender_id
            await event.reply(f'💎 موجودی: {get_balance(target):,} الماس')
            return
        
        game = re.match(r'بازی\s+(\d+)$', text.strip())
        if game:
            amount = int(game.group(1))
            if amount < 20:
                await event.reply('❌ حداقل ۲۰ الماس')
                return
            if get_balance(user_id) < amount:
                await event.reply('❌ موجودی کافی نیست')
                return
            remove_balance(user_id, amount)
            name = (await bot.get_entity(user_id)).first_name
            msg = f"⚔️ نبرد الماس\n👤 {name}\n💰 {amount:,} الماس"
            sent = await event.reply(msg, buttons=[[Button.inline('⚔️ پیوستن', f'join_{amount}_{user_id}')]])
            active_games[(event.chat_id, sent.id)] = {'organizer': user_id, 'amount': amount}
            return
        
        transfer = re.match(r'انتقال\s+الماس\s+(\d+)$', text.strip())
        if transfer and event.is_reply:
            amount = int(transfer.group(1))
            reply = await event.get_reply_message()
            if reply and reply.sender_id and reply.sender_id != user_id:
                if get_balance(user_id) >= amount and amount >= 10:
                    remove_balance(user_id, amount)
                    add_balance(reply.sender_id, amount)
                    await event.reply(f'✅ {amount:,} الماس انتقال یافت')
            return

# =============================================
# هندلر دکمه‌ها
# =============================================
@bot.on(events.CallbackQuery)
async def handle_callbacks(event):
    user_id = event.sender_id
    data = event.data.decode()
    
    # ====== خرید سلف ======
    if data == 'buy_self':
        if get_balance(user_id) < SELF_PRICE:
            await event.answer(f'❌ الماس کافی نیست!', alert=True)
            return
        await event.edit('📱 شماره خود را وارد کنید:')
        user_steps[user_id] = 'phone'
        return
    
    # ====== حساب کاربری ======
    if data == 'account':
        balance = get_balance(user_id)
        session = get_session(user_id)
        text = f"👤 حساب کاربری\n\n🆔 {user_id}\n💎 {balance:,} الماس\n🔐 سلف: {'فعال ✅' if session else 'غیرفعال ❌'}"
        await event.edit(text, buttons=[[Button.inline('🔙 برگشت', b'back')]])
        return
    
    # ====== مدیریت سلف ======
    if data == 'manage_self':
        if not get_session(user_id):
            await event.answer('❌ سلف فعال نیست!', alert=True)
            return
        await event.edit('⚙️ مدیریت سلف\n\nسلف شما فعال است.', buttons=[[Button.inline('🔓 غیرفعال‌سازی', b'disable_self'), Button.inline('🔙 برگشت', b'back')]])
        return
    
    # ====== غیرفعال‌سازی ======
    if data == 'disable_self':
        save_session(user_id, '')
        await event.edit('✅ سلف غیرفعال شد.')
        return
    
    # ====== زیرمجموعه ======
    if data == 'referral':
        bot_username = (await bot.get_me()).username
        await event.edit(f"👥 زیرمجموعه گیری\n\nلینک:\n`https://t.me/{bot_username}?start={user_id}`", buttons=[[Button.inline('🔙 برگشت', b'back')]])
        return
    
    # ====== برگشت ======
    if data == 'back':
        await main_menu(event, user_id)
        return
    
    # ====== پنل مدیریت ======
    if data == 'admin_panel':
        if user_id not in ADMINS:
            await event.answer('❌ دسترسی ندارید!', alert=True)
            return
        await event.edit('🛠 پنل مدیریت', buttons=[
            [Button.inline('➕ اضافه الماس', b'add_balance')],
            [Button.inline('🚫 مسدود کردن', b'ban_user')],
            [Button.inline('🔙 برگشت', b'back')]
        ])
        return
    
    # ====== اضافه الماس ======
    if data == 'add_balance':
        if user_id not in ADMINS:
            await event.answer('❌ دسترسی ندارید!', alert=True)
            return
        await event.edit('➕ آیدی کاربر را وارد کنید:')
        user_steps[user_id] = 'add_balance_user'
        return
    
    # ====== مسدود کردن ======
    if data == 'ban_user':
        if user_id not in ADMINS:
            await event.answer('❌ دسترسی ندارید!', alert=True)
            return
        await event.edit('🚫 آیدی کاربر را وارد کنید:')
        user_steps[user_id] = 'ban_user'
        return
    
    # ====== پیوستن به بازی ======
    if data.startswith('join_'):
        parts = data.split('_')
        amount = int(parts[1])
        organizer = int(parts[2])
        
        if user_id == organizer:
            await event.answer('❌ خودت هستی!', alert=True)
            return
        
        if get_balance(user_id) < amount:
            await event.answer('❌ موجودی کافی نیست!', alert=True)
            return
        
        remove_balance(user_id, amount)
        
        # انتخاب برنده
        winner = random.choice([organizer, user_id])
        prize = amount * 2 - int(amount * 2 * 0.05)
        add_balance(winner, prize)
        
        try:
            await bot.delete_messages(event.chat_id, event.message_id)
        except:
            pass
        
        w_name = (await bot.get_entity(winner)).first_name
        l_name = (await bot.get_entity(organizer if winner == user_id else user_id)).first_name
        
        await bot.send_message(event.chat_id, 
            f"◈ ━━━ 𝐕𝐈𝐏 𝐌𝐑 ━━━ ◈\n"
            f"𝐕𝐈𝐏 | برنده: {w_name}\n"
            f"𝐕𝐈𝐏 | بازنده: {l_name}\n"
            f"𝐕𝐈𝐏 | جایزه: {prize:,} الماس\n"
            f"◈ ━━━ 𝐕𝐈𝐏 𝐌𝐑 ━━━ ◈"
        )
        await event.answer('✅ بازی تمام شد!')
        return

# =============================================
# تابع اصلی
# =============================================
async def main():
    await bot.start()
    print("✅ Bot started")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
