import os, asyncio, threading, logging, time, traceback, json
from telebot import TeleBot, types
from telethon import TelegramClient, functions
from telethon.tl.types import InputUser
from get_user_star_gifts_request import GetUserStarGiftsRequest
from db import get_approved_user, save_approved, get_community_rule

# ─────── CONFIG ───────
api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
session_file = "cleaner-service/sessions/userbot2"
DELAY = 1.5
CLICK_COOLDOWN = 10
SUMGIFTS_COOLDOWN = 600

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_TOKEN_2 = os.getenv("BOT_TOKEN_2")
bot_tokens = [tok for tok in (BOT_TOKEN, BOT_TOKEN_2) if tok]

CLUB_CHAT_IDS = {
    BOT_TOKEN: -1002655130461,      # Knockdown
    BOT_TOKEN_2: -1002760691414,    # Ion Gem
}

LOG_RAW = os.getenv("LOG_RAW_GIFTS", "0") == "1"

# ─────── LOGGING ───────
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("giftbot")

def safe_json(obj):
    def _d(o):
        if isinstance(o, (bytes, bytearray)):
            return f"<{len(o)} bytes>"
        return str(o)
    return json.dumps(obj, default=_d, ensure_ascii=False)

# ─────── TeleBot Setup ───────
bots: list[TeleBot] = [TeleBot(tok, num_threads=1) for tok in bot_tokens]
for b in bots: b.skip_pending = True

# ─────── Async loop + userbot ───────
main_loop = asyncio.new_event_loop()
asyncio.set_event_loop(main_loop)

user_client: TelegramClient | None = None
check_queue: asyncio.Queue = asyncio.Queue()

async def init_userbot():
    global user_client
    user_client = TelegramClient(session_file, api_id, api_hash)
    await user_client.start(); await user_client.get_dialogs()
    log.info("👤 Userbot session готова")

# ─────── Gift Checker ───────
async def check_knockdowns(uid: int, username=None, first_name=None,
                           last_name=None, club_id=None,
                           verbose: bool = True) -> tuple[int, str | None]:
    try:
        rule = get_community_rule(club_id)
        ftype, fval = rule["filter_type"], rule["filter_value"]

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
            async for u in user_client.iter_participants(club_id):
                if u.first_name == first_name and u.last_name == last_name:
                    ent = await user_client.get_input_entity(u.id)
                    if verbose:
                        log.info("✅ %s найден по имени %s %s", uid, first_name, last_name)
                    break
        if not ent:
            return -1, None

        if not isinstance(ent, InputUser):
            ent = InputUser(ent.user_id, ent.access_hash)

        cnt, off = 0, ""
        while True:
            res = await user_client(GetUserStarGiftsRequest(ent, off, 100))
            for g in res.gifts:
                gift = g.to_dict().get("gift", {})

                if LOG_RAW:
                    log.info("GIFT RAW club=%s user=%s → %s",
                             club_id, uid, safe_json(gift)[:1500])

                if ftype == "attribute":
                    if any(a.get("name", "").lower() == fval.lower()
                           for a in gift.get("attributes", [])):
                        cnt += 1
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
        if verbose: log.exception("check_knockdowns")
        return -1, None

# ─────── STATE ───────
_last_click: dict[int, float] = {}
_last_sum: dict[int, float] = {}

