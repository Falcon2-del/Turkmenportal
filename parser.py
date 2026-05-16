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

# Файлы для хранения ID последней обработанной новости (чтобы не спамить)
DB_FILES = {"ru": "last_id_ru.txt", "tm": "last_id_tm.txt"}


def get_last_saved_id(lang):
    if os.path.exists(DB_FILES[lang]):
        with open(DB_FILES[lang], "24r") as f:
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
    """Парсит содержимое конкретной статьи"""
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, "html.parser")

        # Селекторы могут незначительно меняться, берем стандартный заголовок и текст
        title = soup.find("h1")
        title_text = title.text.strip() if title else "Без названия"

        # Ищем основной блок текста (на Turkmenportal это обычно класс .text-theme или .article-content)
        content_div = soup.find("div", class_="article-content") or soup.find(
            "div", class_="text-theme"
        )
        content_html = str(content_div) if content_div else "Не удалось распарсить текст."

        return title_text, content_html
    except Exception as e:
        print(f"Ошибка при парсинге статьи {url}: {e}")
        return None


def check_news():
    # Для корректной работы сохранения состояния в GitHub Actions коммитить изменения обратно сложно,
    # поэтому мы просто проверяем свежие новости за один запуск.
    # Если вам нужна строгая история, лучше использовать GitHub Artifacts или внешнюю БД.
    # В данном примере скрипт отправляет ТОП-3 свежих новостей, если они обновились.

    for lang, url in URLS.items():
        print(f"Проверка новостей для языка: {lang}...")
        try:
            response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if response.status_code != 200:
                print(f"Не удалось получить доступ к {url}")
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            links = soup.find_all("a", href=re.compile(rf"/{lang}/news/\d+"))

            last_saved_id = get_last_saved_id(lang)
            new_max_id = last_saved_id

            # Собираем уникальные ссылки на новости
            processed_urls = set()
            for link in links:
                href = link["href"]
                if not href.startswith("http"):
                    href = "https://turkmenportal.com" + href

                # Извлекаем ID из ссылки
                match = re.search(r"/news/(\d+)", href)
                if match:
                    news_id = int(match.group(1))

                    # Если новость новее, чем сохраненная (или это первый запуск)
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
                            {content}
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