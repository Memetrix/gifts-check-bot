import os
import asyncio
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

bot = TeleBot(bot_token)

async def check_and_kick(user, client):
    try:
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

    except Exception as e:
        print(f"⚠️ Ошибка при проверке @{user.username or '???'} ({user.id}): {e}")
        traceback.print_exc()

async def main():
    async with TelegramClient(session_file, api_id, api_hash) as client:
        group = await client.get_entity(chat_id)

        participants = []
        async for user in client.iter_participants(group):
            participants.append(user)

        print(f"👥 В группе всего участников: {len(participants)}")

        for i, user in enumerate(participants, start=1):
            print(f"🔎 {i}/{len(participants)} → @{user.username or '???'} ({user.id})")
            await check_and_kick(user, client)
            await asyncio.sleep(DELAY)

if __name__ == "__main__":
    asyncio.run(main())
