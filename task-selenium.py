#!/usr/bin/env python3
"""
Site Text Audit – парсер + ИИ аудит текстов на ошибки.
Поддерживает обычный requests, Selenium для динамических страниц,
промежуточные сохранения и возобновление после прерывания.
"""

import os
import re
import sys
import json
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import requests
import pandas as pd
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from gigachat import GigaChat

# ------------------- Selenium (для динамических страниц) ------------------- #
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
# ---------------------------------------------------------------------------- #

BASE_DIR = Path(__file__).resolve().parent
MODULES_PATH = BASE_DIR / "modules.json"
REPORTS_DIR = BASE_DIR / "reports"

load_dotenv(BASE_DIR / ".env")

GIGACHAT_CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS")
GIGACHAT_SCOPE = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_B2B")
GIGACHAT_MODEL = os.getenv("GIGACHAT_MODEL", "GigaChat-2")
GIGACHAT_VERIFY_SSL = os.getenv("GIGACHAT_VERIFY_SSL", "false").lower() == "true"

if not GIGACHAT_CREDENTIALS:
    raise RuntimeError("GIGACHAT_CREDENTIALS is not set in .env")

giga = GigaChat(
    credentials=GIGACHAT_CREDENTIALS,
    scope=GIGACHAT_SCOPE,
    model=GIGACHAT_MODEL,
    verify_ssl_certs=GIGACHAT_VERIFY_SSL,
    timeout=60,
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 site-text-audit-bot"
}

BLOCKED_PREFIXES = [
    "https://www.qifa.ru/member",
    "https://www.qifa.ru/shopping-cart",
    "https://www.qifa.ru/compare",
    "https://www.qifa.ru/passport",
    "https://www.qifa.ru/login",
    "https://www.qifa.ru/logout"
]

BLOCKED_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar", ".7z",
    ".mp4", ".mp3", ".avi", ".mov"
)


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc.lower()
    if netloc == "qifa.ru":
        netloc = "www.qifa.ru"
    path = parsed.path.rstrip("/")
    if not path:
        path = "/"
    return urlunparse((scheme, netloc, path, "", "", ""))


def is_blocked_url(url: str) -> bool:
    normalized = normalize_url(url)
    if any(normalized.startswith(prefix) for prefix in BLOCKED_PREFIXES):
        return True
    path = urlparse(normalized).path.lower()
    if path.endswith(BLOCKED_EXTENSIONS):
        return True
    return False


def is_allowed_url(url: str, allowed_prefixes: list[str]) -> bool:
    normalized = normalize_url(url)
    if is_blocked_url(normalized):
        return False
    return any(
        normalized.startswith(normalize_url(prefix).rstrip("/"))
        for prefix in allowed_prefixes
    )


def is_useful_text(text: str) -> bool:
    if len(text) < 40:
        return False
    if " " not in text:
        return False
    low = text.lower()
    noise_fragments = [
        "cookie", "javascript", "whatsapp", "telegram",
        "личный кабинет", "избранное", "корзина", "сравнение",
        "войти", "регистрация", "choose file", "go to slide",
        "previous slide", "next slide"
    ]
    if any(fragment in low for fragment in noise_fragments):
        return False
    return True


