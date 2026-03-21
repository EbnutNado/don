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

db.init_db()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    player = db.load_player(user_id)
    if player:
        await update.message.reply_text(
            "🔄 У вас есть сохранённая игра. Продолжить или начать новую?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📂 Продолжить", callback_data="continue")],
                [InlineKeyboardButton("🆕 Новая игра", callback_data="new_game")]
            ])
        )
        return SELECT_SIDE
    else:
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
            await query.edit_message_text(
                "Хронология завершена. Теперь выберите сторону:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛡️ Ополчение", callback_data="side_militia")],
                    [InlineKeyboardButton("🇺🇦 ВСУ", callback_data="side_ukraine")],
                    [InlineKeyboardButton("👨‍👩‍👧 Мирный житель", callback_data="side_civilian")]
                ])
            )
            return SELECT_SIDE

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
        # случайное событие при входе
        event_desc, delta, resource = random_event()
        if delta != 0:
            player = context.user_data["player"]
            if resource == "health":
                player["health"] = max(0, min(100, player["health"] + delta))
            elif resource == "food":
                player["resources"]["food"] = max(0, player["resources"]["food"] + delta)
            elif resource == "ammo":
                player["resources"]["ammo"] = max(0, player["resources"]["ammo"] + delta)
            elif resource == "morale":
                player["morale"] = max(0, min(100, player["morale"] + delta))
            db.save_player(player["user_id"], player)
            await query.message.reply_text(f"{event_desc}: {'+' if delta>0 else ''}{delta}")
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

    if data.startswith("do_"):
        _, loc_key, action_id = data.split("_")
        player = context.user_data["player"]
        result = await process_action(user_id, loc_key, action_id, player, context)
        if result.get("combat"):
            enemy_key = result["enemy_key"]
            context.user_data["combat_data"] = {
                "enemy_key": enemy_key,
                "loc_key": loc_key,
                "enemy_health": ENEMIES[enemy_key]["health"]
            }
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
            await query.edit_message_text(result["text"], parse_mode="Markdown")
            await show_location_actions(query.message, loc_key, player)
            return LOCATION_MENU

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
        enemy_health = context.user_data["combat_data"]["enemy_health"]
        player_health = player["health"]
        player_ammo = player["resources"]["ammo"]

        # Бой
        new_player_health, new_enemy_health, new_ammo, log, win = combat(weapon, enemy_key, player_health, enemy_health, player_ammo)

        player["health"] = new_player_health
        player["resources"]["ammo"] = new_ammo
        context.user_data["combat_data"]["enemy_health"] = new_enemy_health
        db.save_player(player["user_id"], player)

        if win is True:
            # Победа
            reward = enemy["reward"]
            player["resources"]["food"] += reward["food"]
            player["resources"]["ammo"] += reward["ammo"]
            player["score"] += reward["score"]
            player["morale"] = min(100, player["morale"] + 5)
            log.append(f"✅ Победа! Вы получили: {reward['food']} еды, {reward['ammo']} патронов, {reward['score']} очков.")
            db.save_player(player["user_id"], player)
            await query.edit_message_text("\n".join(log), parse_mode="Markdown")
            await show_location_actions(query.message, combat_data["loc_key"], player)
            del context.user_data["combat_data"]
            return LOCATION_MENU
        elif win is False:
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
            enemy_health = combat_data.get("enemy_health", enemy["health"])
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
    """Обрабатывает любое действие из локации, возвращает словарь с результатом."""
    side = player["side"]
    res = player["resources"]
    health = player["health"]
    morale = player["morale"]
    score = player["score"]

    def save_and_return(text, combat=False, enemy_key=None):
        db.save_player(user_id, player)
        if combat:
            return {"combat": True, "enemy_key": enemy_key, "text": text}
        return {"text": text}

    # ---------- ДОНЕЦК ----------
    if action_id == "patrol":
        if random.random() < 0.4:
            possible = ["patrol", "sniper", "militant"] if side == "militia" else ["patrol", "sniper", "soldier"]
            enemy = random.choice(possible)
            return save_and_return("🔍 Во время патрулирования вы столкнулись с противником!", combat=True, enemy_key=enemy)
        else:
            gain_ammo = random.randint(5, 20)
            res["ammo"] += gain_ammo
            return save_and_return(f"✅ Патрулирование прошло успешно. Найдено {gain_ammo} патронов.")

    elif action_id == "assault_sbu":
        return save_and_return("⚔️ Начинается штурм здания СБУ!", combat=True, enemy_key="sbu_defender")

    elif action_id == "help_civilians":
        if res["food"] >= 5:
            res["food"] -= 5
            player["morale"] = min(100, player["morale"] + 15)
            player["score"] += 10
            return save_and_return("🤝 Вы помогли мирным жителям. Мораль повышена, +10 очков.")
        else:
            return save_and_return("❌ У вас недостаточно еды для помощи.")

    elif action_id == "scavenge":
        if random.random() < 0.3:
            dmg = random.randint(10, 30)
            player["health"] -= dmg
            return save_and_return(f"💥 Во время поисков вы попали под обстрел! Потеряно {dmg} здоровья.")
        else:
            gain_food = random.randint(5, 20)
            gain_ammo = random.randint(10, 30)
            res["food"] += gain_food
            res["ammo"] += gain_ammo
            return save_and_return(f"🔍 Вы нашли {gain_food} еды и {gain_ammo} патронов.")

    # ---------- ЛУГАНСК ----------
    elif action_id == "investigate_bombing":
        player["score"] += 20
        player["morale"] = min(100, player["morale"] + 5)
        return save_and_return("💣 Вы нашли свидетельства авиаудара. Истина раскрыта. +20 очков, +5 морали.")

    elif action_id == "evacuate":
        if res["food"] >= 10:
            res["food"] -= 10
            player["score"] += 30
            player["morale"] = min(100, player["morale"] + 20)
            return save_and_return("🚐 Вы организовали эвакуацию. Жители спасены. +30 очков.")
        else:
            return save_and_return("❌ Недостаточно еды для организации эвакуации.")

    elif action_id == "defend":
        return save_and_return("🛡️ Диверсанты атакуют блокпост!", combat=True, enemy_key="saboteur")

    elif action_id == "humanitarian":
        if res["food"] >= 8:
            res["food"] -= 8
            player["score"] += 15
            player["morale"] = min(100, player["morale"] + 10)
            return save_and_return("📦 Вы раздали гуманитарную помощь. Мораль повышена, +15 очков.")
        else:
            return save_and_return("❌ Недостаточно еды для раздачи.")

    # ---------- СЛАВЯНСК ----------
    elif action_id == "supply_run":
        return save_and_return("📦 Прорыв блокпостов! Встречайте врага.", combat=True, enemy_key="patrol")

    elif action_id == "breakthrough":
        return save_and_return("💥 Попытка прорыва окружения! На вас идёт усиленный отряд.", combat=True, enemy_key="btr")

    elif action_id == "sniper_duel":
        if random.random() < 0.5:
            res["ammo"] += 5
            player["score"] += 25
            return save_and_return("🎯 Вы победили снайпера! +25 очков, трофейные патроны.")
        else:
            dmg = random.randint(20, 40)
            player["health"] -= dmg
            return save_and_return(f"💔 Снайпер вас ранил! -{dmg} здоровья.")

    elif action_id == "minefield":
        if random.random() < 0.7:
            player["score"] += 40
            player["morale"] = min(100, player["morale"] + 15)
            return save_and_return("⚠️ Вы успешно разминировали участок! +40 очков.")
        else:
            dmg = random.randint(30, 70)
            player["health"] -= dmg
            if player["health"] <= 0:
                return save_and_return("💀 Мина взорвалась... Вы погибли.")
            return save_and_return(f"💥 Мина сработала! -{dmg} здоровья.")

    # ---------- АЭРОПОРТ ----------
    elif action_id == "defend_terminal":
        if side == "ukraine":
            return save_and_return("🛡️ Оборона терминала! Бой с ополчением.", combat=True, enemy_key="militant")
        else:
            return save_and_return("❌ Вы не можете защищать терминал за эту сторону.")

    elif action_id == "storm_terminal":
        if side == "militia":
            return save_and_return("⚔️ Штурм терминала! Бой с украинскими защитниками.", combat=True, enemy_key="soldier")
        else:
            return save_and_return("❌ Вы не можете штурмовать терминал за эту сторону.")

    elif action_id == "evacuate_wounded":
        if res["medkits"] >= 2:
            res["medkits"] -= 2
            player["score"] += 30
            player["morale"] = min(100, player["morale"] + 20)
            return save_and_return("🚑 Вы вывезли раненых. +30 очков.")
        else:
            return save_and_return("❌ Нет аптечек для эвакуации.")

    elif action_id == "tunnel_fight":
        return save_and_return("🚇 Бой в подземельях! Ближний бой с врагом.", combat=True, enemy_key="saboteur")

    # ---------- ИЛОВАЙСК ----------
    elif action_id == "encirclement":
        return save_and_return("💀 Вы в котле! Попытка прорыва.", combat=True, enemy_key="tank")

    elif action_id == "negotiate":
        if player["morale"] > 50 and random.random() < 0.6:
            player["score"] += 50
            return save_and_return("🤝 Переговоры успешны, открыт коридор. +50 очков.")
        else:
            return save_and_return("💔 Переговоры провалились, вас атакуют!", combat=True, enemy_key="patrol")

    elif action_id == "hold_line":
        return save_and_return("⚔️ Удерживайте позиции любой ценой!", combat=True, enemy_key="btr")

    # ---------- БАЗА ----------
    elif action_id == "rest":
        heal = random.randint(15, 40)
        player["health"] = min(100, player["health"] + heal)
        if res["food"] >= 3:
            res["food"] -= 3
        return save_and_return(f"🛌 Вы отдохнули и восстановили {heal} здоровья. Потрачено 3 еды.")

    elif action_id == "train":
        if res["food"] >= 4:
            res["food"] -= 4
            player["morale"] = min(100, player["morale"] + 10)
            return save_and_return("🏋️ Тренировка повысила мораль на 10. Потрачено 4 еды.")
        else:
            return save_and_return("❌ Недостаточно еды для тренировки.")

    elif action_id == "trade":
        if res["ammo"] >= 10:
            res["ammo"] -= 10
            res["food"] += 5
            return save_and_return("🔄 Обмен: -10 патронов, +5 еды.")
        else:
            return save_and_return("❌ Недостаточно патронов для обмена (нужно 10).")

    elif action_id == "quest":
        quests = [
            {"text": "Доставьте медикаменты в госпиталь", "reward_score": 20, "req_medkits": 2},
            {"text": "Патрулируйте опасный район", "reward_score": 15, "req_ammo": 10},
            {"text": "Помогите мирным жителям", "reward_score": 25, "req_food": 8},
        ]
        q = random.choice(quests)
        if "req_medkits" in q and res["medkits"] >= q["req_medkits"]:
            res["medkits"] -= q["req_medkits"]
            player["score"] += q["reward_score"]
            return save_and_return(f"📜 {q['text']} выполнено! +{q['reward_score']} очков.")
        elif "req_ammo" in q and res["ammo"] >= q["req_ammo"]:
            res["ammo"] -= q["req_ammo"]
            player["score"] += q["reward_score"]
            return save_and_return(f"📜 {q['text']} выполнено! +{q['reward_score']} очков.")
        elif "req_food" in q and res["food"] >= q["req_food"]:
            res["food"] -= q["req_food"]
            player["score"] += q["reward_score"]
            return save_and_return(f"📜 {q['text']} выполнено! +{q['reward_score']} очков.")
        else:
            return save_and_return("❌ У вас не хватает ресурсов для выполнения текущего квеста. Попробуйте позже.")

    else:
        # На случай, если добавится новое действие без обработки
        return save_and_return("🚧 Это действие временно недоступно.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Игра прервана. /start для начала.")
    return ConversationHandler.END

def main():
    TOKEN = "8619745303:AAHsEWaPKdPSbenRO7dzVCrDvxUIm0CzDu0"  # Замените на свой токен
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
