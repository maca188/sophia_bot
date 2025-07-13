import sqlite3
import random

def connect():
    return sqlite3.connect("cards.db")

def setup_db():
    with connect() as con:
        cur = con.cursor()

        # Updated cards table with is_event and excluded_from_drop
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                code TEXT PRIMARY KEY,
                member TEXT,
                group_name TEXT,
                rarity TEXT,
                era TEXT,
                image_url TEXT,
                is_event INTEGER DEFAULT 0,
                excluded_from_drop INTEGER DEFAULT 0
            )
        """)

        # Inventory table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                user_id TEXT,
                code TEXT,
                count INTEGER DEFAULT 1,
                PRIMARY KEY (user_id, code),
                FOREIGN KEY (code) REFERENCES cards(code)
            )
        """)

        # Katscoins table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS currency (
                user_id TEXT PRIMARY KEY,
                balance INTEGER DEFAULT 0
            )
        """)

def get_random_card():
    with connect() as con:
        cur = con.cursor()
        cur.execute("SELECT * FROM cards WHERE excluded_from_drop = 0")
        all_cards = cur.fetchall()

    weighted = []
    for card in all_cards:
        # Unpack card fields including is_event and excluded_from_drop
        code, member, group_name, rarity, era, image_url, is_event, excluded_from_drop = card

        if is_event:
            weight = 0.7
        else:
            if rarity == "⭐":
                weight = 40
            elif rarity == "⭐⭐":
                weight = 25
            elif rarity == "⭐⭐⭐":
                weight = 15
            elif rarity == "⭐⭐⭐⭐":
                weight = 10
            elif rarity == "⭐⭐⭐⭐⭐":
                weight = 1
            else:
                weight = 5

        weighted.extend([card] * int(weight * 10))

    if not weighted:
        return None

    return random.choice(weighted)

def give_card_to_user(user_id, code):
    with connect() as con:
        cur = con.cursor()
        cur.execute("SELECT count FROM inventory WHERE user_id = ? AND code = ?", (user_id, code))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE inventory SET count = count + 1 WHERE user_id = ? AND code = ?", (user_id, code))
        else:
            cur.execute("INSERT INTO inventory (user_id, code, count) VALUES (?, ?, 1)", (user_id, code))
        con.commit()

def get_user_inventory(user_id):
    with connect() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT c.code, c.member, c.group_name, c.rarity, c.era, c.image_url, i.count
            FROM inventory i
            JOIN cards c ON i.code = c.code
            WHERE i.user_id = ?
        """, (user_id,))
        return cur.fetchall()

def get_user_card_count(user_id: str, code: str) -> int:
    with connect() as con:
        cur = con.cursor()
        cur.execute("SELECT count FROM inventory WHERE user_id = ? AND code = ?", (user_id, code))
        row = cur.fetchone()
        return row[0] if row else 0

def get_card_by_code(code: str):
    with connect() as con:
        cur = con.cursor()
        cur.execute("SELECT * FROM cards WHERE code = ?", (code,))
        return cur.fetchone()
    

    

    
