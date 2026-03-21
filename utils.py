import random
from events import WEAPONS, ENEMIES

def calculate_damage(weapon_key):
    w = WEAPONS.get(weapon_key, WEAPONS["pistol"])
    return random.randint(w["damage_min"], w["damage_max"])

def combat(player_weapon, enemy_key, player_health, enemy_health, player_ammo):
    """Возвращает (new_player_health, new_enemy_health, player_ammo, log, win)"""
    enemy = ENEMIES[enemy_key]
    log = []

    # Ход игрока
    hit = random.random() <= WEAPONS[player_weapon]["accuracy"]
    if hit:
        dmg = calculate_damage(player_weapon)
        enemy_health -= dmg
        log.append(f"🔫 Вы нанесли {dmg} урона. У {enemy['name']} осталось {max(0, enemy_health)} HP.")
    else:
        log.append("❌ Вы промахнулись!")

    if enemy_health <= 0:
        return player_health, 0, player_ammo, log, True

    # Ход врага
    enemy_dmg = random.randint(max(1, enemy["damage"]-5), enemy["damage"]+5)
    player_health -= enemy_dmg
    log.append(f"💥 {enemy['name']} атакует и наносит {enemy_dmg} урона. У вас {max(0, player_health)} HP.")

    if player_health <= 0:
        return 0, enemy_health, player_ammo, log, False

    return player_health, enemy_health, player_ammo, log, None

def random_event():
    events = [
        ("🎲 Обстрел города – вы ранены", -15, "health"),
        ("🎲 Гуманитарная помощь – получена еда", +10, "food"),
        ("🎲 Перестрелка на блокпосту – потеряны патроны", -10, "ammo"),
        ("🎲 Нашли тайник с боеприпасами", +20, "ammo"),
        ("🎲 Местные жители делятся едой", +8, "food"),
        ("🎲 Провокация – снижение морали", -10, "morale"),
        ("🎲 Успешная операция – повышение морали", +15, "morale")
    ]
    desc, delta, resource = random.choice(events)
    return desc, delta, resource
