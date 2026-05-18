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

# =========================================
# 📊 АНАЛИТИКА: Запись действий пользователя
# =========================================
async def log_user_action(user_id: int, username: str, first_name: str, action: str):
    try:
        conn = await get_db_conn()
        existing = await conn.fetchrow("SELECT id, actions_count FROM bot_analytics WHERE user_id = $1", user_id)
        
        if existing:
            await conn.execute(
                "UPDATE bot_analytics SET last_visit = NOW(), actions_count = $1, last_action = $2 WHERE user_id = $3",
                existing['actions_count'] + 1, action, user_id
            )
        else:
            await conn.execute(
                "INSERT INTO bot_analytics (user_id, username, first_name, last_action) VALUES ($1, $2, $3, $4)",
                user_id, username, first_name, action
            )
        await conn.close()
    except Exception as e:
        print(f"❌ Ошибка логирования: {e}")

async def init_db():
    conn = await get_db_conn()
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
    
    await log_user_action(
        user_id=message.from_user.id,
        username=message.from_user.username or "Нет username",
        first_name=message.from_user.first_name or "Аноним",
        action="Запустил бота (/start)"
    )

@dp.message(Command("stats"))
async def show_stats(message: Message):
    admin_id = os.getenv("ADMIN_ID")
    if str(message.from_user.id) != str(admin_id):
        return
    
    try:
        conn = await get_db_conn()
        total_users = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM bot_analytics")
        today_users = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM bot_analytics WHERE last_visit >= NOW() - INTERVAL '1 day'")
        total_actions = await conn.fetchval("SELECT SUM(actions_count) FROM bot_analytics")
        
        top_actions = await conn.fetch(
            "SELECT last_action, COUNT(*) as cnt FROM bot_analytics GROUP BY last_action ORDER BY cnt DESC LIMIT 5"
        )
        
        await conn.close()
        
        stats_text = f"📊 **Статистика бота Ласково**\n\n"
        stats_text += f"👥 Всего пользователей: {total_users}\n"
        stats_text += f"🆕 За сегодня: {today_users}\n"
        stats_text += f"⚡ Всего действий: {total_actions}\n\n"
        stats_text += f"🔥 Топ-5 действий:\n"
        for i, action in enumerate(top_actions, 1):
            stats_text += f"{i}. {action['last_action']} — {action['cnt']} раз(а)\n"
        
        await message.answer(stats_text)
    except Exception as e:
        await message.answer(f"❌ Ошибка получения статистики: {e}")

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
    await log_user_action(
        user_id=callback.from_user.id,
        username=callback.from_user.username or "Нет username",
        first_name=callback.from_user.first_name or "Аноним",
        action="Нажал: Новинки"
    )
    
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

@dp.message(lambda message: (message.photo or message.video) and message.caption and "#отзыв" in message.caption)
async def save_review(message: Message):
    caption_text = message.caption.replace("#отзыв", "").strip() or "💬 Отзыв клиентки Ласково"
    file_id = message.photo[-1].file_id if message.photo else message.video.file_id
    file_type = "photo" if message.photo else "video"
    try:
        conn = await get_db_conn()
        await conn.execute("INSERT INTO bot_content (content_type, media_file_id, media_type, description) VALUES ($1, $2, $3, $4)", "review", file_id, file_type, caption_text)
        await conn.close()
        await message.answer("✅ Отзыв сохранён в базу навсегда!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.callback_query(lambda c: c.data == "comfort")
async def process_comfort(callback: CallbackQuery):
    await log_user_action(
        user_id=callback.from_user.id,
        username=callback.from_user.username or "Нет username",
        first_name=callback.from_user.first_name or "Аноним",
        action="Нажал: Комфорт и состав"
    )
    
    text = (
        "✨ Комфорт, который не замечаешь\n\n"
        "🤍 Бесшовные — никаких врезавшихся резинок и контуров под одеждой\n"
        "🤍 Мягкие — ткань не колется и не натирает, как вторая кожа\n"
        "🤍 Невидимые — идеально под белые брюки, лосины, трикотаж и шёлк\n\n"
        "Забудь о бельё — помни только о комфорте 💛\n\n"
        "📋 Состав\nПолиамид + эластан. Ластовица из 100% хлопка\n\n"
    )
    try:
        conn = await get_db_conn()
        record = await conn.fetchrow("SELECT * FROM bot_content WHERE content_type = 'comfort' LIMIT 1")
        await conn.close()
        if record:
            if record['media_type'] == "photo":
                await callback.message.answer_photo(photo=record['media_file_id'], caption=text)
            else:
                await callback.message.answer_video(video=record['media_file_id'], caption=text)
        else:
            await callback.message.answer(text)
    except Exception as e:
        await callback.message.answer(text)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "reviews")
