import logging
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes
)

from events import CHRONOLOGY, SIDES, LOCATIONS, ENEMIES, REWARDS
from utils import combat, random_event

# Состояния разговора
SELECT_SIDE, CHRONOLOGY_VIEW, GAME_MAIN, COMBAT, LOCATION_MENU = range(5)

# Хранилище состояний игроков
user_data_store = {}

# ---------- Вспомогательные функции ----------
def get_user_data(user_id):
    if user_id not in user_data_store:
        user_data_store[user_id] = {
            "side": None,
            "health": 100,
            "morale": 50,
            "resources": {"food": 10, "ammo": 30, "medkits": 2},
            "location": "donetsk",
            "completed_events": [],
            "score": 0
        }
    return user_data_store[user_id]

def save_user_data(user_id, data):
    user_data_store[user_id] = data

# ---------- Команды ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    get_user_data(user_id)  # инициализация
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
    user_data = get_user_data(user_id)

    if data == "chronology":
        # Показываем хронологию по частям
        text = "🗓 *Хронология 2014*\n\n" + "\n\n".join(CHRONOLOGY[:3])
        await query.edit_message_text(text, parse_mode="Markdown")
        # Кнопка "Далее"
        keyboard = [[InlineKeyboardButton("➡️ Далее", callback_data="chrono_next")]]
        await query.message.reply_text("Продолжить?", reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data["chrono_idx"] = 3
        return CHRONOLOGY_VIEW

    elif data == "chrono_next":
        idx = context.user_data.get("chrono_idx", 0)
        if idx < len(CHRONOLOGY):
            await query.edit_message_text(
                CHRONOLOGY[idx] + "\n\n" + ("➡️ Далее" if idx+1 < len(CHRONOLOGY) else "🏁 Конец"),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➡️ Далее", callback_data="chrono_next")]
                ]) if idx+1 < len(CHRONOLOGY) else None
            )
            context.user_data["chrono_idx"] = idx + 1
        else:
            await query.edit_message_text("Хронология завершена. Теперь выберите сторону.")
            await query.message.reply_text(
                "Выберите сторону:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛡️ Ополчение", callback_data="side_militia")],
                    [InlineKeyboardButton("🇺🇦 ВСУ", callback_data="side_ukraine")],
                    [InlineKeyboardButton("👨‍👩‍👧 Мирный житель", callback_data="side_civilian")]
                ])
            )
            return SELECT_SIDE

    elif data.startswith("side_"):
        side = data.split("_")[1]
        user_data["side"] = side
        await query.edit_message_text(
            f"Вы выбрали: *{SIDES[side]['name']}*\n\n{SIDES[side]['intro']}",
            parse_mode="Markdown"
        )
        await show_main_menu(query.message, user_data)
        return GAME_MAIN

    elif data == "main_menu":
        await show_main_menu(query.message, user_data)
        return GAME_MAIN

    elif data.startswith("location_"):
        loc_key = data.split("_")[1]
        user_data["location"] = loc_key
        loc = LOCATIONS[loc_key]
        await query.edit_message_text(
            f"📍 *{loc['name']}*\n\n{loc['description']}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 Доступные действия", callback_data=f"actions_{loc_key}")],
                [InlineKeyboardButton("◀️ Назад", callback_data="main_menu")]
            ])
        )
        return LOCATION_MENU

    elif data.startswith("actions_"):
        loc_key = data.split("_")[1]
        loc = LOCATIONS[loc_key]
        keyboard = []
        for action in loc["actions"]:
            keyboard.append([InlineKeyboardButton(action["name"], callback_data=f"do_{loc_key}_{action['id']}")])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data=f"location_{loc_key}")])
        await query.edit_message_text(
            f"*{loc['name']}* – что делаем?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return LOCATION_MENU

    elif data.startswith("do_"):
        _, loc_key, action_id = data.split("_")
        loc = LOCATIONS[loc_key]
        action = next(a for a in loc["actions"] if a["id"] == action_id)
        # Обработка действия
        result = await process_action(user_id, action, user_data)
        if result.get("combat"):
            # Переход в бой
            enemy = result["enemy"]
            context.user_data["combat_data"] = {"enemy": enemy, "loc_key": loc_key}
            await query.edit_message_text(
                f"⚔️ *ВСТУПЛЕНИЕ В БОЙ*\nПротивник: {enemy['name']}\nЗдоровье: {enemy['health']}\n\n{result['text']}",
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
            await show_location_actions(query.message, loc_key, user_data)
            return LOCATION_MENU

    elif data == "combat_attack":
        # Логика боя
        combat_data = context.user_data.get("combat_data")
        if not combat_data:
            await query.edit_message_text("Ошибка боя. Возврат в меню.")
            await show_main_menu(query.message, user_data)
            return GAME_MAIN
        enemy = combat_data["enemy"]
        # Рассчёт урона
        player_damage = random.randint(10, 25)
        enemy["health"] -= player_damage
        result_text = f"Вы нанесли {player_damage} урона. У противника осталось {max(0, enemy['health'])} здоровья.\n"
        if enemy["health"] <= 0:
            # Победа
            reward = REWARDS.get(enemy.get("reward", "default"), {})
            user_data["resources"]["ammo"] += reward.get("ammo", 0)
            user_data["resources"]["food"] += reward.get("food", 0)
            user_data["score"] += reward.get("score", 10)
            result_text += f"✅ Победа! Вы получили: {reward.get('score',10)} очков."
            await query.edit_message_text(result_text, parse_mode="Markdown")
            # Возврат к локации
            await show_location_actions(query.message, combat_data["loc_key"], user_data)
            del context.user_data["combat_data"]
            return LOCATION_MENU
        else:
            # Ответный удар
            enemy_damage = random.randint(5, 20)
            user_data["health"] -= enemy_damage
            result_text += f"Противник атакует: -{enemy_damage} здоровья. У вас осталось {user_data['health']} HP.\n"
            if user_data["health"] <= 0:
                result_text += "💀 Вы погибли... Игра окончена. Начните заново /start."
                await query.edit_message_text(result_text, parse_mode="Markdown")
                return ConversationHandler.END
            # Продолжаем бой
            await query.edit_message_text(
                result_text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔫 Атаковать", callback_data="combat_attack")],
                    [InlineKeyboardButton("💊 Лечиться", callback_data="combat_heal")],
                    [InlineKeyboardButton("🏃 Отступить", callback_data="combat_flee")]
                ])
            )
            return COMBAT

    elif data == "combat_heal":
        if user_data["resources"]["medkits"] > 0:
            heal = random.randint(15, 40)
            user_data["health"] = min(100, user_data["health"] + heal)
            user_data["resources"]["medkits"] -= 1
            await query.edit_message_text(
                f"💉 Вы использовали аптечку. +{heal} HP. Осталось аптечек: {user_data['resources']['medkits']}.",
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

    elif data == "combat_flee":
        success = random.random() < 0.5
        if success:
            await query.edit_message_text("🏃 Вы успешно отступили.", parse_mode="Markdown")
            await show_location_actions(query.message, context.user_data["combat_data"]["loc_key"], user_data)
            del context.user_data["combat_data"]
            return LOCATION_MENU
        else:
            await query.edit_message_text("Не удалось отступить! Противник атакует.", parse_mode="Markdown")
            # Повторяем ход врага
            combat_data = context.user_data["combat_data"]
            enemy = combat_data["enemy"]
            enemy_damage = random.randint(5, 20)
            user_data["health"] -= enemy_damage
            if user_data["health"] <= 0:
                await query.edit_message_text(f"💀 Вы погибли... Игра окончена. /start", parse_mode="Markdown")
                return ConversationHandler.END
            await query.edit_message_text(
                f"Противник нанёс {enemy_damage} урона. У вас {user_data['health']} HP.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔫 Атаковать", callback_data="combat_attack")],
                    [InlineKeyboardButton("💊 Лечиться", callback_data="combat_heal")],
                    [InlineKeyboardButton("🏃 Отступить", callback_data="combat_flee")]
                ])
            )
            return COMBAT

    return GAME_MAIN

