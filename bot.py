import os
import logging
from datetime import datetime, timedelta
from typing import Final, Any, NoReturn
import requests
from dotenv import load_dotenv
from telegram import Update, User, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters
)

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler("app.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

load_dotenv()
BOT_TOKEN: Final[str | None] = os.getenv("TELEGRAM_BOT_TOKEN")
WEATHER_API_KEY: Final[str | None] = os.getenv("API_KEY")
EXCHANGE_API_KEY: Final[str | None] = os.getenv("EXCHANGE_API_KEY")

AWAITING_CITY: Final[int] = 1

DATA_CACHE: dict[str, dict[str, Any]] = {}
CACHE_TTL_MINUTES: Final[int] = 10


def get_cached_data(cache_key: str) -> Any | None:
    """Перевіряє наявність даних у кеші та їхню актуальність (до 10 хвилин)."""
    if cache_key in DATA_CACHE:
        cache_entry = DATA_CACHE[cache_key]
        now = datetime.now()
        if now - cache_entry["timestamp"] < timedelta(minutes=CACHE_TTL_MINUTES):
            logging.info(f"💾 Використано дані з кешу для ключа: {cache_key}")
            return cache_entry["data"]
    return None


def set_cache_data(cache_key: str, data: Any) -> None:
    """Зберігає отримані дані в кеш із міткою поточного часу."""
    DATA_CACHE[cache_key] = {
        "timestamp": datetime.now(),
        "data": data
    }
    logging.info(f"📥 Нові дані успешно збережено в кеш для ключа: {cache_key}")


async def clear_expired_cache_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Фонова задача (Job), яка перевіряє кеш та видаляє застарілі записи (>10 хв)."""
    logging.info("🧹 Запуск фонового очищення застарілого кешу...")
    now = datetime.now()
    keys_to_delete = []

    for key, cache_entry in DATA_CACHE.items():
        if now - cache_entry["timestamp"] >= timedelta(minutes=CACHE_TTL_MINUTES):
            keys_to_delete.append(key)

    for key in keys_to_delete:
        del DATA_CACHE[key]
        logging.info(f"🗑️ Видалено застарілий ключ із кешу: {key}")

    if keys_to_delete:
        logging.info(f"✅ Фонову очистку завершено. Очищено елементів: {len(keys_to_delete)}")
    else:
        logging.info("✅ Фонову очистку завершено. Застарілих елементів не знайдено.")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Надсилає користувачеві вітальне повідомлення та головне меню у вигляді кнопок."""
    user: User | None = update.effective_user
    if user:
        logging.info(f"Користувач {user.first_name} (ID: {user.id}) запустив бот.")

    keyboard = [
        [
            InlineKeyboardButton("⛅ Київ", callback_data="weather:Київ"),
            InlineKeyboardButton("⛅ Одеса", callback_data="weather:Одеса"),
            InlineKeyboardButton("⛅ Львів", callback_data="weather:Львів")
        ],
        [
            InlineKeyboardButton("💵 Курс USD до UAH", callback_data="currency:USD"),
            InlineKeyboardButton("💶 Курс EUR до UAH", callback_data="currency:EUR")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    greeting = (
        f"👋 Привіт, {user.first_name if user else 'гостю'}!\n"
        "Я твій універсальний асистент погоди та фінансів.\n\n"
        "Оберіть місто або валюту нижче на кнопках для миттєвого результату, "
        "або скористайтеся командою /weather для ручного пошуку міста."
    )
    if update.message:
        await update.message.reply_text(greeting, reply_markup=reply_markup)


async def weather_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ініціює ручний запит погоди."""
    if update.message:
        await update.message.reply_text("🌍 Будь ласка, введіть назву міста вручну (наприклад, Харків):")
    return AWAITING_CITY


def fetch_weather_from_api(city_name: str) -> dict[str, Any] | str:
    """Запитує погодні дані або повертає рядок помилки."""
    # ВИПРАВЛЕНО: Змінено базовий URL на правильний ендпоінт API
    url = "https://openweathermap.org"
    params = {"q": city_name, "appid": WEATHER_API_KEY, "units": "metric", "lang": "ua"}

    try:
        response = requests.get(url, params=params)
        if response.status_code != 200:
            return "not_found"
        return response.json()
    except Exception as e:
        logging.error(f"Помилка запиту погоди: {e}")
        return "not_found"


async def handle_weather_logic(city_name: str) -> str:
    """Обробляє логіку отримання погоди з урахуванням 10-хвилинного кешу."""
    cache_key = f"weather:{city_name.lower()}"
    cached_res = get_cached_data(cache_key)
    is_cached = False

    if cached_res:
        data = cached_res
        is_cached = True
    else:
        data = fetch_weather_from_api(city_name)
        if data == "not_found":
            return "❌ Місто не знайдено або сталася помилка API. Перевірте назву."
        set_cache_data(cache_key, data)

    # ВИПРАВЛЕНО: Безпечне витягування даних, weather - це масив словників
    try:
        temp = data["main"]["temp"]
        description = data["weather"][0]["description"].capitalize()
        humidity = data["main"]["humidity"]
        wind_speed = data["wind"]["speed"]
    except (KeyError, IndexError) as e:
        logging.error(f"Помилка парсингу JSON погоди: {e}")
        return "❌ Сталася помилка при обробці даних погоди."

    drink_time = (datetime.now() + timedelta(hours=1)).strftime("%H:%M")
    cache_tag = " ⚠️ *(Оновлено з кешу)*" if is_cached else ""

    return (
        f"🌡️ **Погода в місті {city_name}{cache_tag}:**\n"
        f"• Температура: {temp}°C\n"
        f"• Стан: {description}\n"
        f"• Вологість: {humidity}%\n"
        f"• Швидкість вітру: {wind_speed} м/с\n\n"
        f"🔔 *Нагадування:* Не забудьте випити склянку води о **{drink_time}**!"
    )


async def process_weather(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє текстове повідомлення з назвою міста від користувача."""
    if not update.message or not update.message.text:
        return ConversationHandler.END

    city_name = update.message.text.strip()
    result_message = await handle_weather_logic(city_name)

    await update.message.reply_text(result_message, parse_mode="Markdown")
    return ConversationHandler.END


async def handle_menu_clicks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Перехоплює кліки по інлайн-кнопках (міста та валюти)."""
    query = update.callback_query
    if not query or not query.message:
        return

    await query.answer()

    action_data = query.data.split(":")
    action_type = action_data[0]
    value = action_data[1]

    if action_type == "weather":
        response_text = await handle_weather_logic(value)
        await query.message.reply_text(response_text, parse_mode="Markdown")

    elif action_type == "currency":
        cache_key = f"currency:{value.lower()}"
        cached_rate = get_cached_data(cache_key)
        is_cached = False

        if cached_rate:
            rate = cached_rate
            is_cached = True
        else:
            # ВИПРАВЛЕНО: Виправлено URL-адресу для ExchangeRate-API v6
            url = f"https://exchangerate-api.com{EXCHANGE_API_KEY}/pair/{value}/UAH"
            try:
                res = requests.get(url)
                if res.status_code == 200:
                    rate = res.json().get("conversion_rate", "ошибка")
                    if rate != "ошибка":
                        set_cache_data(cache_key, rate)
                else:
                    rate = "ошибка"
            except Exception as e:
                logging.error(f"Помилка запиту валюти: {e}")
                rate = "ошибка"

        if rate == "ошибка":
            await query.message.reply_text("⚠️ Не вдалося отримати курс валют. Спробуйте пізніше.")
            return

        cache_tag = " ⚠️ *(Оновлено з кешу)*" if is_cached else ""
        currency_signs = {"USD": "💵", "EUR": "💶"}
        sign = currency_signs.get(value, "💰")

        # ВИПРАВЛЕНО: rate тепер гарантовано є числом перед використанням format :.2f
        msg = f"{sign} **Курс обміну {value} до гривні (UAH){cache_tag}:**\n• 1 {value} = {float(rate):.2f} UAH"
        await query.message.reply_text(msg, parse_mode="Markdown")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Скасовує операцію введення міста."""
    if update.message:
        await update.message.reply_text("🚫 Запит скасовано.")
    return ConversationHandler.END


def main() -> str | NoReturn:
    """Запуск додатку та реєстрація обробників разом із фоновим таймером очищення."""
    if not BOT_TOKEN or not WEATHER_API_KEY or not EXCHANGE_API_KEY:
        logging.critical("Перевірте наявність усіх трьох ключів у файлі .env!")
        return "Помилка конфігурації"

    app = Application.builder().token(BOT_TOKEN).build()

    job_queue = app.job_queue
    if job_queue:
        job_queue.run_repeating(clear_expired_cache_job, interval=600, first=10)
        logging.info("Фоновий таймер очищення кешу успішно ініціалізовано.")
    else:
        # Важливе попередження, якщо бібліотека встановлена без [job-queue]
        logging.warning("JobQueue недоступна. Встановіть pip install python-telegram-bot[job-queue]")

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(handle_menu_clicks))

    weather_conversation = ConversationHandler(
        entry_points=[CommandHandler("weather", weather_start)],
        states={
            AWAITING_CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_weather)]
        },
        fallbacks=[CommandHandler("cancel", cancel_command)]
    )

    app.add_handler(weather_conversation)

    logging.info("Бот успішно запущений.")
    app.run_polling()


if __name__ == "__main__":
    main()
