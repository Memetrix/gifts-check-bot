import os, asyncio, traceback, threading, logging, time
from datetime import datetime, timedelta, timezone
from telebot import TeleBot, types
from telethon import TelegramClient, functions
from telethon.tl.types import InputUser
from get_user_star_gifts_request import GetUserStarGiftsRequest
from db import is_approved, save_approved, get_approved_user

# ───────── конфиг ─────────
api_id   = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")
chat_id   = int(os.getenv("CHAT_ID"))
session_file = "cleaner-service/sessions/userbot2"
DELAY = 1.5
CLICK_COOLDOWN = 10

# ───────── логирование ────────
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("giftbot")

# ───────── TeleBot (1 поток → нет 409) ────────
bot = TeleBot(bot_token, num_threads=1)
bot.skip_pending = True

# ───────── asyncio loop + userbot ─────────
main_loop = asyncio.new_event_loop()
asyncio.set_event_loop(main_loop)

user_client: TelegramClient | None = None
check_queue: asyncio.Queue = asyncio.Queue()

async def init_userbot():
    global user_client
    user_client = TelegramClient(session_file, api_id, api_hash)
    await user_client.start()
    await user_client.get_dialogs()
    log.info("👤 Userbot session готова")

# ───────── helpers ─────────
async def is_user_in_group(uid: int) -> bool:
    try:
        await user_client(functions.channels.GetParticipantRequest(
            channel=chat_id, participant=uid))
        return True
    except:
        return False

async def check_knockdowns(uid: int, username=None,
                           first_name=None, last_name=None) -> tuple[int, str | None]:
    try:
        ent = None
        try:
            ent = await user_client.get_input_entity(uid)
            log.info("✅ %s найден по user_id", uid)
        except Exception as e1:
            log.debug("❌ %s не найден по user_id: %s", uid, e1)
            if username:
                try:
                    ent = await user_client.get_input_entity(f"@{username}")
                    log.info("✅ %s найден по username @%s", uid, username)
                except Exception as e2:
                    log.debug("❌ не найден по username: %s", e2)

        if ent is None and first_name and last_name:
            async for u in user_client.iter_participants(chat_id):
                if u.first_name == first_name and u.last_name == last_name:
                    ent = await user_client.get_input_entity(u.id)
                    log.info("✅ %s найден по имени %s %s", uid, first_name, last_name)
                    break

        if not ent:
            return -1, None

        if not isinstance(ent, InputUser):
            ent = InputUser(ent.user_id, ent.access_hash)

        cnt, off = 0, ""
        while True:
            res = await user_client(GetUserStarGiftsRequest(
                user_id=ent, offset=off, limit=100))
            for g in res.gifts:
                gift = g.to_dict().get("gift", {})
                if any(a.get("name", "").lower() == "knockdown"
                       for a in gift.get("attributes", [])):
                    cnt += 1
            if not res.next_offset:
                break
            off = res.next_offset

        log.info("🎯 Результат для %s → %s knockdown", uid, cnt)
        return cnt, getattr(ent, "username", None)
    except Exception:
        log.exception("Ошибка check_knockdowns")
        return -1, None

# ───────── /start ─────────
@bot.message_handler(commands=["start"])
def start_message(msg):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔍 Проверить подарки", callback_data="check_gifts"))
    bot.send_message(msg.chat.id,
        "Привет! Я проверяю, есть ли у тебя минимум 6 knockdown-подарков 🎁\n"
        "Нажми кнопку ниже, чтобы пройти проверку.", reply_markup=kb)

# ───── анти-спам кнопки ─────
_last_click: dict[int, float] = {}

@bot.callback_query_handler(func=lambda c: c.data == "check_gifts")
def handle_check(call):
    now = time.time()
    if now - _last_click.get(call.from_user.id, 0) < CLICK_COOLDOWN:
        bot.answer_callback_query(call.id, "⏳ Подожди пару секунд…"); return
    _last_click[call.from_user.id] = now

    asyncio.run_coroutine_threadsafe(check_queue.put(call), main_loop)
    bot.send_message(call.message.chat.id,
                     "⏳ Проверка началась. Пожалуйста, подожди…")

# ───────── worker очереди ─────────
async def process_queue():
    while True:
        call = await check_queue.get()
        try:
            uid, uname = call.from_user.id, call.from_user.username
            fname, lname = call.from_user.first_name, call.from_user.last_name
            now = datetime.now(timezone.utc)

            if await is_user_in_group(uid):
                bot.send_message(call.message.chat.id, "✅ Ты уже в группе! Всё в порядке.")
                await asyncio.sleep(DELAY); continue

            user = get_approved_user(uid)
            if user:
                invite_link, created_at = user[2], user[3]
                cnt, _ = await check_knockdowns(uid, uname, fname, lname)

                if cnt < 6 or cnt == -1:
                    bot.send_message(call.message.chat.id,
                        "❌ Сейчас у тебя меньше 6 knockdown-подарков.")
                    await asyncio.sleep(DELAY); continue

                if invite_link and created_at and \
                   (now - created_at.replace(tzinfo=timezone.utc)) < timedelta(minutes=15):
                    bot.send_message(call.message.chat.id,
                        f"🔁 Ты недавно проходил проверку.\nВот ссылка:\n{invite_link}")
                    await asyncio.sleep(DELAY); continue

                try:
                    inv = bot.create_chat_invite_link(chat_id=chat_id, member_limit=1)
                    bot.send_message(call.message.chat.id,
                        f"🔁 Проверка пройдена! Вот ссылка:\n{inv.invite_link}")
                    save_approved(uid, uname, cnt, inv.invite_link)
                    log.info("✔️ %s приглашён, %s knockdown", uid, cnt)
                    await asyncio.sleep(DELAY); continue
                except Exception as e:
                    bot.send_message(call.message.chat.id, f"⚠️ Не удалось создать ссылку: {e}")
                    await asyncio.sleep(DELAY); continue

            cnt, _ = await check_knockdowns(uid, uname, fname, lname)
            if cnt >= 6 and cnt != -1:
                inv = bot.create_chat_invite_link(chat_id=chat_id, member_limit=1)
                bot.send_message(call.message.chat.id,
                    f"✅ У тебя {cnt} knockdown-подарков — доступ разрешён!\n{inv.invite_link}")
                save_approved(uid, uname, cnt, inv.invite_link)
                log.info("✔️ %s приглашён, %s knockdown", uid, cnt)
            else:
                bot.send_message(call.message.chat.id,
                    f"❌ У тебя только {cnt if cnt!=-1 else 0} knockdown-подарков.\n"
                    "Купи недостающие на @mrkt.")
        except Exception:
            bot.send_message(call.message.chat.id, "⚠️ Внутренняя ошибка. Попробуй позже.")
            log.exception("Ошибка в worker")
        await asyncio.sleep(DELAY)

# ───────── запуск background loop ─────────
def start_async():
    main_loop.create_task(init_userbot())
    main_loop.create_task(process_queue())
    main_loop.run_forever()

threading.Thread(target=start_async, daemon=True).start()

log.info("🤖 Бот запущен (userbot + один поток, 409 нет)")
bot.infinity_polling(timeout=10, long_polling_timeout=5)