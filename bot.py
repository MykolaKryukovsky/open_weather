import os
import asyncio
import logging
from typing import Any, Final
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import httpx

from telegram import Update, User, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)


load_dotenv()
BOT_TOKEN: Final[str | None] = os.getenv("TELEGRAM_BOT_TOKEN")
WEATHER_API_KEY: Final[str | None] = os.getenv("API_KEY")
EXCHANGE_API_KEY: Final[str | None] = os.getenv("EXCHANGE_API_KEY")

AWAITING_CITY: Final[int] = 1
DATA_CACHE: dict[str, dict[str, Any]] = {}
CACHE_TTL_MINUTES: Final[int] = 10


logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')


flask_app = Flask(__name__)


app = Application.builder().token(BOT_TOKEN).build()


def get_cached_data(cache_key: str) -> Any | None:
    if cache_key in DATA_CACHE:
        cache_entry = DATA_CACHE[cache_key]
        if datetime.now() - cache_entry["timestamp"] < timedelta(minutes=CACHE_TTL_MINUTES):
            logging.info(f"💾 Кеш активовано для: {cache_key}")
            return cache_entry["data"]
    return None


def set_cache_data(cache_key: str, data: Any) -> None:
    DATA_CACHE[cache_key] = {"timestamp": datetime.now(), "data": data}


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user: User | None = update.effective_user
    keyboard = [
        [InlineKeyboardButton("⛅ Київ", callback_data="weather:Київ"),
         InlineKeyboardButton("⛅ Одеса", callback_data="weather:Одеса"),
         InlineKeyboardButton("⛅ Львів", callback_data="weather:Львів")],
        [InlineKeyboardButton("💵 Курс USD", callback_data="currency:USD"),
         InlineKeyboardButton("💶 Курс EUR", callback_data="currency:EUR")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    greeting = f"👋 Привіт, {user.first_name if user else 'гостю'}!\nОберіть дію нижче:"
    if update.message:
        await update.message.reply_text(greeting, reply_markup=reply_markup)


async def weather_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message:
        await update.message.reply_text("🌍 Введіть назву міста:")
    return AWAITING_CITY


async def fetch_weather_from_api(city_name: str) -> dict[str, Any] | str:
    url = "https://openweathermap.org"
    params = {"q": city_name, "appid": WEATHER_API_KEY, "units": "metric", "lang": "ua"}
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10.0)
            return response.json() if response.status_code == 200 else "not_found"
    except Exception:
        return "not_found"


async def handle_weather_logic(city_name: str) -> str:
    cache_key = f"weather:{city_name.lower()}"
    cached_res = get_cached_data(cache_key)
    is_cached = bool(cached_res)

    data = cached_res if is_cached else await fetch_weather_from_api(city_name)
    if data == "not_found":
        return "❌ Місто не знайдено або помилка API."

    if not is_cached:
        set_cache_data(cache_key, data)

    try:
        temp = data["main"]["temp"]
        description = data["weather"][0]["description"].capitalize()
        cache_tag = " ⚠️ *(З кешу)*" if is_cached else ""
        return f"🌡️ **Погода в {city_name}{cache_tag}:**\n• Температура: {temp}°C\n• Стан: {description}"
    except Exception:
        return "❌ Помилка обробки даних погоди."


async def process_weather(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message and update.message.text:
        res = await handle_weather_logic(update.message.text.strip())
        await update.message.reply_text(res, parse_mode="Markdown")
    return ConversationHandler.END


async def handle_menu_clicks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    await query.answer()

    action_type, value = query.data.split(":")

    if action_type == "weather":
        response_text = await handle_weather_logic(value)
        await query.message.reply_text(response_text, parse_mode="Markdown")

    elif action_type == "currency":
        cache_key = f"currency:{value.lower()}"
        cached_rate = get_cached_data(cache_key)
        is_cached = bool(cached_rate)

        rate = None
        if is_cached:
            rate = cached_rate
        else:
            url = f"https://exchangerate-api.com{EXCHANGE_API_KEY}/pair/{value}/UAH"
            try:
                async with httpx.AsyncClient() as client:
                    res = await client.get(url, timeout=10.0)
                    if res.status_code == 200:
                        rate = res.json().get("conversion_rate")
                        if rate:
                            set_cache_data(cache_key, rate)
            except Exception:
                rate = None

        if rate is None:
            await query.message.reply_text("⚠️ Не вдалося отримати курс валют.")
            return

        cache_tag = " ⚠️ *(З кешу)*" if is_cached else ""
        sign = {"USD": "💵", "EUR": "💶"}.get(value, "💰")
        msg = f"{sign} **Курс {value} до гривні (UAH){cache_tag}:**\n• 1 {value} = {rate:.2f} UAH"
        await query.message.reply_text(msg, parse_mode="Markdown")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message:
        await update.message.reply_text("🚫 Запит скасовано.")
    return ConversationHandler.END


app.add_handler(CommandHandler("start", start_command))
app.add_handler(CallbackQueryHandler(handle_menu_clicks))
app.add_handler(ConversationHandler(
    entry_points=[CommandHandler("weather", weather_start)],
    states={AWAITING_CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_weather)]},
    fallbacks=[CommandHandler("cancel", cancel_command)]
))


@flask_app.route(f"/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    """Приймає HTTP-запити від Telegram та передає їх асинхронному додатку бота."""
    update_data = request.get_json()
    if update_data:
        update = Update.de_json(update_data, app.bot)
        asyncio.run(app.process_update(update))
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    if not BOT_TOKEN or not WEATHER_API_KEY or not EXCHANGE_API_KEY:
        print("Помилка конфігурації: відсутні ключі в .env")
    else:
        flask_app.run(port=5000)
