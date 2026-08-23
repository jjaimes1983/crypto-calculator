"""Run this once (or anytime) to create the SQLite tables if they don't exist yet.

    python -m backend.init_db
"""
from .database import engine, Base
from . import models  # noqa: F401  (import so models register on Base.metadata)


def init_db():
    Base.metadata.create_all(bind=engine)
    print(f"Tables created (or already existed) in {engine.url}")


if __name__ == "__main__":
    init_db()
