import asyncio  # в начале файла, если ещё не подключено

# ...

@bot.callback_query_handler(func=lambda call: call.data == "check_gifts")
def handle_check(call):
    telegram_id = call.from_user.id

    try:
        async def check_gifts():
            user = await userbot.get_input_entity(telegram_id)
            result = await userbot(GetUserStarGiftsRequest(user_id=user, offset="", limit=100))

            knockdown_count = 0
            for g in result.gifts:
                data = g.to_dict()
                gift = data.get("gift")
                if not gift or "attributes" not in gift:
                    continue
                for attr in gift["attributes"]:
                    if "name" in attr and attr["name"].lower() == "knockdown":
                        knockdown_count += 1
                        break

            if knockdown_count >= 6:
                return f"✅ У тебя {knockdown_count} knockdown-подарков. Доступ разрешён!"
            else:
                return f"❌ У тебя только {knockdown_count} knockdown-подарков. Нужно минимум 6.\nПопробуй докупить на @mrkt"

        # Запускаем async-функцию вручную
        text = asyncio.run(check_gifts())
        bot.send_message(call.message.chat.id, text)

    except Exception as e:
        bot.send_message(call.message.chat.id, "⚠️ Ошибка при проверке подарков.")
        print("❌ Ошибка:", e)