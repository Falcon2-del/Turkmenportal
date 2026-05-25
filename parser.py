import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
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


def parse_article(url):
    """Парсит заголовок, дату, титульное фото и всё содержимое из id='content'"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
        }
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"Ошибка запроса к статье ({response.status_code}): {url}")
            return None

        soup = BeautifulSoup(response.content, "html.parser", from_encoding=response.encoding)

        # 1. Заголовок
        title_tag = soup.find("div", class_="text-3xl font-bold lg:text-xl sm:leading-7")
        title_text = title_tag.text.strip() if title_tag else (soup.title.text if soup.title else "Без названия")
        title_text = re.sub(r"\s*-\s*Turkmenportal.*", "", title_text, flags=re.IGNORECASE)
        title_text = title_text.replace("turkmenportal.com", "").replace("Turkmenportal", "").strip()

        # 2. Дата публикации
        raw_date = None
        date_container = soup.find("div", class_="flex gap-4 items-center")
        if date_container:
            first_text = date_container.find(text=True)
            if first_text and first_text.strip():
                raw_date = first_text.strip()
        
        if not raw_date:
            time_tag = soup.find("time")
            if time_tag:
                raw_date = time_tag.get("datetime") or time_tag.text.strip()

        if not raw_date:
            raw_date = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

        # 3. Сборка контента
        content_parts = []
        html_images_seen = set()

        # Поиск главной ТИТУЛЬНОЙ картинки (обложки) на странице
        cover_tag = soup.find("img", class_=lambda x: x and "mx-auto" in x, width="500")
        if not cover_tag:
            cover_tag = soup.find("img", class_=lambda x: x and "mx-auto" in x)

        if cover_tag:
            cover_src = cover_tag.get("src")
            if cover_src and not cover_src.startswith("data:"):
                if not cover_src.startswith("http"):
                    cover_src = "https://turkmenportal.com" + cover_src
                
                # Добавляем титульное фото в самое начало контента письма
                content_parts.append(f'<div style="text-align: center; margin-bottom: 25px;"><img src="{cover_src}" style="max-width: 100%; height: auto; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.15); display: inline-block;" /></div>')
                html_images_seen.add(cover_src)

        # Сборка содержимого статьи строго из главного контейнера id="content"
        main_container = soup.find("div", id="content")

        if main_container:
            # Идем по всем элементам внутри контейнера по порядку их появления
            for element in main_container.find_all(True, recursive=False):
                
                # Если это обычный абзац текста
                if element.name == "p":
                    text_content = element.text.strip()
                    if text_content:
                        content_parts.append(f'<p style="margin-bottom: 15px; text-align: justify; font-size: 16px;">{text_content}</p>')
                
                # Если это блок с картинкой внутри статьи (теги картинок или span-обертки)
                else:
                    img_tag = element.find("img") if element.name != "img" else element
                    if img_tag:
                        src = img_tag.get("src")
                        if src and not src.startswith("data:"):
                            if not src.startswith("http"):
                                src = "https://turkmenportal.com" + src
                            
                            # Проверяем, чтобы картинка внутри статьи не дублировала заголовочную
                            if src not in html_images_seen:
                                html_images_seen.add(src)
                                if not any(x in src.lower() for x in ["icon", "eye", "avatar", "loader"]):
                                    content_parts.append(f'<div style="text-align: center; margin: 20px 0;"><img src="{src}" style="max-width: 100%; height: auto; border-radius: 6px; display: inline-block;" /></div>')

        # Запасной критический вариант сборки, если id="content" пуст
        if not main_container or len(content_parts) <= 1:
            paragraphs = soup.find_all("p", style=lambda x: x and "text-align: justify" in x)
            for p in paragraphs:
                if len(p.text.strip()) > 10:
                    content_parts.append(f'<p style="margin-bottom: 15px; text-align: justify;">{p.text.strip()}</p>')

        content_html = "\n".join(content_parts)
        return title_text, raw_date, content_html

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
                            
                            email_body = f"""
                            <html>
                            <head>
                                <meta charset="utf-8">
                                <style>
                                    body {{ font-family: Arial, sans-serif; color: #333; line-height: 1.6; background-color: #fff; margin: 0; padding: 20px; }}
                                    .container {{ max-width: 800px; margin: 0 auto; }}
                                    .meta {{ color: #777; font-size: 14px; margin-bottom: 20px; }}
                                    .title {{ color: #0056b3; text-decoration: none; font-size: 24px; font-weight: bold; line-height: 1.3; }}
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
