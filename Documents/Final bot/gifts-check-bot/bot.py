import os
import telebot
import asyncio
import traceback
from telethon import TelegramClient
from telethon.tl.types import InputUser, InputUserSelf
from get_user_star_gifts_request import GetUserStarGiftsRequest

# Конфигурация
api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")
chat_id = int(os.getenv("CHAT_ID", "-1002655130461"))  # целевая группа
session_file = "userbot_session"

bot = telebot.TeleBot(bot_token)
bot.skip_pending = True

# Проверка knockdown-подарков
def check_knockdowns(user_id: int) -> int:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def run():
        async with TelegramClient(session_file, api_id, api_hash) as client:
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

            return count

    return loop.run_until_complete(run())

# Приветствие
@bot.message_handler(commands=["start"])
def start_message(message):
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("🔍 Проверить подарки", callback_data="check_self"))
    bot.send_message(message.chat.id,
                     "Привет! Я проверяю, есть ли у тебя минимум 6 knockdown‑подарков 🎁\n"
                     "Нажми кнопку ниже, чтобы пройти проверку.",
                     reply_markup=markup)

# Обработка кнопки
@bot.callback_query_handler(func=lambda call: call.data == "check_self")
def handle_check(call):
    user_id = call.from_user.id

    try:
        count = check_knockdowns(user_id)

        if count >= 6:
            # создаём персональную ссылку
            invite = bot.create_chat_invite_link(chat_id=chat_id, member_limit=1)
            bot.send_message(call.message.chat.id,
                f"✅ У тебя {count} knockdown-подарков. Доступ разрешён!\n"
                f"Вот твоя персональная ссылка для входа в группу:\n{invite.invite_link}")
            save_approved(user_id)

        else:
            bot.send_message(call.message.chat.id,
                f"❌ У тебя только {count} knockdown-подарков.\n"
                "Возможно, ты их скрыл или у тебя их недостаточно.\n"
                "Попробуй докупить недостающие на @mrkt.")

    except Exception:
        bot.send_message(call.message.chat.id, "⚠️ Возникла ошибка при проверке. Попробуй позже.")
        traceback.print_exc()

# Сохраняем user_id прошедших проверку
def save_approved(user_id: int):
    try:
        with open("approved_users.txt", "a") as f:
            f.write(str(user_id) + "\n")
    except Exception:
        print("Не удалось сохранить user_id")

print("🤖 Бот запущен и ожидает...")
bot.infinity_polling(timeout=10, long_polling_timeout=5)
