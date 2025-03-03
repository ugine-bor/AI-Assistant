import os
import glob
from bs4 import BeautifulSoup


def extract_text_from_htm(htm_file_path):
    """
    Извлекает только видимый текст из HTM файла,
    удаляя всю разметку и невидимые элементы
    """
    try:
        # Открываем HTM файл и читаем его содержимое
        with open(htm_file_path, 'r', encoding='utf-8') as file:
            htm_content = file.read()

        # Используем BeautifulSoup для парсинга HTM
        soup = BeautifulSoup(htm_content, 'html.parser')

        # Удаляем скрипты, стили и другие невидимые элементы
        for script_or_style in soup(['script', 'style', 'meta', 'noscript', 'head']):
            script_or_style.extract()

        # Получаем текст
        text = soup.get_text()

        # Удаляем лишние пробелы и пустые строки
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)

        return text

    except Exception as e:
        print(f"Ошибка при обработке {htm_file_path}: {e}")
        return ""


def process_all_htm_files_in_folder(folder_path):
    """
    Обрабатывает все HTM файлы в указанной папке
    и сохраняет извлеченный текст в TXT файлы
    """
    # Проверяем, существует ли папка
    if not os.path.exists(folder_path):
        print(f"Папка {folder_path} не существует")
        return

    # Получаем список всех HTM файлов в папке
    htm_files = glob.glob(os.path.join(folder_path, "*.htm"))

    if not htm_files:
        print(f"HTM файлы не найдены в папке {folder_path}")
        return

    print(f"Найдено {len(htm_files)} HTM файлов. Начинаю обработку...")

    # Обрабатываем каждый HTM файл
    for htm_file in htm_files:
        # Получаем имя файла без расширения
        file_name = os.path.basename(htm_file)
        file_name_without_ext = os.path.splitext(file_name)[0]

        # Путь для сохранения TXT файла
        txt_file_path = os.path.join(folder_path, f"{file_name_without_ext}.txt")

        # Извлекаем текст из HTM файла
        extracted_text = extract_text_from_htm(htm_file)

        # Сохраняем извлеченный текст в TXT файл
        if extracted_text:
            with open(txt_file_path, 'w', encoding='utf-8') as txt_file:
                txt_file.write(extracted_text)
            print(f"Обработан: {file_name} -> {file_name_without_ext}.txt")
        else:
            print(f"Не удалось извлечь текст из {file_name}")

    print("Обработка завершена")


# Пример использования программы
if __name__ == "__main__":
    folder_path = input("Введите путь к папке с HTM файлами: ")
    process_all_htm_files_in_folder(folder_path)