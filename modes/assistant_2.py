import os
import logging
import asyncio  # <--- Добавлен импорт asyncio
from aiogram.types import Message
from aiogram.enums import ContentType
from aiogram import Bot
from dotenv import load_dotenv
import google.generativeai as genai
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import aiofiles

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

genai.configure(api_key=GOOGLE_API_KEY)

# Используйте актуальные имена моделей. Gemini 1.5 модели хорошо подходят для мультимодальности.
GENERATION_MODEL_NAME = "gemini-1.5-flash-latest"
EMBEDDING_MODEL_NAME = "models/text-embedding-004"
AUDIO_TRANSCRIPTION_MODEL_NAME = "gemini-1.5-flash-latest"  # Для транскрипции

DATA_DIR = "static/knowledge_files"  # Папка с файлами знаний по умолчанию
MAX_RAG_CHUNKS = 3
CHUNK_SIZE = 512
CHUNK_OVERLAP = 100

# Глобальный флаг, который контролирует, загружена ли база знаний RAG
RAG_LOADED = False

RAG_DATA = {
    "chunks": [],
    "embeddings": None,
    "file_source": []  # Хранит имя файла-источника для каждого чанка
}
USER_CHAT_SESSIONS = {}  # Сессии чата для пользователей

# Настройка логирования
if not logging.getLogger().hasHandlers():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_text_chunks(text: str, filename: str = "generic"):
    """Разделяет текст на управляемые чанки с учетом границ предложений/абзацев и оверлапа."""
    chunks = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(start + CHUNK_SIZE, text_len)
        # Если это не последний чанк и мы можем найти лучший разрыв
        if end < text_len:
            # Ищем перенос строки или точку для более чистого разделения
            # Ищем в диапазоне [start + CHUNK_OVERLAP, end], чтобы не обрезать слишком коротко
            # и чтобы разрыв был не в самом начале следующего оверлапа.
            break_point = -1
            # Сначала ищем в более предпочтительной зоне (не слишком близко к start)
            search_start_for_break = start + CHUNK_SIZE // 2

            # Поиск переноса строки
            temp_bp = text.rfind('\n', search_start_for_break, end)
            if temp_bp != -1:
                break_point = temp_bp + 1  # Включаем сам перенос строки
            else:
                # Если нет переноса, ищем точку
                temp_bp = text.rfind('.', search_start_for_break, end)
                if temp_bp != -1:
                    break_point = temp_bp + 1  # Включаем точку

            # Если нашли хороший разрыв, используем его
            if break_point != -1:
                end = break_point
            # Если хороший разрыв не найден, но мы не в конце текста,
            # и end слишком сильно обрезает, можно попробовать найти разрыв ближе к start,
            # но не раньше чем start + CHUNK_OVERLAP, чтобы иметь смысл для оверлапа.
            # Для простоты, если не нашли идеальный разрыв, режем по CHUNK_SIZE.

        chunks.append(text[start:end])

        if end >= text_len:  # Достигли конца текста
            break

        # Переходим к следующему чанку
        start = end - CHUNK_OVERLAP
        if start < 0:  # Это не должно происходить, если CHUNK_OVERLAP < CHUNK_SIZE
            start = 0  # Защита

    logger.info(f"Разделен '{filename}' на {len(chunks)} чанков.")
    return chunks


async def embed_chunks(text_chunks: list[str]) -> np.ndarray | None:
    """Создаёт эмбеддинги для списка чанков батчами."""
    if not text_chunks:
        return None
    try:
        all_embeddings = []
        # Gemini API для text-embedding-004 рекомендует до 100 текстов на запрос
        batch_size = 100
        for i in range(0, len(text_chunks), batch_size):
            batch = text_chunks[i:i + batch_size]
            result = await genai.embed_content_async(
                model=EMBEDDING_MODEL_NAME,
                content=batch,  # Передаем батч
                task_type="RETRIEVAL_DOCUMENT"
            )
            all_embeddings.extend(result['embedding'])

        if not all_embeddings:  # Если по какой-то причине эмбеддинги не были созданы
            return None
        return np.array(all_embeddings).reshape(len(text_chunks), -1)
    except Exception as e:
        logger.error(f"❌ Ошибка эмбеддинга: {e}")
        return None


