import logging
import random
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes
)

import database as db
from events import CHRONOLOGY, SIDES, LOCATIONS, ENEMIES, WEAPONS
from utils import combat, random_event

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Состояния разговора
SELECT_SIDE, CHRONOLOGY_VIEW, GAME_MAIN, COMBAT, LOCATION_MENU, ACTION_INPUT = range(6)

# Инициализация БД
db.init_db()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    player = db.load_player(user_id)
    if player:
        # Если уже есть сохранённая игра, предложим продолжить
        await update.message.reply_text(
            "🔄 У вас есть сохранённая игра. Продолжить или начать новую?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📂 Продолжить", callback_data="continue")],
                [InlineKeyboardButton("🆕 Новая игра", callback_data="new_game")]
            ])
        )
        return SELECT_SIDE
    else:
        # Новая игра: показываем хронологию или сразу выбор стороны
        await update.message.reply_text(
            "📖 *Донбасс 2014 – интерактивная хроника*\n\n"
            "Это игра, основанная на реальных событиях.\n"
            "Ваши решения влияют на сюжет.\n\n"
            "Сначала ознакомьтесь с хронологией или сразу выберите сторону.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📅 Хронология", callback_data="chronology")],
                [InlineKeyboardButton("⚔️ Выбрать сторону", callback_data="choose_side")]
            ])
        )
        return CHRONOLOGY_VIEW

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    # Обработка продолжения / новой игры
    if data == "continue":
        player = db.load_player(user_id)
        if player:
            context.user_data["player"] = player
            await show_main_menu(query.message, player)
            return GAME_MAIN
        else:
            await query.edit_message_text("Ошибка: сохранения нет. Начните новую игру /start")
            return ConversationHandler.END

    if data == "new_game":
        db.delete_player(user_id)
        context.user_data.clear()
        await query.edit_message_text("Создаём новую игру...")
        await start(update, context)
        return SELECT_SIDE

    # Хронология
    if data == "chronology":
        idx = 0
        await query.edit_message_text(
            CHRONOLOGY[idx] + "\n\n➡️ Далее",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➡️", callback_data=f"chrono_{idx+1}")]])
        )
        context.user_data["chrono_idx"] = idx + 1
        return CHRONOLOGY_VIEW

    if data.startswith("chrono_"):
        idx = int(data.split("_")[1])
        if idx < len(CHRONOLOGY):
            await query.edit_message_text(
                CHRONOLOGY[idx] + "\n\n" + ("➡️ Далее" if idx+1 < len(CHRONOLOGY) else "🏁 Конец"),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➡️", callback_data=f"chrono_{idx+1}")]]) if idx+1 < len(CHRONOLOGY) else None
            )
            context.user_data["chrono_idx"] = idx + 1
        else:
            # Хронология закончена – предлагаем выбрать сторону
            await query.edit_message_text(
                "Хронология завершена. Теперь выберите сторону:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛡️ Ополчение", callback_data="side_militia")],
                    [InlineKeyboardButton("🇺🇦 ВСУ", callback_data="side_ukraine")],
                    [InlineKeyboardButton("👨‍👩‍👧 Мирный житель", callback_data="side_civilian")]
                ])
            )
            return SELECT_SIDE

    # Выбор стороны
    if data == "choose_side":
        await query.edit_message_text(
            "Выберите сторону:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛡️ Ополчение", callback_data="side_militia")],
                [InlineKeyboardButton("🇺🇦 ВСУ", callback_data="side_ukraine")],
                [InlineKeyboardButton("👨‍👩‍👧 Мирный житель", callback_data="side_civilian")]
            ])
        )
        return SELECT_SIDE

    if data.startswith("side_"):
        side = data.split("_")[1]
        if side not in SIDES:
            await query.edit_message_text("Ошибка: неверная сторона.")
            return SELECT_SIDE
        # Инициализация нового игрока
        player = {
            "user_id": user_id,
            "side": side,
            "health": SIDES[side]["starting_health"],
            "morale": SIDES[side]["starting_morale"],
            "resources": SIDES[side]["starting_resources"].copy(),
            "location": "base",
            "completed_events": [],
            "score": 0,
            "achievements": []
        }
        db.save_player(user_id, player)
        context.user_data["player"] = player
        await query.edit_message_text(
            f"Вы выбрали: *{SIDES[side]['name']}*\n\n{SIDES[side]['intro']}",
            parse_mode="Markdown"
        )
        await show_main_menu(query.message, player)
        return GAME_MAIN

    # Основное меню
    if data == "main_menu":
        player = context.user_data["player"]
        await show_main_menu(query.message, player)
        return GAME_MAIN

    if data == "locations_menu":
        keyboard = [[InlineKeyboardButton(loc["name"], callback_data=f"location_{key}")] for key, loc in LOCATIONS.items()]
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="main_menu")])
        await query.edit_message_text("🗺️ Выберите локацию:", reply_markup=InlineKeyboardMarkup(keyboard))
        return LOCATION_MENU

    if data.startswith("location_"):
        loc_key = data.split("_")[1]
        if loc_key not in LOCATIONS:
            await query.edit_message_text("Локация не найдена.")
            return LOCATION_MENU
        loc = LOCATIONS[loc_key]
        context.user_data["current_location"] = loc_key
        await query.edit_message_text(
            f"📍 *{loc['name']}*\n\n{loc['description']}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 Доступные действия", callback_data=f"actions_{loc_key}")],
                [InlineKeyboardButton("◀️ Назад", callback_data="locations_menu")]
            ])
        )
        return LOCATION_MENU

    if data.startswith("actions_"):
        loc_key = data.split("_")[1]
        loc = LOCATIONS[loc_key]
        keyboard = [[InlineKeyboardButton(action["name"], callback_data=f"do_{loc_key}_{action['id']}")] for action in loc["actions"]]
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data=f"location_{loc_key}")])
        await query.edit_message_text(
            f"*{loc['name']}* – что делаем?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return LOCATION_MENU

    # Обработка действий
    if data.startswith("do_"):
        _, loc_key, action_id = data.split("_")
        player = context.user_data["player"]
        result = await process_action(user_id, loc_key, action_id, player, context)
        if result.get("combat"):
            # Переход в бой
            enemy_key = result["enemy_key"]
            context.user_data["combat_data"] = {"enemy_key": enemy_key, "loc_key": loc_key}
            await query.edit_message_text(
                f"⚔️ *ВСТУПЛЕНИЕ В БОЙ*\nПротивник: {ENEMIES[enemy_key]['name']}\nЗдоровье: {ENEMIES[enemy_key]['health']}\n\n{result['text']}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔫 Атаковать", callback_data="combat_attack")],
                    [InlineKeyboardButton("💊 Лечиться", callback_data="combat_heal")],
                    [InlineKeyboardButton("🏃 Отступить", callback_data="combat_flee")]
                ])
            )
            return COMBAT
        else:
            # Обычный исход
            await query.edit_message_text(result["text"], parse_mode="Markdown")
            # Возвращаем в меню локации
            await show_location_actions(query.message, loc_key, player)
            return LOCATION_MENU

    # Боевые действия
    if data == "combat_attack":
        combat_data = context.user_data.get("combat_data")
        if not combat_data:
            await query.edit_message_text("Ошибка боя. Возврат в меню.")
            await show_main_menu(query.message, context.user_data["player"])
            return GAME_MAIN
        player = context.user_data["player"]
        enemy_key = combat_data["enemy_key"]
        enemy = ENEMIES[enemy_key]
        weapon = player["resources"].get("weapon", "pistol")

        # Проверка боеприпасов для РПГ
        if weapon == "rpg" and player["resources"].get("ammo", 0) < 1:
            await query.edit_message_text("❌ Нет боеприпасов для РПГ! Используйте другое оружие.")
            # Можно вернуться к боевому меню
            return COMBAT

        # Бой
        # Здесь нужно вести временное здоровье врага, сохраняя его в context
        enemy_health = context.user_data.get("enemy_health", enemy["health"])
        player_health = player["health"]
        player_ammo = player["resources"]["ammo"]

        # Выстрел
        if weapon == "rpg":
            # Используем один боеприпас
            if player_ammo >= 1:
                player_ammo -= 1
                # Урон по врагу
                dmg = random.randint(WEAPONS["rpg"]["damage_min"], WEAPONS["rpg"]["damage_max"])
                enemy_health -= dmg
                log = [f"🚀 Вы выпустили РПГ! Урон {dmg}."]
            else:
                log = ["❌ Нет боеприпасов!"]
        else:
            # Стандартная атака
            new_player_health, new_enemy_health, new_ammo, log, win = combat(weapon, enemy_key, player_health, enemy_health, player_ammo)
            player_health = new_player_health
            enemy_health = new_enemy_health
            player_ammo = new_ammo

        # Обновляем временные данные
        context.user_data["enemy_health"] = enemy_health
        player["health"] = player_health
        player["resources"]["ammo"] = player_ammo

        if enemy_health <= 0:
            # Победа
            reward = enemy["reward"]
            player["resources"]["food"] += reward["food"]
            player["resources"]["ammo"] += reward["ammo"]
            player["score"] += reward["score"]
            player["morale"] = min(100, player["morale"] + 5)
            log.append(f"✅ Победа! Вы получили: {reward['food']} еды, {reward['ammo']} патронов, {reward['score']} очков.")
            db.save_player(player["user_id"], player)
            await query.edit_message_text("\n".join(log), parse_mode="Markdown")
            # Возврат к локации
            await show_location_actions(query.message, combat_data["loc_key"], player)
            del context.user_data["combat_data"]
            return LOCATION_MENU
        elif player_health <= 0:
            # Поражение
            log.append("💀 Вы погибли... Игра окончена.")
            await query.edit_message_text("\n".join(log), parse_mode="Markdown")
            db.delete_player(player["user_id"])
            return ConversationHandler.END
        else:
            # Бой продолжается
            log.append("⚔️ Бой продолжается!")
            await query.edit_message_text(
                "\n".join(log),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔫 Атаковать", callback_data="combat_attack")],
                    [InlineKeyboardButton("💊 Лечиться", callback_data="combat_heal")],
                    [InlineKeyboardButton("🏃 Отступить", callback_data="combat_flee")]
                ])
            )
            return COMBAT

    if data == "combat_heal":
        player = context.user_data["player"]
        if player["resources"].get("medkits", 0) > 0:
            heal = random.randint(15, 40)
            player["health"] = min(100, player["health"] + heal)
            player["resources"]["medkits"] -= 1
            db.save_player(player["user_id"], player)
            await query.edit_message_text(
                f"💉 Вы использовали аптечку. +{heal} HP. Осталось аптечек: {player['resources']['medkits']}.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔫 Атаковать", callback_data="combat_attack")],
                    [InlineKeyboardButton("🏃 Отступить", callback_data="combat_flee")]
                ])
            )
        else:
            await query.edit_message_text(
                "❌ Нет аптечек!",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔫 Атаковать", callback_data="combat_attack")],
                    [InlineKeyboardButton("🏃 Отступить", callback_data="combat_flee")]
                ])
            )
        return COMBAT

    if data == "combat_flee":
        success = random.random() < 0.5
        if success:
            await query.edit_message_text("🏃 Вы успешно отступили.", parse_mode="Markdown")
            combat_data = context.user_data.get("combat_data", {})
            loc_key = combat_data.get("loc_key", "base")
            await show_location_actions(query.message, loc_key, context.user_data["player"])
            del context.user_data["combat_data"]
            return LOCATION_MENU
        else:
            # Не удалось отступить – враг атакует
            combat_data = context.user_data["combat_data"]
            enemy_key = combat_data["enemy_key"]
            enemy = ENEMIES[enemy_key]
            player = context.user_data["player"]
            enemy_health = context.user_data.get("enemy_health", enemy["health"])
            enemy_dmg = random.randint(max(1, enemy["damage"]-5), enemy["damage"]+5)
            player["health"] -= enemy_dmg
            if player["health"] <= 0:
                await query.edit_message_text(f"💀 Вы погибли... Игра окончена. /start", parse_mode="Markdown")
                db.delete_player(player["user_id"])
                return ConversationHandler.END
            db.save_player(player["user_id"], player)
            await query.edit_message_text(
                f"Не удалось отступить! {enemy['name']} нанёс {enemy_dmg} урона. У вас {player['health']} HP.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔫 Атаковать", callback_data="combat_attack")],
                    [InlineKeyboardButton("💊 Лечиться", callback_data="combat_heal")],
                    [InlineKeyboardButton("🏃 Отступить", callback_data="combat_flee")]
                ])
            )
            return COMBAT

    if data == "inventory":
        player = context.user_data["player"]
        inv = f"🍞 Еда: {player['resources']['food']}\n🔫 Патроны: {player['resources']['ammo']}\n💊 Аптечки: {player['resources']['medkits']}\n🔫 Оружие: {WEAPONS[player['resources']['weapon']]['name']}"
        await query.edit_message_text(
            f"📦 *Инвентарь*\n{inv}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="main_menu")]])
        )
        return GAME_MAIN

    if data == "events_list":
        player = context.user_data["player"]
        events = player.get("completed_events", [])
        if events:
            text = "📜 *Завершённые события*\n- " + "\n- ".join(events)
        else:
            text = "📜 *Завершённые события*: пока нет."
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="main_menu")]]))
        return GAME_MAIN

    if data == "end_game":
        await query.edit_message_text("🏁 Игра завершена. Ваш прогресс удалён. Для новой игры введите /start")
        db.delete_player(user_id)
        return ConversationHandler.END

    return GAME_MAIN

