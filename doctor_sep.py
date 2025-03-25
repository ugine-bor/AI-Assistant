import os
import json
import logging
from pathlib import Path
import asyncio

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

# Конфигурация
API_TOKEN = os.getenv("DOCTOR_SEP_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
QUESTIONNAIRE_FILE = Path(os.getenv("DOCTOR_QUESTIONS"))

client = AsyncOpenAI(api_key=OPENAI_KEY)


# Определяем состояния опроса
class InterviewState(StatesGroup):
    ACTIVE = State()


# Функция загрузки опросника из файла
async def load_questionnaire() -> list:
    questions = []
    with open(QUESTIONNAIRE_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            questions.append(json.loads(line))
    return questions


# Обработчик команды /start – запуск интервью
async def start_interview_handler(message: types.Message, state: FSMContext):
    questionnaire = await load_questionnaire()
    if not questionnaire:
        await message.answer("Опросник пуст.")
        return

    await state.clear()
    first_question = questionnaire[0]['question']
    await message.answer(f"Answer:\n{first_question}")
    await state.update_data(
        current_step=0,
        history=[{"role": "assistant", "content": first_question}],
        awaiting_reply=True,
        answers=[]
    )


# Обработчик входящих сообщений во время опроса
async def process_message_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if 'current_step' not in data:
        await message.answer("Пожалуйста, начните опрос командой /start")
        return

    current_step = data.get('current_step', 0)
    questionnaire = await load_questionnaire()

    if current_step >= len(questionnaire):
        await finish_interview(message, state)
        return

    if data.get('awaiting_reply', False):
        history = data.get('history', []) + [{"role": "user", "content": message.text}]
        await state.update_data(history=history)
        await validate_answer(message, state, questionnaire[current_step])


# Функция для отправки очередного вопроса (при необходимости)
async def ask_question(message: types.Message, state: FSMContext, question_data: dict):
    question_text = f"mode4:\n{question_data['question']}"
    await message.answer(question_text)
    history = (await state.get_data()).get('history', []) + [{"role": "assistant", "content": question_text}]
    await state.update_data(
        history=history,
        awaiting_reply=True
    )


# Функция проверки ответа через OpenAI
async def validate_answer(message: types.Message, state: FSMContext, question_data: dict):
    data = await state.get_data()
    history = data.get('history', [])
    current_step = data.get('current_step', 0)

    dialog_history = "\n".join(
        f"{msg['role']}: {msg['content']}"
        for msg in history
        if msg['role'] in ['user', 'assistant']
    )

    system_msg = {
        "role": "system",
        "content": f"""You are a medical assistant. Analyze the ENTIRE previous dialog:

Current question: {question_data['question']}
Required information(if present): {question_data.get('context', '')}

Full dialog:
{dialog_history}

1. Check if data is absurd or logically incorrect, ask again.
2. Check that all needed information is present in the dialog or can be interpreted from user input.
3. Respond with "STEP_COMPLETE" if ALL criteria are met.
4. If data is missing, take it as "no" or ask for clarification.
5. Always Respond in Russian."""
    }

    messages = [system_msg]

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.5,
        max_tokens=200
    )

    assessment = response.choices[0].message.content.strip()
    print('msg', system_msg)
    print('response:', response)

    if assessment == "STEP_COMPLETE":
        await process_valid_answer(message, state)
    else:
        clarification = assessment if assessment else "Пожалуйста, уточните ваш ответ"
        await message.answer(f"check:\n{clarification}")
        new_history = history + [
            {"role": "user", "content": message.text},
            {"role": "assistant", "content": clarification}
        ]
        await state.update_data(
            history=new_history,
            awaiting_reply=True
        )


# Функция обработки корректного ответа
async def process_valid_answer(message: types.Message, state: FSMContext):
    data = await state.get_data()
    questionnaire = await load_questionnaire()
    current_step = data.get('current_step', 0)
    history = data.get('history', [])
    user_answers = [msg for msg in history if msg['role'] == 'user']
    last_answer = user_answers[-1]['content'] if user_answers else ""
    answers = data.get('answers', [])
    answers.append({
        "question": questionnaire[current_step]['question'],
        "answer": last_answer
    })
    await state.update_data(answers=answers)

    new_step = current_step + 1
    if new_step >= len(questionnaire):
        await finish_interview(message, state)
        return

    next_question_data = questionnaire[new_step]
    await message.answer(f"Answer:\n{next_question_data['question']}")
    new_history = history + [{"role": "assistant", "content": next_question_data['question']}]
    await state.update_data(
        current_step=new_step,
        history=new_history,
        awaiting_reply=True
    )


# Генерация итогового медицинского отчёта через OpenAI
async def generate_medical_report(answers: list) -> str:
    try:
        answers_text = "\n".join(
            [f"Вопрос: {item['question']}\nОтвет: {item['answer']}" for item in answers]
        )
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": """Вы опытный врач-терапевт. На основании предоставленных ответов пациента:
1. Составьте официальный медицинский документ
2. Укажите жалобы и симптомы
3. Предположите возможные диагнозы
4. Составьте рекомендации по обследованиям
5. Предложите варианты лечения
Оформите ответ на русском языке в структурированном виде"""
                },
                {
                    "role": "user",
                    "content": f"Ответы пациента:\n{answers_text}"
                }
            ],
            temperature=0.3,
            max_tokens=1500
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Ошибка генерации отчета: {e}")
        return "Не удалось сформировать медицинский отчет"


# Завершение интервью – отправка итогового отчёта
async def finish_interview(message: types.Message, state: FSMContext):
    data = await state.get_data()
    answers = data.get('answers', [])
    report = await generate_medical_report(answers)
    await message.answer("Answer:\n✅ Опрос завершен! Спасибо!")
    formatted_report = f"🩺   Медицинское заключение:\n\n{report}"
    await message.answer(formatted_report)
    await state.clear()


# Главная функция и регистрация хендлеров
async def main():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=API_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    dp.message.register(start_interview_handler, Command(commands=["start"]))
    dp.message.register(process_message_handler, lambda message: message.text is not None)

    async def on_startup():
        print("Бот запущен")

    dp.startup.register(on_startup)

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == '__main__':
    asyncio.run(main())
