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
DELAY = float(os.getenv("CHECK_DELAY", "1.0"))

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

async def check_and_kick(user, client, approved_ids):
    try:
        # 1. Если user.id не в approved_users → кик без проверки
        if user.id not in approved_ids:
            print(f"🚫 @{user.username or '???'} ({user.id}) — НЕ в approved_users → кик сразу")
            bot.ban_chat_member(chat_id, user.id)
            bot.unban_chat_member(chat_id, user.id)
            try:
                bot.send_message(user.id, "🚫 Ты был удалён из группы, так как не проходил проверку.")
            except:
                print(f"⚠️ Не удалось отправить сообщение @{user.username or user.id}")
            return True

        # 2. Если в approved_users → проверить knockdown
        entity = InputUser(user.id, user.access_hash)

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
            print(f"❌ @{user.username or '???'} ({user.id}) — {count} knockdown → кик")
            bot.ban_chat_member(chat_id, user.id)
            bot.unban_chat_member(chat_id, user.id)
            try:
                bot.send_message(user.id, f"🚫 У тебя осталось {count} knockdown-подарков. Ты был удалён из группы.")
            except:
                print(f"⚠️ Не удалось отправить сообщение @{user.username or user.id}")
        else:
            print(f"✅ @{user.username or '???'} ({user.id}) — {count} knockdown → всё ок")

        return True

    except Exception as e:
        print(f"⚠️ Ошибка при проверке @{user.username or '???'} ({user.id}): {e}")
        traceback.print_exc()
        return False

async def main():
    async with TelegramClient(session_file, api_id, api_hash) as client:
        group = await client.get_entity(chat_id)

        # Загружаем участников группы
        participants = []
        async for user in client.iter_participants(group):
            participants.append(user)
        print(f"👥 Всего в группе: {len(participants)}")

        # Загружаем approved_users
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id FROM approved_users")
                approved_ids = set(row[0] for row in cur.fetchall())
        print(f"📋 В approved_users: {len(approved_ids)} записей")

        total_checked = 0
        total_skipped = 0

        for user in participants:
            ok = await check_and_kick(user, client, approved_ids)
            await asyncio.sleep(DELAY)
            total_checked += 1
            if not ok:
                total_skipped += 1

        print(f"\n✅ Готово: проверено {total_checked} участников")
        if total_skipped:
            print(f"⚠️ Пропущено по ошибке: {total_skipped}")

if __name__ == "__main__":
    asyncio.run(main())
