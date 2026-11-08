"""Один раз запустить на своём компьютере, чтобы получить строку сессии технического аккаунта.

    pip install telethon==1.45.0
    python scraper/make_session.py

Скрипт спросит api_id, api_hash, номер телефона и код из Telegram (и пароль, если включена
двухэтапная проверка). В конце напечатает длинную строку — её нужно положить в секрет TG_SESSION.
Эта строка — полный доступ к аккаунту: никому не пересылайте, в чат и в код не вставляйте.
"""
from telethon.sessions import StringSession
from telethon.sync import TelegramClient

api_id = int(input("api_id: ").strip())
api_hash = input("api_hash: ").strip()
with TelegramClient(StringSession(), api_id, api_hash) as client:
    print("\nГотово. Скопируйте строку ниже в секрет TG_SESSION:\n")
    print(client.session.save())
