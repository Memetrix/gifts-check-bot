import os
import asyncio
import psycopg2
from telebot import TeleBot
from db import get_all_approved_users, get_user_gift_count

# Конфигурация
bot_token = os.getenv("BOT_TOKEN")
chat_id = int(os.getenv("CHAT_ID"))
admin_id = 1462824  # твой user_id
slava_id = 1911659577

bot = TeleBot(bot_token)
bot.skip_pending = True

def get_connection():
    return psycopg2.connect(
        dbname=os.getenv("PGDATABASE"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        host=os.getenv("PGHOST"),
        port=os.getenv("PGPORT"),
        sslmode="require"
    )

async def run_cleaner():
    print("📋 Cleaner стартовал (без Telethon)")
    message_lines = ["📋 Проверка участников:\n"]

    # Получаем список всех участников чата (через бот API)
    participants = []
    try:
        for member in bot.get_chat_administrators(chat_id):
            participants.append(member.user.id)

        offset = 0
        limit = 200
        while True:
            chat_members = bot.get_chat_members(chat_id, offset, limit)
            if not chat_members:
                break
            for user in chat_members:
                participants.append(user.user.id)
            offset += limit
    except Exception as e:
        print(f"⚠️ Не удалось получить участников: {e}")
        return

    print(f"👥 Найдено участников: {len(set(participants))}")

    approved = get_all_approved_users()
    approved_dict = {row[0]: row for row in approved}

    flagged = 0
    for user_id in set(participants):
        record = approved_dict.get(user_id)
        if not record:
            message_lines.append(f"⚠️ {user_id} — нет в approved_users")
            flagged += 1
            continue

        gifts = get_user_gift_count(user_id)
        if gifts is not None and gifts < 6:
            message_lines.append(f"⚠️ {user_id} — только {gifts} knockdown")
            flagged += 1

    if flagged == 0:
        print("✅ Нарушений не найдено")
        return

    message_lines.append(f"\n👥 Всего в чате: {len(set(participants))}")
    message = "\n".join(message_lines)

    # Отправка в личку тебе и Славе
    try:
        bot.send_message(admin_id, message)
        bot.send_message(slava_id, message)
    except Exception as e:
        print(f"❗️ Ошибка при отправке отчёта: {e}")

if __name__ == "__main__":
    asyncio.run(run_cleaner())
