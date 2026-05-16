# -*- coding: utf-8 -*-
import asyncio
import json
import os
import sys
import re
import sqlite3
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiohttp import web


# 🔍 ПРОВЕРКА ТОКЕНА
TOKEN = os.getenv("TOKEN")
print(f" TOKEN = '{TOKEN}'", flush=True)

if not TOKEN or len(TOKEN) < 30:
    print("❌ ОШИБКА: TOKEN пустой или слишком короткий!", flush=True)
    sys.exit(1)
else:
    print(f"✅ Токен найден: {TOKEN[:20]}...", flush=True)
    bot = Bot(token=TOKEN)
    print("✅ Бот создан успешно!", flush=True)

# 💾 НАСТРОЙКА БАЗЫ ДАННЫХ (SQLite)
DB_FILE = "laskovo_bot.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS new_arrivals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            media_file_id TEXT NOT NULL,
            media_type TEXT NOT NULL,
            description TEXT,
            ozon_link TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

# Создаём таблицу при запуске
init_db()

dp = Dispatcher()
user_data = {}

# Данные для других разделов (хранятся в памяти, так как их мало)
ABOUT_VIDEO_FILE_ID = None
REVIEWS = []
COMFORT_FILE_ID = None
current_review = 0

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
    user_id = message.from_user.id
    if user_id in user_data:
        del user_data[user_id]
    
    await message.answer(
        "Добро пожаловать в Ласково! 🌿\n"
        "Здесь будут скидки, новинки и помощь с выбором.\n"
        "Нажимай на кнопку 👇",
        reply_markup=get_main_keyboard()
    )

