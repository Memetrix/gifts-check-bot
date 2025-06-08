import os, asyncio, threading, time, logging, traceback, json
from dotenv import load_dotenv
from telebot import TeleBot, types
from telethon import TelegramClient
from telethon.tl.types import InputUser
from get_user_star_gifts_request import GetUserStarGiftsRequest
from db import save_approved

# — Загружаем .env только для локальной отладки
load_dotenv()

# — Переменные окружения
api_id       = int(os.getenv("API_ID"))
api_hash     = os.getenv("API_HASH")
bot_token    = os.getenv("BOT_TOKEN")
chat_id      = int(os.getenv("CHAT_ID"))
session_file = os.getenv("SESSION_PATH", "userbot.session")
filter_type  = os.getenv("FILTER_TYPE", "attribute")
filter_value = os.getenv("FILTER_VALUE", "Knockdown")
min_gifts    = int(os.getenv("MIN_GIFTS", 6))
club_name    = os.getenv("CLUB_NAME", "Club")

# — Telegram
bot = TeleBot(bot_token, num_threads=1)
bot.skip_pending = True

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("giftbot")

main_loop = asyncio.new_event_loop()
asyncio.set_event_loop(main_loop)
user_client = None
check_queue: asyncio.Queue = asyncio.Queue()

# — Подсчёт подарков
def matches(gift: dict) -> bool:
    if filter_type == "attribute":
        return any(a.get("name", "").lower() == filter_value.lower()
                   for a in gift.get("attributes", []))
    return gift.get(filter_type, "") == filter_value

async def count_gifts(uid, chat_id, username=None, first=None, last=None) -> int:
    try:
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
                log.info(f"GIFT RAW chat={chat_id} user={uid} → {json.dumps(gift, ensure_ascii=False)[:500]}")
                if matches(gift):
                    total += 1
            if not res.next_offset: break
            offset = res.next_offset
        return total
    except Exception:
        log.exception("count_gifts")
        return -1

# — Обработка /start
@bot.message_handler(commands=["start"])
def on_start(msg):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔍 Проверить подарки / Check gifts", callback_data="check_gifts"))
    bot.send_message(msg.chat.id,
        f"👋 Привет! Я проверяю подарки в твоём профиле. "
        f"Если они подходят — получишь доступ в {club_name} 🔐\n\n"
        f"👋 Hi! I check the gifts in your profile. "
        f"If they match — you’ll get access to {club_name} 🔐",
        reply_markup=kb)

# — /sumgifts
_last_sumgifts = 0
@bot.message_handler(commands=["sumgifts"])
def sumgifts_handler(msg):
    global _last_sumgifts
    if time.time() - _last_sumgifts < 600:
        bot.reply_to(msg, "⏳ Подождите немного. Команду можно раз в 10 минут.")
        return
    _last_sumgifts = time.time()
    bot.send_message(chat_id, "🔄 Считаем подарки всех участников клуба…")

    async def calc():
        total = 0
        async for u in user_client.iter_participants(chat_id):
            if u.bot or not u.access_hash: continue
            cnt = await count_gifts(u.id, chat_id, u.username, u.first_name, u.last_name)
            if cnt > 0: total += cnt
        bot.send_message(chat_id, f"🔥 В клубе уже {total} подходящих подарков!\n🔥 The club already has {total} valid gifts!")

    asyncio.run_coroutine_threadsafe(calc(), main_loop)

# — Inline проверка
_last_click = {}
@bot.callback_query_handler(func=lambda c: c.data == "check_gifts")
def on_click(call):
    now = time.time()
    if now - _last_click.get(call.from_user.id, 0) < 10:
        bot.answer_callback_query(call.id, "⏳ Подождите…"); return
    _last_click[call.from_user.id] = now
    asyncio.run_coroutine_threadsafe(check_queue.put(call), main_loop)
    bot.send_message(call.message.chat.id, "⏳ Идёт проверка…")

# — Очередь проверок
async def process_queue():
    while True:
        call = await check_queue.get()
        try:
            uid = call.from_user.id
            cnt = await count_gifts(uid, chat_id,
                call.from_user.username,
                call.from_user.first_name,
                call.from_user.last_name)

            if cnt < min_gifts:
                bot.send_message(call.message.chat.id,
                    f"❌ У тебя {cnt} подарков. Нужно минимум {min_gifts} с атрибутом {filter_value}.")
                continue

            try: await bot.unban_chat_member(chat_id, uid)
            except: pass

            inv = bot.create_chat_invite_link(chat_id, creates_join_request=True,
                                              expire_date=int(time.time())+3600,
                                              name=f"gift-{uid}")
            bot.send_message(call.message.chat.id,
                f"✅ Всё ок! Ссылка на вступление:\n{inv.invite_link}")
            save_approved(chat_id, uid, call.from_user.username, cnt, inv.invite_link)
        except Exception:
            bot.send_message(call.message.chat.id, "⚠️ Внутренняя ошибка.")
            traceback.print_exc()
        await asyncio.sleep(1.5)

# — Join Request
@bot.chat_join_request_handler()
def on_request(req):
    async def approve():
        cnt = await count_gifts(req.from_user.id, chat_id,
                                req.from_user.username,
                                req.from_user.first_name,
                                req.from_user.last_name)
        if cnt >= min_gifts:
            bot.approve_chat_join_request(chat_id, req.from_user.id)
        else:
            bot.decline_chat_join_request(chat_id, req.from_user.id)
    asyncio.run_coroutine_threadsafe(approve(), main_loop)

# — Kick обходящих
@bot.chat_member_handler()
def kick_unchecked(msg: types.ChatMemberUpdated):
    u = msg.new_chat_member.user
    if u.is_bot or msg.new_chat_member.status != 'member': return

    async def check():
        cnt = await count_gifts(u.id, chat_id, u.username, u.first_name, u.last_name)
        if cnt < min_gifts:
            try:
                bot.ban_chat_member(chat_id, u.id, until_date=int(time.time())+60)
            except: pass
    asyncio.run_coroutine_threadsafe(check(), main_loop)

# — Старт бота
async def init_userbot():
    global user_client
    user_client = TelegramClient(session_file, api_id, api_hash)
    await user_client.start()
    await user_client.get_dialogs()
    log.info("👤 Userbot session ready")
    main_loop.create_task(process_queue())

threading.Thread(target=lambda: main_loop.run_until_complete(init_userbot()), daemon=True).start()
log.info("🤖 Bot is running!")
bot.infinity_polling(timeout=10, long_polling_timeout=5)