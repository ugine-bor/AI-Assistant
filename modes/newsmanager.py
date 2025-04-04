import os

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

from news_include.rubert import RubertClassifier
from news_include.parser import Parser
from news_include.chatgpt import shortener, summarizer
from news_include.videoparser import VideoParser

from re import compile, match

from dotenv import load_dotenv

load_dotenv()
vid = VideoParser()


def filter_by_theme(articles, classes):
    new_articles = {}
    for link, data in articles.items():
        buff = []

        for probe in range(len(classes)):
            if data[2][probe] > float(os.getenv("INTENSE")):
                buff.append(classes[probe])
        if buff:
            new_articles[link] = data[0:2]
            new_articles[link].append(buff)
    return new_articles


async def send_long_message(bot, user_id, text):
    MAX_LENGTH = 4000

    if len(text) <= MAX_LENGTH:
        await bot.send_message(user_id, text, parse_mode='Markdown')
        return

    message_parts = []
    for i in range(0, len(text), MAX_LENGTH):
        message_parts.append(text[i:i + MAX_LENGTH])

    for i, part in enumerate(message_parts):
        part_indicator = f"Часть {i + 1}/{len(message_parts)}: " if len(message_parts) > 1 else ""
        await bot.send_message(user_id, f"{part_indicator}{part}", parse_mode='MarkdownV2')


async def process_message(message, bot):
    await bot.send_message(message.from_user.id, "Ищу новости...")

    if ',' in message.text:
        url = message.text.split(',')[0].strip()
        classes = list(map(lambda x: x.strip(), message.text.split(',')[1:]))
        vidid = vid.getytid(url)
        if vidid:
            subtitle = vid.parse(vidid)
            summ = summarizer(subtitle, classes)
            result = vid.postprocess(summ, url)
            await send_long_message(bot, message.from_user.id, result)
            return
    else:
        vidid = vid.getytid(message.text)
        if vidid:
            subtitle = vid.parse(vidid)
            summ = summarizer(subtitle, 'any')
            result = vid.postprocess(summ, message.text.strip())
            await send_long_message(bot, message.from_user.id, result)
            return

    # Classes
    rubert = RubertClassifier(os.getenv("RUBERT"))
    parser = Parser(message.from_user.id, bot)

    # Variables
    sites = {
        "1": os.getenv('ODINC'),
        "2": os.getenv('UCHET'),
        "3": os.getenv('PRO1C'),
        "4": os.getenv('MYBUH'),
        "5": os.getenv('GOS24')}
    date = compile(r'^(0?[1-9]|[12]\d|3[01])\.(0?[1-9]|1[0-2])\.(\d{4})$')
    try:
        msg = message.text.split(',')
        if not msg[0].strip().isdigit():
            site, days, classes = '1', ('int', int(os.getenv('LAST_DAYS'))), msg[:]
        elif not msg[1].strip().isdigit() and not date.match(msg[1].strip()) and '-' not in msg[1].strip():
            sites[msg[0].strip()]
            site, days, classes = msg[0].strip(), ('int', int(os.getenv('LAST_DAYS'))), msg[1:]
        else:
            sites[msg[0].strip()]
            mode = 'int'  # int, one day, range
            if '-' in msg[1].strip():
                mode = 'range'
                dat1, dat2 = map(lambda x: x.strip(), msg[1].split('-'))
                if not date.match(dat1) or not date.match(dat2):
                    raise ValueError
                days = (mode, dat1, dat2)
            elif date.match(msg[1].strip()):
                mode = 'one day'
                if not date.match(msg[1].strip()):
                    raise ValueError
                days = (mode, msg[1].strip())
            else:
                if not msg[1].strip().isdigit():
                    raise ValueError
                days = int(msg[1].strip())
                if days < 1 or days > 30:
                    raise ValueError
                days = (mode, days)
            site, classes = msg[0].strip(), msg[2:]

        classes = list(map(lambda x: x.strip(), classes))
        if len(classes) == 1:
            classes.append('none')

    except (KeyError, ValueError, IndexError):
        await bot.send_message(message.from_user.id,
                               "Неверный формат запроса. Пример: 1, 3, Бухгалтерия, Обучающие курсы, Обновление")
        return

    # Get themes from file
    # with open(os.getenv('THEMES'), 'r', encoding='utf-8') as f:
    #    classes = f.read().split('\n')
    #    choice = sites[message.text]

    # Parse news
    articles = await parser.get_news(sites[site], days)
    if not articles:
        await bot.send_message(message.from_user.id, "Не удалось получить новости")
        return
    texts = [item[1] for item in articles.values()]

    await bot.send_message(message.from_user.id,
                           f"Найдено {len(articles)} новостей за заданный период на сайте {sites[site]}.\nПроверяю тематику...")

    # Check themes
    probes = []
    for text in texts:
        probes.append(rubert.predict(text, classes, normalize=False))

    [articles[key].append(probes[i]) for i, key in enumerate(articles.keys())]
    print(articles)

    articles = filter_by_theme(articles, classes)
    news = []

    await bot.send_message(message.from_user.id,
                           f"{len(articles)} новых статей соотвествуют желаемым темам. Обрабатываю их...")

    # Enshorten text and add to message
    for link, data in articles.items():
        news.append(
            f'Дата: {data[0]}\n'
            f'Темы: {", ".join(data[2])}\n'
            f'{shortener(data[1])}\n'
            f'Ссылка: {link}\n\n---'
        )

    text = ''
    for txt in news:
        text += txt + "\n\n"
    result = f'''📰 Краткое содержание новостей:
    
    {text}'''

    # Return result
    await send_long_message(bot, message.from_user.id, result)
