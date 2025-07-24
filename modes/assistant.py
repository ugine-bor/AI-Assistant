import os
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import CommandStart, Command
from openai import AsyncOpenAI
from dotenv import load_dotenv

# --- Загрузка переменных окружения ---
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ASSISTANT_ID = os.getenv("OPENAI_ASSIST_TOKEN")

if not all([BOT_TOKEN, OPENAI_API_KEY, ASSISTANT_ID]):
    print("⚠️  Missing required environment variables! Check your .env file.")
    exit()

# --- Инициализация клиентов ---
client = AsyncOpenAI(api_key=OPENAI_API_KEY)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Словарь для хранения ID тредов для каждого пользователя
# {user_id: thread_id}
USER_THREADS = {}


# --- Функции для работы с тредами ---

async def get_or_create_thread(user_id: int) -> str:
    """Получает ID треда для пользователя или создает новый, если его нет."""
    if user_id not in USER_THREADS:
        try:
            thread = await client.beta.threads.create()
            USER_THREADS[user_id] = thread.id
            print(f"✨ Created new thread {thread.id} for user {user_id}")
            return thread.id
        except Exception as e:
            print(f"❌ Error creating thread for user {user_id}: {e}")
            return None
    return USER_THREADS[user_id]


async def reset_thread_for_user(user_id: int):
    """
    Удаляет тред пользователя как локально, так и на серверах OpenAI.
    """
    if user_id in USER_THREADS:
        thread_id_to_delete = USER_THREADS[user_id]
        del USER_THREADS[user_id]
        try:
            # Отправляем запрос в API на удаление треда
            await client.beta.threads.delete(thread_id=thread_id_to_delete)
            print(f"🗑️ Thread {thread_id_to_delete} for user {user_id} has been deleted on OpenAI.")
            return True
        except Exception as e:
            # Ошибка может возникнуть, если тред уже удален или недействителен
            print(f"⚠️ Could not delete thread {thread_id_to_delete} on OpenAI: {e}")
            return False
    return False


# --- Обработчики сообщений ---

@dp.message(CommandStart())
async def handle_start(message: Message):
    """Обработчик команды /start."""
    await message.answer(
        "Привет! Я ваш ассистент. Просто напишите мне что-нибудь. \nДля сброса диалога используйте команду /reset")


@dp.message(Command("reset"))
async def handle_reset(message: Message):
    """Обработчик команды /reset."""
    user_id = message.from_user.id
    if await reset_thread_for_user(user_id):
        await message.answer("✅ Контекст диалога сброшен. Можем начать сначала!")
    else:
        await message.answer("ℹ️ У вас не было активного диалога. Просто начните писать!")


@dp.message(F.text)
async def process_message(message: Message, bot: Bot):
    """Обрабатывает все текстовые сообщения от пользователя."""
    user_id = message.from_user.id

    # Получаем или создаем тред
    thread_id = await get_or_create_thread(user_id)
    if not thread_id:
        await message.answer("🚫 Не удалось создать сессию для диалога. Попробуйте позже.")
        return

    # Отправляем сообщение в тред
    try:
        await client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=message.text
        )

        # Запускаем ассистента
        run = await client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=ASSISTANT_ID
        )

        # Ожидаем завершения работы
        while run.status in ["queued", "in_progress"]:
            await asyncio.sleep(1)  # Делаем задержку чуть больше
            run = await client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run.id
            )

        if run.status == "failed":
            print(f"❌ Execution error: {run.last_error.message if run.last_error else 'Unknown error'}")
            await message.answer("🚫 Произошла ошибка при обработке вашего запроса. Попробуйте /reset")
            return

        # Получаем ответ
        messages = await client.beta.threads.messages.list(
            thread_id=thread_id,
            order="desc",
            limit=1  # Нам нужен только последний ответ ассистента
        )

        if messages.data and messages.data[0].content:
            response = messages.data[0].content[0].text.value
            await message.answer(response, parse_mode=None)
        else:
            await message.answer("🤔 Ассистент не дал ответа.")

    except Exception as e:
        print(f"❌ Request error for user {user_id}: {e}")
        await message.answer("🚫 Произошла критическая ошибка. Пожалуйста, попробуйте сбросить диалог командой /reset")

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


async def main():
    """Основная функция для запуска бота."""
    try:
        assistant = await client.beta.assistants.retrieve(ASSISTANT_ID)
        print(f"🧠 Assistant loaded: {assistant.name} (Model: {assistant.model})")
    except Exception as e:
        print(f"❌ Initialization error: Could not retrieve assistant. {e}")
        return

    print("🚀 Bot is starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
