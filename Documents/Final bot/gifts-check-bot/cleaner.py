import os
import asyncio
import psycopg2
import traceback
from telebot import TeleBot
from telethon import TelegramClient
from telethon.tl.types import InputUser
from get_user_star_gifts_request import GetUserStarGiftsRequest

# Конфигурация
api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")
chat_id = int(os.getenv("CHAT_ID", "-1002655130461"))
session_file = "userbot_session"

PGHOST = os.getenv("PGHOST")
PGPORT = os.getenv("PGPORT")
PGDATABASE = os.getenv("PGDATABASE")
PGUSER = os.getenv("PGUSER")
PGPASSWORD = os.getenv("PGPASSWORD")

bot = TeleBot(bot_token)

def get_connection():
    return psycopg2.connect(
        dbname=PGDATABASE,
        user=PGUSER,
        password=PGPASSWORD,
        host=PGHOST,
        port=PGPORT,
        sslmode="require"
    )

async def check_user_and_kick(user_id, username, client):
    try:
        entity = await client.get_input_entity(user_id)
        if not isinstance(entity, InputUser):
            entity = InputUser(entity.user_id, entity.access_hash)

        result = await client(GetUserStarGiftsRequest(user_id=entity, offset="", limit=100))
        count = 0
        for g in result.gifts:
            data = g.to_dict()
            gift_data = data.get("gift")
            if not gift_data or "title" not in gift_data or "slug" not in gift_data:
                continue
            for attr in gift_data.get("attributes", []):
                if "name" in attr and attr["name"].lower() == "knockdown":
                    count += 1
                    break

        if count < 6:
            print(f"❌ {user_id} ({username}) — {count} knockdown, кикаем")
            bot.ban_chat_member(chat_id, user_id)
            bot.unban_chat_member(chat_id, user_id)
            bot.send_message(user_id, f"🚫 У тебя осталось {count} knockdown-подарков.\nТы больше не соответствуешь условиям и был удалён из группы.")
        else:
            print(f"✅ {user_id} — {count} knockdown")

    except Exception as e:
        print(f"⚠️ Ошибка при проверке {user_id}: {e}")
        traceback.print_exc()

async def main():
    async with TelegramClient(session_file, api_id, api_hash) as client:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id, username FROM approved_users")
                users = cur.fetchall()
                print(f"👥 Проверяется: {len(users)} пользователей")

                for user_id, username in users:
                    await check_user_and_kick(user_id, username, client)

if __name__ == "__main__":
    asyncio.run(main())
