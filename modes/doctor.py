import json
import os
from pathlib import Path
from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

# Конфигурация
API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
QUESTIONNAIRE_FILE = Path(os.getenv("DOCTOR_QUESTIONS"))
client = AsyncOpenAI(api_key=OPENAI_KEY)


class InterviewState(StatesGroup):
    ACTIVE = State()


async def load_questionnaire() -> list[dict]:
    questions = []
    with open(QUESTIONNAIRE_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            questions.append(json.loads(line))
    return questions


async def start_interview(chat_id: int, bot: Bot, state: FSMContext):
    questionnaire = await load_questionnaire()
    if not questionnaire:
        await bot.send_message(chat_id, "Опросник пуст.")
        return

    await state.clear()
    first_question = questionnaire[0]['question']
    await bot.send_message(chat_id, f"mode4:\n{first_question}")
    await state.update_data(
        current_step=0,
        history=[{"role": "assistant", "content": first_question}],
        awaiting_reply=True,
        bot_instance=bot,
        answers=[]  # Инициализируем хранилище ответов
    )


async def process_message(message: Message, state: FSMContext):  # Убрали bot из аргументов
    data = await state.get_data()
    bot = data.get('bot_instance')  # Получаем бота из состояния
    current_step = data.get('current_step', 0)
    questionnaire = await load_questionnaire()

    if current_step >= len(questionnaire):
        await finish_interview(message, state)
        return

    if data.get('awaiting_reply', False):
        history = data.get('history', []) + [{"role": "user", "content": message.text}]
        await state.update_data(history=history)
        await validate_answer(message, state, questionnaire[current_step])


async def ask_question(message: Message, bot: Bot, state: FSMContext, question_data: dict):
    question_text = f"mode4:\n{question_data['question']}"
    await bot.send_message(message.chat.id, question_text)

    # Обновляем историю
    history = (await state.get_data()).get('history', []) + [{"role": "assistant", "content": question_text}]
    await state.update_data(
        history=history,
        awaiting_reply=True
    )


async def validate_answer(message: Message, state: FSMContext, question_data: dict):
    data = await state.get_data()
    history = data.get('history', [])
    current_step = data['current_step']

    # Формируем полный контекст диалога
    dialog_history = "\n".join(
        f"{msg['role']}: {msg['content']}"
        for msg in history
        if msg['role'] in ['user', 'assistant']
    )

    system_msg = {
        "role": "system",
        "content": f"""You are a medical assistant. Analyze the ENTIRE previous dialog:

        Current question: {question_data['question']}
        Required information(if present): {question_data['context']}

        Full dialog:
        {dialog_history}

        1. Check that all needed information is present in the dialog or can be interpreted from user input.
        2. Respond with "STEP_COMPLETE" if ALL criteria are met.
        3. If data is missing, take it as "no" or ask for clarification.
        4. Always Respond in Russian."""
    }

    messages = [system_msg]

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.5,
        max_tokens=200
    )

    assessment = response.choices[0].message.content.strip()

    print('msg', system_msg, '\n', response, '\n', assessment)

    if assessment == "STEP_COMPLETE":
        await process_valid_answer(message, state)
    else:
        clarification = assessment if assessment else "Пожалуйста, уточните ваш ответ"
        await message.answer(f"mode4_val:\n{clarification}")

        # Обновляем историю с уточнением
        new_history = history + [
            {"role": "user", "content": message.text},
            {"role": "assistant", "content": clarification}
        ]
        await state.update_data(
            history=new_history,
            awaiting_reply=True
        )


async def process_valid_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    questionnaire = await load_questionnaire()
    current_step = data['current_step']

    # Сохраняем успешный ответ
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

    bot = data['bot_instance']
    next_question_data = questionnaire[new_step]

    await bot.send_message(
        chat_id=message.chat.id,
        text=f"mode4:\n{next_question_data['question']}"
    )

    new_history = history + [
        {"role": "assistant", "content": next_question_data['question']}
    ]

    await state.update_data(
        current_step=new_step,
        history=new_history,
        awaiting_reply=True
    )


async def generate_medical_report(answers: list[dict]) -> str:
    try:
        # Формируем текст с ответами для промпта
        answers_text = "\n".join(
            [f"Вопрос: {item['question']}\nОтвет: {item['answer']}" for item in answers]
        )

        # Создаем запрос к нейросети
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


async def finish_interview(message: Message, state: FSMContext):
    data = await state.get_data()
    answers = data.get('answers', [])

    # Генерируем и отправляем отчет
    report = await generate_medical_report(answers)
    await message.answer("mode4:\n✅ Опрос завершен! Спасибо!")
    formatted_report = f"🩺   Медицинское заключение:\n\n{report}"
    await message.answer(formatted_report)
    await state.clear()