async def show_reviews(callback: CallbackQuery):
    await log_user_action(
        user_id=callback.from_user.id,
        username=callback.from_user.username or "Нет username",
        first_name=callback.from_user.first_name or "Аноним",
        action="Нажал: Отзывы клиентов"
    )
    
    try:
        conn = await get_db_conn()
        records = await conn.fetch("SELECT * FROM bot_content WHERE content_type = 'review' ORDER BY id DESC")
        await conn.close()
        if not records:
            await callback.message.answer("🚧 **Раздел в разработке**.")
            await callback.answer()
            return
        user_data[callback.from_user.id] = {"reviews": records, "current": 0}
        await show_review_from_db(callback, 0)
    except Exception as e:
        await callback.message.answer(f"Ошибка: {e}")
    await callback.answer()

async def show_review_from_db(callback: CallbackQuery, index: int):
    user_id = callback.from_user.id
    reviews = user_data.get(user_id, {}).get("reviews", [])
    if not reviews or index >= len(reviews): return
    review = reviews[index]
    caption = review["description"] or "💬 Отзыв клиентки Ласково"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    nav_buttons = []
    if index > 0: nav_buttons.append(InlineKeyboardButton(text="← Назад", callback_data="prev_review_db"))
    if index < len(reviews) - 1: nav_buttons.append(InlineKeyboardButton(text="Вперёд →", callback_data="next_review_db"))
    if nav_buttons: keyboard.inline_keyboard.append(nav_buttons)
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="🛒 В магазин", url="https://ozon.ru/s/laskovo")])
    if review["media_type"] == "photo":
        await callback.message.answer_photo(photo=review["media_file_id"], caption=caption, reply_markup=keyboard)
    else:
        await callback.message.answer_video(video=review["media_file_id"], caption=caption, reply_markup=keyboard)

@dp.callback_query(lambda c: c.data == "next_review_db")
async def next_review_db(callback: CallbackQuery):
    user_id = callback.from_user.id
    reviews = user_data.get(user_id, {}).get("reviews", [])
    current = user_data.get(user_id, {}).get("current", 0)
    if current < len(reviews) - 1:
        user_data[user_id]["current"] = current + 1
        await callback.message.delete()
        await show_review_from_db(callback, current + 1)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "prev_review_db")
async def prev_review_db(callback: CallbackQuery):
    user_id = callback.from_user.id
    reviews = user_data.get(user_id, {}).get("reviews", [])
    current = user_data.get(user_id, {}).get("current", 0)
    if current > 0:
        user_data[user_id]["current"] = current - 1
        await callback.message.delete()
        await show_review_from_db(callback, current - 1)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "about")
async def process_about(callback: CallbackQuery):
    await log_user_action(
        user_id=callback.from_user.id,
        username=callback.from_user.username or "Нет username",
        first_name=callback.from_user.first_name or "Аноним",
        action="Нажал: О нас"
    )
    
    text = (
        "🌿 Ласково — бельё, которое мы создаем, а не перепродаем\n\n"
        "🔹 Разработка лекал и пошив тестовых партий\n"
        "🔹 Примерка на реальных женщинах всех размеров\n"
        "🔹 Внесение корректировок до идеальной посадки\n\n"
        "✨ Что вы получаете:\n"
        "• Бесшовные стринги (наборы по 3 шт.) в стильной жестяной упаковке.\n"
        "• Честные размеры 42–52 без сюрпризов.\n"
        "• Комфорт, который не замечаешь, но чувствуешь.\n\n"
        "💛 Наша философия:\n"
        "«Идеальное бельё — это когда о нём забываешь, но чувствуешь себя в нём невероятно»."
    )
    try:
        conn = await get_db_conn()
        record = await conn.fetchrow("SELECT * FROM bot_content WHERE content_type = 'about' LIMIT 1")
        await conn.close()
        if record:
            await callback.message.answer_video(video=record['media_file_id'], caption=text)
        else:
            await callback.message.answer(text)
    except Exception as e:
        await callback.message.answer(text)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "promo")
