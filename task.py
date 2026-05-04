#!/usr/bin/env python3

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
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".zip",
    ".rar",
    ".7z",
    ".mp4",
    ".mp3",
    ".avi",
    ".mov"
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
        "cookie",
        "javascript",
        "whatsapp",
        "telegram",
        "личный кабинет",
        "избранное",
        "корзина",
        "сравнение",
        "войти",
        "регистрация",
        "choose file",
        "go to slide",
        "previous slide",
        "next slide"
    ]

    if any(fragment in low for fragment in noise_fragments):
        return False

    return True


def extract_text_and_links(url: str):
    response = requests.get(url, headers=HEADERS, timeout=25)
    response.raise_for_status()

    content_type = response.headers.get("content-type", "").lower()

    if "text/html" not in content_type:
        return [], []

    soup = BeautifulSoup(response.text, "html.parser")

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

    # Отладочный вывод собранных ссылок (можно закомментировать)
    print(f"[DEBUG] Собранные ссылки со страницы {url}:", file=sys.stderr, flush=True)
    for lnk in links:
        print(f"  {lnk}", file=sys.stderr, flush=True)

    return text_blocks, links


def load_modules():
    if not MODULES_PATH.exists():
        raise FileNotFoundError(f"modules.json not found: {MODULES_PATH}")

    with open(MODULES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def crawl_module(module: dict):
    start_urls = [normalize_url(url) for url in module["start_urls"]]
    allowed_prefixes = [
        normalize_url(prefix)
        for prefix in module["allowed_prefixes"]
    ]

    exact_urls_only = bool(module.get("exact_urls_only", False))
    link_source_only = bool(module.get("link_source_only", False))
    source_urls = set(start_urls) if link_source_only else set()

    queue = list(start_urls)
    visited = set()
    pages = []

    while queue:
        url = normalize_url(queue.pop(0))

        print(f"[CRAWL] ➜ Проверяю: {url}", file=sys.stderr, flush=True)

        if url in visited:
            continue

        if exact_urls_only and url not in source_urls:
            continue

        if link_source_only and url in source_urls:
            try:
                _, links = extract_text_and_links(url)   # получаем только ссылки
                visited.add(url)
                for link in links:
                    link = normalize_url(link)
                    if link in visited:
                        continue
                    if is_allowed_url(link, allowed_prefixes):
                        queue.append(link)
                time.sleep(0.5)
            except Exception:
                pass
            continue

        if not is_allowed_url(url, allowed_prefixes):
            continue

        try:
            text_blocks, links = extract_text_and_links(url)

            print(f"[EXTRACT] ✓ {url} — получено блоков: {len(text_blocks)}", file=sys.stderr, flush=True)

            pages.append({
                "url": url,
                "text_blocks": text_blocks,
                "technical_error": ""
            })

            visited.add(url)

            if not exact_urls_only:
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

            visited.add(url)

    return pages


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
    print(f"[GIGA] ✉ Отправка чанка ({len(chunk)} симв.) для {url}…", file=sys.stderr, flush=True)

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

    print(f"[GIGA] ✔ Ответ получен, ошибок в чанке: {len(issues)}", file=sys.stderr, flush=True)
    return issues


def run_audit(module_id: str, module: dict):
    pages = crawl_module(module)
    rows = []
    total = len(pages)

    for idx, page in enumerate(pages, 1):
        url = page["url"]
        print(f"[AUDIT] Страница {idx}/{total} — {url}", file=sys.stderr, flush=True)

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

        block_map = {
            block["block_id"]: block
            for block in page["text_blocks"]
        }

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

    return rows, pages


def save_report(module_id: str, rows: list):
    REPORTS_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    xlsx_path = REPORTS_DIR / f"site_audit_qifa_{module_id}_{timestamp}.xlsx"

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

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Ошибки", index=False)

    return xlsx_path


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

        rows, pages = run_audit(module_id, module)
        xlsx_path = save_report(module_id, rows)

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