# ─────── BOT HANDLERS ───────
def setup(bot: TeleBot):
    @bot.message_handler(commands=["start"])
    def start_msg(msg):
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔍 Проверить подарки", callback_data="check_gifts"))
        bot.send_message(
            msg.chat.id,
            "Привет! Я проверяю подарки и пускаю в клуб, если всё ок 🎁",
            reply_markup=kb)

    @bot.message_handler(commands=["sumgifts"])
    def sumgifts_handler(msg):
        club_id = CLUB_CHAT_IDS.get(bot.token)
        if not club_id:
            bot.reply_to(msg, "❌ Этот бот не привязан к клубу."); return
        if time.time() - _last_sum.get(club_id, 0) < SUMGIFTS_COOLDOWN:
            bot.reply_to(msg, "⏳ Подождите немного…"); return

        _last_sum[club_id] = time.time()
        rule = get_community_rule(club_id)
        bot.send_message(msg.chat.id,
            f"🔄 Считаем подарки по правилу ({rule['filter_type']}={rule['filter_value']})…")

        async def calculate():
            total = 0
            async for user in user_client.iter_participants(club_id):
                if user.bot or not user.access_hash: continue
                try:
                    count, _ = await check_knockdowns(user.id, user.username,
                        user.first_name, user.last_name, club_id, verbose=False)
                    if count > 0: total += count
                except: continue
            bot.send_message(msg.chat.id,
                f"🔥 В клубе уже <b>{total}</b> подарков.", parse_mode="HTML")
        asyncio.run_coroutine_threadsafe(calculate(), main_loop)

    @bot.callback_query_handler(func=lambda c: c.data == "check_gifts")
    def handle_check(call):
        now = time.time()
        if now - _last_click.get(call.from_user.id, 0) < CLICK_COOLDOWN:
            bot.answer_callback_query(call.id, "⏳ Подождите пару секунд…"); return
        _last_click[call.from_user.id] = now
        asyncio.run_coroutine_threadsafe(check_queue.put(call), main_loop)
        bot.send_message(call.message.chat.id,
            "⏳ Проверка началась, пожалуйста, подожди…")

    @bot.chat_join_request_handler()
    def join_req(req):
        async def approve_flow():
            club_id = req.chat.id
            cnt, _ = await check_knockdowns(req.from_user.id, req.from_user.username,
                req.from_user.first_name, req.from_user.last_name, club_id)
            rule = get_community_rule(club_id)
            if cnt >= rule["min_gifts"]:
                bot.approve_chat_join_request(club_id, req.from_user.id)
            else:
                bot.decline_chat_join_request(club_id, req.from_user.id)
        asyncio.run_coroutine_threadsafe(approve_flow(), main_loop)

    @bot.chat_member_handler()
    def guard(msg: types.ChatMemberUpdated):
        new = msg.new_chat_member
        if new.status == 'member' and not new.user.is_bot:
            async def check_and_kick():
                club_id = msg.chat.id
                cnt, _ = await check_knockdowns(new.user.id, new.user.username,
                    new.user.first_name, new.user.last_name, club_id)
                rule = get_community_rule(club_id)
                if cnt < rule["min_gifts"]:
                    try:
                        bot.ban_chat_member(club_id, new.user.id,
                                            until_date=int(time.time()) + 60)
                    except: pass
            asyncio.run_coroutine_threadsafe(check_and_kick(), main_loop)

for b in bots:
    setup(b)

# ─────── QUEUE WORKER ───────
async def process_queue():
    while True:
        call = await check_queue.get()
        try:
            token = call.bot.token
            club_id = CLUB_CHAT_IDS.get(token)
            if club_id is None:
                log.warning("❌ Нет club_id для токена %s", token); continue

            uid = call.from_user.id
            cnt, _ = await check_knockdowns(uid, call.from_user.username,
                call.from_user.first_name, call.from_user.last_name, club_id)
            rule = get_community_rule(club_id)

            if cnt < rule["min_gifts"] or cnt == -1:
                call.bot.send_message(call.message.chat.id,
                    f"❌ У тебя {max(cnt,0)} подарков. Нужно минимум {rule['min_gifts']}.")
                await asyncio.sleep(DELAY); continue

            try:
                await call.bot.unban_chat_member(club_id, uid)
            except: pass

            link = call.bot.create_chat_invite_link(
                club_id, creates_join_request=True,
                expire_date=int(time.time())+3600, name=f"gift-{uid}")
            call.bot.send_message(call.message.chat.id,
                f"✅ Всё ок! Ссылка действует 1 час:\n{link.invite_link}")
            save_approved(club_id, uid, call.from_user.username, cnt, link.invite_link)
        except Exception:
            call.bot.send_message(call.message.chat.id, "⚠️ Внутренняя ошибка. Попробуй позже.")
            traceback.print_exc()
        await asyncio.sleep(DELAY)

# ─────── STARTUP ───────
def start_async():
    main_loop.create_task(init_userbot())
    main_loop.create_task(process_queue())
    main_loop.run_forever()

threading.Thread(target=start_async, daemon=True).start()
log.info("🤖 Все боты запущены (JoinRequest + auto-kick + multi-club)")
bots[0].infinity_polling(timeout=10, long_polling_timeout=5)