async def update_rag_knowledge_base_from_folder(folder_path: str):
    """Загружает все .txt из указанной папки в RAG_DATA."""
    global RAG_LOADED  # Мы будем менять этот флаг
    if not os.path.isdir(folder_path):
        logger.error(f"Папка не найдена: {folder_path}")
        return False

    any_file_processed_successfully = False
    for filename in os.listdir(folder_path):
        if filename.endswith(".txt"):
            filepath = os.path.join(folder_path, filename)
            # При загрузке из папки не очищаем существующие для файла, если он уже был (предполагаем, что это начальная загрузка)
            # Если нужно поведение обновления, clear_existing_for_file можно сделать True
            success = await update_rag_knowledge_base(filepath, clear_existing_for_file=False,
                                                      source_identifier=filename)
            if success:
                any_file_processed_successfully = True

    if any_file_processed_successfully:
        logger.info("✅ База знаний из папки обновлена.")
        RAG_LOADED = True  # Устанавливаем флаг, т.к. хотя бы один файл успешно загружен
        return True
    else:
        logger.error("❌ Не удалось загрузить ни один файл из папки.")
        # RAG_LOADED не меняем на False, если он уже был True от других загрузок
        return False


async def update_rag_knowledge_base(
        filepath: str,
        clear_existing_for_file: bool = False,
        source_identifier: str = None
):
    """Добавляет (или обновляет) один файл в RAG_DATA."""
    global RAG_DATA, RAG_LOADED
    source_identifier = source_identifier or os.path.basename(filepath)  # Имя файла как идентификатор по умолчанию

    if clear_existing_for_file:
        # Удаляем старые чанки и эмбеддинги для этого источника
        indices_to_keep = [i for i, src in enumerate(RAG_DATA["file_source"]) if src != source_identifier]

        RAG_DATA["chunks"] = [RAG_DATA["chunks"][i] for i in indices_to_keep]
        RAG_DATA["file_source"] = [RAG_DATA["file_source"][i] for i in indices_to_keep]
        if RAG_DATA["embeddings"] is not None and RAG_DATA["embeddings"].size > 0:
            if indices_to_keep:  # Если остались какие-то чанки
                RAG_DATA["embeddings"] = RAG_DATA["embeddings"][indices_to_keep]
            else:  # Если все чанки были от этого источника и их удалили
                RAG_DATA["embeddings"] = None

        if not RAG_DATA["chunks"]:  # Если после очистки чанков не осталось
            RAG_DATA["embeddings"] = None  # Убедимся, что эмбеддинги тоже пусты
            # RAG_LOADED здесь не меняем на False, т.к. это может быть временное состояние перед добавлением новых
        logger.info(f"Очищены существующие RAG данные для источника: {source_identifier}")

    try:
        async with aiofiles.open(filepath, "r", encoding="utf-8") as f:
            content = await f.read()
    except Exception as e:
        logger.error(f"❌ Ошибка чтения файла {filepath}: {e}")
        return False

    new_chunks = get_text_chunks(content, filename=source_identifier)
    if not new_chunks:
        logger.warning(f"Из {filepath} не создано ни одного чанка (файл может быть пуст или слишком мал).")
        # Если чанки не созданы, но файл был прочитан, это не обязательно ошибка, но RAG не обновится
        # Если после очистки и отсутствия новых чанков база осталась пустой, RAG_LOADED должен отражать это.
        if not RAG_DATA["chunks"]:
            RAG_LOADED = False
        return True  # Считаем операцию "успешной" в плане обработки файла, хоть и без добавления чанков

    new_embeddings = await embed_chunks(new_chunks)
    if new_embeddings is None:
        logger.error(f"Не удалось создать эмбеддинги для чанков из {filepath}")
        return False

    RAG_DATA["chunks"].extend(new_chunks)
    RAG_DATA["file_source"].extend([source_identifier] * len(new_chunks))

    if RAG_DATA["embeddings"] is None or RAG_DATA["embeddings"].size == 0:
        RAG_DATA["embeddings"] = new_embeddings
    else:
        RAG_DATA["embeddings"] = np.vstack([RAG_DATA["embeddings"], new_embeddings])

    logger.info(
        f"✅ База знаний обновлена {len(new_chunks)} чанками из {filepath}. "
        f"Всего чанков: {len(RAG_DATA['chunks'])}"
    )
    RAG_LOADED = True  # Успешное добавление чанков означает, что RAG загружен
    return True