# ------------------- Selenium helpers ------------------- #
def get_html_selenium(url: str, stable_threshold: int = 3, max_wait_between_scrolls: int = 4) -> str:
    """
    Загружает страницу через headless Chrome и прокручивает до тех пор,
    пока высота страницы не перестанет увеличиваться stable_threshold раз подряд.
    """
    print(f"[SELENIUM] Загружаю {url} с бесконечной прокруткой...", file=sys.stderr, flush=True)
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.page_load_strategy = 'eager'

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()),
                              options=options)
    driver.set_page_load_timeout(25)
    try:
        driver.get(url)
        time.sleep(3)  # начальная подгрузка

        stable_count = 0
        last_height = driver.execute_script("return document.body.scrollHeight")
        scroll_attempts = 0

        while stable_count < stable_threshold:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)  # пауза на подгрузку
            new_height = driver.execute_script("return document.body.scrollHeight")

            if new_height == last_height:
                stable_count += 1
                print(f"[SELENIUM] Высота не изменилась ({stable_count}/{stable_threshold})",
                      file=sys.stderr, flush=True)
            else:
                stable_count = 0  # сброс, так как ещё что-то подгрузилось
                print(f"[SELENIUM] Увеличение высоты: {last_height} -> {new_height}",
                      file=sys.stderr, flush=True)
                last_height = new_height

            scroll_attempts += 1
            # На всякий случай – аварийный выход после очень большого числа попыток
            if scroll_attempts > 100:
                print("[SELENIUM] Достигнут лимит в 100 прокруток, завершаю.", file=sys.stderr, flush=True)
                break

        print(f"[SELENIUM] Прокрутка завершена после {scroll_attempts} шагов.", file=sys.stderr, flush=True)
        html = driver.page_source
    finally:
        driver.quit()
    return html


# ------------------- Core extraction ------------------- #
def extract_text_and_links(url: str, html: str = None):
    """
    Извлекает текстовые блоки и ссылки.
    Если html передан, использует его, иначе загружает через requests.
    """
    if html is None:
        response = requests.get(url, headers=HEADERS, timeout=25)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if "text/html" not in content_type:
            return [], []
        html = response.text

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()

    text_blocks = []
    seen_texts = set()
    block_id = 1

    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "span", "div"]):
        value = clean_text(el.get_text(" "))
        if not is_useful_text(value):
            continue
        if value in seen_texts:
            continue
        seen_texts.add(value)
        text_blocks.append({
            "block_id": block_id,
            "tag": el.name,
            "text": value
        })
        block_id += 1

    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href:
            continue
        if href.startswith(("mailto:", "tel:", "javascript:", "whatsapp:", "tg:")):
            continue
        absolute = normalize_url(urljoin(url, href))
        links.append(absolute)

    return text_blocks, links


