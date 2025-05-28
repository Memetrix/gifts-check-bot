import os
import asyncio
import psycopg2
from telethon import TelegramClient
from telethon.tl.types import InputUser
from get_user_star_gifts_request import GetUserStarGiftsRequest
from telebot import TeleBot

# Конфиг
api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
session_file = "userbot_session"
chat_id = int(os.getenv("CHAT_ID"))
bot_token = os.getenv("BOT_TOKEN")
bot = TeleBot(bot_token)

# Получение knockdown-подарков
async def get_knockdown_count_safe(client, entity):
    count = 0
    offset = ""
    try:
        while True:
            result = await client(GetUserStarGiftsRequest(user_id=entity, offset=offset, limit=100))
            if not result.gifts:
                break
            for g in result.gifts:
                data = g.to_dict()
                gift_data = data.get("gift")
                if not gift_data:
                    continue
                for attr in gift_data.get("attributes", []):
                    if "name" in attr and attr["name"].lower() == "knockdown":
                        count += 1
                        break
            offset = result.next_offset or ""
            if not offset:
                break
    except Exception as e:
        print(f"⚠️ Ошибка при получении подарков: {e}")
    return count

# Считаем общее количество knockdown-подарков
async def report_total_knockdowns():
    async with TelegramClient(session_file, api_id, api_hash) as client:
        conn = psycopg2.connect(
            host=os.getenv("PGHOST"),
            dbname=os.getenv("PGDATABASE"),
            user=os.getenv("PGUSER"),
            password=os.getenv("PGPASSWORD"),
            port=os.getenv("PGPORT")
        )
        cur = conn.cursor()
        cur.execute("SELECT user_id, username FROM approved_users")
        rows = cur.fetchall()
        total = 0

        for user_id, username in rows:
            try:
                entity = await client.get_input_entity(user_id)
                count = await get_knockdown_count_safe(client, entity)
                print(f"🎁 {username or user_id} → {count}")
                total += count
                await asyncio.sleep(0.3)  # чтобы не поймать FloodWait
            except Exception as e:
                print(f"⚠️ Ошибка у {username or user_id}: {e}")

        # Отправляем результат
        bot.send_message(chat_id, f"🎁 Общее количество knockdown-подарков у всех участников: {total}")

        cur.close()
        conn.close()

if __name__ == "__main__":
    asyncio.run(report_total_knockdowns())
