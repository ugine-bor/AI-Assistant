import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from dotenv import load_dotenv

from modes import assistant, faq, newsmanager, doctor, assistant_2, audio_to_text

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# (1 - режим FAQ, 2 - режим Assistant, 3 - режим поиска новостей)
user_modes = {}


# Команды для переключения режимов
@dp.message(Command("mode1"))
async def switch_to_mode1(message: types.Message):
    user_id = message.from_user.id
    user_modes[user_id] = 1
    await message.answer("✅ Активирован режим FAQ-помощника")


@dp.message(Command("mode2"))
async def switch_to_mode2(message: types.Message):
    user_id = message.from_user.id
    await assistant.reset_thread_for_user(user_id)
    user_modes[user_id] = 2
    await message.answer("✅ Активирован режим AI-ассистента")


@dp.message(Command("mode3"))
async def switch_to_mode3(message: types.Message):
    user_id = message.from_user.id
    user_modes[user_id] = 3
    await message.answer(f'''✅ Активирован режим поиска новостей
Отправьте номер новостной страницы или url любого новостного сайта, за сколько дней искать статьи, и темы для поиска:
     1 - `{os.getenv('ODINC')[8:-6]}`
     2 - `{os.getenv('UCHET')[8:-6]}`
     3 - `{os.getenv('PRO1C')[8:-6]}`
     4 - `{os.getenv('MYBUH')[8:-6]}`
     5 - `{os.getenv('GOS24')[8:-1]}`
     6 - `{os.getenv('KGD')[8:-1]}` (Вместо тем перечислите коды ФНО)

Пример запроса:
1, 10, Бухгалтерия, Обучающие курсы, Обновление

Результат:
краткая сводка новостей по темам 'Бухгалтерия', 'Обучающие курсы' или 'Обновление' за последние 30 дней с сайта `{os.getenv('ODINC')[8:-6]}`

Другие примеры запросов:
pro1c.kz, 3, Новая версия, Отчёт
6, 10.01.2024 - 17.04.2025, 200, 700.00, 701.00, 701.01, 870, 910, 100
uchet.kz, Продукты

Для поиска новостей в видео введите ссылку и темы также через запятую.
Пример запроса: https://www.youtube.com/watch?v=xxxxxx, Бухгалтерия, Обучающие курсы, Обновление''',
                         disable_web_page_preview=True)


@dp.message(Command("mode4"))
async def switch_to_mode4(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_modes[user_id] = 4
    await message.answer("✅ Активирован режим AI-терапевта")
    await doctor.start_interview(message.chat.id, bot, state)


@dp.message(Command("mode5"))
async def switch_to_mode5(message: types.Message):
    user_id = message.from_user.id
    user_modes[user_id] = 5
    await message.answer("✅ Активирован режим AI-ассистента от GOOGLE")


@dp.message(Command("mode6"))
async def switch_to_mode6(message: types.Message):
    user_id = message.from_user.id
    user_modes[user_id] = 6
    await message.answer("✅ Активирован режим аудио-транскрипции (Whisper)")

# Общий обработчик сообщений, делегирующий их в соответствующий режим
@dp.message()
async def handle_message(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    print(f"Получено сообщение от {user_id}: {message.text}")
    mode = user_modes.get(user_id, 1)  # По умолчанию режим FAQ (1)

    if mode == 1:
        await faq.process_message(message, bot)
    elif mode == 2:
        await assistant.process_message(message, bot)
    elif mode == 3:
        await newsmanager.process_message(message, bot)
    elif mode == 4:
        await doctor.process_message(message, state)
    elif mode == 5:
        await assistant_2.process_message(message, bot)
    elif mode == 6:
        await audio_to_text.process_message(message, bot)


async def main():
    await assistant.initialize_assistant()
    print("Бот запущен...")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