def load_modules():
    if not MODULES_PATH.exists():
        raise FileNotFoundError(f"modules.json not found: {MODULES_PATH}")
    with open(MODULES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ------------------- Crawling ------------------- #
def crawl_module(module: dict, module_id: str = ""):
    """Обход модуля с учётом ранее посещённых URL (для возобновления)."""
    start_urls = [normalize_url(url) for url in module["start_urls"]]
    allowed_prefixes = [normalize_url(prefix) for prefix in module["allowed_prefixes"]]

    exact_urls_only = bool(module.get("exact_urls_only", False))
    link_source_only = bool(module.get("link_source_only", False))
    source_urls = set(start_urls) if link_source_only else set()

    # Файл с посещёнными URL для этого модуля
    visited_file = REPORTS_DIR / f"visited_{module_id}.txt"
    REPORTS_DIR.mkdir(exist_ok=True)

    # Загружаем уже посещённые URL, если файл существует
    if visited_file.exists():
        with open(visited_file, "r", encoding="utf-8") as f:
            visited = set(line.strip() for line in f if line.strip())
        print(f"[RESUME] Найдено {len(visited)} уже посещённых URL", file=sys.stderr, flush=True)
    else:
        visited = set()

    # Очередь: исключаем уже посещённые
    queue = [url for url in start_urls if url not in visited]
    pages = []

    while queue:
        url = normalize_url(queue.pop(0))

        print(f"[CRAWL] ({len(queue)} в очереди) ➜ {url}", file=sys.stderr, flush=True)

        if url in visited:
            continue

        if exact_urls_only and url not in source_urls:
            continue

        # --- Режим "только источник ссылок" ---
        if link_source_only and url in source_urls:
            try:
                if module.get("use_selenium"):
                    html = get_html_selenium(url)
                    _, links = extract_text_and_links(url, html=html)
                else:
                    _, links = extract_text_and_links(url)

                # Сохраняем как посещённый
                with open(visited_file, "a", encoding="utf-8") as f:
                    f.write(url + "\n")
                visited.add(url)

                for link in links:
                    link = normalize_url(link)
                    if link in visited:
                        continue
                    if is_allowed_url(link, allowed_prefixes):
                        queue.append(link)
                time.sleep(0.5)
            except Exception as e:
                print(f"[LINK SOURCE ERROR] {url}: {e}", file=sys.stderr, flush=True)
                with open(visited_file, "a", encoding="utf-8") as f:
                    f.write(url + "\n")
                visited.add(url)
            continue

        # --- Обычная проверка URL ---
        if not is_allowed_url(url, allowed_prefixes):
            continue

        try:
            text_blocks, links = extract_text_and_links(url)

            print(f"[EXTRACT] ✓ {url} — блоков: {len(text_blocks)}", file=sys.stderr, flush=True)

            pages.append({
                "url": url,
                "text_blocks": text_blocks,
                "technical_error": ""
            })

            with open(visited_file, "a", encoding="utf-8") as f:
                f.write(url + "\n")
            visited.add(url)

            # ВАЖНО: не добавляем новые ссылки, если стоит флаг no_follow_on_targets
            if not exact_urls_only and not module.get("no_follow_on_targets", False):
                for link in links:
                    link = normalize_url(link)
                    if link in visited:
                        continue
                    if is_allowed_url(link, allowed_prefixes):
                        queue.append(link)

            time.sleep(0.5)

        except Exception as e:
            pages.append({
                "url": url,
                "text_blocks": [],
                "technical_error": str(e)
            })
            with open(visited_file, "a", encoding="utf-8") as f:
                f.write(url + "\n")
            visited.add(url)

    return pages


# ------------------- Chunking & GigaChat ------------------- #
def make_chunks(text_blocks, max_chars=4500):
    chunks = []
    current_lines = []
    current_len = 0

    for block in text_blocks:
        clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', block["text"])
        safe_text = clean.replace('"', "'")
        line = f'BLOCK_ID={block["block_id"]}; TAG={block["tag"]}; TEXT="{safe_text}"'
        line_len = len(line)

        if current_lines and current_len + line_len > max_chars:
            chunks.append("\n".join(current_lines))
            current_lines = [line]
            current_len = line_len
        else:
            current_lines.append(line)
            current_len += line_len

    if current_lines:
        chunks.append("\n".join(current_lines))

    return chunks


def extract_json_array(text: str):
    cleaned = text.strip()
    cleaned = cleaned.replace("```json", "").replace("```", "").strip()
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("JSON array not found")
    return json.loads(cleaned[start:end + 1])


def check_chunk(url: str, chunk: str):
    print(f"[GIGA] ✉ Чанк ({len(chunk)} симв.) для {url}…", file=sys.stderr, flush=True)

    prompt = f"""
Ты профессиональный корректор и редактор русскоязычных сайтов.

Нужно найти только реальные ошибки:
- орфографические
- грамматические
- пунктуационные
- логические
- стилистические

Не считай ошибками:
- элементы меню
- названия категорий
- отдельные слова
- кнопки
- отсутствие контекста
- SEO-фразы без явной ошибки
- технические артикулы
- названия брендов
- коды товаров

Каждая строка имеет формат:
BLOCK_ID=номер; TAG=html_тег; TEXT="текст"

Верни строго JSON-массив.
Без markdown, без комментариев, без текста до или после JSON.

Формат:
[
  {{
    "block_id": 1,
    "error_type": "орфография|грамматика|пунктуация|логика|стиль|другое",
    "fragment": "точная цитата с ошибкой",
    "problem": "объяснение ошибки",
    "suggestion": "исправленный вариант"
  }}
]

Если ошибок нет, верни:
[]

URL:
{url}

Текст:
{chunk}
"""

    response = giga.chat(prompt)
    content = response.choices[0].message.content.strip()
    issues = extract_json_array(content)
    print(f"[GIGA] ✔ Ошибок в чанке: {len(issues)}", file=sys.stderr, flush=True)
    return issues


# ------------------- Excel сохранение ------------------- #
def save_dataframe_to_excel(path: Path, rows: list, module_id: str):
    if rows:
        df = pd.DataFrame(rows)
    else:
        df = pd.DataFrame([{
            "module": module_id,
            "url": "",
            "block_id": "",
            "html_tag": "",
            "fragment": "",
            "error_type": "none",
            "problem": "Ошибки не найдены",
            "suggestion": ""
        }])
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Ошибки", index=False)


def save_report(module_id: str, rows: list):
    REPORTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    xlsx_path = REPORTS_DIR / f"site_audit_qifa_{module_id}_{timestamp}.xlsx"
    save_dataframe_to_excel(xlsx_path, rows, module_id)
    return xlsx_path


# ------------------- Аудит с чекпоинтами ------------------- #
def run_audit(module_id: str, module: dict, checkpoint_interval: int = 5):
    pages = crawl_module(module, module_id)
    rows = []
    total = len(pages)
    checkpoint_files = []

    for idx, page in enumerate(pages, 1):
        url = page["url"]
        print(f"[AUDIT] Стр. {idx}/{total} — {url}", file=sys.stderr, flush=True)

        if page["technical_error"]:
            rows.append({
                "module": module_id,
                "url": url,
                "block_id": "",
                "html_tag": "",
                "fragment": "",
                "error_type": "technical",
                "problem": page["technical_error"],
                "suggestion": ""
            })
            continue

        block_map = {block["block_id"]: block for block in page["text_blocks"]}
        chunks = make_chunks(page["text_blocks"])

        for chunk in chunks:
            try:
                issues = check_chunk(url, chunk)
            except Exception as e:
                rows.append({
                    "module": module_id,
                    "url": url,
                    "block_id": "",
                    "html_tag": "",
                    "fragment": "",
                    "error_type": "technical",
                    "problem": f"Ошибка проверки через GigaChat: {e}",
                    "suggestion": ""
                })
                continue

            for issue in issues:
                block_id = issue.get("block_id")
                block = block_map.get(block_id, {})
                rows.append({
                    "module": module_id,
                    "url": url,
                    "block_id": block_id,
                    "html_tag": block.get("tag", ""),
                    "fragment": issue.get("fragment", ""),
                    "error_type": issue.get("error_type", ""),
                    "problem": issue.get("problem", ""),
                    "suggestion": issue.get("suggestion", "")
                })

        if idx % checkpoint_interval == 0:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            checkpoint_path = REPORTS_DIR / f"checkpoint_{module_id}_{timestamp}.xlsx"
            save_dataframe_to_excel(checkpoint_path, rows, module_id)
            checkpoint_files.append(checkpoint_path)
            print(f"[CHECKPOINT] Сохранено {len(rows)} записей в {checkpoint_path.name}",
                  file=sys.stderr, flush=True)

    xlsx_path = save_report(module_id, rows)

    for f in checkpoint_files:
        try:
            os.remove(f)
        except Exception:
            pass

    return rows, pages, xlsx_path


# ------------------- Main ------------------- #
def main():
    try:
        if len(sys.argv) < 2:
            raise Exception("Не указан модуль. Пример: python task.py home")

        module_id = sys.argv[1]
        modules = load_modules()

        if module_id not in modules:
            raise Exception(
                f"Неизвестный модуль: {module_id}. "
                f"Доступные модули: {', '.join(modules.keys())}"
            )

        module = modules[module_id]
        rows, pages, xlsx_path = run_audit(module_id, module)

        print(json.dumps({
            "ok": True,
            "module": module_id,
            "module_name": module.get("name", module_id),
            "pages_checked": len(pages),
            "issues_found": len(rows),
            "xlsx": str(xlsx_path)
        }, ensure_ascii=False, indent=2))

    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e)
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()