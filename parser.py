import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
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
        # Исправлено: "24r" заменено на стандартный "r"
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


def parse_article(url):
    """Парсит заголовок и тело статьи с Turkmenportal"""
    try:
        # Добавили полноценные заголовки, чтобы сайт отдавал корректную верстку
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
        }
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"Ошибка запроса к статье ({response.status_code}): {url}")
            return None

        soup = BeautifulSoup(response.text, "html.parser")

        # 1. Поиск заголовка (пробуем класс single-title, затем любой h1, затем тег title)
        title_tag = soup.find("h1", class_="single-title") or soup.find("h1")
        if title_tag:
            title_text = title_tag.text.strip()
        else:
            title_text = soup.title.text.replace("- Turkmenportal", "").strip() if soup.title else "Без названия"

        # 2. Поиск основного текста статьи
        # На Turkmenportal контент обычно обернут в класс 'vul-content' или 'post-content'
        content_div = (
            soup.find("div", class_="vul-content") or 
            soup.find("div", class_="post-content") or
            soup.find("article")
        )

        if content_div:
            # Очищаем от ненужных скриптов или рекламы, если они есть внутри
            for s in content_div(["script", "style"]):
                s.decompose()
            content_html = str(content_div)
        else:
            # Если блок не найден, собираем все абзацы p, которые есть на странице (крайний случай)
            paragraphs = soup.find_all("p")
            if paragraphs:
                content_html = "".join([str(p) for p in paragraphs if len(p.text.strip()) > 10])
            else:
                content_html = "Не удалось распарсить текст."

        return title_text, content_html
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
            # Ищем все ссылки, содержащие паттерн новостей
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
                            title, content = article_data
                            email_body = f"""
                            <h2><a href="{href}">{title}</a></h2>
                            <hr>
                            <div>{content}</div>
                            <br><br>
                            <small>Источник: {href}</small>
                            """
                            send_email(
                                f"[Turkmenportal {lang.upper()}] {title}",
                                email_body,
                            )

            if new_max_id > last_saved_id:
                save_last_id(lang, new_max_id)

        except Exception as e:
            print(f"Ошибка при обработке ленты {lang}: {e}")


if __name__ == "__main__":
    check_news()