async def show_main_menu(message, user_data):
    side = user_data["side"]
    health = user_data["health"]
    morale = user_data["morale"]
    res = user_data["resources"]
    text = (
        f"🎮 *Главное меню*\n"
        f"Сторона: {SIDES[side]['name']}\n"
        f"❤️ Здоровье: {health} | 💪 Мораль: {morale}\n"
        f"🍞 Еда: {res['food']} | 🔫 Патроны: {res['ammo']} | 💊 Аптечки: {res['medkits']}\n\n"
        f"Выберите действие:"
    )
    keyboard = [
        [InlineKeyboardButton("🗺️ Локации", callback_data="locations_menu")],
        [InlineKeyboardButton("📦 Инвентарь", callback_data="inventory")],
        [InlineKeyboardButton("📜 События", callback_data="events_list")],
        [InlineKeyboardButton("🏁 Завершить игру", callback_data="end_game")]
    ]
    await message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def show_location_actions(message, loc_key, user_data):
    loc = LOCATIONS[loc_key]
    keyboard = []
    for action in loc["actions"]:
        keyboard.append([InlineKeyboardButton(action["name"], callback_data=f"do_{loc_key}_{action['id']}")])
    keyboard.append([InlineKeyboardButton("◀️ Назад в меню", callback_data="main_menu")])
    await message.reply_text(
        f"*{loc['name']}* – доступные действия:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def process_action(user_id, action, user_data):
    # Здесь можно реализовать логику каждого действия
    # Пример для действия "Патруль" – случайная встреча с врагом
    if action["id"] == "patrol":
        # Шанс встретить противника
        if random.random() < 0.4:
            enemy = random.choice(ENEMIES)
            return {"combat": True, "enemy": enemy.copy(), "text": "Вы наткнулись на вражеский патруль!"}
        else:
            # Награда
            gain = random.randint(5, 15)
            user_data["resources"]["ammo"] += gain
            return {"text": f"✅ Патрулирование прошло успешно. Найдено {gain} патронов."}
    elif action["id"] == "assault_sbu":
        # Штурм СБУ – сложный бой
        enemy = next(e for e in ENEMIES if e["name"] == "Оборона СБУ")
        return {"combat": True, "enemy": enemy.copy(), "text": "Начался штурм здания СБУ!"}
    # ... другие действия
    else:
        return {"text": "Действие в разработке."}

# ---------- Запуск ----------
def main():
    TOKEN = "8619745303:AAHsEWaPKdPSbenRO7dzVCrDvxUIm0CzDu0"
    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHRONOLOGY_VIEW: [CallbackQueryHandler(button_handler)],
            SELECT_SIDE: [CallbackQueryHandler(button_handler)],
            GAME_MAIN: [CallbackQueryHandler(button_handler)],
            COMBAT: [CallbackQueryHandler(button_handler)],
            LOCATION_MENU: [CallbackQueryHandler(button_handler)],
        },
        fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)]
    )
    app.add_handler(conv_handler)
    app.run_polling()

if __name__ == "__main__":
    main()
