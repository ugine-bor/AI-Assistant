import os
import glob


def combine_txt_files(folder_path, output_file_name="combined_text.txt"):
    """
    Объединяет все TXT файлы из указанной папки в один файл
    с форматированием:

    название файла1:
    содержимое файла1


    название файла2:
    содержимое файла2


    ...
    """
    # Проверяем, существует ли папка
    if not os.path.exists(folder_path):
        print(f"Папка {folder_path} не существует")
        return

    # Получаем список всех TXT файлов в папке
    txt_files = glob.glob(os.path.join(folder_path, "*.txt"))

    if not txt_files:
        print(f"TXT файлы не найдены в папке {folder_path}")
        return

    print(f"Найдено {len(txt_files)} TXT файлов. Начинаю объединение...")

    # Путь для сохранения объединенного файла
    output_path = os.path.join(folder_path, output_file_name)

    # Создаем или перезаписываем выходной файл
    with open(output_path, 'w', encoding='utf-8') as output_file:
        # Перебираем все TXT файлы и добавляем их содержимое в объединенный файл
        for i, txt_file_path in enumerate(txt_files):
            # Получаем имя файла без пути
            file_name = os.path.basename(txt_file_path)

            try:
                # Читаем содержимое файла
                with open(txt_file_path, 'r', encoding='utf-8') as txt_file:
                    content = txt_file.read()

                # Записываем имя файла и его содержимое в формате, указанном пользователем
                output_file.write(f"{file_name}:\n")
                output_file.write(f"{content}")

                # Добавляем две пустые строки после содержимого файла
                # (если это не последний файл)
                if i < len(txt_files) - 1:
                    output_file.write("\n\n\n")

                print(f"Добавлен файл: {file_name}")

            except Exception as e:
                print(f"Ошибка при обработке {file_name}: {e}")

    print(f"Объединение завершено. Результат сохранен в файл: {output_file_name}")
    return output_path


# Пример использования программы
if __name__ == "__main__":
    folder_path = input("Введите путь к папке с TXT файлами: ")
    output_file_name = input("Введите имя для объединенного файла (по умолчанию: combined_text.txt): ")

    if not output_file_name:
        output_file_name = "combined_text.txt"

    result_file = combine_txt_files(folder_path, output_file_name)

    if result_file:
        print(f"Все TXT файлы успешно объединены в файл: {result_file}")