async def show_main_menu(message, player):
    side_name = SIDES[player["side"]]["name"]
    health = player["health"]
    morale = player["morale"]
    res = player["resources"]
    text = (
        f"🎮 *Главное меню*\n"
        f"Сторона: {side_name}\n"
        f"❤️ Здоровье: {health} | 💪 Мораль: {morale}\n"
        f"🍞 Еда: {res['food']} | 🔫 Патроны: {res['ammo']} | 💊 Аптечки: {res['medkits']}\n"
        f"⭐ Очки: {player['score']}\n\n"
        f"Выберите действие:"
    )
    keyboard = [
        [InlineKeyboardButton("🗺️ Локации", callback_data="locations_menu")],
        [InlineKeyboardButton("📦 Инвентарь", callback_data="inventory")],
        [InlineKeyboardButton("📜 События", callback_data="events_list")],
        [InlineKeyboardButton("🏁 Завершить игру", callback_data="end_game")]
    ]
    await message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def show_location_actions(message, loc_key, player):
    loc = LOCATIONS[loc_key]
    keyboard = [[InlineKeyboardButton(action["name"], callback_data=f"do_{loc_key}_{action['id']}")] for action in loc["actions"]]
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data=f"location_{loc_key}")])
    await message.reply_text(
        f"*{loc['name']}* – доступные действия:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def process_action(user_id, loc_key, action_id, player, context):
    # Логика действий
    if action_id == "patrol":
        # Случайная встреча
        if random.random() < 0.4:
            enemy = random.choice(list(ENEMIES.keys()))
            return {"combat": True, "enemy_key": enemy, "text": "🔍 Во время патрулирования вы столкнулись с противником!"}
        else:
            # Находка
            ammo_gain = random.randint(5, 20)
            player["resources"]["ammo"] += ammo_gain
            db.save_player(user_id, player)
            return {"text": f"✅ Патрулирование прошло успешно. Найдено {ammo_gain} патронов."}
    elif action_id == "assault_sbu":
        return {"combat": True, "enemy_key": "sbu_defender", "text": "⚔️ Начинается штурм здания СБУ! Будьте осторожны."}
    elif action_id == "help_civilians":
        # Повышение морали, трата еды
        if player["resources"]["food"] >= 5:
            player["resources"]["food"] -= 5
            player["morale"] = min(100, player["morale"] + 15)
            player["score"] += 10
            db.save_player(user_id, player)
            return {"text": "🤝 Вы помогли мирным жителям. Мораль повышена, получено +10 очков."}
        else:
            return {"text": "❌ У вас недостаточно еды для помощи."}
    elif action_id == "scavenge":
        # Риск обстрела
        if random.random() < 0.3:
            dmg = random.randint(10, 30)
            player["health"] -= dmg
            db.save_player(user_id, player)
            return {"text": f"💥 Во время поисков вы попали под обстрел! Потеряно {dmg} здоровья."}
        else:
            food_gain = random.randint(5, 20)
            ammo_gain = random.randint(10, 30)
            player["resources"]["food"] += food_gain
            player["resources"]["ammo"] += ammo_gain
            db.save_player(user_id, player)
            return {"text": f"🔍 Вы нашли {food_gain} еды и {ammo_gain} патронов."}
    # Добавьте другие действия аналогично
    else:
        # Заглушка
        return {"text": "🚧 Это действие пока в разработке."}

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Игра прервана. /start для начала.")
    return ConversationHandler.END

def main():
    TOKEN = "8619745303:AAHsEWaPKdPSbenRO7dzVCrDvxUIm0CzDu0"
    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECT_SIDE: [CallbackQueryHandler(button_handler)],
            CHRONOLOGY_VIEW: [CallbackQueryHandler(button_handler)],
            GAME_MAIN: [CallbackQueryHandler(button_handler)],
            COMBAT: [CallbackQueryHandler(button_handler)],
            LOCATION_MENU: [CallbackQueryHandler(button_handler)],
            ACTION_INPUT: [CallbackQueryHandler(button_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_handler)
    app.run_polling()

if __name__ == "__main__":
    main()
