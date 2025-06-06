import os, asyncio, threading, logging, time, traceback, json
from telebot import TeleBot, types
from telethon import TelegramClient
from telethon.tl.types import InputUser
from get_user_star_gifts_request import GetUserStarGiftsRequest
from db import get_community_rule, save_approved

# ───────── CONFIG ─────────
api_id   = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
session_path = os.getenv("SESSION_PATH", "cleaner-service/sessions/userbot2.session")
bot_tokens   = [os.getenv("BOT_TOKEN"), os.getenv("BOT_TOKEN_2")]

DUMP_UID = int(os.getenv("DUMP_UID", "0"))      # ← TG-ID для gift-dump (0 = выключено)

DELAY, CLICK_COOLDOWN, SUMGIFTS_COOLDOWN = 1.5, 10, 600

# ───────── LOGS ─────────
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("giftbot")

# ───────── FRONT-боты ─────────
bots = [TeleBot(tok, num_threads=1) for tok in bot_tokens if tok]
for b in bots:
    b.skip_pending = True

# ───────── USER-бот ─────────
main_loop = asyncio.new_event_loop()
asyncio.set_event_loop(main_loop)
user_client: TelegramClient | None = None
check_queue: asyncio.Queue = asyncio.Queue()

async def init_userbot():
    global user_client
    user_client = TelegramClient(session_path, api_id, api_hash)
    await user_client.start()
    await user_client.get_dialogs()
    log.info("👤 userbot session started")

# ───────── HELPERS ─────────
def matches_rule(gift: dict, ftype: str, fval: str) -> bool:
    if ftype == "model":       return gift.get("model") == fval
    if ftype == "slug":        return gift.get("slug")  == fval
    if ftype == "collection":  return gift.get("collection") == fval
    if ftype == "attribute":
        tgt = fval.lower()
        return any(isinstance(v, str) and v.lower() == tgt
                   for a in gift.get("attributes", []) for v in a.values())
    if ftype == "name":
        return gift.get("name", "").lower().startswith(fval.lower())
    return False

async def count_valid_gifts(uid, chat_id, username=None, first=None, last=None) -> int:
    rule = get_community_rule(chat_id)
    ftype, fval = rule["filter_type"], rule["filter_value"]

    # — InputUser —
    ent = None
    try: ent = await user_client.get_input_entity(uid)
    except:
        if username:
            try: ent = await user_client.get_input_entity(f"@{username}")
            except: pass
    if ent is None and first and last:
        async for u in user_client.iter_participants(chat_id):
            if u.first_name == first and u.last_name == last:
                ent = await user_client.get_input_entity(u.id); break
    if not ent: return -1
    if not isinstance(ent, InputUser):
        ent = InputUser(ent.user_id, ent.access_hash)

    # — gifts —
    total, offset, dumped = 0, "", False
    while True:
        res = await user_client(GetUserStarGiftsRequest(
            user_id=ent, offset=offset, limit=100
        ))
        for g in res.gifts:
            gift_dict = g.to_dict().get("gift", {})
            if not dumped and DUMP_UID and uid == DUMP_UID:
                log.warning("GIFT DUMP (%s) →\n%s",
                            uid, json.dumps(gift_dict, indent=2, ensure_ascii=False)[:1500])
                dumped = True
            if matches_rule(gift_dict, ftype, fval):
                total += 1
        if not res.next_offset: break
        offset = res.next_offset
    return total

# ───────── STATE ─────────
_last_click: dict[int, float] = {}
_last_sumgifts_call = 0.0

