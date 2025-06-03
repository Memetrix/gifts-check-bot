import os
import asyncio
import traceback
import threading
from datetime import datetime, timedelta, timezone
from telebot import TeleBot, types
from telethon import TelegramClient, functions
from telethon.tl.types import InputUser
from get_user_star_gifts_request import GetUserStarGiftsRequest
from db import is_approved, save_approved, get_approved_user

# Конфигурация
api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")
chat_id = int(os.getenv("CHAT_ID"))
session_file = "cleaner-service/sessions/userbot2"
DELAY = 1.5

bot = TeleBot(bot_token)
bot.skip_pending = True

main_loop = asyncio.new_event_loop()
asyncio.set_event_loop(main_loop)
check_queue = asyncio.Queue()

# Кэш подписчиков @narrator
subscribers_cache = set()

async def preload_narrator_subscribers():
    async with TelegramClient(session_file, api_id, api_hash) as client:
        async for user in client.iter_participants("@narrator"):
            subscribers_cache.add(user.id)
    print(f"👥 Кэш @narrator загружен: {len(subscribers_cache)} пользователей")

# Проверка: состоит ли пользователь в группе
async def is_user_in_group(user_id: int) -> bool:
    async with TelegramClient(session_file, api_id, api_hash) as client:
        try:
            await client.get_dialogs()
            await client(functions.channels.GetParticipantRequest(
                channel=chat_id,
                participant=user_id
            ))
            return True
        except:
            return False

# Проверка knockdown-подарков (ASYNC!)
async def check_knockdowns(user_id: int, username: str = None, first_name: str = None, last_name: str = None) -> (int, str):
    async with TelegramClient(session_file, api_id, api_hash) as client:
        try:
            await client.get_dialogs()
            entity = None
            try:
                entity = await client.get_input_entity(user_id)
                print(f"✅ Найден по user_id: {user_id}")
            except Exception as e1:
                print(f"❌ Не найден по user_id: {e1}")
                if username:
                    try:
                        entity = await client.get_input_entity(f"@{username}")
                        print(f"✅ Найден по username: @{username}")
                    except Exception as e2:
                        print(f"❌ Не найден по username: {e2}")
            if entity is None and first_name and last_name:
                async for user in client.iter_participants(chat_id):
                    if user.first_name == first_name and user.last_name == last_name:
                        entity = await client.get_input_entity(user.id)
                        print(f"✅ Найден по имени и фамилии: {first_name} {last_name}")
                        break
                else:
                    print(f"❌ Не удалось найти по имени и фамилии: {first_name} {last_name}")

            if not entity:
                return -1, None

            if not isinstance(entity, InputUser):
                entity = InputUser(entity.user_id, entity.access_hash)

            count = 0
            offset = ""
            while True:
                result = await client(GetUserStarGiftsRequest(user_id=entity, offset=offset, limit=100))
                for g in result.gifts:
                    gift = g.to_dict().get("gift")
                    if not gift:
                        continue
                    for attr in gift.get("attributes", []):
                        if "name" in attr and attr["name"].lower() == "knockdown":
                            count += 1
                            break
                if not result.next_offset:
                    break
                offset = result.next_offset

            print(f"🎯 Результат для {user_id} → {count} knockdown")
            return count, getattr(entity, "username", None)
        except Exception as e:
            print(f"❌ Ошибка при проверке: {e}")
            return -1, None

# Команда /start
@bot.message_handler(commands=["start"])
def start_message(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔍 Проверить подарки", callback_data="check_gifts"))
    bot.send_message(message.chat.id,
        "Привет! Я проверяю, есть ли у тебя минимум 6 knockdown‑подарков 🎁\n"
        "Нажми кнопку ниже, чтобы пройти проверку.",
        reply_markup=markup)

# Кнопка проверки
@bot.callback_query_handler(func=lambda call: call.data == "check_gifts")
def handle_check(call):
    user_id = call.from_user.id
    if user_id not in subscribers_cache:
        bot.send_message(call.message.chat.id,
            "📢 Пожалуйста, подпишись на канал @narrator и нажми кнопку снова.")
        return

    asyncio.run_coroutine_threadsafe(check_queue.put(call), main_loop)
    bot.send_message(call.message.chat.id,
        "⏳ Проверка началась. Пожалуйста, подожди — твой запрос добавлен в очередь.")

# Обработчик очереди
async def process_check_queue():
    while True:
        call = await check_queue.get()
        try:
            user_id = call.from_user.id
            username = call.from_user.username
            first_name = call.from_user.first_name
            last_name = call.from_user.last_name
            now = datetime.now(timezone.utc)

            if await is_user_in_group(user_id):
                bot.send_message(call.message.chat.id, "✅ Ты уже в группе! Всё в порядке.")
                await asyncio.sleep(DELAY)
                continue

            user = get_approved_user(user_id)
            if user:
                invite_link = user[2]
                created_at = user[3]
                count, _ = await check_knockdowns(user_id, username, first_name, last_name)

                if count < 6:
                    bot.send_message(call.message.chat.id,
                        "❌ Ранее ты проходил проверку, но сейчас у тебя меньше 6 knockdown-подарков.")
                    await asyncio.sleep(DELAY)
                    continue

                if invite_link and created_at:
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)
                    if (now - created_at) < timedelta(minutes=15):
                        bot.send_message(call.message.chat.id,
                            f"🔁 Ты недавно прошёл проверку.\nВот твоя персональная ссылка:\n{invite_link}")
                        await asyncio.sleep(DELAY)
                        continue

                try:
                    invite = bot.create_chat_invite_link(chat_id=chat_id, member_limit=1)
                    bot.send_message(call.message.chat.id,
                        f"🔁 Ты снова прошёл проверку! Вот новая ссылка:\n{invite.invite_link}")
                    save_approved(user_id, username, count, invite.invite_link)
                    await asyncio.sleep(DELAY)
                    continue
                except Exception as e:
                    bot.send_message(call.message.chat.id, f"⚠️ Не удалось создать ссылку: {e}")
                    await asyncio.sleep(DELAY)
                    continue

            count, _ = await check_knockdowns(user_id, username, first_name, last_name)
            if count >= 6:
                invite = bot.create_chat_invite_link(chat_id=chat_id, member_limit=1)
                bot.send_message(call.message.chat.id,
                    f"✅ У тебя {count} knockdown-подарков. Доступ разрешён!\n"
                    f"Вот твоя персональная ссылка:\n{invite.invite_link}")
                save_approved(user_id, username, count, invite.invite_link)
            else:
                bot.send_message(call.message.chat.id,
                    f"❌ У тебя только {count} knockdown-подарков.\nПожалуйста, купи недостающие на @mrkt.")
        except Exception as e:
            bot.send_message(call.message.chat.id, "⚠️ Внутренняя ошибка. Попробуй позже.")
            traceback.print_exc()
        await asyncio.sleep(DELAY)

# Старт loop-а в фоновом потоке
def start_async_loop():
    main_loop.create_task(preload_narrator_subscribers())
    main_loop.create_task(process_check_queue())
    main_loop.run_forever()

threading.Thread(target=start_async_loop, daemon=True).start()

print("🤖 Бот запущен с очередью и проверкой подписки")
bot.infinity_polling(timeout=10, long_polling_timeout=5)