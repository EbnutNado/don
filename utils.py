import random

def combat(player, enemy):
    # Простая боевая механика (для примера)
    pass

def random_event():
    events = [
        "🎲 Обстрел города – вы ранены (-10 HP).",
        "🎲 Гуманитарная помощь – получена еда (+5 food).",
        "🎲 Перестрелка на блокпосту – потеряны патроны (-5 ammo)."
    ]
    return random.choice(events)
