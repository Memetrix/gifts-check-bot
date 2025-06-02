import os
import psycopg2
from datetime import datetime

def get_connection():
    return psycopg2.connect(
        dbname=os.getenv("PGDATABASE"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
        host=os.getenv("PGHOST"),
        port=os.getenv("PGPORT"),
        sslmode="require"
    )

def ensure_table_exists():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS approved_users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    approved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    gift_count INT,
                    invite_link TEXT,
                    invite_created_at TIMESTAMP
                )
            """)
            conn.commit()

def is_approved(user_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM approved_users WHERE user_id = %s", (user_id,))
            return cur.fetchone() is not None

def get_approved_user(user_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT username, gift_count, invite_link, invite_created_at
                FROM approved_users
                WHERE user_id = %s
            """, (user_id,))
            return cur.fetchone()

def save_approved(user_id, username, gift_count, invite_link):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO approved_users (user_id, username, gift_count, invite_link, invite_created_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    gift_count = EXCLUDED.gift_count,
                    invite_link = EXCLUDED.invite_link,
                    invite_created_at = EXCLUDED.invite_created_at
            """, (user_id, username, gift_count, invite_link, datetime.utcnow()))
            conn.commit()
