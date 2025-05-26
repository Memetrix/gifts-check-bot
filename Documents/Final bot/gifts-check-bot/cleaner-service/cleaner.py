async def check_and_kick(user, client):
    try:
        entity = InputUser(user.id, user.access_hash)

        result = await client(GetUserStarGiftsRequest(user_id=entity, offset="", limit=100))

        # Защита: Telegram не вернул подарки
        if not result.gifts:
            print(f"⚠️ @{user.username or '???'} ({user.id}) — подарки не получены → пропускаем")
            return True

        # Нормальная проверка
        count = 0
        for g in result.gifts:
            data = g.to_dict()
            gift_data = data.get("gift")
            if not gift_data or "title" not in gift_data or "slug" not in gift_data:
                continue
            for attr in gift_data.get("attributes", []):
                if "name" in attr and attr["name"].lower() == "knockdown":
                    count += 1
                    break

        if count < 6:
            print(f"❌ @{user.username or '???'} ({user.id}) — {count} knockdown → кик")
            bot.ban_chat_member(chat_id, user.id)
            bot.unban_chat_member(chat_id, user.id)
            try:
                bot.send_message(user.id, f"🚫 У тебя осталось {count} knockdown-подарков. Ты был удалён из группы.")
            except:
                print(f"⚠️ Не удалось отправить сообщение @{user.username or user.id}")
        else:
            print(f"✅ @{user.username or '???'} ({user.id}) — {count} knockdown → всё ок")

        return True

    except Exception as e:
        print(f"⚠️ Ошибка при проверке @{user.username or '???'} ({user.id}): {e}")
        traceback.print_exc()
        return False
