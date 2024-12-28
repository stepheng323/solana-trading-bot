import os
from dotenv import load_dotenv
from pyrogram import Client

load_dotenv()

API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
WORKDIR = "sessions" 

if not API_ID or not API_HASH:
    raise ValueError("TELEGRAM_API_ID or TELEGRAM_API_HASH is missing in your .env file.")

async def create_sessions():
    while True:
        session_name = input('Enter a name for the session (press Enter to exit):\n')
        if not session_name:
            return

        session = Client(
            name=session_name,
            api_id=API_ID,
            api_hash=API_HASH,
            workdir=WORKDIR,
            device_model='Samsung SM-G998B',
            system_version='SDK 31',
            app_version='11.5.3 (5511)'
        )

        async with session:
            user_data = await session.get_me()

        print(f'Session created successfully! +{user_data.phone_number} @{user_data.username}')

if __name__ == "__main__":
    import asyncio
    asyncio.run(create_sessions())
