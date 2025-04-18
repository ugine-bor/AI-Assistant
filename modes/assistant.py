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
DEFAULT_FILE = "knowledge.txt"


async def update_assistant_files(file_ids):
    try:
        vector_store = await client.beta.vector_stores.create(
            name="Knowledge Base",
            file_ids=file_ids
        )

        await client.beta.assistants.update(
            ASSISTANT_ID,
            tools=[{"type": "file_search"}],
            tool_resources={
                "file_search": {
                    "vector_store_ids": [vector_store.id]
                }
            }
        )
        print("✅ Assistant files updated")
    except Exception as e:
        print(f"❌ Error updating assistant: {e}")


async def upload_file(filepath):
    try:
        with open(filepath, "rb") as f:
            file = await client.files.create(file=f, purpose="assistants")
            return file.id
    except Exception as e:
        print(f"❌ File upload error: {e}")
        return None


async def initialize_assistant():
    try:
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
    if message.text.startswith("/update"):
        file_id = await upload_file(DEFAULT_FILE)
        if file_id:
            await update_assistant_files([file_id])
            await message.answer("✅ Knowledge base updated!")
        return

    elif message.content_type == ContentType.DOCUMENT:
        doc = message.document
        file_path = DEFAULT_FILE
        file = await bot.get_file(doc.file_id)
        await bot.download_file(file.file_path, destination=file_path)

        file_id = await upload_file(file_path)
        if file_id:
            await update_assistant_files([file_id])
            await message.answer("✅ File uploaded and applied!")
        return

    # Process text queries
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
        await message.answer('mode2:\n' + response)

    except Exception as e:
        print(f"❌ Request error: {e}")
        await message.answer("🚫 Failed to retrieve response")