async def process_promo(callback: CallbackQuery):
    await log_user_action(
        user_id=callback.from_user.id,
        username=callback.from_user.username or "Нет username",
        first_name=callback.from_user.first_name or "Аноним",
        action="Нажал: Получить промокод"
    )
    
    await callback.message.answer(
        "🎉 Держи свой промокод: LSKV96F8E315\n\n"
        "Только для подписчиков бота: скидка 5% на весь ассортимент\n"
        "👉 Перейти в магазин: https://ozon.ru/s/laskovo\n\n"
        "Просто введи код при оформлении заказа 💛"
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "faq")
async def process_faq(callback: CallbackQuery):
    await log_user_action(
        user_id=callback.from_user.id,
        username=callback.from_user.username or "Нет username",
        first_name=callback.from_user.first_name or "Аноним",
        action="Нажал: Возврат"
    )
    
    await callback.message.answer(
        "📦 Отказ и возврат:\n"
        "Отказаться от заказа можно бесплатно в пункте выдачи — пока не забрали посылку\n\n"
        "После получения возврат, к сожалению, невозможен: бельё — товар личной гигиены и по закону обмену не подлежит\n\n"
        "Правильные мерки = идеальный размер 💛"
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "size_quiz")
async def start_size_quiz(callback: CallbackQuery):
    await log_user_action(
        user_id=callback.from_user.id,
        username=callback.from_user.username or "Нет username",
        first_name=callback.from_user.first_name or "Аноним",
        action="Начал подбор размера"
    )
    
    user_id = callback.from_user.id
    user_data[user_id] = {"step": "waiting_hips"}
    await callback.message.answer(
        "📏 Подберём размер для вас\n\n"
        "Напишите обхват бёдер (в см).\n"
        "Измерьте по самым выступающим точкам.\n\n"
        "Пример: 96"
    )
    await callback.answer()

@dp.message()
async def process_measurements(message: Message):
    user_id = message.from_user.id
    if user_id not in user_data: return
    try:
        value = int(message.text)
        user_step = user_data[user_id].get("step")
        if user_step == "waiting_hips":
            if value < 80 or value > 120:
                await message.answer("Пожалуйста, введите реальный обхват бёдер (от 80 до 120 см).")
                return
            user_data[user_id]["hips"] = value
            user_data[user_id]["step"] = "waiting_waist"
            await message.answer("Отлично! Теперь напишите обхват талии (в см).\nИзмерьте в самом узком месте.\n\nПример: 68")
        elif user_step == "waiting_waist":
            if value < 50 or value > 100:
                await message.answer("Пожалуйста, введите реальный обхват талии (от 50 до 100 см).")
                return
            hips = user_data[user_id]["hips"]
            waist = value
            size = calculate_size(hips, waist)
            text = (
                f"✨ Ваш идеальный размер: {size}\n\n"
                f"📏 Ваши параметры:\n• Бёдра: {hips} см\n• Талия: {waist} см\n\n"
                "📋 Наша размерная сетка:\nРазмер | Талия | Бёдра\n"
                "42-44 | 63-67 | 92-98\n44-46 | 68-72 | 94-102\n46-48 | 73-77 | 98-106\n"
                "48-50 | 78-82 | 102-110\n50-52 | 83-87 | 106-114\n\n"
                "💡 Если параметры попали на границу — берите больший размер.\n\n"
                "🛒 Посмотреть модели:\nhttps://ozon.ru/s/laskovo"
            )
            await message.answer(text, reply_markup=get_main_keyboard())
            del user_data[user_id]
    except ValueError:
        await message.answer("Пожалуйста, введите число (например: 96)")

def calculate_size(hips, waist):
    if hips <= 98 and waist <= 67: return "42-44"
    elif hips <= 102 and waist <= 72: return "44-46"
    elif hips <= 106 and waist <= 77: return "46-48"
    elif hips <= 110 and waist <= 82: return "48-50"
    else: return "50-52"

# =========================================
# ЗАПУСК
# =========================================
async def main():
    await init_db()
    print("✅ База данных подключена!")
    
    # 🌐 Health check для UptimeRobot
    app = web.Application()
    
    async def health_check(request):
        return web.Response(text="<h1>Bot is running! 💛</h1>", content_type='text/html')
    
    app.router.add_get('/', health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"✅ Порт открыт на {port}")
    print(f"✅ Health check доступен на http://localhost:{port}/")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
