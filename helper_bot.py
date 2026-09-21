#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Helper Bot — استخراج و نمایش کد ایموجی پریمیوم + اینلاین
مثل ربات‌های ID-extractor (مثلاً pyiuebot)

محیط سرور:
  HELPER_BOT_TOKEN=توکن_ربات_هلپر
  API_ID=...
  API_HASH=...
  (اختیاری) HELPER_INLINE_BOT=SelfmrhelPerbot
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
from pyrogram.enums import ParseMode, MessageEntityType
from pyrogram.raw import functions, types as raw_types

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
)
log = logging.getLogger("helper")

BOT_TOKEN = os.environ.get("HELPER_BOT_TOKEN") or os.environ.get("BOT_TOKEN") or ""
API_ID = int(os.environ.get("API_ID") or os.environ.get("TELEGRAM_API_ID") or "0")
API_HASH = (os.environ.get("API_HASH") or os.environ.get("TELEGRAM_API_HASH") or "").strip()

if not BOT_TOKEN:
    raise SystemExit("❌ HELPER_BOT_TOKEN (یا BOT_TOKEN) تنظیم نشده")
if not API_ID or not API_HASH:
    raise SystemExit("❌ API_ID و API_HASH لازم است")

app = Client(
    "selfmr_helper",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True,
)

BOT_USERNAME = None  # بعد از start پر می‌شود


def utf16_slice(text: str, offset: int, length: int) -> str:
    try:
        b = text.encode("utf-16-le")
        return b[offset * 2 : (offset + length) * 2].decode("utf-16-le")
    except Exception:
        return "⭐"


def extract_custom_emojis(message: Message):
    """لیست dict: id, fallback, offset, length"""
    out = []
    text = message.text or message.caption or ""
    entities = list(message.entities or []) + list(message.caption_entities or [])
    for ent in entities:
        cid = getattr(ent, "custom_emoji_id", None)
        if not cid:
            t = str(getattr(ent, "type", "") or "")
            if "CUSTOM_EMOJI" not in t.upper() and "custom_emoji" not in t.lower():
                continue
            cid = getattr(ent, "custom_emoji_id", None)
        if not cid:
            continue
        off = int(getattr(ent, "offset", 0) or 0)
        ln = int(getattr(ent, "length", 0) or 0)
        fb = utf16_slice(text, off, ln) if text and ln else "⭐"
        if not (fb or "").strip():
            fb = "⭐"
        out.append({
            "id": int(cid),
            "fallback": fb,
            "offset": off,
            "length": ln,
        })
    return out


def format_result(items: list, bot_username: str) -> str:
    """
    خروجی شبیه ربات‌های استخراج‌کننده:
    متن + کد عددی + تگ HTML + @یوزرنیم
    """
    uname = (bot_username or "SelfmrhelPerbot").lstrip("@")
    lines = []
    for i, it in enumerate(items, 1):
        cid = it["id"]
        fb = it["fallback"]
        lines.append(f"{fb}")
        lines.append(f"`{cid}`")
        lines.append(f"<tg-emoji emoji-id=\"{cid}\">{html.escape(fb)}</tg-emoji>")
        lines.append(f"@{uname}")
        if i < len(items):
            lines.append("──────────")
    if not lines:
        return "❌ ایموجی پریمیوم در پیام پیدا نشد.\n\nیک پیام که داخلش ایموجی پریمیوم باشد بفرست."
    header = f"✨ <b>کد ایموجی پریمیوم</b> | @{uname}\n\n"
    return header + "\n".join(lines)


def format_result_plain(items: list, bot_username: str) -> str:
    """نسخه mono برای کپی راحت (بدون HTML پیچیده)"""
    uname = (bot_username or "SelfmrhelPerbot").lstrip("@")
    parts = []
    for it in items:
        cid = it["id"]
        fb = it["fallback"]
        parts.append(f"{fb}\n{cid}\n@{uname}")
    return "\n──────────\n".join(parts) if parts else "no emoji"


# -------------------- handlers --------------------

@app.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    uname = BOT_USERNAME or "SelfmrhelPerbot"
    text = (
        f"👋 <b>هلپر self MR</b>\n"
        f"یوزرنیم: @{uname}\n\n"
        f"📌 <b>نحوه استفاده:</b>\n"
        f"۱) یک پیام حاوی <b>ایموجی پریمیوم</b> بفرست\n"
        f"۲) کد عددی + تگ HTML را بگیر\n\n"
        f"🔹 اینلاین:\n"
        f"<code>@{uname} </code> + ایموجی/متن\n\n"
        f"🔹 در کانال/گپ با ادمین بودن ربات هم می‌توانی "
        f"از تگ <code>tg-emoji</code> استفاده کنی."
    )
    await message.reply_text(text, parse_mode=ParseMode.HTML)


