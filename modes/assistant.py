import os
import asyncio
from aiogram.types import Message
from aiogram.enums import ContentType
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY").strip()
ASSISTANT_ID = os.getenv("OPENAI_ASSIST_TOKEN").strip()

if not all([BOT_TOKEN, OPENAI_API_KEY, ASSISTANT_ID]):
    print("⚠️ Missing required environment variables!")
    exit()

client = AsyncOpenAI(api_key=OPENAI_API_KEY)
USER_THREADS = {}


async def reset_thread_for_user(user_id: int):
    if user_id in USER_THREADS:
        del USER_THREADS[user_id]
        print(f"🗑️ Thread for user {user_id} has been reset.")

async def initialize_assistant():
    try:
        global USER_THREADS
        USER_THREADS = {}
        assistant = await client.beta.assistants.retrieve(ASSISTANT_ID)
        print(f"🧠 Assistant ready: {assistant.name} (Model: {assistant.model})")

        if any(tool.type == "file_search" for tool in assistant.tools):
            print("📁 Assistant supports file search")
        else:
            print("⚠️ Assistant does not support file search")

        return assistant
    except Exception as e:
        print(f"❌ Initialization error: {e}")
        return None


async def get_thread(user_id):
    if user_id not in USER_THREADS:
        thread = await client.beta.threads.create()
        USER_THREADS[user_id] = thread.id
    return USER_THREADS[user_id]


async def process_message(message: Message, bot):
    if message.text.startswith("reset"):
        await reset_thread_for_user(message.from_user.id)

    thread_id = await get_thread(message.from_user.id)

    try:
        await client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=message.text
        )

        run = await client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=ASSISTANT_ID
        )

        while run.status not in ["completed", "failed"]:
            await asyncio.sleep(0.5)
            run = await client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run.id
            )

        if run.status == "failed":
            print(f"❌ Execution error: {run.last_error}")
            await message.answer("🚫 Error processing request")
            return

        messages = await client.beta.threads.messages.list(
            thread_id=thread_id,
            order="desc"
        )

        response = messages.data[0].content[0].text.value
        await message.answer('mode2:\n' + response, parse_mode=None)

    except Exception as e:
        print(f"❌ Request error: {e}")
        await message.answer("🚫 Failed to retrieve response")
