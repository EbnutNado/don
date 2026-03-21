import sqlite3
import json
from contextlib import closing

DB_PATH = 'game.db'

def init_db():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS players (
                user_id INTEGER PRIMARY KEY,
                side TEXT,
                health INTEGER,
                morale INTEGER,
                resources TEXT,
                location TEXT,
                completed_events TEXT,
                score INTEGER,
                achievements TEXT
            )
        ''')
        conn.commit()

def load_player(user_id):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute('SELECT * FROM players WHERE user_id = ?', (user_id,))
        row = cur.fetchone()
        if row:
            return dict(row)
        return None

def save_player(user_id, data):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute('''
            INSERT OR REPLACE INTO players
            (user_id, side, health, morale, resources, location, completed_events, score, achievements)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            data['side'],
            data['health'],
            data['morale'],
            json.dumps(data['resources']),
            data['location'],
            json.dumps(data['completed_events']),
            data['score'],
            json.dumps(data.get('achievements', []))
        ))
        conn.commit()

def delete_player(user_id):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute('DELETE FROM players WHERE user_id = ?', (user_id,))
        conn.commit()
