import asyncio
from config.settings import validate
from src.db import init_db
from src.bot import run_bot

if __name__ == "__main__":
    validate()
    init_db()
    asyncio.set_event_loop(asyncio.new_event_loop())
    run_bot()
