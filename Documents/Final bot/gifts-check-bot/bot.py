import os, asyncio, threading, logging, time, json, traceback
from telebot import TeleBot, types
from telethon import TelegramClient
from telethon.tl.types import InputUser
from get_user_star_gifts_request import GetUserStarGiftsRequest
from db import get_community_rule, save_approved

# ───────── CONFIG ─────────
api_id   = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
session_path = "cleaner-service/sessions/userbot2"

# BOT_TOKEN, BOT_TOKEN_2, BOT_TOKEN_3 …
bot_tokens = [v for k, v in os.environ.items()
              if k.startswith("BOT_TOKEN") and v]

DELAY, CLICK_COOLDOWN, SUMGIFTS_COOLDOWN = 1.5, 10, 600
RAW = os.getenv("LOG_RAW_GIFTS", "0") == "1"        # 1 → логировать JSON подарков

# ───────── LOGS ─────────
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("giftbot")

# ───────── helper для безопасного JSON ─────────
def safe_json(obj) -> str:
    def _default(o):
        if isinstance(o, (bytes, bytearray)):
            return f"<{len(o)} bytes>"
        return str(o)
    return json.dumps(obj, default=_default, ensure_ascii=False)

# ───────── FRONT BOTS ─────────
bots: list[TeleBot] = [TeleBot(tok, num_threads=1) for tok in bot_tokens]
for b in bots:
    b.skip_pending = True

# ───────── USER BOT ─────────
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

# ───────── RULE MATCHERS ─────────
def matches_rule(gift: dict, ftype: str, fval: str) -> bool:
    """slug/model/collection/name"""
    if ftype == "slug":        return str(gift.get("slug"))        == fval
    if ftype == "model":       return gift.get("model")            == fval
    if ftype == "collection":  return gift.get("collection")       == fval
    if ftype == "name":        return gift.get("name", "").startswith(fval)
    return False

def attribute_match(gift: dict, target: str) -> bool:
    """Knockdown, Ion Gem и любые другие — ищем в attributes[].name, title, slug"""
    tgt = target.lower()
    if any(a.get("name", "").lower() == tgt for a in gift.get("attributes", [])):
        return True
    if gift.get("title", "").lower().startswith(tgt):
        return True
    if str(gift.get("slug", "")).lower().startswith(tgt):
        return True
    return False

# ───────── MAIN COUNTER ─────────
async def count_gifts(uid: int, chat_id: int,
                      username=None, first=None, last=None) -> int:
    rule = get_community_rule(chat_id)
    ftype, fval = rule["filter_type"], rule["filter_value"]

    # InputUser
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

    # Gifts paging
    total, offset = 0, ""
    while True:
        res = await user_client(GetUserStarGiftsRequest(
            user_id=ent, offset=offset, limit=100))
        for g in res.gifts:
            gift = g.to_dict().get("gift", {})

            if RAW:
                log.info("GIFT RAW chat=%s user=%s → %s",
                         chat_id, uid, safe_json(gift)[:2000])

            # Attribute rules (Knockdown / Ion Gem и т.д.)
            if ftype == "attribute" and attribute_match(gift, fval):
                total += 1
            # Generic rules
            elif matches_rule(gift, ftype, fval):
                total += 1
        if not res.next_offset: break
        offset = res.next_offset
    return total

# ───────── STATE ─────────
_last_click: dict[int, float] = {}
_last_sumgifts: dict[int, float] = {}

# ───────── HANDLER SETUP ─────────
def setup(bot: TeleBot):

    @bot.message_handler(commands=["start"])
    def cmd_start(msg):
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔍 Проверить подарки", callback_data="check_gifts"))
        bot.send_message(msg.chat.id,
            "👋 Добро пожаловать! Нажмите кнопку, чтобы пройти проверку.", reply_markup=kb)

    @bot.message_handler(commands=["sumgifts"])
    def cmd_sumgifts(msg):
        cid = msg.chat.id
        if time.time() - _last_sumgifts.get(cid, 0) < SUMGIFTS_COOLDOWN:
            bot.reply_to(msg, "⏳ Можно раз в 10 минут."); return
        _last_sumgifts[cid] = time.time()
        rule = get_community_rule(cid)
        bot.reply_to(msg, f"🔄 Считаем подарки ({rule['filter_type']}={rule['filter_value']})…")

        async def calc():
            total = 0
            async for u in user_client.iter_participants(cid):
                if u.bot or not u.access_hash: continue
                total += max(0, await count_gifts(u.id, cid, u.username, u.first_name, u.last_name))
            bot.send_message(cid, f"🔥 В клубе <b>{total}</b> подарков.", parse_mode="HTML")
        asyncio.run_coroutine_threadsafe(calc(), main_loop)

    @bot.callback_query_handler(func=lambda c: c.data == "check_gifts")
    def cb_check(call):
        if time.time() - _last_click.get(call.from_user.id, 0) < CLICK_COOLDOWN:
            bot.answer_callback_query(call.id, "⏳ Секундочку…"); return
        _last_click[call.from_user.id] = time.time()
        asyncio.run_coroutine_threadsafe(check_queue.put(call), main_loop)
        bot.send_message(call.message.chat.id, "⏳ Проверяем подарки…")

    @bot.chat_join_request_handler()
    def join(req):
        async def flow():
            cnt = await count_gifts(req.from_user.id, req.chat.id,
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
            async def kick():
                cnt = await count_gifts(new.user.id, ev.chat.id,
                                        new.user.username,
                                        new.user.first_name,
                                        new.user.last_name)
                rule = get_community_rule(ev.chat.id)
                if cnt < rule["min_gifts"]:
                    try:
                        await bot.ban_chat_member(ev.chat.id, new.user.id,
                                                  until_date=int(time.time())+60)
                    except: pass
            asyncio.run_coroutine_threadsafe(kick(), main_loop)

# ───────── QUEUE WORKER ─────────
async def queue_worker():
    while True:
        call = await check_queue.get()
        try:
            cid = call.message.chat.id
            uid = call.from_user.id
            cnt = await count_gifts(uid, cid,
                                    call.from_user.username,
                                    call.from_user.first_name,
                                    call.from_user.last_name)
            rule = get_community_rule(cid)

            log.info("CHECK chat=%s user=%s → %s gifts (need %s)",
                     cid, uid, cnt, rule["min_gifts"])

            if cnt < rule["min_gifts"]:
                bots[0].send_message(cid,
                    f"❌ У вас {cnt} подарков, нужно {rule['min_gifts']}.")
            else:
                link = bots[0].create_chat_invite_link(
                    cid, creates_join_request=True,
                    expire_date=int(time.time())+3600, name=f"gift-{uid}")
                bots[0].send_message(cid,
                    f"✅ Всё ок! Ссылка действует час:\n{link.invite_link}")
                save_approved(cid, uid, call.from_user.username,
                              cnt, link.invite_link)
        except Exception:
            traceback.print_exc()
        await asyncio.sleep(DELAY)

# ───────── STARTUP ─────────
def bootstrap():
    main_loop.create_task(init_userbot())
    main_loop.create_task(queue_worker())
    main_loop.run_forever()

threading.Thread(target=bootstrap, daemon=True).start()
for b in bots:
    setup(b)

log.info("🤖 Запущено %s ботов, 1 user-сессия", len(bots))
bots[0].infinity_polling(timeout=10, long_polling_timeout=5)