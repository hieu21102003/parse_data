# db/session.py

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine import URL

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 5432))
DB_NAME = os.getenv("DB_NAME", "standards_ai")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")

DATABASE_URL = URL.create(
    drivername="postgresql+psycopg",
    username=DB_USER,
    password=DB_PASSWORD,
    host=DB_HOST,
    port=DB_PORT,
    database=DB_NAME,
)

engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


def get_session():
    """
    Dependency dùng cho FastAPI sau này
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_connection():
    """
    Chạy file này trực tiếp để test DB
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version();"))
            print("✅ PostgreSQL connected:")
            print(result.fetchone()[0])
    except Exception as e:
        print("❌ Connection failed:", e)


if __name__ == "__main__":
    test_connection()