async def retrieve_relevant_chunks(query: str, top_n: int = MAX_RAG_CHUNKS) -> list[str]:
    """Извлекает из RAG_DATA до top_n наиболее релевантных чанков по косинусной близости."""
    if not RAG_DATA["chunks"] or RAG_DATA["embeddings"] is None or RAG_DATA["embeddings"].size == 0:
        return []

    try:
        query_embedding_result = await genai.embed_content_async(
            model=EMBEDDING_MODEL_NAME,
            content=query,
            task_type="RETRIEVAL_QUERY"
        )
        query_embedding = np.array(query_embedding_result['embedding']).reshape(1, -1)

        similarities = cosine_similarity(query_embedding, RAG_DATA["embeddings"])[0]

        # Получаем индексы N лучших чанков
        # argsort сортирует по возрастанию, поэтому берем последние N и разворачиваем
        sorted_indices = np.argsort(similarities)[-top_n:][::-1]

        relevant_chunks = []
        for index in sorted_indices:
            if similarities[index] > 0.5:  # Порог отсечения по схожести
                relevant_chunks.append(RAG_DATA["chunks"][index])
            # else:
            # Если самый релевантный из top_n уже ниже порога, можно остановиться,
            # так как sorted_indices отсортированы по убыванию схожести.
            # break
        # Однако, если top_n=3, и схожести [0.9, 0.4, 0.8], то break после 0.4 не даст нам 0.8.
        # Поэтому лучше проверить все top_n выбранные индексы.
        # argsort не гарантирует, что [-top_n:] даст отсортированные по убыванию значения схожести,
        # он дает индексы элементов, которые БЫЛИ БЫ на этих местах при полной сортировке.
        # Для получения топ-N с порогом, лучше отсортировать все схожести, а потом брать топ.

        # Более корректный способ взять топ N релевантных с порогом:
        # 1. Получить все схожести.
        # 2. Отфильтровать те, что выше порога.
        # 3. Из отфильтрованных взять топ N.

        # Или: взять топ N по схожести, потом из них отфильтровать по порогу. (Как сделано сейчас)

        logger.info(
            f"Извлечено {len(relevant_chunks)} релевантных чанков из {len(sorted_indices)} кандидатов (top_n={top_n}, порог=0.5).")
        return relevant_chunks
    except Exception as e:
        logger.error(f"❌ Ошибка извлечения релевантных чанков: {e}")
        return []


async def get_chat_session(user_id: int) -> genai.ChatSession:
    """Получает или создаёт сессию чата Gemini для данного пользователя."""
    if user_id not in USER_CHAT_SESSIONS:
        logger.info(f"Создание новой сессии чата для пользователя {user_id}")
        model = genai.GenerativeModel(
            GENERATION_MODEL_NAME,  # Используем основную модель для генерации ответов
            system_instruction=(
                "Ты — полезный ассистент. "
                "Когда предоставляется контекст из базы знаний, используй его в первую очередь для ответа. "
                "Если контекст нерелевантен или отсутствует, отвечай на основе своих общих знаний."
            )
        )
        USER_CHAT_SESSIONS[user_id] = model.start_chat(history=[])
    return USER_CHAT_SESSIONS[user_id]


async def initialize_gemini_assistant():
    """Инициализация RAG-ассистента: загружает все .txt из DATA_DIR."""
    # RAG_LOADED будет обновлен внутри update_rag_knowledge_base_from_folder
    logger.info("Попытка инициализации базы знаний RAG из DATA_DIR...")
    success = await update_rag_knowledge_base_from_folder(DATA_DIR)
    if success:
        logger.info("🧠 База знаний RAG успешно инициализирована из DATA_DIR.")
    else:
        logger.warning(
            "Не удалось инициализировать базу знаний RAG из DATA_DIR (файлы не найдены или произошла ошибка).")
    return success  # Возвращает True, если хотя бы один файл был успешно загружен