# ───────── HANDLERS ─────────
def setup(bot: TeleBot):

    @bot.message_handler(commands=["start"])
    def start(msg):
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔍 Проверить подарки", callback_data="check_gifts"))
        bot.send_message(msg.chat.id,
            "👋 Добро пожаловать!\nНажмите кнопку ниже, чтобы пройти проверку доступа.",
            reply_markup=kb)

    @bot.message_handler(commands=["sumgifts"])
    def sumgifts(msg):
        global _last_sumgifts_call
        if time.time() - _last_sumgifts_call < SUMGIFTS_COOLDOWN:
            bot.reply_to(msg, "⏳ Подождите, команда доступна раз в 10 минут."); return
        _last_sumgifts_call = time.time(); bot.reply_to(msg, "🔄 Считаем подарки клуба…")

        async def calc():
            total = 0
            async for u in user_client.iter_participants(msg.chat.id):
                if u.bot or not u.access_hash: continue
                cnt = await count_valid_gifts(u.id, msg.chat.id, u.username,
                                              u.first_name, u.last_name)
                if cnt > 0: total += cnt
            bot.send_message(msg.chat.id,
                f"🔥 В клубе <b>{total}</b> подарков по условиям.", parse_mode="HTML")
        asyncio.run_coroutine_threadsafe(calc(), main_loop)

    @bot.callback_query_handler(func=lambda c: c.data == "check_gifts")
    def check(call):
        if time.time() - _last_click.get(call.from_user.id,0) < CLICK_COOLDOWN:
            bot.answer_callback_query(call.id, "⏳ Подождите немного…"); return
        _last_click[call.from_user.id] = time.time()
        asyncio.run_coroutine_threadsafe(check_queue.put(call), main_loop)
        bot.send_message(call.message.chat.id, "⏳ Проверка началась, подождите…")

    @bot.chat_join_request_handler()
    def join(req):
        async def flow():
            cnt = await count_valid_gifts(req.from_user.id, req.chat.id,
                                          req.from_user.username,
                                          req.from_user.first_name,
                                          req.from_user.last_name)
            rule = get_community_rule(req.chat.id)
            if cnt >= rule["min_gifts"]:
                await bot.approve_chat_join_request(req.chat.id, req.from_user.id)
            else:
                await bot.decline_chat_join_request(req.chat.id, req.from_user.id)
        asyncio.run_coroutine_threadsafe(flow(), main_loop)

    @bot.chat_member_handler()
    def guard(ev: types.ChatMemberUpdated):
        new = ev.new_chat_member
        if new.status == 'member' and not new.user.is_bot:
            async def kick_if_needed():
                cnt = await count_valid_gifts(new.user.id, ev.chat.id,
                                              new.user.username,
                                              new.user.first_name,
                                              new.user.last_name)
                rule = get_community_rule(ev.chat.id)
                if cnt < rule["min_gifts"]:
                    try:
                        await bot.ban_chat_member(ev.chat.id, new.user.id,
                                                  until_date=int(time.time())+60)
                    except: pass
            asyncio.run_coroutine_threadsafe(kick_if_needed(), main_loop)

# ───────── QUEUE WORKER ─────────
async def queue_worker():
    while True:
        call = await check_queue.get()
        try:
            cid, uid = call.message.chat.id, call.from_user.id
            cnt = await count_valid_gifts(uid, cid,
                                          call.from_user.username,
                                          call.from_user.first_name,
                                          call.from_user.last_name)
            rule = get_community_rule(cid)
            if cnt < rule["min_gifts"]:
                bots[0].send_message(cid,
                    f"❌ У вас {cnt} подарков, требуется {rule['min_gifts']}.")
            else:
                link = bots[0].create_chat_invite_link(
                    cid, creates_join_request=True,
                    expire_date=int(time.time())+3600, name=f"gift-{uid}")
                bots[0].send_message(cid,
                    f"✅ Всё ок! Ссылка на вход действует час:\n{link.invite_link}")
                save_approved(cid, uid, call.from_user.username, cnt, link.invite_link)
        except Exception: traceback.print_exc()
        await asyncio.sleep(DELAY)

# ───────── STARTUP ─────────
def bootstrap():
    main_loop.create_task(init_userbot())
    main_loop.create_task(queue_worker())
    main_loop.run_forever()

threading.Thread(target=bootstrap, daemon=True).start()
for b in bots: setup(b)

log.info("🤖 Боты запущены (одна user-сессия)")
bots[0].infinity_polling(timeout=10, long_polling_timeout=5)