import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header  # Важно для корректных заголовков на кириллице и туркменском
from datetime import datetime
import requests
from bs4 import BeautifulSoup

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
    # Кодируем тему письма в UTF-8, чтобы избежать английских букв и кракозябр
    msg["Subject"] = Header(subject, "utf-8")
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
    """Возвращает оригинальный текст даты с сайта (сохраняя родной GMT+5) без конвертации"""
    if not date_source:
        return "Не указана"
    return str(date_source).strip()


def parse_article(url):
    """Парсит заголовок, дату, главное изображение и только нужные блоки текста статьи"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
        }
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"Ошибка запроса к статье ({response.status_code}): {url}")
            return None

        # Явно задаем кодировку ответа, чтобы не ломались специфичные туркменские и русские символы
        response.encoding = "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")

        # 1. Точечный поиск заголовка по указанному классу
        title_tag = soup.find("div", class_="text-3xl font-bold lg:text-xl sm:leading-7")
        title_text = title_tag.text.strip() if title_tag else "Без названия"

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
            raw_date = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

        date_text = format_to_custom_date(raw_date)

        # 3. Сборка контента (Только главное фото и параграфы с text-align: justify)
        content_parts = []

        # Ищем главное изображение статьи
        img_tag = soup.find("img", class_=lambda x: x and "mx-auto" in x and "cursor-pointer" in x)
        if img_tag:
            img_src = img_tag.get("src") or img_tag.get("data-src")
            if img_src:
                img_src = img_src.strip()
                if not img_src.startswith("http"):
                    img_src = "https://turkmenportal.com" + img_src
                
                content_parts.append(f'<img src="{img_src}" style="display: block; max-width: 100%; height: auto; margin: 15px auto; border-radius: 6px;" />')

        # Зачищаем ненужные блоки-параграфы (афиши, анонсы концертов), которые могут иметь стиль justify
        for bad_p in soup.find_all("p", class_=lambda x: x and ("line-clamp" in x or "text-center" in x)):
            bad_p.decompose()

        # Дополнительно чистим по ключевым классам родительских блоков рекламы/афиш
        for unwanted in soup.select("[class*='afisha'], [class*='banner'], .interesting-news, .related-news"):
            unwanted.decompose()

        # Ищем исключительно параграфы статьи с нужным стилем выравнивания
        paragraphs = soup.find_all("p", style=lambda x: x and "text-align: justify" in x)
        if paragraphs:
            for p in paragraphs:
                # Дополнительная проверка, чтобы мусорные строки не попали в финальный список
                p_text = p.text.strip()
                if p_text and not p.find_parent(class_=lambda x: x and "afisha" in x):
                    content_parts.append(str(p))
        
        # Если ничего не нашли по точным селекторам, подстраховываемся чистыми p без классов афиш
        if not content_parts or (len(content_parts) == 1 and img_tag):
            all_p = soup.find_all("p")
            valid_p = [str(p) for p in all_p if len(p.text.strip()) > 10 and not p.get("class")]
            if valid_p:
                content_parts.extend(valid_p)
            else:
                content_parts.append("<p>Не удалось распарсить текст статьи.</p>")

        content_html = "\n".join(content_parts)

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

            response.encoding = "utf-8"
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
                            
                            # Письмо в формате HTML с жестким указанием utf-8 в метатегах
                            email_body = f"""
                            <html>
                            <head>
                                <meta charset="utf-8">
                                <style>
                                    body {{ font-family: Arial, sans-serif; color: #333; line-height: 1.6; background-color: #fff; margin: 0; padding: 20px; }}
                                    .container {{ max-width: 800px; margin: 0 auto; }}
                                    .meta {{ color: #777; font-size: 14px; margin-bottom: 20px; }}
                                    .title {{ color: #0056b3; text-decoration: none; }}
                                    .content-body img {{ max-width: 100% !important; height: auto !important; display: block; margin: 15px auto; border-radius: 6px; }}
                                    .content-body p {{ margin-bottom: 15px; text-align: justify; }}
                                </style>
                            </head>
                            <body>
                                <div class="container">
                                    <p class="meta">
                                        <strong>Дата публикации:</strong> {date_str}
                                    </p>
                                    <h2><a href="{href}" class="title">{title}</a></h2>
                                    <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
                                    <div class="content-body">
                                        {content}
                                    </div>
                                    <br><br>
                                    <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;">
                                    <small style="color: #999;">Источник: <a href="{href}">{href}</a></small>
                                </div>
                            </body>
                            </html>
                            """
                            
                            send_email(title, email_body)

            if new_max_id > last_saved_id:
                save_last_id(lang, new_max_id)

        except Exception as e:
            print(f"Ошибка при обработке ленты {lang}: {e}")


if __name__ == "__main__":
    check_news()
