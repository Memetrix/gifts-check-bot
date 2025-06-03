import os
import asyncio
import psycopg2
from datetime import datetime
from telethon import TelegramClient
from telethon.tl.types import InputUser
from get_user_star_gifts_request import GetUserStarGiftsRequest

# Конфиг
api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
session_file = "sessions/userbot2"
admin_user_id = int(os.getenv("ADMIN_USER_ID"))
slava_user_id = 1911659577
chat_id = int(os.getenv("CHAT_ID"))

EXCLUDED_ADMINS = {
    "gifts_check_bot", "knockdownclub", "tap_monster", "knockdown_club",
    8123231575, 934264793, 5855748096, 7071295533, 7870945546
}

async def get_knockdown_count_safe(client, user_id, access_hash):
    count = 0
    offset = ""
    try:
        entity = InputUser(user_id, access_hash)
        while True:
            result = await client(GetUserStarGiftsRequest(user_id=entity, offset=offset, limit=100))
            if not result.gifts:
                break
            for g in result.gifts:
                gift = g.to_dict().get("gift")
                if not gift:
                    continue
                for attr in gift.get("attributes", []):
                    if "name" in attr and attr["name"].lower() == "knockdown":
                        count += 1
                        break
            offset = result.next_offset or ""
            if not offset:
                break
        return count, None
    except Exception as e:
        return -1, str(e)

async def main():
    async with TelegramClient(session_file, api_id, api_hash) as client:
        conn = psycopg2.connect(
            host=os.getenv("PGHOST"),
            dbname=os.getenv("PGDATABASE"),
            user=os.getenv("PGUSER"),
            password=os.getenv("PGPASSWORD"),
            port=os.getenv("PGPORT")
        )
        cur = conn.cursor()

        users = []
        total = 0

        async for user in client.iter_participants(chat_id):
            total += 1
            user_id = user.id
            username = user.username.lower() if user.username else None

            if user_id in EXCLUDED_ADMINS or (username and username in EXCLUDED_ADMINS):
                continue

            if user.username:
                label = f"@{user.username}"
            else:
                full_name = f"{(user.first_name or '').strip()} {(user.last_name or '').strip()}".strip()
                label = f"{full_name} — {user.id}"

            if not user.access_hash:
                users.append(("⚠️", label, "нет access_hash"))
                continue

            count, error = await get_knockdown_count_safe(client, user_id, user.access_hash)
            if error:
                users.append(("⚠️", label, f"ошибка — {error}"))
            elif count < 6:
                users.append(("❗️", label, f"{count} knockdown"))
            else:
                users.append(("🎁", label, f"{count} knockdown"))

        users.sort(key=lambda x: int(x[2].split()[0]) if "knockdown" in x[2] else -1, reverse=True)

        html = [
            "<b>📋 Отчёт по knockdown‑подаркам</b>",
            f"<i>👥 Users in group — {total}</i>",
            ""
        ]

        for icon, label, detail in users:
            if label.startswith("@"):
                html.append(f"{icon} <code>{label}</code>: {detail}")
            elif "—" in label:
                name_part, id_part = map(str.strip, label.split("—", 1))
                html.append(f"{icon} <code>{name_part}</code> (ID <code>{id_part}</code>): {detail}")
            else:
                html.append(f"{icon} <code>{label}</code>: {detail}")

        html_report = "\n".join(html)

        for uid in [admin_user_id, slava_user_id]:
            await client.send_message(uid, html_report, parse_mode="html")

if __name__ == "__main__":
    asyncio.run(main())
