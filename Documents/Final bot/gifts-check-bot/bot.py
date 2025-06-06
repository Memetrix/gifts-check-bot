import os, asyncio, threading, logging, time, traceback
from datetime import datetime, timedelta, timezone
from telebot import TeleBot, types
from telethon import TelegramClient, functions
from telethon.tl.types import InputUser

from get_user_star_gifts_request import GetUserStarGiftsRequest
from db import get_approved_user, save_approved, get_community_rule   # ← новая функция

# ────────────── конфиг ──────────────
api_id   = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")
chat_id   = int(os.getenv("CHAT_ID"))
session_file = "cleaner-service/sessions/userbot2"
DELAY = 1.5
CLICK_COOLDOWN = 10

# ────────────── логирование ─────────
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("giftbot")

# ────────────── TeleBot ─────────────
bot = TeleBot(bot_token, num_threads=1)
bot.skip_pending = True

# ────────── asyncio loop + userbot ─────────
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

# ────────── helpers ──────────
async def is_user_in_group(uid: int) -> bool:
    try:
        await user_client(functions.channels.GetParticipantRequest(
            channel=chat_id, participant=uid))
        return True
    except:
        return False

async def check_knockdowns(uid: int, username=None,
                           first_name=None, last_name=None,
                           verbose: bool = True) -> tuple[int, str | None]:
    """
    Считает подарки, подходящие под правило текущего chat_id.
    Правило берётся из таблицы communities.
    """
    try:
        # --- правило клуба ---
        rule = get_community_rule(chat_id)
        ftype, fval, min_need = (
            rule["filter_type"], rule["filter_value"], rule["min_gifts"]
        )

        ent = None
        try:
            ent = await user_client.get_input_entity(uid)
            if verbose: log.info("✅ %s найден по user_id", uid)
        except Exception:
            if username:
                try:
                    ent = await user_client.get_input_entity(f"@{username}")
                    if verbose: log.info("✅ %s найден по username @%s", uid, username)
                except Exception:
                    pass
        if ent is None and first_name and last_name:
            async for u in user_client.iter_participants(chat_id):
                if u.first_name == first_name and u.last_name == last_name:
                    ent = await user_client.get_input_entity(u.id)
                    if verbose:
                        log.info("✅ %s найден по имени %s %s", uid, first_name, last_name)
                    break
        if not ent:
            return -1, None

        if not isinstance(ent, InputUser):
            ent = InputUser(ent.user_id, ent.access_hash)

        # --- подсчёт подарков ---
        cnt, off = 0, ""
        while True:
            res = await user_client(GetUserStarGiftsRequest(
                user_id=ent, offset=off, limit=100))
            for g in res.gifts:
                gift = g.to_dict().get("gift", {})

                # ① старый способ (Knockdown по атрибуту)
                if ftype == "attribute":
                    if any(a.get("name", "").lower() == fval.lower()
                           for a in gift.get("attributes", [])):
                        cnt += 1

                # ② slug / model / collection / name
                elif ftype == "slug" and gift.get("slug") == fval:
                    cnt += 1
                elif ftype == "model" and gift.get("model") == fval:
                    cnt += 1
                elif ftype == "collection" and gift.get("collection") == fval:
                    cnt += 1
                elif ftype == "name" and gift.get("name", "").startswith(fval):
                    cnt += 1

            if not res.next_offset:
                break
            off = res.next_offset

        if verbose:
            log.info("🎯 %s → %s gifts match rule (%s=%s)",
                     uid, cnt, ftype, fval)
        return cnt, getattr(ent, "username", None)
    except Exception:
        if verbose:
            log.exception("check_knockdowns")
        return -1, None

# ───────── /start ─────────
@bot.message_handler(commands=["start"])
def start_msg(msg):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔍 Проверить подарки", callback_data="check_gifts"))
    bot.send_message(
        msg.chat.id,
        "Привет! Я проверяю подарки и пускаю в клуб, если всё ок 🎁\n"
        "Нажми кнопку ниже, чтобы пройти проверку.",
        reply_markup=kb)

# ───────── /sumgifts ─────────
_last_sumgifts_call: float = 0
SUMGIFTS_COOLDOWN = 600  # 10 минут

