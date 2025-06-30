import os

import newspaper
from bs4 import BeautifulSoup as bs
import aiohttp
import asyncio
from dotenv import load_dotenv
from datetime import datetime, timedelta

import requests
from urllib.parse import urljoin, urlparse
from lxml import etree
import io

from news_include.chatgpt import link_finder_deepseek as link_finder

from newspaper import Article

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

        self._session = None

    async def _get_session(self):
        if self._session is None or self._session.closed:
            import random
            user_agent = random.choice(self.user_agents)
            headers = {'User-Agent': user_agent}
            self._session = aiohttp.ClientSession(headers=headers, timeout=self.timeout)
            print(f"Создана новая сессия aiohttp с User-Agent: {user_agent}")
        return self._session

    async def close_session(self):
        if self._session and not self._session.closed:
            await self._session.close()
            print("Сессия aiohttp закрыта.")
            self._session = None

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

    async def get_news(self, url, days=('int', int(os.getenv('LAST_DAYS'))), **kwargs):  # ('int', 3) ('one day', 21.04.2022) ('range', 21.04.2022, 21.05.2022)
        handlers = {
            #os.getenv('ODINC'): self.odinc,
            #os.getenv('UCHET'): self.uchet,
            #os.getenv('MYBUH'): self.mybuh,
            #os.getenv('PRO1C'): self.pro1c,
            #os.getenv('GOS24'): self.gos24,
            os.getenv('KGD'): self.kgd
        }
        if url not in handlers:
            url = await self.find_news_page_url(url)
            articles = await self.get_article_list(url, days)
            print('ARTICLES:', articles)
            data = dict()
            for article in articles:
                try:
                    article_obj = Article(article[1])
                    article_obj.download()
                    article_obj.parse()
                    data.setdefault(article[1], [article[0], article_obj.text])
                except newspaper.article.ArticleException as e:
                    article[1] = article[1].rstrip('/')
                    article_obj = Article(article[1])
                    article_obj.download()
                    article_obj.parse()
                    data.setdefault(article[1], [article[0], article_obj.text])
                except Exception as e:
                    print(f"Error parsing article {article[1]}: Type={type(e)}, Error={e}")
            return data
        else:
            soup = await self.get_soup(url)
            if not soup:
                print("Failed to parse page")
                return None

            rng = self.parse_days(days)

            print(f"Проверяем {url} на наличие новостей за период {rng[0]} - {rng[1]}")

            return await handlers[url](soup, rng, **kwargs)

    async def check_url_exists(self, url, session):
        try:
            response = session.head(url, timeout=20, allow_redirects=True)
            if not response.ok or response.status_code >= 400:
                response = session.get(url, timeout=7, allow_redirects=True, stream=True)
            response.raise_for_status()
            print(f"✔️ URL '{url}' существует (статус {response.status_code}).")
            return True
        except requests.exceptions.RequestException as e:
            return False
        except Exception as e:
            print(f"Неожиданная ошибка при проверке URL '{url}': {e}")
            return False

    async def find_news_page_url(self, base_url):
        if not base_url.startswith(('http://', 'https://')):
            base_url = 'https://' + base_url
        if '/' in base_url.split('//')[1].rstrip('/'):
            return base_url

        normalized_base_url = base_url.rstrip('/')

        print(f"Ищем новостную страницу для: {normalized_base_url}")

        headers = {
            'User-Agent': self.user_agents[0]
        }
        session = requests.Session()
        session.headers.update(headers)

        with open(os.getenv('NEWS_PAGE_VARS'), 'r', encoding='utf-8') as f:
            newspagevars = f.read().split('\n')

        for var in newspagevars:
            print(f"\n1. Проверяем наличие /{var}...")
            news_url = urljoin(normalized_base_url, f'/{var}')
            if await self.check_url_exists(news_url, session):
                print(f"Найден URL: {news_url}")
                return news_url + '/'
            else:
                print(f"  URL {news_url} не найден или недоступен.")

        print("\n4. Ни один из приоритетных URL не найден или не доступен.")
        print(f"Возвращаем базовый URL: {normalized_base_url}")
        return normalized_base_url

    async def search_site(self, url):
        session = await self._get_session()
        sitemap_urls = []

        print(f"\n Поиск в {url}...")
        try:
            async with session.get(url, allow_redirects=True) as response:
                print(f"  Статус ответа: {response.status}")
                if not response.ok:
                    print(f"  Ошибка: Сервер вернул статус {response.status}")

                content_type = response.headers.get('Content-Type', '').lower()
                print(f"  Content-Type: {content_type}")
                content_bytes = await response.read()

                is_parsed_as_xml = False
                if 'xml' in content_type or not content_type:
                    print("  Пытаемся парсить как XML...")
                    try:
                        xml_content = io.BytesIO(content_bytes)
                        tree = etree.parse(xml_content)
                        root = tree.getroot()
                        ns_map = root.nsmap
                        ns = {'ns': ns_map.get(None, 'http://www.sitemaps.org/schemas/sitemap/0.9')}

                        loc_tags = root.xpath('//ns:url/ns:loc/text()', namespaces=ns)
                        loc_tags.extend(root.xpath('//ns:sitemap/ns:loc/text()', namespaces=ns))

                        sitemap_urls = [urljoin(url, loc.strip()) for loc in loc_tags]
                        print(f"  Успешно распарсен XML. Найдено {len(sitemap_urls)} URL.")
                        is_parsed_as_xml = True
                    except etree.XMLSyntaxError:
                        print("  Не удалось распарсить как XML (ошибка синтаксиса).")
                    except Exception as e_xml:
                        print(f"  Неожиданная ошибка при парсинге XML: {e_xml}")

                if not is_parsed_as_xml and ('html' in content_type or content_bytes.strip().startswith(b'<')):
                    print(f"  Пытаемся парсить как HTML...")
                    try:
                        html_text = await response.text()
                        soup = bs(html_text, "lxml")
                        links_found = [a.get('href') for a in soup.find_all('a') if a.get('href')]
                        valid_links = []
                        for link in links_found:
                            abs_link = urljoin(url, link.strip())
                            parsed_link = urlparse(abs_link)
                            if parsed_link.scheme in (
                                    'http', 'https') and not parsed_link.fragment and not abs_link.startswith(
                                'javascript:'):
                                valid_links.append(abs_link)

                        sitemap_urls = list(dict.fromkeys(valid_links))
                        print(f"  Распарсен HTML. Найдено {len(sitemap_urls)} уникальных валидных ссылок.")
                        return sitemap_urls
                    except Exception as e_html:
                        print(f"  Ошибка при парсинге HTML: {e_html}")

                if not sitemap_urls:
                    print("  Не удалось извлечь ссылки ни из XML, ни из HTML.")

                return sitemap_urls

        except aiohttp.ClientResponseError as e:
            print(f"  Ошибка HTTP при доступе к {url}: {e.status} {e.message}")
            return []
        except aiohttp.ClientError as e:
            print(f"  Ошибка сети (aiohttp) при доступе к {url}: {e}")
            return []
        except asyncio.TimeoutError:
            print(f"  Таймаут при доступе к {url}")
            return []
        except Exception as e:
            print(f"  Неожиданная ошибка при обработке {url}: {type(e).__name__} {e}")
            return []

    async def get_article_list(self, url, days=('int', int(os.getenv('LAST_DAYS')))):
        print(f"Ищем статьи на {url}...")

        async def search_sitemap(parent, paths, url):
            for path in paths:
                print(
                    f"  Проверяем путь: {path} c родителем {parent} и ссылкой {url} ({url.split('//')[1].split('/')[1]})")
                if (path.endswith(('.rss', '.atom')) or 'rss' in path) and url.split('//')[1].split('/')[1] in path:
                    print(f"  Найден RSS/Atom фид: {path}")
                    return (path, 'rss')
                elif url in path:
                    print(f"  Найден путь к статьям: {parent}")
                    return (paths, 'sitemap')
                elif path.endswith('.xml'):
                    print(f"  Найден XML путь: {path}")
                    newpaths = await self.search_site(path)
                    print([i for i in newpaths])
                    res = await search_sitemap(path, newpaths, url)
                    if res:
                        return res
            return None

        page = await self.get_soup(url)
        links = link_finder(page, days)
        print('links are', links)
        lst = []
        for link in links.split(','):
            lst.append(link.split(';'))
        print('lst is', lst)
        lst = [
            [d, url + '/'.join(x.strip().strip('/').split('/')[1:]) + '/']
            if '//' not in x else [d, x.strip().rstrip('/') + '/']
            for d, x in lst
        ]
        return lst

        # parsed_url = urlparse(url)
        # sitemapurl = f"{parsed_url.scheme}://{parsed_url.netloc}" + '/sitemap.xml'
        # sitemap_paths = await self.search_site(sitemapurl)
        # articlespath = await search_sitemap(sitemapurl, sitemap_paths, url)
        # print('articles are', articlespath)
        # if 'rss' in articlespath:
        #    print("Достаю новости из RSS")
        # elif 'sitemap' in articlespath:
        #    print("Достаю новости из sitemap ссылки")
        # else:
        #    print("Достаю новости из HTML")

    async def odinc(self, soup, rng):
        print("Parsing ODINC")
        try:
            articles = {}

            tbody = soup.select_one(os.getenv('ODINC_LIST'))

            for item in tbody.find_all('tr', class_='pb-1'):
                time_el = item.find('td', class_='news-date-time').text.strip()
                link = item.find('a')
                article_date = datetime.strptime(time_el, '%d.%m.%Y').date()
                if rng[0] <= article_date <= rng[1]:
                    base_url = '/'.join(os.getenv('ODINC').split('/')[:-2])
                    ur = f"{base_url}{link.get('href')}"
                    page = await self.get_soup(ur)

                    if page:
                        txt = page.find('main', class_='p-3')
                        articles[ur] = [time_el, txt.text]
        except Exception as e:
            print(f"Error parsing ODINC: {e}")
            await self.bot.send_message(self.id, f"Ошибка парсинга ODINC: {e}")
            return None
        print(articles)
        return articles

    async def uchet(self, soup, rng):
        articles = {}

        tbody = soup.select_one(os.getenv('UCHET_LIST'))

        for item in tbody.find_all('div', class_='w-100'):
            time_el = item.find('small', class_='text-info').text.strip()
            link = item.find('a')
            article_date = datetime.strptime(time_el, '%d.%m.%Y').date()

            if rng[0] <= article_date <= rng[1]:
                base_url = '/'.join(os.getenv('UCHET').split('/')[:-2])
                ur = f"{base_url}{link.get('href')}"
                page = await self.get_soup(ur)

                if page:
                    txt = page.find('article', itemprop='articleBody')
                    articles[ur] = [time_el, txt.text]

        return articles

    async def mybuh(self, soup, rng):
        articles = {}

        tbody = soup.select_one("ul.popular-news__list.scroll")

        for item in tbody.find_all('li'):
            time_el = item.find('time')
            if not time_el:
                continue

            time_el = time_el.text.strip().split(', ')[0]
            link = item.find('a')
            article_date = datetime.strptime(time_el, '%d.%m.%Y').date()

            if rng[0] <= article_date <= rng[1]:
                base_url = '/'.join(os.getenv('MYBUH').split('/')[:-2])
                ur = f"{base_url}{link.get('href')}"
                page = await self.get_soup(ur)

                if page:
                    txt = page.find('div', class_='d_text')
                    articles[ur] = [time_el, txt.text]

        return articles

    async def pro1c(self, soup, rng):
        articles = {}

        tbody = soup.select_one(os.getenv('PRO1C_LIST'))

        for item in tbody.find_all('li'):
            time_el = item.find('small', class_='text-muted')
            if not time_el:
                continue

            time_el = time_el.text.strip()
            link = item.find('a')
            article_date = datetime.strptime(time_el, '%d.%m.%Y').date()

            if rng[0] <= article_date <= rng[1]:
                base_url = '/'.join(os.getenv('PRO1C').split('/')[:-2])
                ur = f"{base_url}{link.get('href')}"
                page = await self.get_soup(ur)

                if page:
                    txt = page.find('div', itemprop='articleBody')
                    articles[ur] = [time_el, txt.text]

        return articles

    async def gos24(self, soup, rng):
        articles = {}

        tbody = soup.select_one(os.getenv('GOS24_LIST'))

        for item in tbody.find_all('div', class_='news-block'):
            time_el = item.find('div', class_='date').text.strip()
            link = item.find('a')

            formatted_date = self.dateformat(time_el)
            article_date = datetime.strptime(formatted_date, '%d.%m.%Y').date()

            if rng[0] <= article_date <= rng[1]:
                ur = f"{os.getenv('GOS24')[:-1]}{link.get('href')}"
                page = await self.get_soup(ur)

                if page:
                    txt = page.find('div', class_='editor')
                    articles[ur] = [formatted_date, txt.text]

        return articles

    async def kgd(self, soup, rng, **nums):
        res = []

        tbody = soup.select_one(os.getenv('KGD_LIST'))

        for numtr in tbody.find_all('tr'):
            tds = numtr.find_all('td')
            if len(tds) < 2:
                continue

            first_td_text = tds[0].get_text(strip=True)
            last_td_link = tds[-1].find('a')
            time_el = tds[-2].find('span').text.strip()
            if not any(c.isdigit() for c in time_el):
                continue
            article_date = datetime.strptime(time_el, '%d.%m.%Y').date()

            if rng[0] <= article_date <= rng[1] and first_td_text and last_td_link and first_td_text in nums['nums']:
                form_number = first_td_text
                download_link = last_td_link.get('href')
                res.append((form_number, article_date.strftime('%d.%m.%Y'), download_link))

        return res

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

    @staticmethod
    def parse_days(days):

        now = datetime.now().date()

        mode = days[0]
        if mode == 'int':
            delta = days[1]
            start_date = now - timedelta(days=delta)
            return start_date, now
        elif mode == 'one day':
            date_str = days[1]
            date_obj = datetime.strptime(date_str, '%d.%m.%Y').date()
            return date_obj, date_obj
        elif mode == 'range':
            start_str = days[1]
            end_str = days[2]
            start_date = datetime.strptime(start_str, '%d.%m.%Y').date()
            end_date = datetime.strptime(end_str, '%d.%m.%Y').date()
            return start_date, end_date
        else:
            delta = int(os.getenv('LAST_DAYS', 3))
            start_date = now - timedelta(days=delta)
            return start_date, now
