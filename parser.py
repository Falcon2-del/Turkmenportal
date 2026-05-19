import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

# Настройки из GitHub Secrets
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))

URLS = {
    "ru": "https://turkmenportal.com/ru/news",
    "tm": "https://turkmenportal.com/tm/news",
}

DB_FILES = {"ru": "last_id_ru.txt", "tm": "last_id_tm.txt"}


def get_last_saved_id(lang):
    if os.path.exists(DB_FILES[lang]):
        with open(DB_FILES[lang], "r") as f:
            try:
                return int(f.read().strip())
            except ValueError:
                return 0
    return 0


def save_last_id(lang, news_id):
    with open(DB_FILES[lang], "w") as f:
        f.write(str(news_id))


def send_email(subject, body_html):
    if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER]):
        print("Ошибка: Настройки почты (Secrets) не заполнены.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER

    msg.attach(MIMEText(body_html, "html", "utf-8"))

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
        server.quit()
        print(f"Письмо успешно отправлено: {subject}")
    except Exception as e:
        print(f"Ошибка отправки почты: {e}")


def format_to_custom_date(date_source):
    """Вспомогательная функция для приведения даты к формату ДД.ММ.ГГГГ ЧЧ:ММ:СС"""
    if not date_source:
        return None
    try:
        if isinstance(date_source, str) and (date_source.endswith("GMT") or date_source.endswith("UTC")):
            dt = datetime.strptime(date_source, "%a, %d %b %Y %H:%M:%S %Z")
            return dt.strftime("%d.%m.%Y %H:%M:%S")
        
        if isinstance(date_source, datetime):
            return date_source.strftime("%d.%m.%Y %H:%M:%S")
            
        dt = date_parser.parse(str(date_source))
        return dt.strftime("%d.%m.%Y %H:%M:%S")
    except Exception:
        return str(date_source)


def parse_article(url):
    """Парсит заголовок, дату и оригинальное тело статьи с Turkmenportal"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
        }
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"Ошибка запроса к статье ({response.status_code}): {url}")
            return None

        soup = BeautifulSoup(response.text, "html.parser")

        # 1. Поиск заголовка
        title_tag = soup.find("h1", class_="single-title") or soup.find("h1")
        if title_tag:
            title_text = title_tag.text.strip()
        else:
            title_text = soup.title.text.replace("- Turkmenportal", "").strip() if soup.title else "Без названия"

        # 2. Поиск даты публикации
        raw_date = None
        time_tag = soup.find("time")
        if time_tag:
            raw_date = time_tag.get("datetime") or time_tag.text.strip()
            
        if not raw_date:
            date_tag = soup.find(class_="vul-date") or soup.find(class_="date")
            if date_tag:
                raw_date = date_tag.text.strip()
            
        if not raw_date:
            meta_date = soup.find("meta", property="article:published_time") or soup.find("meta", itemprop="datePublished")
            if meta_date and meta_date.get("content"):
                raw_date = meta_date["content"]

        if not raw_date:
            raw_date = response.headers.get("Last-Modified") or response.headers.get("Date")

        if not raw_date:
            raw_date = datetime.now()

        date_text = format_to_custom_date(raw_date)

        # 3. Поиск основного текста статьи
        content_div = (
            soup.find("div", class_="vul-content") or 
            soup.find("div", class_="post-content") or
            soup.find("article")
        )

        if content_div:
            # Расширенный список селекторов для вырезания рекламы, блоков «Афиша», «Статьи» и виджетов
            unwanted_selectors = [
                "script", "style", ".interesting-news", ".related-news", 
                ".share-blocks", ".tags-block", ".comments-block", 
                "aside", ".read-also", ".banner", ".recommended-news",
                "#recommended", ".post-recommendations", 
                ".afisha-sidebar", ".article-sidebar", "[class*='afisha']", "[class*='article']"
            ]
            for selector in unwanted_selectors:
                for match in content_div.select(selector):
                    match.decompose()
            
            # РЕШЕНИЕ ПРОБЛЕМЫ С ФОТО (Lazy Loading + Абсолютные ссылки)
            for img in content_div.find_all("img"):
                # Если у картинки есть дата-атрибут с реальным изображением, берем его
                real_src = img.get("data-src") or img.get("data-original") or img.get("src")
                
                if real_src:
                    real_src = real_src.strip()
                    if not real_src.startswith("http"):
                        real_src = "https://turkmenportal.com" + real_src
                    
                    # Принудительно пишем правильный путь в src и убираем ленивую загрузку
                    img["src"] = real_src
                    if img.get("style"):
                        img["style"] = img["style"] + "; display: block; max-width: 100%; height: auto;"
                    else:
                        img["style"] = "display: block; max-width: 100%; height: auto;"
                    
            content_html = str(content_div)
        else:
            paragraphs = soup.find_all("p")
            if paragraphs:
                content_html = "".join([str(p) for p in paragraphs if len(p.text.strip()) > 10])
            else:
                content_html = "Не удалось распарсить текст."

        return title_text, date_text, content_html
    except Exception as e:
        print(f"Ошибка при парсинге статьи {url}: {e}")
        return None


def check_news():
    for lang, url in URLS.items():
        print(f"Проверка новостей для языка: {lang}...")
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                print(f"Не удалось получить доступ к ленте {url}")
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            links = soup.find_all("a", href=re.compile(rf"/{lang}/news/\d+"))

            last_saved_id = get_last_saved_id(lang)
            new_max_id = last_saved_id

            processed_urls = set()
            for link in links:
                href = link["href"]
                if not href.startswith("http"):
                    href = "https://turkmenportal.com" + href

                match = re.search(r"/news/(\d+)", href)
                if match:
                    news_id = int(match.group(1))

                    if news_id > last_saved_id and href not in processed_urls:
                        processed_urls.add(href)
                        if news_id > new_max_id:
                            new_max_id = news_id

                        print(f"Найдена новая статья [{lang}]: {href}")
                        article_data = parse_article(href)

                        if article_data:
                            title, date_str, content = article_data
                            
                            # Тело письма, повторяющее стили сайта + адаптивность для картинок
                            email_body = f"""
                            <div style="font-family: Arial, sans-serif; color: #333; line-height: 1.6; max-width: 800px; margin: 0 auto;">
                                <p style="color: #777; font-size: 14px; margin-bottom: 20px;">
                                    <strong>Дата публикации:</strong> {date_str}
                                </p>
                                <h2><a href="{href}" style="color: #0056b3; text-decoration: none;">{title}</a></h2>
                                <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
                                <div class="web-content-body">
                                    {content}
                                </div>
                                <br><br>
                                <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
                                <small style="color: #999;">Источник: <a href="{href}">{href}</a></small>
                            </div>
                            """
                            
                            send_email("Turkmenportal", email_body)

            if new_max_id > last_saved_id:
                save_last_id(lang, new_max_id)

        except Exception as e:
            print(f"Ошибка при обработке ленты {lang}: {e}")


if __name__ == "__main__":
    check_news()
