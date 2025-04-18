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


def parse_days(text, use_default=False):
    date = compile(r'\d{2}.\d{2}.\d{4}')
    if use_default and not (text.isdigit() or date.match(text) or '-' in text):
        return ('int', int(os.getenv('LAST_DAYS')))

    if '-' in text:
        mode = 'range'
        dats = [s.strip() for s in text.split('-')]
        print(dats, date.match(dats[0]), date.match(dats[1]))
        if len(dats) != 2 or not date.match(dats[0]) or not date.match(dats[1]):
            raise ValueError
        return (mode, dats[0], dats[1])

    elif date.match(text):
        mode = 'one day'
        return (mode, text)

    else:
        if not text.isdigit():
            raise ValueError
        days_int = int(text)
        if days_int < 1 or days_int > 256:
            raise ValueError
        return ('int', days_int)


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

    # Classes
    rubert = RubertClassifier(os.getenv("RUBERT"))
    parser = Parser(message.from_user.id, bot)

    # Variables
    sites = {
        "1": os.getenv('ODINC'),
        "2": os.getenv('UCHET'),
        "3": os.getenv('PRO1C'),
        "4": os.getenv('MYBUH'),
        "5": os.getenv('GOS24'),
        "6": os.getenv('KGD')}
    date = compile(r'^(0?[1-9]|[12]\d|3[01])\.(0?[1-9]|1[0-2])\.(\d{4})$')
    try:
        # video:
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

        # site:
        msg = message.text.split(',')
        msg = [m.strip() for m in msg]

        first = msg[0]
        second = msg[1] if len(msg) > 1 else ''
        rest = msg[2:] if len(msg) > 2 else []

        if not first.isdigit():
            site = first if '.' in first else sites['1']
            days = parse_days(second, use_default=True)
            classes = msg[:]
        elif not second.isdigit() and not date.match(second) and '-' not in second:
            site = sites[first]
            days = ('int', int(os.getenv('LAST_DAYS')))
            classes = msg[1:]
        else:
            site = sites[first]
            days = parse_days(second, use_default=False)
            classes = rest

        classes = [cl.strip() for cl in classes]
        if len(classes) == 1:
            classes.append('none')

    except (KeyError, ValueError, IndexError):
        await bot.send_message(message.from_user.id,
                               f"Неверный формат запроса. Пример: 1, 3, Бухгалтерия, Обучающие курсы, Обновление")
        return

    # Get themes from file
    # with open(os.getenv('THEMES'), 'r', encoding='utf-8') as f:
    #    classes = f.read().split('\n')
    #    choice = sites[message.text]

    # Parse KGD
    if first == '6':
        data = await parser.get_news(site, days, nums=classes)
        text = ""
        for element in data:
            text += f"Код ФНО: {element[0]}\nДата: {element[1]}\nСкачать: {element[2]}\n\n---\n\n"
        await send_long_message(bot, message.from_user.id, text)
        return

    # Parse news
    articles = await parser.get_news(site, days)
    if not articles:
        await bot.send_message(message.from_user.id, "Не удалось получить новости")
        return
    texts = [item[1] for item in articles.values()]

    await bot.send_message(message.from_user.id,
                           f"Найдено {len(articles)} новостей за заданный период.\nПроверяю тематику...")

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
