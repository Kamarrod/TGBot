import logging
import json
import asyncio
import psycopg2
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Настройки логирования
logging.basicConfig(level=logging.INFO)

# Чтение конфигурации базы данных из файла config.json
with open('config.json', 'r') as config_file:
    DB_CONFIG = json.load(config_file)

# Чтение токена бота из файла token.txt
TOKEN = open('token.txt').read().strip()

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher()

# Функция для добавления пользователя в базу данных, если он ещё не существует
async def add_user_if_not_exists(telegram_id):
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)  # Подключение к базе данных
        cursor = conn.cursor()

        # Проверяем, существует ли пользователь в базе данных
        cursor.execute("SELECT user_id FROM users WHERE telegram_id = %s", (telegram_id,))
        user = cursor.fetchone()

        if not user:  # Если пользователь не найден, добавляем его
            cursor.execute("INSERT INTO users (telegram_id) VALUES (%s) RETURNING user_id", (telegram_id,))
            new_user_id = cursor.fetchone()[0]
            conn.commit()
            return new_user_id  # Возвращаем ID нового пользователя
        else:
            return user[0]  # Возвращаем ID существующего пользователя

    except Exception as e:
        logging.error(f"Ошибка добавления пользователя: {e}")
    finally:
        if conn:
            cursor.close()
            conn.close()

# Функция для получения user_id по telegram_id
async def get_user_id(telegram_id):
    conn = None
    user_id = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE telegram_id = %s", (telegram_id,))
        user_id = cursor.fetchone()
        if user_id:
            user_id = user_id[0]
    except Exception as e:
        logging.error(f"Ошибка получения user_id: {e}")
    finally:
        if conn:
            cursor.close()
            conn.close()
    return user_id

# Функция для добавления книги в список пользователя
async def add_book_to_user(user_id, book_title):
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO user_books (user_id, book_id)
            VALUES (%s, (SELECT book_id FROM books WHERE book_title ILIKE %s))
            """,
            (user_id, book_title))
        conn.commit()
    except Exception as e:
        logging.error(f"Ошибка добавления книги: {e}")
    finally:
        if conn:
            cursor.close()
            conn.close()

# Функция для получения рекомендаций книг на основе названия книги
async def get_recommendations(book_title, offset=0):
    conn = None
    recommendations = []
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # SQL-запрос для получения рекомендаций
        cursor.execute("""
            SELECT b.book_title FROM user_books ub
            JOIN books b ON ub.book_id = b.book_id
            WHERE ub.user_id IN (
                SELECT user_id FROM user_books WHERE book_id IN (
                    SELECT book_id FROM books WHERE book_title = %s
                )
            ) AND b.book_title != %s
            GROUP BY b.book_title
            ORDER BY COUNT(*) DESC
            LIMIT 100 OFFSET %s;
        """, (book_title, book_title, offset))

        recommendations = cursor.fetchall()
        recommendations = [rec[0] for rec in recommendations]

    except Exception as e:
        logging.error(f"Ошибка получения рекомендаций: {e}")
    finally:
        if conn:
            cursor.close()
            conn.close()

    return recommendations

# Функция для получения случайных книг
async def get_random_books():
    conn = None
    random_books = []
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # SQL-запрос для получения случайных книг
        cursor.execute("SELECT book_title FROM books ORDER BY RANDOM() LIMIT 5;")
        random_books = cursor.fetchall()
        random_books = [book[0] for book in random_books]

    except Exception as e:
        logging.error(f"Ошибка получения случайных книг: {e}")
    finally:
        if conn:
            cursor.close()
            conn.close()

    return random_books

# Обработчик команды /start
@dp.message(Command(commands=['start']))
async def start_command(message: types.Message):
    await message.reply("Привет! Напиши название книги, чтобы получить рекомендации.")

# Обработчик команды /clear
@dp.message(Command(commands=['clear']))
async def clear_context(message: types.Message):
    await message.reply("Контекст очищен.")

# Обработчик команды /recommend
@dp.message(Command(commands=['recommend']))
async def recommend_books(message: types.Message):
    telegram_id = message.from_user.id
    user_id = await add_user_if_not_exists(telegram_id)

    # Разделяем текст команды на части
    message_text = message.text.strip()
    parts = message_text.split(' ', 1)

    if len(parts) > 1:
        book_title = parts[1]  # Название книги, если оно указано
    else:
        book_title = None

    # Сохраняем книгу в список пользователя
    if book_title:
        await add_book_to_user(user_id, book_title)

    # Получаем рекомендации для книги
    recommendations = await get_recommendations(book_title)

    if recommendations:
        await send_recommendations(message.chat.id, recommendations, book_title, 0)
    else:
        await message.reply("Извините, у меня нет рекомендаций для вас.")

# Функция для отправки рекомендаций с кнопками "Вывести еще"
async def send_recommendations(chat_id, recommendations, book_title, offset):
    limit = 5
    current_recommendations = recommendations[offset:offset + limit]

    if current_recommendations:
        response_message = "Вот что я могу порекомендовать:\n" + "\n".join(current_recommendations)

        # Создаем клавиатуру с кнопкой "Вывести еще"
        inline_buttons = []
        if len(recommendations) - offset - limit > 0:
            inline_buttons = [
                InlineKeyboardButton(
                    text="Вывести еще",
                    callback_data=f"show_more,{offset + limit},{book_title}"
                )
            ]

        # Передаем inline_keyboard в конструктор
        keyboard = InlineKeyboardMarkup(inline_keyboard=[inline_buttons])

        await bot.send_message(chat_id, response_message, reply_markup=keyboard)
    else:
        await bot.send_message(chat_id, "Больше рекомендаций нет.")


# Обработчик кнопки "Вывести еще"
@dp.callback_query(lambda callback_query: callback_query.data.startswith("show_more"))
async def process_show_more(callback_query: types.CallbackQuery):
    """Обработчик кнопки "Вывести еще"."""
    _, offset, book_title = callback_query.data.split(',')
    offset = int(offset)

    telegram_id = callback_query.from_user.id

    # Получаем рекомендации
    recommendations = await get_recommendations(book_title)

    # Отправляем следующие рекомендации
    await send_recommendations(callback_query.message.chat.id, recommendations, book_title, offset)

    # Уведомляем Telegram, что запрос обработан
    await bot.answer_callback_query(callback_query.id)


# Обработчик команды /random
@dp.message(Command(commands=['random']))
async def random_books_command(message: types.Message):
    random_books = await get_random_books()

    if random_books:
        await message.reply("Вот 5 случайных книг:\n" + "\n".join(random_books))
    else:
        await message.reply("Извините, не удалось получить случайные книги.")

# Основная функция запуска бота
async def main():
    logging.info("Бот запущен.")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
