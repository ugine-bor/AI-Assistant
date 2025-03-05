import os
from bs4 import BeautifulSoup as bs
import aiohttp
import asyncio
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()


class Parser:
    def __init__(self, id, bot):
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'
        ]
        self.timeout = aiohttp.ClientTimeout(total=20, connect=20)
        self.id = id
        self.bot = bot

    async def _get_html(self, url):
        for user_agent in self.user_agents:
            headers = {'User-Agent': user_agent}
            try:
                async with aiohttp.ClientSession(timeout=self.timeout, headers=headers) as session:
                    async with session.get(url, allow_redirects=True) as response:
                        response.raise_for_status()
                        return await response.text()
            except aiohttp.ClientConnectionError:
                print(f"Connection error for {url} with User-Agent: {user_agent}")
            except aiohttp.ClientResponseError as e:
                print(f"HTTP Error {e.status} for {url} with User-Agent: {user_agent}")
            except asyncio.TimeoutError:
                print(f"Timeout for {url} with User-Agent: {user_agent}")
            except Exception as e:
                print(f"Unexpected error for {url}: {str(e)}")
            await asyncio.sleep(1)  # Задержка между попытками
        return None

    async def get_soup(self, url):
        html = await self._get_html(url)
        if not html:
            await self.bot.send_message(self.id, f"Не удалось получить страницу {url}")
            print("Failed to get HTML")
            return None
        try:
            return bs(html, 'lxml')
        except Exception as e:
            print(f"BeautifulSoup error: {e}")
            return None

    async def get_news(self, url, days=int(os.getenv('LAST_DAYS'))):
        handlers = {
            os.getenv('ODINC'): self.odinc,
            os.getenv('UCHET'): self.uchet,
            os.getenv('MYBUH'): self.mybuh,
            os.getenv('PRO1C'): self.pro1c,
            os.getenv('GOS24'): self.gos24
        }

        if url not in handlers:
            return None

        soup = await self.get_soup(url)
        if not soup:
            print("Failed to parse page")
            return None

        return await handlers[url](soup, days)

    async def odinc(self, soup, days):
        curtime = datetime.now()
        until = (curtime - timedelta(days=days)).date()
        articles = {}

        tbody = soup.select_one(os.getenv('ODINC_LIST'))

        for item in tbody.find_all('tr', class_='pb-1'):
            time_el = item.find('td', class_='news-date-time').text.strip()
            link = item.find('a')
            article_date = datetime.strptime(time_el, '%d.%m.%Y').date()

            if article_date >= until:
                base_url = '/'.join(os.getenv('ODINC').split('/')[:-2])
                ur = f"{base_url}{link.get('href')}"
                page = await self.get_soup(ur)

                if page:
                    txt = page.find('main', class_='p-3')
                    articles[ur] = [time_el, txt.text]

        return articles

    async def uchet(self, soup, days):
        curtime = datetime.now()
        until = (curtime - timedelta(days=days)).date()
        articles = {}

        tbody = soup.select_one(os.getenv('UCHET_LIST'))

        for item in tbody.find_all('div', class_='w-100'):
            time_el = item.find('small', class_='text-info').text.strip()
            link = item.find('a')
            article_date = datetime.strptime(time_el, '%d.%m.%Y').date()

            if article_date >= until:
                base_url = '/'.join(os.getenv('UCHET').split('/')[:-2])
                ur = f"{base_url}{link.get('href')}"
                page = await self.get_soup(ur)

                if page:
                    txt = page.find('article', itemprop='articleBody')
                    articles[ur] = [time_el, txt.text]

        return articles

    async def mybuh(self, soup, days):
        curtime = datetime.now()
        until = (curtime - timedelta(days=days)).date()
        articles = {}

        tbody = soup.select_one("ul.popular-news__list.scroll")

        for item in tbody.find_all('li'):
            time_el = item.find('time')
            if not time_el:
                continue

            time_el = time_el.text.strip().split(', ')[0]
            link = item.find('a')
            article_date = datetime.strptime(time_el, '%d.%m.%Y').date()

            if article_date >= until:
                base_url = '/'.join(os.getenv('MYBUH').split('/')[:-2])
                ur = f"{base_url}{link.get('href')}"
                page = await self.get_soup(ur)

                if page:
                    txt = page.find('div', class_='d_text')
                    articles[ur] = [time_el, txt.text]

        return articles

    async def pro1c(self, soup, days):
        curtime = datetime.now()
        until = (curtime - timedelta(days=days)).date()
        articles = {}

        tbody = soup.select_one(os.getenv('PRO1C_LIST'))

        for item in tbody.find_all('li'):
            time_el = item.find('small', class_='text-muted')
            if not time_el:
                continue

            time_el = time_el.text.strip()
            link = item.find('a')
            article_date = datetime.strptime(time_el, '%d.%m.%Y').date()

            if article_date >= until:
                base_url = '/'.join(os.getenv('PRO1C').split('/')[:-2])
                ur = f"{base_url}{link.get('href')}"
                page = await self.get_soup(ur)

                if page:
                    txt = page.find('div', itemprop='articleBody')
                    articles[ur] = [time_el, txt.text]

        return articles

    async def gos24(self, soup, days):
        curtime = datetime.now()
        until = (curtime - timedelta(days=days)).date()
        articles = {}

        tbody = soup.select_one(os.getenv('GOS24_LIST'))

        for item in tbody.find_all('div', class_='news-block'):
            time_el = item.find('div', class_='date').text.strip()
            link = item.find('a')

            formatted_date = self.dateformat(time_el)
            article_date = datetime.strptime(formatted_date, '%d.%m.%Y').date()

            if article_date >= until:
                ur = f"{os.getenv('GOS24')[:-1]}{link.get('href')}"
                page = await self.get_soup(ur)

                if page:
                    txt = page.find('div', class_='editor')
                    articles[ur] = [formatted_date, txt.text]

        return articles

    @staticmethod
    def dateformat(date_str):
        months = {
            'января': '01', 'февраля': '02', 'марта': '03',
            'апреля': '04', 'мая': '05', 'июня': '06',
            'июля': '07', 'августа': '08', 'сентября': '09',
            'октября': '10', 'ноября': '11', 'декабря': '12',
            'қаңтар': '01', 'ақпан': '02', 'наурыз': '03',
            'сәуір': '04', 'мамыр': '05', 'маусым': '06',
            'шілде': '07', 'тамыз': '08', 'қыркүйек': '09',
            'қазан': '10', 'қараша': '11', 'желтоқсан': '12'
        }

        parts = date_str.strip().split()
        return f"{parts[0]}.{months[parts[1]].lower()}.{parts[2]}"
