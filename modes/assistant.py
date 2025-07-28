import asyncio
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import Command
from openai import AsyncOpenAI

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DIR_FILES = "static/files"
MODEL_NAME = "gpt-4o-mini"

with open("static/prompt1.txt", 'r', encoding="utf-8") as fil:
    system_prompt = fil.read()
SYSTEM_PROMPT = system_prompt

client = AsyncOpenAI(api_key=OPENAI_API_KEY)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

USER_LAST_RESPONSE_ID = {}
VECTOR_STORE_ID = None

async def initialize_assistant():
    global VECTOR_STORE_ID
    if VECTOR_STORE_ID is not None:
        return
    vector_store = await client.vector_stores.create(name="Support Documents")
    VECTOR_STORE_ID = vector_store.id
    for file_name in os.listdir(DIR_FILES):
        file_path = os.path.join(DIR_FILES, file_name)
        if os.path.isfile(file_path):
            with open(file_path, "rb") as f:
                await client.vector_stores.file_batches.upload_and_poll(
                    vector_store_id=VECTOR_STORE_ID,
                    files=[f]
                )

def reset_user_context(user_id: int) -> None:
    USER_LAST_RESPONSE_ID.pop(user_id, None)

@dp.message(Command("reset"))
async def cmd_reset(message: Message):
    reset_user_context(message.from_user.id)
    await message.answer("🔄 Контекст диалога сброшен. Можем начинать заново!")

@dp.message(F.text & ~F.text.startswith("/"))
async def process_message(message: Message, bot: Bot):
    user_id = message.from_user.id
    user_input = message.text
    if VECTOR_STORE_ID is None:
        await message.answer("🚫 Поиск по файлу временно недоступен.")
        return
    previous_id = USER_LAST_RESPONSE_ID.get(user_id)
    try:
        await bot.send_chat_action(chat_id=user_id, action="typing")
        if previous_id:
            response = await client.responses.create(
                model=MODEL_NAME,
                instructions=SYSTEM_PROMPT,
                input=user_input,
                tools=[{
                    "type": "file_search",
                    "vector_store_ids": [VECTOR_STORE_ID],
                    "max_num_results": 10
                }],
                previous_response_id=previous_id
            )
        else:
            response = await client.responses.create(
                model=MODEL_NAME,
                instructions=SYSTEM_PROMPT,
                input=user_input,
                tools=[{
                    "type": "file_search",
                    "vector_store_ids": [VECTOR_STORE_ID],
                    "max_num_results": 10
                }]
            )
        USER_LAST_RESPONSE_ID[user_id] = response.id
        await message.answer(response.output_text, parse_mode=None)
    except Exception as err:
        await message.answer(f"🚫 Произошла ошибка. Попробуйте команду /reset. [{str(err)}]")

dp.startup.register(initialize_assistant)
