import os
import psycopg2
from datetime import datetime

# ───────────────── helpers ──────────────────
def get_connection():
    return psycopg2.connect(
        dbname=os.getenv("PGDATABASE"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        host=os.getenv("PGHOST"),
        port=os.getenv("PGPORT"),
        sslmode="require"
    )

# ───────────────── schema ──────────────────
def ensure_table_exists():
    with get_connection() as conn:
        with conn.cursor() as cur:
            # таблица клуб-правил
            cur.execute("""
                CREATE TABLE IF NOT EXISTS communities (
                    chat_id      BIGINT PRIMARY KEY,
                    filter_type  TEXT   NOT NULL DEFAULT 'model',   -- model | slug | collection
                    filter_value TEXT   NOT NULL DEFAULT 'Knockdown',
                    min_gifts    INT    NOT NULL DEFAULT 6,
                    created_at   TIMESTAMP DEFAULT now()
                )
            """)
            # таблица одобренных участников (chat_id + user_id — PK)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS approved_users (
                    chat_id           BIGINT,
                    user_id           BIGINT,
                    username          TEXT,
                    approved_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    gift_count        INT,
                    invite_link       TEXT,
                    invite_created_at TIMESTAMP,
                    PRIMARY KEY (chat_id, user_id)
                )
            """)
            conn.commit()

# ───────────────── communities ──────────────────
def get_community_rule(chat_id: int) -> dict:
    """
    Возвращает словарь правила для указанного чата.
    Если клуб в таблице отсутствует — fallback к классическому
    'Knockdown ≥ 6', чтобы старый бот не сломался.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT filter_type, filter_value, min_gifts
                FROM communities
                WHERE chat_id = %s
            """, (chat_id,))
            row = cur.fetchone()
            if row:
                return {
                    "filter_type":  row[0],
                    "filter_value": row[1],
                    "min_gifts":    row[2]
                }
            # дефолт для «старого» клуба
            return {
                "filter_type":  "model",
                "filter_value": "Knockdown",
                "min_gifts":    6
            }

# ───────────────── approved_users helpers ──────────────────
def is_approved(chat_id: int, user_id: int) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 1 FROM approved_users
                WHERE chat_id = %s AND user_id = %s
            """, (chat_id, user_id))
            return cur.fetchone() is not None

def get_approved_user(chat_id: int, user_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT username, gift_count, invite_link, invite_created_at
                FROM approved_users
                WHERE chat_id = %s AND user_id = %s
            """, (chat_id, user_id))
            return cur.fetchone()

def save_approved(chat_id: int, user_id: int, username: str,
                  gift_count: int, invite_link: str):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO approved_users
                      (chat_id, user_id, username, gift_count,
                       invite_link, invite_created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (chat_id, user_id) DO UPDATE SET
                    username          = EXCLUDED.username,
                    gift_count        = EXCLUDED.gift_count,
                    invite_link       = EXCLUDED.invite_link,
                    invite_created_at = EXCLUDED.invite_created_at
            """, (
                chat_id, user_id, username, gift_count,
                invite_link, datetime.utcnow()
            ))
            conn.commit()