import os

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
from bs4 import BeautifulSoup as bs
import requests
from dotenv import load_dotenv
from datetime import datetime
from datetime import timedelta

load_dotenv()


class Parser:

    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'}

    def _get_html(self, url):
        try:
            r = requests.get(url, headers=self.headers, timeout=(20, 80))
            r.raise_for_status()
            return r.text
        except requests.exceptions.RequestException as e:
            print(f"Ошибка при запросе {url}: {e}")
            return None

    def get_soup(self, url):
        html = self._get_html(url)
        if not html:
            print("Не удалось получить HTML")
            return None
        return bs(html, 'lxml')

    def get_news(self, url, days=int(os.getenv('LAST_DAYS'))):
        news = None
        if url == os.getenv('ODINC'):
            news = self.odinc(self.get_soup(url), days)
        elif url == os.getenv('UCHET'):
            news = self.uchet(self.get_soup(url), days)
        elif url == os.getenv('MYBUH'):
            news = self.mybuh(self.get_soup(url), days)
        elif url == os.getenv('PRO1C'):
            news = self.pro1c(self.get_soup(url), days)
        elif url == os.getenv('GOS24'):
            news = self.gos24(self.get_soup(url), days)

        return news

    def odinc(self, soup, days):

        curtime = datetime.now()
        until = (curtime - timedelta(days=days)).date()
        articles = {}

        tbody = soup.select_one(os.getenv('ODINC_LIST'))

        for item in tbody.find_all('tr', class_='pb-1'):
            time_el = item.find('td', attrs={'class': 'news-date-time'}).text.strip()
            link = item.find('a')
            article_date = datetime.strptime(time_el, '%d.%m.%Y').date()
            if article_date >= until:
                ur = '/'.join(os.getenv('ODINC').split('/')[:-2]) + link.get('href')
                page = self.get_soup(ur)
                if page is None:
                    continue

                txt = page.find('main', attrs={'class': 'p-3'})

                articles[ur] = [time_el, txt.text]

        return articles

    def uchet(self, soup, days):

        curtime = datetime.now()
        until = (curtime - timedelta(days=days)).date()
        articles = {}

        tbody = soup.select_one(os.getenv('UCHET_LIST'))

        for item in tbody.find_all('div', class_='w-100'):
            time_el = item.find('small', attrs={'class': 'text-info'}).text.strip()
            link = item.find('a')
            article_date = datetime.strptime(time_el, '%d.%m.%Y').date()
            if article_date >= until:
                ur = '/'.join(os.getenv('UCHET').split('/')[:-2]) + link.get('href')
                page = self.get_soup(ur)
                if page is None:
                    continue

                txt = page.find('article', attrs={'itemprop': 'articleBody'})

                articles[ur] = [time_el, txt.text]

        return articles

    def mybuh(self, soup, days):

        curtime = datetime.now()
        until = (curtime - timedelta(days=days)).date()
        articles = {}

        tbody = soup.select_one("ul.popular-news__list.scroll")

        for item in tbody.find_all('li'):
            time_el = item.find('time')
            if time_el is None:
                continue
            time_el = time_el.text.strip().split(', ')[0]
            link = item.find('a')
            article_date = datetime.strptime(time_el, '%d.%m.%Y').date()
            if article_date >= until:
                ur = '/'.join(os.getenv('MYBUH').split('/')[:-2]) + link.get('href')
                page = self.get_soup(ur)
                if page is None:
                    continue

                txt = page.find('div', attrs={'class': 'd_text'})

                articles[ur] = [time_el, txt.text]

        return articles

    def pro1c(self, soup, days):

        curtime = datetime.now()
        until = (curtime - timedelta(days=days)).date()
        articles = {}

        tbody = soup.select_one(os.getenv('PRO1C_LIST'))

        for item in tbody.find_all('li'):
            time_el = item.find('small', attrs={'class': 'text-muted'})
            if time_el is None:
                continue
            time_el = time_el.text.strip()
            link = item.find('a')
            article_date = datetime.strptime(time_el, '%d.%m.%Y').date()
            if article_date >= until:
                ur = '/'.join(os.getenv('PRO1C').split('/')[:-2]) + link.get('href')
                page = self.get_soup(ur)
                if page is None:
                    continue

                txt = page.find('div', attrs={'itemprop': 'articleBody'})

                articles[ur] = [time_el, txt.text]

        return articles

    def gos24(self, soup, days):
        curtime = datetime.now()
        until = (curtime - timedelta(days=days)).date()
        articles = {}

        tbody = soup.select_one(os.getenv('GOS24_LIST'))

        for item in tbody.find_all('div', class_='news-block news grid_type'):
            time_el = item.find('div', attrs={'class': 'date'}).text.strip()
            link = item.find('a')

            time_el = self.dateformat(time_el)
            article_date = datetime.strptime(time_el, '%d.%m.%Y').date()
            if article_date >= until:
                ur = os.getenv('GOS24')[:-1] + link.get('href')
                page = self.get_soup(ur)
                if page is None:
                    continue

                txt = page.find('div', attrs={'class': 'editor'})

                articles[ur] = [time_el, txt.text]

        return articles

    @staticmethod
    def dateformat(date_str):

        parts = date_str.strip().split()

        months = {
            'января': '01',
            'февраля': '02',
            'марта': '03',
            'апреля': '04',
            'мая': '05',
            'июня': '06',
            'июля': '07',
            'августа': '08',
            'сентября': '09',
            'октября': '10',
            'ноября': '11',
            'декабря': '12',

            'қаңтар': '01',
            'ақпан': '02',
            'наурыз': '03',
            'сәуір': '04',
            'мамыр': '05',
            'маусым': '06',
            'шілде': '07',
            'тамыз': '08',
            'қыркүйек': '09',
            'қазан': '10',
            'қараша': '11',
            'желтоқсан': '12',
        }

        day = parts[0]
        month_ru = parts[1].lower()
        year = parts[2]

        month_num = months[month_ru]

        formatted_date = f"{day}.{month_num}.{year}"

        return formatted_date
