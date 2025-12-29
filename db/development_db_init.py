
import psycopg
from dotenv import load_dotenv
import os

load_dotenv()
from api.graph.get_users import get_users_with_name_and_email



db_url = os.getenv("DEVELOPMENT_DB_URL")

def upsert_users(users):
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        
        # Upsert users
        with conn.cursor() as cur:
            for user in users:
                cur.execute("""
                    INSERT INTO users (name, email)
                    VALUES (%s, %s)
                    ON CONFLICT (email)
                    DO UPDATE SET
                        name = EXCLUDED.name,
                        updated_at = CURRENT_TIMESTAMP
                """, (user['name'], user['email']))
        
        conn.commit()

users_ds = get_users_with_name_and_email()

print(users_ds)