async def process_message(message: Message, bot: Bot):
    global RAG_LOADED, RAG_DATA  # Доступ к глобальным переменным

    user_id = message.from_user.id
    chat_id = message.chat.id
    user_query_text = None  # Здесь будет текст для обработки (из аудио или текстового сообщения)

    # 1. Обработка аудиосообщений
    if message.content_type in [ContentType.VOICE, ContentType.AUDIO]:
        await bot.send_message(chat_id, "🎤 Обрабатываю ваше аудиосообщение...")

        file_id_tg = message.voice.file_id if message.content_type == ContentType.VOICE else message.audio.file_id
        file_info_tg = await bot.get_file(file_id_tg)

        downloaded_file_io = await bot.download_file(file_info_tg.file_path)
        audio_data_bytes = downloaded_file_io.read()

        # Временное сохранение аудиофайла для upload_file
        temp_audio_dir = "static/temp_audio"
        os.makedirs(temp_audio_dir, exist_ok=True)
        # Имя файла может включать расширение из mime_type, если доступно
        # Для простоты, предполагаем ogg или mp3, которые Gemini обычно распознает
        file_extension = ".ogg"  # По умолчанию
        if message.audio and message.audio.mime_type:
            ext_candidate = message.audio.mime_type.split('/')[-1]
            if ext_candidate in ["ogg", "mp3", "wav", "flac", "opus", "m4a", "aac"]:
                file_extension = f".{ext_candidate}"

        temp_audio_path = os.path.join(temp_audio_dir, f"user_{user_id}_{file_id_tg}{file_extension}")

        async with aiofiles.open(temp_audio_path, "wb") as f:
            await f.write(audio_data_bytes)

        try:
            audio_transcription_model = genai.GenerativeModel(AUDIO_TRANSCRIPTION_MODEL_NAME)
            logger.info(f"Загрузка аудиофайла {temp_audio_path} в Gemini для транскрипции...")

            # Загружаем файл в Gemini
            audio_file_resource = genai.upload_file(path=temp_audio_path)
            logger.info(f"Аудиофайл загружен: {audio_file_resource.name}. Ожидание обработки...")

            # Ожидаем, пока Gemini обработает файл
            while audio_file_resource.state.name == "PROCESSING":
                await asyncio.sleep(2)  # Пауза перед повторной проверкой
                audio_file_resource = genai.get_file(name=audio_file_resource.name)  # Обновляем статус файла

            if audio_file_resource.state.name == "FAILED":
                raise Exception(f"Обработка аудиофайла в Gemini не удалась: {audio_file_resource.state.name}")

            logger.info(f"Аудиофайл успешно обработан Gemini: {audio_file_resource.name}")

            # Запрос на транскрипцию
            response = await audio_transcription_model.generate_content_async([
                audio_file_resource,  # Передаем обработанный ресурс файла
                "Transcribe this audio to text in Russian."  # Промпт для транскрипции
            ])
            transcription = response.text
            user_query_text = transcription  # <--- Сохраняем транскрипцию для дальнейшей обработки

            await bot.send_message(chat_id, f"🎤 Ваше аудио транскрибировано:\n{user_query_text}")

            # Опционально: удалить файл из Gemini после использования, если он больше не нужен
            # try:
            #     await genai.delete_file_async(audio_file_resource.name)
            #     logger.info(f"Удален файл из Gemini хранилища: {audio_file_resource.name}")
            # except Exception as e_del_gemini:
            #     logger.warning(f"Не удалось удалить файл из Gemini хранилища {audio_file_resource.name}: {e_del_gemini}")

        except Exception as e:
            logger.error(f"❌ Ошибка обработки аудио: {e}")
            await bot.send_message(chat_id, f"🚫 К сожалению, не удалось обработать ваше аудиосообщение: {str(e)}")
            return  # Выходим, если аудио не обработано
        finally:
            # Удаляем временный локальный аудиофайл
            if os.path.exists(temp_audio_path):
                try:
                    os.remove(temp_audio_path)
                except Exception as e_rem:
                    logger.error(f"Не удалось удалить временный аудиофайл {temp_audio_path}: {e_rem}")

        # Если транскрипция прошла успешно, user_query_text установлен, и код пойдет дальше

    # 2. Обработка документов (.txt файлов для базы знаний)
    elif message.content_type == ContentType.DOCUMENT:
        if message.document.mime_type == "text/plain":
            doc = message.document
            original_file_name = doc.file_name or f"user_upload_{doc.file_unique_id}.txt"

            temp_docs_dir = "static/temp_docs"  # Папка для временных документов
            os.makedirs(temp_docs_dir, exist_ok=True)
            # Уникальное имя для временного файла, чтобы избежать конфликтов
            temp_file_path = os.path.join(temp_docs_dir, f"user_{user_id}_{doc.file_unique_id}_{original_file_name}")

            try:
                await bot.send_message(chat_id, f"📥 Обрабатываю ваш документ: {original_file_name}...")
                file_info_tg = await bot.get_file(doc.file_id)
                await bot.download_file(file_info_tg.file_path, destination=temp_file_path)

                # При добавлении/обновлении файла через загрузку, очищаем его старые версии из RAG
                if await update_rag_knowledge_base(
                        temp_file_path,
                        clear_existing_for_file=True,
                        source_identifier=original_file_name  # Используем имя файла как идентификатор
                ):
                    await bot.send_message(chat_id,
                                           f"✅ Документ '{original_file_name}' успешно обработан и добавлен/обновлен в базе знаний!")
                else:
                    await bot.send_message(chat_id,
                                           f"⚠️ Не удалось обработать документ '{original_file_name}' или добавить его в базу знаний.")
            except Exception as e:
                logger.error(f"Ошибка обработки документа '{original_file_name}': {e}")
                await bot.send_message(chat_id, "❌ Произошла ошибка при обработке вашего документа.")
            finally:
                if os.path.exists(temp_file_path):
                    try:
                        os.remove(temp_file_path)
                    except Exception as e_rem:
                        logger.error(f"Не удалось удалить временный файл документа {temp_file_path}: {e_rem}")
            return  # Обработка документа - это конечное действие для данного сообщения
        else:
            await bot.send_message(chat_id,
                                   "⚠️ Пожалуйста, загрузите текстовый файл (.txt) для добавления в базу знаний.")
            return

    # 3. Обработка текстовых сообщений
    elif message.text:
        user_query_text = message.text

    # 4. Если есть текст для обработки (из аудио или обычного сообщения), запускаем RAG и генерацию ответа
    if user_query_text:
        # Ленивая инициализация базы знаний из DATA_DIR, если она еще не была загружена
        # (например, при первом запросе после старта бота, если не было команд или загрузок файлов)
        # Проверяем, есть ли чанки в RAG_DATA. Если нет, и RAG_LOADED тоже False, то пытаемся загрузить.
        if not RAG_DATA["chunks"] and not RAG_LOADED:
            logger.info("База знаний RAG пуста. Попытка инициализации из стандартной папки DATA_DIR...")
            await initialize_gemini_assistant()  # Эта функция обновит RAG_LOADED, если успешно

        await bot.send_chat_action(chat_id, "typing")  # Показываем, что бот "печатает"
        think_msg = await bot.send_message(chat_id, "⏳ Думаю над вашим запросом...")

        chat_session = await get_chat_session(user_id)

        relevant_chunks = []
        # Извлекаем релевантные чанки, только если RAG_DATA содержит чанки
        # RAG_LOADED может быть True, но чанков нет, если все было удалено или не загрузилось.
        if RAG_DATA["chunks"]:
            relevant_chunks = await retrieve_relevant_chunks(user_query_text)

        if relevant_chunks:
            context_str = "\n\n---\n\n".join(relevant_chunks)
            prompt_for_gemini = (
                """Ты — полезный ИИ-ассистент, который помогает пользователям понять, как выполнять различные действия в системе, основываясь на предоставленных сценариях. Твоя задача — извлечь шаги из сценария и представить их в виде инструкции.

### Руководство по ответам:

1.  **Язык ответа:** Всегда отвечай только на РУССКОМ языке.
2.  **Пропуск начального шага:** НЕ включай в ответ шаг, описывающий открытие окна. Обычно он начинается со слов "Когда открылось окно...". Твоя инструкция для пользователя должна начинаться со ВТОРОГО логического действия, описанного в сценарии.
3.  **Обобщение данных (КРАЙНЕ ВАЖНО):**
    *   Когда извлекаешь шаги, НЕ ИСПОЛЬЗУЙ КОНКРЕТНЫЕ ЗНАЧЕНИЯ из примеров в тексте сценария.
    *   Вместо этого, формулируй шаг так, чтобы пользователь понял, КАКОЕ ДЕЙСТВИЕ ему нужно совершить и ГДЕ, но со СВОИМИ данными.
    *   **Примеры обобщения:**
        *   Если в сценарии: `И из выпадающего списка с именем 'ВидОперации' я выбираю точное значение "Перечисление авансов работникам"`
            Твой ответ должен быть: `Из выпадающего списка с именем 'ВидОперации' выберите необходимое значение (например, "Перечисление авансов работникам", но пользователь должен выбрать свое).` или просто `Выберите вид операции из списка 'ВидОперации'.`
        *   Если в сценарии: `И в поле с именем 'НомерСчета' я ввожу текст "2"`
            Твой ответ должен быть: `В поле с именем 'НомерСчета' введите соответствующий номер счета.`
        *   Если в сценарии: `И в поле с именем 'Дата' я ввожу текст "23.05.2025 12:12:34"`
            Твой ответ должен быть: `В поле с именем 'Дата' введите актуальную дату и время.`
        *   Если в сценарии: `И из выпадающего списка с именем 'Получатель' я выбираю точное значение "Акмолинский областной филиал акционерного общества \"Казпочта\""`
            Твой ответ должен быть: `Из выпадающего списка с именем 'Получатель' выберите нужного получателя.`
    *   **Цель:** Пользователь должен получить общую инструкцию, а не повторение тестовых данных. Поля (`'ВидОперации'`, `'НомерСчета'`) называть нужно, а вот их значения из примера — нет.

4.  **Исключение вспомогательных шагов активации поля (КРАЙНЕ ВАЖНО):**
    *   Если в сценарии встречается шаг, описывающий нажатие на элемент интерфейса для активации поля ввода или выбора (например, `И я нажимаю кнопку выбора у поля с именем '[ИМЯ_ПОЛЯ]'`), и **сразу за ним** следует шаг непосредственного ввода данных или выбора значения в **это же самое поле** (например, `И в поле с именем '[ИМЯ_ПОЛЯ]' я ввожу текст "[ЗНАЧЕНИЕ]"` или `И из выпадающего списка с именем '[ИМЯ_ПОЛЯ]' я выбираю точное значение "[ЗНАЧЕНИЕ]"`):
        *   **НЕ включай** в инструкцию шаг о нажатии кнопки выбора (или аналогичный вспомогательный шаг активации).
        *   Вместо этого, представь это как **единое действие** по заполнению поля, обобщенное согласно пункту 3.
    *   **Пример:**
        *   Если в сценарии:
            `И я нажимаю кнопку выбора у поля с именем 'Дата'`
            `И в поле с именем 'Дата' я ввожу текст "23.05.2025 12:12:34"`
        *   Твой ответ для этого действия должен быть: `В поле с именем 'Дата' введите актуальную дату и время.` (то есть, шаг "Нажмите кнопку выбора..." опускается).

5.  **Структура ответа:** Представляй шаги в виде нумерованного И маркированного списка. Маркировка содержит в себе '!!' в самом начале и '!!' в самом конце ответа. Ответ должен быть четким и последовательным.
6.  **Недостаток информации:** Если предоставленный контекст не содержит информации для ответа на вопрос пользователя, четко укажи, что ответ не может быть дан на основе этой информации.
7.  **Уточняющие вопросы:** Если запрос пользователя неясен, попроси его уточнить.
8.  **Цитирование (если применимо):** Если ты используешь информацию из конкретного документа (хотя в данном случае это шаги), указывай источник кратко. (Этот пункт менее релевантен для вашей задачи, но оставлю его как хорошую практику).

### Пример того, как НЕ НАДО отвечать (с конкретными данными И с лишним шагом):

НЕПРАВИЛЬНО:
1. Из выпадающего списка с именем 'ВидОперации' я выбираю точное значение "Перечисление авансов работникам"
2. И в поле с именем 'НомерСчета' я ввожу текст "2"
3. И я нажимаю кнопку выбора у поля с именем 'Дата'  <-- ЭТОТ ШАГ ЛИШНИЙ В ИНСТРУКЦИИ
4. И в поле с именем 'Дата' я ввожу текст "23.05.2025 12:12:34"
...

### Пример того, КАК НАДО отвечать (обобщенно и без лишних шагов активации):

ПРАВИЛЬНО (на вопрос "Как сделать списание средств?"):
!! Чтобы выполнить списание денежных средств, следуйте этим шагам:
1.  Из выпадающего списка с именем 'ВидОперации' выберите необходимый вид операции.
 2.  В поле с именем 'НомерСчета' введите номер счета.
 3.  В поле с именем 'Дата' введите актуальную дату и время.
 4.  В поле с именем 'ДатаОплаты' введите дату оплаты.
 5.  Из выпадающего списка с именем 'Шаблон' выберите соответствующий шаблон.
 6.  Из выпадающего списка с именем 'СтатьяРасходов' выберите статью расходов.
 7.  Из выпадающего списка с именем 'СчетУчреждения' выберите счет учреждения.
 8.  Из выпадающего списка с именем 'Получатель' выберите получателя. !!"""
                f"КОНТЕКСТ ИЗ БАЗЫ ЗНАНИЙ:\n{context_str}\n\n"
                f"ВОПРОС ПОЛЬЗОВАТЕЛЯ: {user_query_text}"
            )
            logger.info(
                f"Сформирован дополненный промпт для пользователя {user_id} с {len(relevant_chunks)} чанк(ами) контекста.")
        else:
            prompt_for_gemini = user_query_text  # Если релевантных чанков нет, используем только исходный запрос
            if RAG_DATA["chunks"]:  # Если чанки в базе есть, но релевантных не нашлось
                logger.info(
                    f"Релевантные чанки для запроса пользователя {user_id} не найдены. Используется только сам запрос.")
            else:  # Если база знаний пуста
                logger.info(f"База знаний RAG пуста. Используется только запрос пользователя {user_id}.")

        try:
            response = await chat_session.send_message_async(prompt_for_gemini)
            await bot.edit_message_text(  # Редактируем сообщение "Думаю..." на ответ
                chat_id=chat_id,
                text=response.text,
                message_id=think_msg.message_id
            )
            logger.info(f"Ответ успешно отправлен пользователю {user_id}.")
        except Exception as e:
            logger.error(f"❌ Ошибка взаимодействия с Gemini API при генерации ответа: {e}")
            error_message_text = "🚫 Произошла ошибка при генерации ответа."
            # Более детальная обработка ошибок Gemini (например, safety settings)
            if hasattr(e, 'args') and e.args:
                err_content_str = str(e.args[0]).lower()
                if "safety" in err_content_str or "blocked" in err_content_str:
                    error_message_text = "⚠️ Ваш запрос или сгенерированный ответ не соответствуют политикам безопасности. Попробуйте переформулировать."
                elif "candidate" in err_content_str and "finish_reason: SAFETY" in str(
                        e):  # Более специфично для Gemini
                    error_message_text = "⚠️ Ответ не может быть предоставлен из-за настроек безопасности (Safety)."

            await bot.edit_message_text(chat_id=chat_id, text=error_message_text, message_id=think_msg.message_id)

            # Очистка последнего сообщения из истории чата, если оно вызвало ошибку,
            # чтобы избежать "застревания" сессии на проблемном промпте.
            if chat_session.history:
                last_entry = chat_session.history[-1]
                # Проверяем, что последнее сообщение - это наш проблемный промпт пользователя
                if last_entry.role == "user" and last_entry.parts and last_entry.parts[0].text == prompt_for_gemini:
                    logger.warning("Удаление последнего сообщения из истории чата Gemini из-за ошибки генерации.")
                    chat_session.history.pop()
        return

    # Если ни одно из условий не сработало (например, стикер, фото и т.д.)
    # Можно добавить лог или стандартный ответ, если это не команда
    if message.text and message.text.startswith('/'):  # Не логируем команды как "неподдерживаемый тип"
        pass
    elif not user_query_text:  # Если user_query_text не был установлен (т.е. это не текст, аудио или документ)
        logger.info(
            f"Получен неподдерживаемый тип контента от {user_id}: {message.content_type}. Сообщение проигнорировано.")
        # await bot.send_message(chat_id, "Я умею работать с текстом, голосовыми сообщениями и .txt файлами для базы знаний.")

# Не забудьте добавить в ваш основной файл (где создается Dispatcher и Bot) хендлер для сообщений:
# from your_module import process_message # Замените your_module на имя вашего файла
# ...
# dp.message.register(process_message, F.content_type.in_({ContentType.TEXT, ContentType.VOICE, ContentType.AUDIO, ContentType.DOCUMENT}))
# ...
# Также, если у вас есть команды /start, /clear_rag и т.д., для них нужны отдельные хендлеры.
# Например, /start может вызывать initialize_gemini_assistant().