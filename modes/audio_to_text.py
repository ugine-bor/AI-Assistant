from aiogram.types import Message
from aiogram.enums import ContentType
from transformers import WhisperProcessor, WhisperForConditionalGeneration
from datasets import Audio, load_dataset
import os

# --- For mode6: async audio-to-text transcription using Whisper ---
SAVE_DIR = "static/audio"

# Load model and processor once
processor = WhisperProcessor.from_pretrained("openai/whisper-small")
model = WhisperForConditionalGeneration.from_pretrained("openai/whisper-small")
forced_decoder_ids = processor.get_decoder_prompt_ids(language="russian", task="transcribe")

async def process_message(message: Message, bot):
    # Only handle audio messages
    if message.content_type not in [ContentType.VOICE, ContentType.AUDIO]:
        await message.reply("Пожалуйста, отправьте аудиосообщение для транскрипции.")
        return

    # Download audio file from Telegram
    file_id = message.voice.file_id if message.content_type == ContentType.VOICE else message.audio.file_id
    file = await bot.get_file(file_id)
    file_path = file.file_path
    local_path = os.path.join(SAVE_DIR, f"{file_id}.ogg")
    os.makedirs(SAVE_DIR, exist_ok=True)
    file_content = await bot.download_file(file_path)
    with open(local_path, "wb") as f:
        f.write(file_content.getvalue())

    # Load and process audio
    try:
        ds = load_dataset(
            "audiofolder",
            data_dir=SAVE_DIR,
            split="train",
            streaming=True,
            keep_in_memory=False,
        )
        ds = ds.cast_column("audio", Audio(sampling_rate=16_000))
        # Find the sample with the correct file name
        sample = None
        for s in ds:
            if os.path.basename(s["audio"]["path"]) == f"{file_id}.ogg":
                sample = s
                break
        if sample is None:
            await message.reply("Не удалось загрузить аудиофайл для транскрипции.")
            return
        input_array = sample["audio"]["array"]
        sampling_rate = sample["audio"]["sampling_rate"]
        processed_output = processor(input_array, sampling_rate=sampling_rate, return_tensors="pt")
        input_features = processed_output.input_features
    except Exception as e:
        await message.reply(f"Ошибка обработки аудио: {e}")
        return

    # Generate transcription
    try:
        predicted_ids = model.generate(input_features, forced_decoder_ids=forced_decoder_ids)
        transcription = processor.batch_decode(predicted_ids, skip_special_tokens=True)[0]
        await message.reply(f"mode6 (audio-to-text):\n{transcription}")
    except Exception as e:
        await message.reply(f"Ошибка распознавания речи: {e}")