@bot.message_handler(commands=["sumgifts"])
def sumgifts_handler(msg):
    global _last_sumgifts_call

    now = time.time()
    if now - _last_sumgifts_call < SUMGIFTS_COOLDOWN:
        bot.reply_to(msg, "⏳ Подожди немного. Команду можно раз в 10 минут.")
        return

    _last_sumgifts_call = now
    rule = get_community_rule(chat_id)
    bot.send_message(chat_id,
        f"🔄 Считаем подарки по правилу ({rule['filter_type']}={rule['filter_value']})…")

    async def calculate():
        total = 0
        async for user in user_client.iter_participants(chat_id):
            if user.bot or not user.access_hash:
                continue
            try:
                count, _ = await check_knockdowns(user.id, user.username,
                                                  user.first_name, user.last_name,
                                                  verbose=False)
                if count > 0:
                    total += count
            except Exception:
                continue
        bot.send_message(chat_id,
            f"🔥 В клубе уже <b>{total}</b> подарков по условию.",
            parse_mode="HTML")
        log.info("✅ /sumgifts выполнен")

    asyncio.run_coroutine_threadsafe(calculate(), main_loop)

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
                     "⏳ Проверка началась, пожалуйста, подожди…")

# ───────── worker очереди ─────────
async def process_queue():
    while True:
        call = await check_queue.get()
        try:
            uid   = call.from_user.id
            uname = call.from_user.username
            fname, lname = call.from_user.first_name, call.from_user.last_name

            cnt, _ = await check_knockdowns(uid, uname, fname, lname)
            rule = get_community_rule(chat_id)

            if cnt < rule["min_gifts"] or cnt == -1:
                bot.send_message(call.message.chat.id,
                    f"❌ У тебя {max(cnt,0)} подарков. "
                    f"Нужно минимум {rule['min_gifts']}.")
                await asyncio.sleep(DELAY); continue

            # 🔓 Разбан перед выдачей ссылки
            try:
                await bot.unban_chat_member(chat_id, uid)
            except: pass

            inv = bot.create_chat_invite_link(
                chat_id, creates_join_request=True,
                expire_date=int(time.time())+3600, name=f"gift-{uid}")

            bot.send_message(call.message.chat.id,
                f"✅ Всё ок! Ссылка действует 1 час:\n{inv.invite_link}")
            save_approved(chat_id, uid, uname, cnt, inv.invite_link)
        except Exception:
            bot.send_message(call.message.chat.id,
                             "⚠️ Внутренняя ошибка. Попробуй позже.")
            traceback.print_exc()
        await asyncio.sleep(DELAY)

# ───── Join-request handler ─────
@bot.chat_join_request_handler()
def join_req(req):
    async def approve_flow():
        uid = req.from_user.id
        uname = req.from_user.username
        cnt, _ = await check_knockdowns(uid, uname,
                                        req.from_user.first_name,
                                        req.from_user.last_name)
        rule = get_community_rule(chat_id)
        if cnt >= rule["min_gifts"]:
            bot.approve_chat_join_request(chat_id, uid)
        else:
            bot.decline_chat_join_request(chat_id, uid)
    asyncio.run_coroutine_threadsafe(approve_flow(), main_loop)

# ───── auto-kick обходящих JoinRequest ─────
@bot.chat_member_handler()
def guard(msg: types.ChatMemberUpdated):
    new = msg.new_chat_member
    if new.status == 'member' and not new.user.is_bot:
        async def check_and_kick():
            cnt, _ = await check_knockdowns(
                new.user.id, new.user.username,
                new.user.first_name, new.user.last_name
            )
            rule = get_community_rule(chat_id)
            if cnt < rule["min_gifts"]:
                try:
                    bot.ban_chat_member(chat_id, new.user.id,
                                        until_date=int(time.time()) + 60)
                except: pass
        asyncio.run_coroutine_threadsafe(check_and_kick(), main_loop)

# ───────── background loop ─────────
def start_async():
    main_loop.create_task(init_userbot())
    main_loop.create_task(process_queue())
    main_loop.run_forever()

threading.Thread(target=start_async, daemon=True).start()

log.info("🤖 Бот запущен (JoinRequest + auto-kick + /sumgifts)")
bot.infinity_polling(timeout=10, long_polling_timeout=5)