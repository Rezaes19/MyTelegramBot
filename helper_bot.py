#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Helper Bot — تبدیل کد ایموجی پریمیوم مثل @pyiuebot

نحوه استفاده در هر چت:
  @SelfmrhelPerbot متن [کد] متن

مثال:
  @SelfmrhelPerbot سلام [6298332994260175589] خوبی؟

محیط سرور:
  HELPER_BOT_TOKEN=توکن
  API_ID=...
  API_HASH=...
"""

import os
import re
import html
import logging
import asyncio

from pyrogram import Client, filters, idle
from pyrogram.types import (
    Message,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from pyrogram.enums import ParseMode

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
)
log = logging.getLogger("helper")

BOT_TOKEN = os.environ.get("HELPER_BOT_TOKEN") or os.environ.get("BOT_TOKEN") or ""
API_ID = int(os.environ.get("API_ID") or os.environ.get("TELEGRAM_API_ID") or "0")
API_HASH = (os.environ.get("API_HASH") or os.environ.get("TELEGRAM_API_HASH") or "").strip()

if not BOT_TOKEN:
    raise SystemExit("❌ HELPER_BOT_TOKEN تنظیم نشده")
if not API_ID or not API_HASH:
    raise SystemExit("❌ API_ID و API_HASH لازم است")

app = Client(
    "selfmr_helper",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True,
)

BOT_USERNAME = "SelfmrhelPerbot"

# [عدد بلند] = کد ایموجی پریمیوم
CODE_RE = re.compile(r"\[(\d{10,})\]")


def count_codes(text: str) -> int:
    return len(CODE_RE.findall(text or ""))


def build_html_with_premium(text: str) -> str:
    """
    متن را به HTML تبدیل می‌کند:
    سلام [6298...] خوبی؟  →  سلام <tg-emoji ...>⭐</tg-emoji> خوبی؟
    """
    if not text:
        return ""

    def repl(m):
        cid = m.group(1)
        # fallback ساده — کلاینت پریمیوم واقعی را نشان می‌دهد
        return f'<tg-emoji emoji-id="{cid}">⭐</tg-emoji>'

    # بقیه متن را escape کن ولی تگ‌های ما را بعداً برگردان
    parts = []
    last = 0
    for m in CODE_RE.finditer(text):
        parts.append(html.escape(text[last:m.start()]))
        parts.append(repl(m))
        last = m.end()
    parts.append(html.escape(text[last:]))
    return "".join(parts)


def preview_plain(text: str) -> str:
    """پیش‌نمایش ساده بدون تگ"""
    return CODE_RE.sub("⭐", text or "")


# -------------------- handlers --------------------

@app.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    uname = BOT_USERNAME
    text = (
        f"👑 به ربات تبدیل ایموجی پریمیوم خوش آمدید\n\n"
        f"تعداد کانال‌های ثبت شده شما: 0\n\n"
        f"‼️ نحوه استفاده:\n"
        f"در هر چتی تایپ کنید:\n"
        f"<code>@{uname}</code> متن [کد] متن\n\n"
        f"مثال:\n"
        f"<code>@{uname} سلام [6298332994260175589] خوبی؟</code>\n\n"
        f"پیام شما تبدیل شده و قابل ارسال خواهد بود\n"
        f"و توجه داشته باشید کد ایموجی را از کانال\n"
        f"https://t.me/CustomEmojiPack بردارید"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⭐ ایموجی‌های پرکاربرد", url="https://t.me/CustomEmojiPack"),
            InlineKeyboardButton("💎 Rich Text/مقاله", url="https://t.me/CustomEmojiPack"),
        ],
        [
            InlineKeyboardButton("📢 قسمت کانال", callback_data="ch"),
            InlineKeyboardButton("➡️ راهنما", callback_data="help"),
        ],
    ])
    await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


@app.on_callback_query()
async def cb_handler(client, callback):
    data = callback.data or ""
    uname = BOT_USERNAME
    if data == "help":
        await callback.answer()
        await callback.message.reply_text(
            f"📖 راهنما\n\n"
            f"۱) کد ایموجی را از کانال‌های پک بگیر\n"
            f"۲) در هر چت بنویس:\n"
            f"<code>@{uname} متن [کد] متن</code>\n"
            f"۳) روی نتیجه اینلاین بزن تا پیام پریمیوم ارسال شود\n\n"
            f"مثال:\n"
            f"<code>@{uname} سلام [6298332994260175589] خوبی؟</code>",
            parse_mode=ParseMode.HTML,
        )
    elif data == "ch":
        await callback.answer("کانال پک‌ها را از لینک زیر باز کنید", show_alert=True)
    else:
        await callback.answer()


@app.on_message(filters.private & filters.incoming & ~filters.command("start"))
async def private_handler(client: Client, message: Message):
    """در پیوی: اگر [کد] داشت پیش‌نمایش بده؛ اگر ایموجی پریمیوم فرستاد ID بده"""
    text = message.text or message.caption or ""
    items = []
    entities = list(message.entities or []) + list(message.caption_entities or [])
    for ent in entities:
        cid = getattr(ent, "custom_emoji_id", None)
        if cid:
            items.append(int(cid))

    if items:
        lines = [f"`{cid}`" for cid in items]
        await message.reply_text(
            "📋 کد ایموجی‌های پیام شما:\n\n" + "\n".join(lines) +
            f"\n\nاستفاده:\n<code>@{BOT_USERNAME} متن [{items[0]}] متن</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    if CODE_RE.search(text):
        n = count_codes(text)
        html_body = build_html_with_premium(text)
        await message.reply_text(
            f"پیام شما با {n} کد ایموجی پریمیوم آماده تبدیل است.\n\n"
            f"پیش‌نمایش:\n{html_body}\n\n"
            f"در چت بنویس:\n<code>@{BOT_USERNAME} {html.escape(text)}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    await message.reply_text(
        f"در هر چتی تایپ کنید:\n"
        f"<code>@{BOT_USERNAME} سلام [6298332994260175589] خوبی؟</code>",
        parse_mode=ParseMode.HTML,
    )


@app.on_inline_query()
async def inline_handler(client: Client, query: InlineQuery):
    """
    اینلاین مثل pyiuebot:
    کوئری: سلام [6298332994260175589] خوبی؟
    → نتیجه قابل ارسال با ایموجی پریمیوم واقعی
    """
    q = (query.query or "").strip()
    uname = BOT_USERNAME
    results = []

    n = count_codes(q)
    if n > 0:
        html_body = build_html_with_premium(q)
        plain = preview_plain(q)
        # نتیجه اصلی — با HTML tg-emoji
        results.append(
            InlineQueryResultArticle(
                id="convert_main",
                title="پیام آماده تبدیل",
                description=f"پیام با {n} ایموجی پریمیوم",
                input_message_content=InputTextMessageContent(
                    message_text=html_body,
                    parse_mode=ParseMode.HTML,
                ),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("تبدیل و ارسال پیام", switch_inline_query_current_chat=q)]
                ]),
            )
        )
        # نتیجه دوم بدون دکمه (ارسال مستقیم)
        results.append(
            InlineQueryResultArticle(
                id="convert_send",
                title=f"ارسال مستقیم ({n} ایموجی)",
                description=plain[:60],
                input_message_content=InputTextMessageContent(
                    message_text=html_body,
                    parse_mode=ParseMode.HTML,
                ),
            )
        )
    else:
        # راهنما وقتی هنوز کدی ننوشته
        sample = f"سلام [6298332994260175589] خوبی؟"
        results.append(
            InlineQueryResultArticle(
                id="help",
                title="‼️ نحوه استفاده",
                description=f"@{uname} متن [کد] متن",
                input_message_content=InputTextMessageContent(
                    message_text=(
                        f"👑 تبدیل ایموجی پریمیوم\n\n"
                        f"تایپ کنید:\n"
                        f"@{uname} متن [کد] متن\n\n"
                        f"مثال:\n"
                        f"@{uname} {sample}\n\n"
                        f"کدها را از https://t.me/CustomEmojiPack بردارید"
                    ),
                ),
            )
        )

    try:
        await query.answer(
            results,
            cache_time=1,
            is_personal=True,
            switch_pm_text="راهنما / استارت ربات" if n == 0 else f"{n} کد آماده تبدیل",
            switch_pm_parameter="start",
        )
    except Exception as e:
        log.warning("inline answer: %s", e)
        try:
            await query.answer(results[:1], cache_time=0, is_personal=True)
        except Exception as e2:
            log.warning("inline fallback: %s", e2)


async def main():
    global BOT_USERNAME
    await app.start()
    me = await app.get_me()
    BOT_USERNAME = (me.username or "SelfmrhelPerbot").lstrip("@")
    log.info("✅ Helper started @%s id=%s", BOT_USERNAME, me.id)
    await idle()
    await app.stop()


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