@app.on_message(filters.private & filters.incoming & ~filters.command("start"))
async def private_emoji_handler(client: Client, message: Message):
    items = extract_custom_emojis(message)
    if not items:
        # اگر فقط متن عادی بود راهنما بده
        await message.reply_text(
            "❌ در این پیام ایموجی <b>پریمیوم</b> پیدا نشد.\n\n"
            "یک پیام که داخلش ایموجی پریمیوم باشد بفرست "
            "(از پک‌های پریمیوم تلگرام).",
            parse_mode=ParseMode.HTML,
        )
        return

    uname = BOT_USERNAME or "SelfmrhelPerbot"
    body = format_result(items, uname)

    # دکمه کپی‌محور: نسخه ساده mono
    plain = format_result_plain(items, uname)
    try:
        await message.reply_text(body, parse_mode=ParseMode.HTML)
    except Exception as e:
        log.warning("html reply fail: %s", e)
        await message.reply_text(plain)

    # پیام دوم فقط کدها برای کپی سریع
    codes = "\n".join(f"`{it['id']}`" for it in items)
    try:
        await message.reply_text(
            f"📋 <b>کدها (قابل کپی):</b>\n{codes}\n\n@{uname}",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass


@app.on_inline_query()
async def inline_handler(client: Client, query: InlineQuery):
    """اینلاین: نمایش نتایج با ایموجی پریمیوم در متن"""
    q = (query.query or "").strip()
    uname = BOT_USERNAME or "SelfmrhelPerbot"
    results = []

    # اگر کوئری عدد خالص است = custom_emoji_id
    cid = None
    fallback = "⭐"
    if q.isdigit() and len(q) >= 15:
        cid = int(q)
    else:
        # جستجوی entity در خود کوئری ممکن نیست؛ فقط متن
        # فرمت: id یا id|emoji
        if "|" in q:
            a, b = q.split("|", 1)
            if a.strip().isdigit():
                cid = int(a.strip())
                fallback = (b.strip() or "⭐")[:8]
        elif q:
            fallback = q[:8]

    if cid:
        # نتیجه با entity پریمیوم از طریق HTML در InputTextMessageContent
        # Bot API: parse_mode HTML + tg-emoji
        html_text = f'<tg-emoji emoji-id="{cid}">{html.escape(fallback)}</tg-emoji>'
        title = f"پریمیوم {cid}"
        description = f"{fallback} → {cid}"
        results.append(
            InlineQueryResultArticle(
                id=f"pe_{cid}",
                title=title,
                description=description,
                input_message_content=InputTextMessageContent(
                    message_text=html_text,
                    parse_mode=ParseMode.HTML,
                ),
            )
        )
        # نسخه متنی کد
        results.append(
            InlineQueryResultArticle(
                id=f"code_{cid}",
                title="کپی کد عددی",
                description=str(cid),
                input_message_content=InputTextMessageContent(
                    message_text=f"{fallback}\n`{cid}`\n@{uname}",
                    parse_mode=ParseMode.MARKDOWN,
                ),
            )
        )
    else:
        results.append(
            InlineQueryResultArticle(
                id="help",
                title="راهنما",
                description="عدد custom_emoji_id را بنویس یا در پیوی ایموجی بفرست",
                input_message_content=InputTextMessageContent(
                    message_text=(
                        f"هلپر @{uname}\n"
                        f"در پیوی یک ایموجی پریمیوم بفرست تا کد بگیری.\n"
                        f"اینلاین: @{uname} 6033..."
                    ),
                ),
            )
        )

    try:
        await query.answer(results, cache_time=5, is_personal=True)
    except Exception as e:
        log.warning("inline answer: %s", e)
        try:
            await query.answer([], cache_time=0)
        except Exception:
            pass


async def main():
    global BOT_USERNAME
    await app.start()
    me = await app.get_me()
    BOT_USERNAME = me.username or "SelfmrhelPerbot"
    log.info("✅ Helper started @%s id=%s", BOT_USERNAME, me.id)
    await idle()
    await app.stop()


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
