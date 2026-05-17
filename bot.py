# -*- coding: utf-8 -*-
import asyncio
import os
import sys
import re
import asyncpg
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiohttp import web

# 🔍 ПРОВЕРКА ТОКЕНА
TOKEN = os.getenv("TOKEN")
if not TOKEN or len(TOKEN) < 30:
    sys.exit("❌ ОШИБКА: TOKEN пустой!")
    
bot = Bot(token=TOKEN)
dp = Dispatcher()

# 🔗 ПОДКЛЮЧЕНИЕ К БАЗЕ ДАННЫХ
DATABASE_URL = os.getenv("DATABASE_URL")

async def get_db_conn():
    return await asyncpg.connect(DATABASE_URL)

async def init_db():
    conn = await get_db_conn()
    # Таблица для новинок
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS new_arrivals (
            id SERIAL PRIMARY KEY,
            media_file_id TEXT NOT NULL,
            media_type TEXT NOT NULL,
            description TEXT,
            ozon_link TEXT,
            added_at TIMESTAMP DEFAULT NOW()
        )
    ''')
    # Единая таблица для всего контента (О нас, Комфорт, Отзывы)
    await conn.execute('''
        CREATE TABLE IF NOT EXISTS bot_content (
            id SERIAL PRIMARY KEY,
            content_type TEXT NOT NULL,
            media_file_id TEXT NOT NULL,
            media_type TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    ''')
    await conn.close()

user_data = {}

def get_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Наш магазин на Ozon", url="https://ozon.ru/s/laskovo")],
        [InlineKeyboardButton(text="📸 Instagram", url="https://www.instagram.com/laskovo_lingerie/")],
        [InlineKeyboardButton(text="🎁 Получить промокод", callback_data="promo")],
        [InlineKeyboardButton(text="📏 Подобрать размер за 10 секунд", callback_data="size_quiz")],
        [InlineKeyboardButton(text="🧵 Комфорт и состав", callback_data="comfort")],
        [InlineKeyboardButton(text="💬 Отзывы клиентов", callback_data="reviews")],
        [InlineKeyboardButton(text="📦 Возврат", callback_data="faq")],
        [InlineKeyboardButton(text="ℹ️ О нас", callback_data="about")],
        [InlineKeyboardButton(text="🆕 Новинки", callback_data="new_arrivals")],
        [InlineKeyboardButton(text="💬 Написать нам", callback_data="contact_support")],
    ])

@dp.message(Command("start"))
async def cmd_start(message: Message):
    if message.from_user.id in user_data: 
        del user_data[message.from_user.id]
        
    await message.answer(
        "Добро пожаловать в Ласково! 🌿\nНажимай на кнопку 👇", 
        reply_markup=get_main_keyboard()
    )
    
    await message.answer(
        "✨ Бот постоянно обновляется!\n"
        "Мы добавляем новые функции, акции и товары 🎁\n\n"
        "Чтобы всегда видеть актуальное меню:\n"
        "1️⃣ Напиши /start — и меню обновится\n"
        "2️⃣ Или очисти историю чата с ботом и напиши /start\n\n"
        "Это займёт 5 секунд, а ты всегда будешь в курсе новинок! 💛"
    )

@dp.callback_query(lambda c: c.data == "contact_support")
async def start_support(callback: CallbackQuery):
    user_data[callback.from_user.id] = {"step": "support"}
    await callback.message.answer("Напишите ваш вопрос. Мы ответим вам сюда! 💛")
    await callback.answer()

@dp.message(lambda msg: user_data.get(msg.from_user.id, {}).get("step") == "support")
async def handle_support_message(message: Message):
    admin_id = os.getenv("ADMIN_ID")
    if not admin_id: return
    await bot.send_message(admin_id, f"📩Новый вопрос:\n\n{message.text}\n\nID: {message.from_user.id}")
    await message.answer("✅ Сообщение отправлено! Ждите ответа.")

# =========================================
# 💬 ОТВЕТ АДМИНА ПОЛЬЗОВАТЕЛЮ
# =========================================
@dp.message(lambda msg: msg.reply_to_message and str(msg.from_user.id) == str(os.getenv("ADMIN_ID")))
async def admin_reply(message: Message):
    original_text = message.reply_to_message.text
    if "ID:" in original_text:
        user_id = original_text.split("ID:")[-1].strip()
        try:
            await bot.send_message(user_id, f"💬 **Ответ поддержки:**\n\n{message.text}")
            await message.answer("✅ Ответ отправлен клиенту!")
        except Exception as e:
            await message.answer(f"❌ Ошибка отправки: {e}")
    else:
        await message.answer("⚠️ Отвечай (Reply) на сообщение, где есть ID пользователя!")

# =========================================
# 🆕 НОВИНКИ (в базу)
# =========================================
@dp.message(lambda msg: (msg.photo or msg.video) and msg.caption and "#новинка" in msg.caption.lower())
async def save_new_arrival(message: Message):
    admin_id = os.getenv("ADMIN_ID")
    if str(message.from_user.id) != str(admin_id): return
    if message.video:
        media_file_id = message.video.file_id
        media_type = "video"
    elif message.photo:
        media_file_id = message.photo[-1].file_id
        media_type = "photo"
    else: return
    caption = message.caption.replace("#новинка", "").strip()
    ozon_link = ""
    url_match = re.search(r'(https?://ozon\.ru/\S+)', caption)
    if url_match: ozon_link = url_match.group(1)
    try:
        conn = await get_db_conn()
        await conn.execute(
            '''INSERT INTO new_arrivals (media_file_id, media_type, description, ozon_link) VALUES ($1, $2, $3, $4)''', 
            media_file_id, media_type, caption, ozon_link)
        await conn.close()
        await message.answer("✅ Новинка сохранена в базу навсегда!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.callback_query(lambda c: c.data == "new_arrivals")
async def show_new_arrivals(callback: CallbackQuery):
    try:
        conn = await get_db_conn()
        records = await conn.fetch('SELECT * FROM new_arrivals ORDER BY id DESC LIMIT 5')
        await conn.close()
        if not records:
            await callback.message.answer("🆕 Новинки скоро появятся!", reply_markup=get_main_keyboard())
            await callback.answer()
            return
        await callback.message.answer("🆕 **Наши новинки**:\n\n")
        for item in records:
            text = f"🌟 {item['description'] or 'Без описания'}\n"
            if item['ozon_link']: text += f"\n🛒 [Купить на Ozon]({item['ozon_link']})"
            if item['media_type'] == "video":
                await callback.message.answer_video(video=item['media_file_id'], caption=text, parse_mode="Markdown")
            else:
                await callback.message.answer_photo(photo=item['media_file_id'], caption=text, parse_mode="Markdown")
            await asyncio.sleep(0.5)
        await callback.message.answer("\n💛 Больше новинок скоро!", reply_markup=get_main_keyboard())
    except Exception as e:
        await callback.message.answer(f"Ошибка: {e}")
    await callback.answer()

# =========================================
# 📹 О НАС (в базу)
# =========================================
@dp.message(lambda message: message.video and message.caption and "#о_нас" in message.caption)
async def save_about_video(message: Message):
    try:
        conn = await get_db_conn()
        await conn.execute("DELETE FROM bot_content WHERE content_type = 'about'")
        await conn.execute("INSERT INTO bot_content (content_type, media_file_id, media_type) VALUES ($1, $2, $3)", "about", message.video.file_id, "video")
        await conn.close()
        await message.answer("✅ Видео «О нас» сохранено в базу!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

# =========================================
# 📸 КОМФОРТ (в базу)
# =========================================
@dp.message(lambda message: (message.photo or message.video) and message.caption and "#комфорт" in message.caption)
async def save_comfort(message: Message):
    media_file_id = message.photo[-1].file_id if message.photo else message.video.file_id
    media_type = "photo" if message.photo else "video"
    try:
        conn = await get_db_conn()
        await conn.execute("DELETE FROM bot_content WHERE content_type = 'comfort'")
        await conn.execute("INSERT INTO bot_content (content_type, media_file_id, media_type) VALUES ($1, $2, $3)", "comfort", media_file_id, media_type)
        await conn.close()
        await message.answer("✅ Раздел «Комфорт» сохранён в базу!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

# =========================================
# 💬 ОТЗЫВЫ (в базу)
# =========================================
@dp.message(lambda message: (message.photo or message.video) and message.caption and "#отзыв" in message.caption)
async def save_review(message: Message):
    caption_text = message.caption.replace("#отзыв", "").strip() or "💬 Отзыв клиентки Ласково"
    file_id = message.photo[-1].file_id if message.photo else message.video.file_id
    file_type = "