# 🔘 ОБРАБОТКА НАЖАТИЯ НА КНОПКУ "НАПИСАТЬ НАМ"
@dp.callback_query(lambda c: c.data == "contact_support")
async def start_support(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_data[user_id] = {"step": "support"}
    await callback.message.answer("Напишите ваш вопрос. Мы ответим вам сюда! 💛")
    await callback.answer()

# 📨 ПОЛУЧЕНИЕ СООБЩЕНИЯ ОТ КЛИЕНТА И ПЕРЕСЫЛКА ТЕБЕ
@dp.message(lambda msg: user_data.get(msg.from_user.id, {}).get("step") == "support")
async def handle_support_message(message: Message):
    admin_id = os.getenv("ADMIN_ID")
    if not admin_id: return
    
    await bot.send_message(
        admin_id, 
        f"📩Новый вопрос:\n\n{message.text}\n\nID: {message.from_user.id}"
    )
    await message.answer("✅ Сообщение отправлено! Ждите ответа.")

# 💬 ТВОЙ ОТВЕТ КЛИЕНТУ
@dp.message(lambda msg: msg.reply_to_message and msg.reply_to_message.text and "📩" in msg.reply_to_message.text)
async def handle_admin_reply(message: Message):
    match = re.search(r'ID:\s*(\d+)', message.reply_to_message.text)
    if match:
        client_id = int(match.group(1))
        try:
            await bot.send_message(client_id, message.text)
            await message.answer("✅ Ответ ушёл клиенту!")
        except:
            await message.answer("❌ Не удалось отправить")

# 🔧 СОХРАНЕНИЕ ВИДЕО ДЛЯ «О НАС»
@dp.message(lambda message: message.video and message.caption and "#о_нас" in message.caption)
async def save_about_video(message: Message):
    global ABOUT_VIDEO_FILE_ID
    ABOUT_VIDEO_FILE_ID = message.video.file_id
    await message.answer("✅ **Видео для «О нас» сохранено!**")

# 🔧 СОХРАНЕНИЕ КОНТЕНТА ДЛЯ «КОМФОРТ И СОСТАВ»
@dp.message(lambda message: (message.photo or message.video) and message.caption and "#комфорт" in message.caption)
async def save_comfort(message: Message):
    global COMFORT_FILE_ID
    if message.photo:
        COMFORT_FILE_ID = message.photo[-1].file_id
    else:
        COMFORT_FILE_ID = message.video.file_id
    await message.answer("✅ **Раздел «Комфорт» сохранён!**")

# 🔧 СОХРАНЕНИЕ ОТЗЫВА
@dp.message(lambda message: (message.photo or message.video) and message.caption and "#отзыв" in message.caption)
async def save_review(message: Message):
    caption_text = message.caption.replace("#отзыв", "").strip()
    
    if message.photo:
        file_id = message.photo[-1].file_id
        file_type = "photo"
    else:
        file_id = message.video.file_id
        file_type = "video"
    
    if not caption_text:
        caption_text = "💬 Отзыв клиентки Ласково"
    
    REVIEWS.append({
        "type": file_type,
        "file_id": file_id,
        "caption": caption_text
    })
    await message.answer(f"✅ **Отзыв сохранён!** Всего отзывов: {len(REVIEWS)}")

# 🧵 РАЗДЕЛ «КОМФОРТ И СОСТАВ»
@dp.callback_query(lambda c: c.data == "comfort")
async def process_comfort(callback: CallbackQuery):
    text = (
        "✨ Комфорт, который не замечаешь\n\n"
        "🤍 Бесшовные — никаких врезавшихся резинок и контуров под одеждой\n"
        "🤍 Мягкие — ткань не колется и не натирает, как вторая кожа\n"
        "🤍 Невидимые — идеально под белые брюки, лосины, трикотаж и шёлк\n\n"
        "Забудь о бельё — помни только о комфорте 💛\n\n"
        "📋 Состав\n"
        "Полиамид + эластан. Ластовица из 100% хлопка\n\n"
    )

    if COMFORT_FILE_ID:
        try:
            await callback.message.answer_photo(photo=COMFORT_FILE_ID, caption=text)
        except:
            await callback.message.answer_video(video=COMFORT_FILE_ID, caption=text)
    else:
        await callback.message.answer(text)
    await callback.answer()

# 💬 ПОКАЗ ОТЗЫВОВ
@dp.callback_query(lambda c: c.data == "reviews")
async def show_reviews(callback: CallbackQuery):
    global current_review
    if not REVIEWS:
        await callback.message.answer("🚧 **Раздел в разработке**. Скоро здесь будут отзывы! 💛")
        await callback.answer()
        return
    
    current_review = 0
    await show_review(callback, 0)
    await callback.answer()

async def show_review(callback: CallbackQuery, index: int):
    review = REVIEWS[index]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    nav_buttons = []
    
    if index > 0:
        nav_buttons.append(InlineKeyboardButton(text="← Назад", callback_data="prev_review"))
    if index < len(REVIEWS) - 1:
        nav_buttons.append(InlineKeyboardButton(text="Вперёд →", callback_data="next_review"))
    
    if nav_buttons:
        keyboard.inline_keyboard.append(nav_buttons)
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="🛒 В магазин", url="https://ozon.ru/s/laskovo")])
    
    if review["type"] == "photo":
        await callback.message.answer_photo(photo=review["file_id"], caption=review["caption"], reply_markup=keyboard)
    elif review["type"] == "video":
        await callback.message.answer_video(video=review["file_id"], caption=review["caption"], reply_markup=keyboard)

@dp.callback_query(lambda c: c.data == "next_review")
async def next_review(callback: CallbackQuery):
    global current_review
    if current_review < len(REVIEWS) - 1:
        current_review += 1
        await callback.message.delete()
        await show_review(callback, current_review)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "prev_review")
async def prev_review(callback: CallbackQuery):
    global current_review
    if current_review > 0:
        current_review -= 1
        await callback.message.delete()
        await show_review(callback, current_review)
    await callback.answer()

# ℹ️ РАЗДЕЛ «О НАС»
@dp.callback_query(lambda c: c.data == "about")
async def process_about(callback: CallbackQuery):
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
    
    if ABOUT_VIDEO_FILE_ID:
        await callback.message.answer_video(video=ABOUT_VIDEO_FILE_ID, caption=text)
    else:
        await callback.message.answer(text)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "promo")
async def process_promo(callback: CallbackQuery):
    await callback.message.answer(
        "🎉 Держи свой промокод: LSKV96F8E315\n\n"
        "Только для подписчиков бота: скидка 5% на весь ассортимент\n"
        "👉 Перейти в магазин: https://ozon.ru/s/laskovo\n\n"
        "Просто введи код при оформлении заказа 💛"
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "faq")
async def process_faq(callback: CallbackQuery):
    await callback.message.answer(
        "📦 Отказ и возврат:\n"
        "Отказаться от заказа можно бесплатно в пункте выдачи — пока не забрали посылку\n\n"
        "После получения возврат, к сожалению, невозможен: бельё — товар личной гигиены и по закону обмену не подлежит\n\n"
        "Правильные мерки = идеальный размер 💛"
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "sizes")
async def process_sizes(callback: CallbackQuery):
    await callback.message.answer_photo(
        photo="https://i.postimg.cc/90yYMGTp/Kartocki-Ozon-900h1200-Belye-13.png",
        caption="📏 Размерная сетка Ласково:\n\nМы шьём трусики размеров 42–52\n\nДля правильного подбора:\n1️⃣ Измерьте бёдра (самое широкое место)\n2️⃣ Сравните с таблицей на фото 👆\n💡 Если замеры между двумя размерами — выбирайте больший 💛"
    )
    await callback.answer()

