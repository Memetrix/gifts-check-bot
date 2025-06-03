# bot.py
import os, sys, time, asyncio, threading, logging, traceback
from datetime import datetime, timedelta, timezone

from telebot import TeleBot, types
from telethon import TelegramClient, functions
from telethon.tl.types import InputUser
from get_user_star_gifts_request import GetUserStarGiftsRequest
from db import get_approved_user, save_approved

# ───────── конфиг ─────────
api_id        = int(os.getenv("API_ID"))
api_hash      = os.getenv("API_HASH")
bot_token     = os.getenv("BOT_TOKEN")
chat_id       = int(os.getenv("CHAT_ID"))
session_file  = "cleaner-service/sessions/userbot2"

DELAY          = 1.5          # пауза между сообщениями
CLICK_COOLDOWN = 10           # анти-спам на кнопку

# ─────── логирование ──────
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("giftbot")

# ────────── TeleBot ────────
bot = TeleBot(bot_token, num_threads=1)      # один поток ⇒ нет 409
bot.skip_pending = True

# ───── asyncio loop + userbot ─────
main_loop = asyncio.new_event_loop()
asyncio.set_event_loop(main_loop)

user_client: TelegramClient | None = None
userbot_ready = asyncio.Event()              # <─ флаг готовности
check_queue: asyncio.Queue = asyncio.Queue()

# ─── однократная чистка старых инвайтов ───
async def revoke_all_links_once():
    links = bot.get_chat_invite_links(
        chat_id,
        limit=1000,
        is_revoked=False
    )
    log.info("Найдено %s активных ссылок", len(links))
    for l in links:
        try:
            bot.revoke_chat_invite_link(chat_id, l.invite_link)
            log.info("• revoked %s", l.invite_link)
            time.sleep(0.2)   # анти-флуд
        except Exception as e:
            log.warning("⚠️  не смог отозвать %s → %s", l.invite_link, e)

# ────────── инициализация user-бота ─────────
async def init_userbot():
    global user_client
    user_client = TelegramClient(session_file, api_id, api_hash)
    await user_client.start()
    await user_client.get_dialogs()
    log.info("👤 Userbot session готова")
    userbot_ready.set()

# ────────── helpers ──────────
async def is_user_in_group(uid: int) -> bool:
    await userbot_ready.wait()
    try:
        await user_client(functions.channels.GetParticipantRequest(
            channel=chat_id, participant=uid))
        return True
    except:
        return False

async def check_knockdowns(uid: int,
                           username=None,
                           first_name=None,
                           last_name=None) -> tuple[int, str | None]:
    await userbot_ready.wait()
    try:
        ent = None
        # ─── поиск entity ───
        try:
            ent = await user_client.get_input_entity(uid)
            log.info("✅ %s найден по user_id", uid)
        except Exception:
            if username:
                try:
                    ent = await user_client.get_input_entity(f"@{username}")
                    log.info("✅ %s найден по username @%s", uid, username)
                except Exception:
                    pass
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
        log.info("🎯 %s → %s knockdown", uid, cnt)
        return cnt, getattr(ent, "username", None)
    except Exception:
        log.exception("check_knockdowns")
        return -1, None

# ───────── /start ─────────
@bot.message_handler(commands=["start"])
def start_msg(msg):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔍 Проверить подарки", callback_data="check_gifts"))
    bot.send_message(
        msg.chat.id,
        "Привет! Я проверяю, есть ли у тебя минимум 6 knockdown-подарков 🎁\n"
        "Нажми кнопку ниже, чтобы пройти проверку.",
        reply_markup=kb)

# ─── анти-спам кнопки ───
_last_click: dict[int, float] = {}
@bot.callback_query_handler(func=lambda c: c.data == "check_gifts")
def handle_check(call):
    now = time.time()
    if now - _last_click.get(call.from_user.id, 0) < CLICK_COOLDOWN:
        bot.answer_callback_query(call.id, "⏳ Подожди пару секунд…"); return
    _last_click[call.from_user.id] = now

    asyncio.run_coroutine_threadsafe(check_queue.put(call), main_loop)
    bot.send_message(call.message.chat.id, "⏳ Проверка началась, пожалуйста, подожди…")

# ───── worker очереди ─────
async def process_queue():
    while True:
        call = await check_queue.get()
        try:
            uid   = call.from_user.id
            uname = call.from_user.username
            fname,lname = call.from_user.first_name, call.from_user.last_name

            cnt, _ = await check_knockdowns(uid, uname, fname, lname)
            if cnt < 6:
                bot.send_message(call.message.chat.id,
                    f"❌ У тебя {cnt if cnt!=-1 else 0} knockdown-подарков.\n"
                    "Нужно минимум 6.")
                await asyncio.sleep(DELAY); continue

            inv = bot.create_chat_invite_link(
                chat_id,
                creates_join_request=True,
                expire_date=int(time.time()) + 3600,  # 1-часовая ссылка
                name=f"gift-{uid}"
            )
            bot.send_message(call.message.chat.id,
                f"✅ Доступ разрешён! Ссылка действует 1 час:\n{inv.invite_link}")
            save_approved(uid, uname, cnt, inv.invite_link)

        except Exception:
            bot.send_message(call.message.chat.id, "⚠️ Внутренняя ошибка. Попробуй позже.")
            traceback.print_exc()
        await asyncio.sleep(DELAY)

# ───── Join-Request ─────
@bot.chat_join_request_handler()
def join_req(r):
    async def flow():
        cnt, _ = await check_knockdowns(
            r.from_user.id, r.from_user.username,
            r.from_user.first_name, r.from_user.last_name
        )
        if cnt >= 6:
            bot.approve_chat_join_request(chat_id, r.from_user.id)
            log.info("✔️ %s approved (%s knockdown)", r.from_user.id, cnt)
        else:
            bot.decline_chat_join_request(chat_id, r.from_user.id)
            # доп. страховка: сжечь ссылку, если она ещё активна
            try:
                bot.revoke_chat_invite_link(chat_id, r.invite_link)
            except Exception:
                pass
            log.info("🚫 %s declined (%s knockdown)", r.from_user.id, cnt)
    asyncio.run_coroutine_threadsafe(flow(), main_loop)

# ───── запуск ─────
def start_async():
    # 1) чистка старых ссылок (по желанию)
    if os.getenv("CLEAN_INVITES") == "1":
        asyncio.run(revoke_all_links_once())
        log.info("Чистка завершена, выходим.")
        sys.exit(0)

    # 2) обычный режим
    main_loop.create_task(init_userbot())
    main_loop.create_task(process_queue())
    main_loop.run_forever()

threading.Thread(target=start_async, daemon=True).start()

log.info("🤖 Бот запущен (Join-Request, auto-revoke)")
bot.infinity_polling(timeout=10, long_polling_timeout=5)