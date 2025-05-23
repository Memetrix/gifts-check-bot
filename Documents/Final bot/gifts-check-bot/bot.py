import os
import traceback
import telebot
from db import is_approved, save_approved

# Конфигурация
bot_token = os.getenv("BOT_TOKEN")
chat_id = int(os.getenv("CHAT_ID", "-1002655130461"))

bot = telebot.TeleBot(bot_token)
bot.skip_pending = True

# /start
@bot.message_handler(commands=["start"])
def start_message(message):
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("🔓 Получить доступ", callback_data="grant_access"))
    bot.send_message(message.chat.id,
        "Привет! Сейчас доступ в группу открыт для всех 🟢\n"
        "Нажми кнопку ниже, чтобы получить ссылку:",
        reply_markup=markup)

# Обработка кнопки
@bot.callback_query_handler(func=lambda call: call.data == "grant_access")
def handle_grant_access(call):
    user_id = call.from_user.id
    username = call.from_user.username or None

    if is_approved(user_id):
        bot.send_message(call.message.chat.id,
            "✅ Ты уже получил доступ ранее. Если потерял ссылку — просто напиши.")
        return

    try:
        invite = bot.create_chat_invite_link(chat_id=chat_id, member_limit=1)
        bot.send_message(call.message.chat.id,
            f"✅ Доступ разрешён!\nВот твоя персональная ссылка в группу:\n{invite.invite_link}")
        save_approved(user_id, username, gift_count=0)
    except Exception:
        bot.send_message(call.message.chat.id, "⚠️ Произошла ошибка при выдаче ссылки. Попробуй позже.")
        traceback.print_exc()

print("🤖 Бот запущен и выдаёт доступ всем")
bot.infinity_polling(timeout=10, long_polling_timeout=5)