# 👇 ПОДБОР РАЗМЕРА
@dp.callback_query(lambda c: c.data == "size_quiz")
async def start_size_quiz(callback: CallbackQuery):
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
    if user_id not in user_data:
        return
    
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
            
            text = f"✨ Ваш идеальный размер: {size}\n\n"
            text += f"📏 Ваши параметры:\n• Бёдра: {hips} см\n• Талия: {waist} см\n\n"
            text += "📋 Наша размерная сетка:\nРазмер | Талия | Бёдра\n"
            text += "42-44 | 63-67 | 92-98\n44-46 | 68-72 | 94-102\n46-48 | 73-77 | 98-106\n"
            text += "48-50 | 78-82 | 102-110\n50-52 | 83-87 | 106-114\n\n"
            text += "💡 Если параметры попали на границу — берите больший размер.\n\n"
            text += "🛒 Посмотреть модели:\nhttps://ozon.ru/s/laskovo"
            
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
# 🆕 БЛОК НОВИНКИ (SQLite)
# =========================================

# 📸 ЗАГРУЗКА НОВИНКИ
@dp.message(lambda msg: (msg.photo or msg.video) and msg.caption and "#новинка" in msg.caption.lower())
async def save_new_arrival(message: Message):
    print(f"📩 Получена новинка от {message.from_user.id}")
    
    admin_id = os.getenv("ADMIN_ID")
    if str(message.from_user.id) != str(admin_id):
        return

    if message.video:
        media_file_id = message.video.file_id
        media_type = "video"
    elif message.photo:
        media_file_id = message.photo[-1].file_id
        media_type = "photo"
    else:
        return

    caption = message.caption.replace("#новинка", "").strip()
    
    ozon_link = ""
    url_match = re.search(r'(https?://ozon\.ru/\S+)', caption)
    if url_match:
        ozon_link = url_match.group(1)

    # Сохраняем в SQLite
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''INSERT INTO new_arrivals (media_file_id, media_type, description, ozon_link) 
                      VALUES (?, ?, ?, ?)''', 
                   (media_file_id, media_type, caption, ozon_link))
    conn.commit()
    conn.close()

    await message.answer("✅ Новинка сохранена в базу!")

# 🔘 КНОПКА "НОВИНКИ" (ПОКАЗ)
@dp.callback_query(lambda c: c.data == "new_arrivals")
async def show_new_arrivals(callback: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM new_arrivals ORDER BY id DESC LIMIT 5')
    new_items = cursor.fetchall()
    conn.close()

    if new_items:
        await callback.message.answer("🆕 **Наши новинки**:\n\n")
        
        for item in new_items:
            text = f"🌟 {item['description'] or 'Без описания'}\n"
            if item['ozon_link']:
                text += f"\n🛒 [Купить на Ozon]({item['ozon_link']})"
            
            if item['media_type'] == "video":
                await callback.message.answer_video(
                    video=item['media_file_id'],
                    caption=text,
                    parse_mode="Markdown"
                )
            else:
                await callback.message.answer_photo(
                    photo=item['media_file_id'],
                    caption=text,
                    parse_mode="Markdown"
                )
            
            await asyncio.sleep(0.5)
            
        await callback.message.answer(
            "\n💛 Подпишись на нас, чтобы не пропустить новые поступления!",
            reply_markup=get_main_keyboard()
        )
    else:
        await callback.message.answer(
            "🆕 Новинки скоро появятся!\n\nСледите за обновлениями 💛",
            reply_markup=get_main_keyboard()
        )
    
    await callback.answer()

# =========================================
# ГЛАВНАЯ ФУНКЦИЯ ЗАПУСКА
# =========================================

async def main():
    app = web.Application()
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"✅ Порт открыт на {port}")

    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
