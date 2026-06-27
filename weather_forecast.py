import os
import logging
from datetime import datetime, timedelta
from typing import Final
import requests
from dotenv import load_dotenv


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
API_KEY: Final[str | None] = os.getenv("API_KEY")


if not API_KEY:
    logging.error("API_KEY не знайдено у файлі .env. Програму завершено.")
    exit()


def get_day_forecast(city_name: str) -> None:
    """Надсилає запит до OpenWeather API для отримання прогнозу погоди на 24 години.

    Логує етапи виконання, обробляє помилки відповіді сервера та виводить
    результат у консоль разом із часом для нагадування про прийом води.

    Args:
        city_name (str): Назва міста для пошуку прогнозу.
    """
    url: str = "https://openweathermap.org"
    params: dict[str, str | None] = {
        "q": city_name,
        "appid": API_KEY,
        "units": "metric",
        "lang": "ua"
    }

    logging.info(f"Надсилання запиту прогнозу погоди для міста: {city_name}")

    try:
        response: requests.Response = requests.get(url, params=params)

        if response.status_code != 200:
            logging.error(
                f"Невдалий запит. Код помилки API: {response.status_code}. Відповідь: {response.text.strip()}"
            )
            return

        if "application/json" not in response.headers.get("Content-Type", ""):
            logging.error(
                f"Сервер повернув некоректний формат даних замість JSON. Відповідь: {response.text[:100]}"
            )
            return

        data: dict = response.json()

        logging.info(f"Успішно отримано погодні дані для міста {city_name}.")

        print(f"\n☀️ Прогноз погоди в місті {city_name} на найближчі 24 години:")
        print("=" * 55)

        forecast_list: list = data["list"][:8]
        for item in forecast_list:
            time_text: str = item["dt_txt"]
            time_short: str = time_text.split()[-1][:5]
            temp: float = item["main"]["temp"]
            feels_like: float = item["main"]["feels_like"]
            description: str = item["weather"][0]["description"].capitalize()
            wind: float = item["wind"]["speed"]

            print(f"⏰ Час: {time_short} | 🌡️ {temp:>5}°C (Відчувається: {feels_like:>5}°C)")
            print(f"   📋 Стан: {description} | 💨 Вітер: {wind} м/с")
            print("-" * 55)

        drink_time: str = (datetime.now() + timedelta(hours=1)).strftime("%H:%M")
        logging.info(f"⏰ Нагадування: Час, коли потрібно буде випити склянку води — {drink_time}")

    except requests.exceptions.RequestException as e:
        logging.error(f"Мережева помилка під час запиту до API: {e}")


if __name__ == "__main__":
    city: str = input("Введіть назву міста для отримання прогнозу на день: ").strip()
    if city:
        get_day_forecast(city)
    else:
        logging.warning("Користувач ввів порожній рядок замість назви міста.")
