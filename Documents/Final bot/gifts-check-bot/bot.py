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

# BOT_TOKEN, BOT_TOKEN_2 … берём из переменных окружения
bot_tokens = {k: v for k, v in os.environ.items()
              if k.startswith("BOT_TOKEN") and v}

# сопоставляем токен ↔ чат-id клуба
# !!! подставьте свои ids !!!
CLUB_CHAT_IDS = {
    os.getenv("BOT_TOKEN"):   -1002655130461,   # Knockdown Club
    os.getenv("BOT_TOKEN_2"): -1002760691414,   # Ion Gem Club
}

DELAY, CLICK_COOLDOWN, SUMGIFTS_COOLDOWN = 1.5, 10, 600
RAW = os.getenv("LOG_RAW_GIFTS", "0") == "1"        # 1 → логируем JSON подарков

# ───────── LOGS ─────────
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("giftbot")

def safe_json(obj) -> str:
    def _d(o): return f"<{len(o)} bytes>" if isinstance(o, (bytes, bytearray)) else str(o)
    return json.dumps(obj, default=_d, ensure_ascii=False)

# ───────── FRONT BOTS ─────────
bots: list[TeleBot] = [TeleBot(tok, num_threads=1) for tok in bot_tokens.values()]
for b in bots: b.skip_pending = True

# ───────── USER BOT ─────────
main_loop = asyncio.new_event_loop()
asyncio.set_event_loop(main_loop)
user_client: TelegramClient | None = None
check_queue: asyncio.Queue = asyncio.Queue()

async def init_userbot():
    global user_client
    user_client = TelegramClient(session_path, api_id, api_hash)
    await user_client.start(); await user_client.get_dialogs()
    log.info("👤 userbot session started")

# ───────── MATCHERS ─────────
def matches_rule(gift: dict, ftype: str, fval: str) -> bool:
    if ftype == "slug":        return str(gift.get("slug"))        == fval
    if ftype == "model":       return gift.get("model")            == fval
    if ftype == "collection":  return gift.get("collection")       == fval
    if ftype == "name":        return gift.get("name", "").startswith(fval)
    return False

def attribute_match(gift: dict, tgt: str) -> bool:
    tgt = tgt.lower()
    if any(a.get("name", "").lower() == tgt for a in gift.get("attributes", [])): return True
    if gift.get("title", "").lower().startswith(tgt): return True
    if str(gift.get("slug", "")).lower().startswith(tgt): return True
    return False

# ───────── COUNTER ─────────
async def count_gifts(uid:int, chat_id:int, username=None, first=None, last=None)->int:
    rule = get_community_rule(chat_id)
    ftype, fval = rule["filter_type"], rule["filter_value"]

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

    total, offset = 0, ""
    while True:
        res = await user_client(GetUserStarGiftsRequest(ent, offset, 100))
        for g in res.gifts:
            gift = g.to_dict().get("gift", {})
            if RAW: log.info("GIFT RAW chat=%s user=%s → %s",
                             chat_id, uid, safe_json(gift)[:1500])
            if ftype == "attribute" and attribute_match(gift, fval): total += 1
            elif matches_rule(gift, ftype, fval):                    total += 1
        if not res.next_offset: break
        offset = res.next_offset
    return total

# ───────── STATE ─────────
_last_click: dict[int,float] = {}; _last_sum: dict[int,float] = {}

# ───────── HANDLERS ─────────
def setup(bot: TeleBot):

    @bot.message_handler(commands=["start"])
    def cmd_start(msg):
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔍 Проверить подарки",
                                          callback_data="check_gifts"))
        bot.send_message(msg.chat.id, "👋 Добро пожаловать!\nНажмите кнопку.", reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data=="check_gifts")
    def cb_check(call):
        if time.time()-_last_click.get(call.from_user.id,0)<CLICK_COOLDOWN:
            bot.answer_callback_query(call.id,"⏳ Секундочку…");return
        _last_click[call.from_user.id]=time.time()
        asyncio.run_coroutine_threadsafe(check_queue.put(call), main_loop)
        bot.send_message(call.message.chat.id,"⏳ Проверяем подарки…")

    @bot.message_handler(commands=["sumgifts"])
    def cmd_sumgifts(msg):
        club_id = CLUB_CHAT_IDS.get(bot.token)
        if not club_id: return
        if time.time()-_last_sum.get(club_id,0)<SUMGIFTS_COOLDOWN:
            bot.reply_to(msg,"⏳ Раз в 10 минут.");return
        _last_sum[club_id]=time.time()
        rule=get_community_rule(club_id)
        bot.reply_to(msg,f"🔄 Считаем подарки ({rule['filter_type']}={rule['filter_value']})…")
        async def calc():
            total=0
            async for u in user_client.iter_participants(club_id):
                if u.bot or not u.access_hash: continue
                total+=max(0,await count_gifts(u.id,club_id,u.username,u.first_name,u.last_name))
            bot.send_message(msg.chat.id,f"🔥 В клубе <b>{total}</b> подарков.",parse_mode="HTML")
        asyncio.run_coroutine_threadsafe(calc(),main_loop)

    # join / guard остаются без изменений (работают в самом клубе)

for b in bots: setup(b)

# ───────── QUEUE WORKER ─────────
async def queue_worker():
    while True:
        call = await check_queue.get()
        try:
            token = call.bot.token
            club_id = CLUB_CHAT_IDS.get(token)
            if club_id is None:
                log.warning("No club id mapped for token %s", token); continue

            uid = call.from_user.id
            cnt = await count_gifts(uid, club_id,
                                    call.from_user.username,
                                    call.from_user.first_name,
                                    call.from_user.last_name)
            rule = get_community_rule(club_id)
            log.info("CHECK club=%s user=%s → %s gifts (need %s)",
                     club_id, uid, cnt, rule["min_gifts"])

            # ссылка создаётся для клуба, а отправляется в личку
            if cnt < rule["min_gifts"]:
                call.bot.send_message(call.message.chat.id,
                    f"❌ У вас {cnt} подарков, нужно {rule['min_gifts']}.")
            else:
                link = call.bot.create_chat_invite_link(
                    club_id, creates_join_request=True,
                    expire_date=int(time.time())+3600, name=f"gift-{uid}")
                call.bot.send_message(call.message.chat.id,
                    f"✅ Всё ок! Ссылка действует час:\n{link.invite_link}")
                save_approved(club_id, uid, call.from_user.username,
                              cnt, link.invite_link)
        except Exception: traceback.print_exc()
        await asyncio.sleep(DELAY)

# ───────── STARTUP ─────────
def bootstrap():
    main_loop.create_task(init_userbot())
    main_loop.create_task(queue_worker())
    main_loop.run_forever()

threading.Thread(target=bootstrap, daemon=True).start()
log.info("🤖 Запущено %s ботов, 1 user-сессия", len(bots))
bots[0].infinity_polling(timeout=10, long_polling_timeout=5)