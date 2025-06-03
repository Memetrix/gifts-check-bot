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

# ───── конфигурация ─────
api_id   = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")
chat_id   = int(os.getenv("CHAT_ID"))
session_file = "cleaner-service/sessions/userbot2"
DELAY = 1.5

# ───── TeleBot ─────  (один поток → нет 409)
bot = TeleBot(bot_token, num_threads=1)
bot.skip_pending = True

# ───── asyncio loop ─────
main_loop = asyncio.new_event_loop()
asyncio.set_event_loop(main_loop)
check_queue: asyncio.Queue = asyncio.Queue()

# ───── helpers ─────
async def is_user_in_group(user_id: int) -> bool:
    async with TelegramClient(session_file, api_id, api_hash) as client:
        try:
            await client(functions.channels.GetParticipantRequest(
                channel=chat_id,
                participant=user_id
            ))
            return True
        except:
            return False

async def check_knockdowns(user_id: int,
                           username: str | None = None,
                           first_name: str | None = None,
                           last_name: str | None = None) -> tuple[int, str | None]:
    async with TelegramClient(session_file, api_id, api_hash) as client:
        try:
            entity = None
            try:
                entity = await client.get_input_entity(user_id)
            except Exception:
                if username:
                    try:
                        entity = await client.get_input_entity(f"@{username}")
                    except Exception:
                        pass
            if entity is None and first_name and last_name:
                async for u in client.iter_participants(chat_id):
                    if u.first_name == first_name and u.last_name == last_name:
                        entity = await client.get_input_entity(u.id)
                        break
            if not entity:
                return -1, None

            if not isinstance(entity, InputUser):
                entity = InputUser(entity.user_id, entity.access_hash)

            cnt, off = 0, ""
            while True:
                res = await client(GetUserStarGiftsRequest(entity, offset=off, limit=100))
                for g in res.gifts:
                    gift = g.to_dict().get("gift")
                    if gift and any(
                        a.get("name", "").lower() == "knockdown"
                        for a in gift.get("attributes", [])
                    ):
                        cnt += 1
                if not res.next_offset:
                    break
                off = res.next_offset
            return cnt, getattr(entity, "username", None)
        except Exception:
            traceback.print_exc()
            return -1, None

# ───── /start ─────
@bot.message_handler(commands=["start"])
def start_message(msg):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔍 Проверить подарки", callback_data="check_gifts"))
    bot.send_message(
        msg.chat.id,
        "Привет! Я проверяю, есть ли у тебя минимум 6 knockdown-подарков 🎁\n"
        "Нажми кнопку ниже, чтобы пройти проверку.",
        reply_markup=kb)

# ───── кнопка ─────
@bot.callback_query_handler(func=lambda c: c.data == "check_gifts")
def handle_check(call):
    asyncio.run_coroutine_threadsafe(check_queue.put(call), main_loop)
    bot.send_message(call.message.chat.id,
                     "⏳ Проверка началась. Пожалуйста, подожди — твой запрос добавлен в очередь.")

# ───── worker ─────
async def process_check_queue():
    while True:
        call = await check_queue.get()
        try:
            uid, uname = call.from_user.id, call.from_user.username
            fname, lname = call.from_user.first_name, call.from_user.last_name
            now = datetime.now(timezone.utc)

            if await is_user_in_group(uid):
                bot.send_message(call.message.chat.id, "✅ Ты уже в группе! Всё в порядке.")
                await asyncio.sleep(DELAY)
                continue

            user = get_approved_user(uid)
            if user:
                invite_link, created_at = user[2], user[3]
                cnt, _ = await check_knockdowns(uid, uname, fname, lname)

                if cnt < 6:
                    bot.send_message(call.message.chat.id,
                        "❌ Сейчас у тебя меньше 6 knockdown-подарков.")
                    await asyncio.sleep(DELAY)
                    continue

                if invite_link and created_at and \
                   (now - created_at.replace(tzinfo=timezone.utc)) < timedelta(minutes=15):
                    bot.send_message(call.message.chat.id,
                        f"🔁 Ты недавно проходил проверку.\nВот ссылка:\n{invite_link}")
                    await asyncio.sleep(DELAY)
                    continue

                try:
                    inv = bot.create_chat_invite_link(chat_id=chat_id, member_limit=1)
                    bot.send_message(call.message.chat.id,
                        f"🔁 Ты снова прошёл проверку! Вот новая ссылка:\n{inv.invite_link}")
                    save_approved(uid, uname, cnt, inv.invite_link)
                    await asyncio.sleep(DELAY)
                    continue
                except Exception as e:
                    bot.send_message(call.message.chat.id, f"⚠️ Не удалось создать ссылку: {e}")
                    await asyncio.sleep(DELAY)
                    continue

            cnt, _ = await check_knockdowns(uid, uname, fname, lname)
            if cnt >= 6:
                inv = bot.create_chat_invite_link(chat_id=chat_id, member_limit=1)
                bot.send_message(call.message.chat.id,
                    f"✅ У тебя {cnt} knockdown-подарков. Доступ разрешён!\n{inv.invite_link}")
                save_approved(uid, uname, cnt, inv.invite_link)
            else:
                bot.send_message(call.message.chat.id,
                    f"❌ У тебя только {cnt} knockdown-подарков.\nКупи недостающие на @mrkt.")
        except Exception:
            bot.send_message(call.message.chat.id, "⚠️ Внутренняя ошибка. Попробуй позже.")
            traceback.print_exc()
        await asyncio.sleep(DELAY)

# ───── запуск loop ─────
def start_async():
    main_loop.create_task(process_check_queue())
    main_loop.run_forever()

threading.Thread(target=start_async, daemon=True).start()

print("🤖 Бот запущен (num_threads=1 — без 409)")
bot.infinity_polling(
    timeout=10,
    long_polling_timeout=5,
    skip_pending=True
)