# Site Text Audit

Инструмент для автоматизированного аудита текстового контента сайта QIFA с использованием LLM GigaChat.

Приложение обходит выбранный модуль сайта, извлекает текстовые блоки, отправляет их на проверку в GigaChat и формирует Excel-отчёт с найденными орфографическими, грамматическими, пунктуационными, логическими и стилистическими ошибками.

Проект рассчитан на модульный прогон большого сайта: вместо проверки всех страниц одним запуском сайт делится на смысловые разделы, каждый из которых можно проверять отдельно.

---

## Возможности

- модульный обход сайта;
- извлечение текстового контента из HTML;
- фильтрация технического и нерелевантного DOM-контента;
- проверка текста через GigaChat API;
- фиксация найденных ошибок, пояснений и предложенных исправлений;
- генерация Excel-отчёта;
- хранение отчётов в отдельной директории `reports/`;
- возможность интеграции с OpenClaw;
- подготовленная MCP-обёртка для дальнейшего подключения как tool;
- поддержка динамических страниц через Selenium;
- возобновление обхода (resume);
- промежуточные checkpoint-сохранения.

---

## Технологический стек

- Python 3.12
- requests
- BeautifulSoup4
- pandas
- openpyxl
- python-dotenv
- gigachat
- MCP Python SDK
- OpenClaw
- Git

---

## Структура проекта

```text
site_text_audit/
├── task.py              # основной скрипт аудита
├── task-selenium.py     # версия с Selenium, resume и checkpoint
├── modules.json         # описание модулей сайта
├── mcp_server.py        # MCP-обёртка для tool-вызова
├── SKILL.md             # описание skill для OpenClaw
├── README.md            # документация проекта
├── .env                 # локальные секреты, не коммитить
├── .gitignore
└── reports/             # Excel-отчёты
```

---

## Установка

Перейдите в директорию проекта:

```bash
cd ~/.openclaw/workspace/skills/site_text_audit
```

Активируйте виртуальное окружение:

```bash
source ~/openclaw-env/bin/activate
```

Установите зависимости:

```bash
pip install requests beautifulsoup4 pandas openpyxl python-dotenv gigachat mcp
```

Если в проекте есть `requirements.txt`, можно установить зависимости так:

```bash
pip install -r requirements.txt
```

---

## Настройка GigaChat

Создайте файл `.env` в корне проекта:

```bash
nano .env
```

Пример содержимого:

```env
GIGACHAT_CREDENTIALS=your_credentials
GIGACHAT_SCOPE=GIGACHAT_API_B2B
GIGACHAT_VERIFY_SSL=false
GIGACHAT_MODEL=GigaChat-2-Pro
```

Параметры:

- `GIGACHAT_CREDENTIALS` — ключ авторизации GigaChat API;
- `GIGACHAT_SCOPE` — scope доступа, например `GIGACHAT_API_B2B`;
- `GIGACHAT_VERIFY_SSL` — проверка SSL-сертификатов;
- `GIGACHAT_MODEL` — модель GigaChat.

Файл `.env` содержит секреты и не должен попадать в Git.

---

## Проверка подключения к GigaChat

Перед запуском аудита рекомендуется проверить, что GigaChat API работает:

```bash
/home/qifa/openclaw-env/bin/python - <<'PY'
from dotenv import load_dotenv
from gigachat import GigaChat
import os

load_dotenv("/home/qifa/.openclaw/workspace/skills/site_text_audit/.env")

g = GigaChat(
    credentials=os.getenv("GIGACHAT_CREDENTIALS"),
    scope=os.getenv("GIGACHAT_SCOPE"),
    model=os.getenv("GIGACHAT_MODEL"),
    verify_ssl_certs=False,
    timeout=30
)

r = g.chat("Найди ошибку: Превет мир")
print(r.choices[0].message.content)
PY
```

Если ответ получен, можно запускать аудит.

---

## Модульная архитектура

Сайт проверяется не единым большим прогоном, а по модулям. Каждый модуль описан в `modules.json`.

Модуль определяет:

- название раздела;
- стартовые URL;
- разрешённые префиксы URL;
- режим обхода, например только точные URL.

Пример модуля:

```json
{
  "home": {
    "name": "Главная",
    "start_urls": [
      "https://www.qifa.ru/"
    ],
    "allowed_prefixes": [
      "https://www.qifa.ru/"
    ],
    "exact_urls_only": true
  }
}
```

---

## Доступные модули

Ниже приведён рекомендуемый список модулей для сайта QIFA.

| Модуль | Назначение | Команда запуска |
|---|---|---|
| `home` | Главная страница | `task.py home` |
| `full_site` | Полный обход сайта | `task.py full_site` |
| `catalog` | Каталог товаров, категории и листинги | `task.py catalog` |
| `sumki` | Раздел "Сумки и чемоданы" | `task.py sumki` |
| `sumki2` | Листинг сумок | `task.py sumki2` |
| `sumki_cards_selenium` | Карточки сумок через Selenium (с листинга) | `task.py sumki_cards_selenium` |
| `product` | Карточки товаров | `task.py product` |
| `help` | Помощь, FAQ, инструкции | `task.py help` |
| `news` | Новости | `task.py news` |
| `blog` | Статьи и блог | `task.py blog` |
| `company` | О компании и платформа | `task.py company` |
| `contacts` | Контакты | `task.py contacts` |
| `legal` | Юридические страницы | `task.py legal` |
| `marketing` | Лендинги, акции, маркетинговые страницы | `task.py marketing` |
| `search` | Поиск и поисковые страницы | `task.py search` |
| `user` | Личный кабинет и пользовательские разделы | `task.py user` |

Рекомендуется начинать с небольших модулей:

```text
home
contacts
legal
help
```

После проверки стабильности можно запускать крупные модули:

```text
catalog
product
full_site
```

---

## Пример `modules.json`

```json
{
  "home": {
    "name": "Главная",
    "start_urls": [
      "https://www.qifa.ru/"
    ],
    "allowed_prefixes": [
      "https://www.qifa.ru/"
    ],
    "exact_urls_only": true
  },
  "full_site": {
    "name": "Полный сайт",
    "start_urls": [
      "https://www.qifa.ru/"
    ],
    "allowed_prefixes": [
      "https://www.qifa.ru/"
    ]
  },
  "catalog": {
    "name": "Каталог",
    "start_urls": [
      "https://www.qifa.ru/market/postavka-so-sklada-rf",
      "https://www.qifa.ru/market/postavka-s-proizvodstva-knr"
    ],
    "allowed_prefixes": [
      "https://www.qifa.ru/catalog",
      "https://www.qifa.ru/chigoods",
      "https://www.qifa.ru/market"
    ]
  },
  "product": {
    "name": "Карточки товаров",
    "start_urls": [
      "https://www.qifa.ru/chigoods"
    ],
    "allowed_prefixes": [
      "https://www.qifa.ru/chigoods"
    ]
  },
  "help": {
    "name": "Помощь",
    "start_urls": [
      "https://www.qifa.ru/help"
    ],
    "allowed_prefixes": [
      "https://www.qifa.ru/help"
    ]
  },
  "news": {
    "name": "Новости",
    "start_urls": [
      "https://www.qifa.ru/news"
    ],
    "allowed_prefixes": [
      "https://www.qifa.ru/news"
    ]
  },
  "blog": {
    "name": "Блог",
    "start_urls": [
      "https://www.qifa.ru/article"
    ],
    "allowed_prefixes": [
      "https://www.qifa.ru/article"
    ]
  },
  "company": {
    "name": "О компании",
    "start_urls": [
      "https://www.qifa.ru/o-kompanii",
      "https://www.qifa.ru/platform"
    ],
    "allowed_prefixes": [
      "https://www.qifa.ru/o-kompanii",
      "https://www.qifa.ru/platform"
    ]
  },
  "contacts": {
    "name": "Контакты",
    "start_urls": [
      "https://www.qifa.ru/contacts"
    ],
    "allowed_prefixes": [
      "https://www.qifa.ru/contacts"
    ]
  },
  "legal": {
    "name": "Юридические страницы",
    "start_urls": [
      "https://www.qifa.ru/confidentiality",
      "https://www.qifa.ru/passport-license",
      "https://www.qifa.ru/passport-privacy"
    ],
    "allowed_prefixes": [
      "https://www.qifa.ru/confidentiality",
      "https://www.qifa.ru/passport-license",
      "https://www.qifa.ru/passport-privacy"
    ]
  },
  "marketing": {
    "name": "Маркетинг и лендинги",
    "start_urls": [
      "https://www.qifa.ru/"
    ],
    "allowed_prefixes": [
      "https://www.qifa.ru/smart-delivery",
      "https://www.qifa.ru/window_to_china",
      "https://www.qifa.ru/market"
    ]
  },
  "search": {
    "name": "Поиск",
    "start_urls": [
      "https://www.qifa.ru/"
    ],
    "allowed_prefixes": [
      "https://www.qifa.ru/search"
    ]
  },
  "user": {
    "name": "Личный кабинет",
    "start_urls": [
      "https://www.qifa.ru/member/login"
    ],
    "allowed_prefixes": [
      "https://www.qifa.ru/member"
    ]
  }
}
```

---



---

## Работа с динамическими страницами (Selenium)

В проекте добавлен альтернативный скрипт:

`task-selenium.py`

Он используется для страниц с динамической подгрузкой (infinite scroll, JS-контент).


## Как запускать модули (обычный режим vs Selenium)

В проекте есть **два скрипта запуска**:

* `task.py` — стандартный обход (requests)
* `task-selenium.py` — обход с поддержкой Selenium

Важно:
**Selenium НЕ включается автоматически через параметр модуля.**
Нужно запускать соответствующий скрипт.

### Обычные модули (без Selenium)

Запускаются через:

python task.py MODULE

Примеры:

python task.py home
python task.py catalog
python task.py product
python task.py help
python task.py blog

Эти модули используют:

* requests
* статический HTML
* быстрый обход


### Модули с Selenium

Если модуль использует параметр:

```json
"use_selenium": true
```

то его нужно запускать через:

```bash
python task-selenium.py MODULE
```

---

### Текущие Selenium-модули

| Модуль                 | Как запускать                                  | Назначение                                     |
| ---------------------- | ---------------------------------------------- | ---------------------------------------------- |
| `sumki_cards_selenium` | `python task-selenium.py sumki_cards_selenium` | сбор карточек товаров с динамического листинга |

---

### Почему это важно

Если запустить Selenium-модуль через `task.py`:

python task.py sumki_cards_selenium

то:

* Selenium НЕ будет использован
* динамический контент не загрузится
* часть страниц/товаров не попадёт в аудит


### Рекомендация

* использовать `task.py` для большинства модулей (быстрее);
* использовать `task-selenium.py` только там, где есть:

  * infinite scroll
  * динамическая подгрузка
  * карточки, которых нет в HTML.



### Возможности

- headless Chrome (selenium);
- автоматическая прокрутка страницы до полной загрузки;
- обработка динамического контента;
- возобновление обхода после остановки;
- checkpoint-сохранения.

### Дополнительные параметры модулей

#### use_selenium

Включает загрузку страницы через Selenium:

```json
"use_selenium": true
```


#### link_source_only

Стартовые URL используются только как источник ссылок:

```json
"link_source_only": true
```

- текст не проверяется;
- проверяются только найденные страницы.


#### no_follow_on_targets

Отключает дальнейший обход:

```json
"no_follow_on_targets": true
```

Используется для точечного сбора карточек.

---


## Запуск аудита

Формат запуска:

```bash
/home/qifa/openclaw-env/bin/python task.py MODULE
```

где `MODULE` — ключ модуля из `modules.json`.

Примеры:

```bash
/home/qifa/openclaw-env/bin/python task.py home
/home/qifa/openclaw-env/bin/python task.py contacts
/home/qifa/openclaw-env/bin/python task.py help
/home/qifa/openclaw-env/bin/python task.py catalog
```

---

## Результат выполнения

После завершения скрипт выводит JSON:

```json
{
  "ok": true,
  "module": "home",
  "module_name": "Главная",
  "pages_checked": 1,
  "issues_found": 2,
  "xlsx": "/home/qifa/.openclaw/workspace/skills/site_text_audit/reports/site_audit_qifa_home_2026-04-28_12-00-00.xlsx"
}
```

Поля:

- `ok` — статус выполнения;
- `module` — ключ модуля;
- `module_name` — человекочитаемое название;
- `pages_checked` — количество проверенных страниц;
- `issues_found` — количество найденных ошибок;
- `xlsx` — путь к Excel-отчёту.

---

## Где сохраняются отчёты

Все Excel-отчёты сохраняются в папку:

```text
reports/
```

Пример имени файла:

```text
site_audit_qifa_home_2026-04-28_12-00-00.xlsx
```

Формат имени:

```text
site_audit_qifa_<module>_<timestamp>.xlsx
```

---

## Структура Excel-отчёта

Excel-файл содержит один лист:

```text
Ошибки
```

Колонки:

| Колонка | Описание |
|---|---|
| `module` | модуль проверки |
| `url` | URL страницы |
| `block_id` | идентификатор текстового блока |
| `html_tag` | HTML-тег источника текста |
| `fragment` | фрагмент с ошибкой |
| `error_type` | тип ошибки |
| `problem` | пояснение проблемы |
| `suggestion` | предложенное исправление |

---

## Использование через OpenClaw

Команда для запуска из OpenClaw через `exec`:

```text
выполни:
/home/qifa/openclaw-env/bin/python /home/qifa/.openclaw/workspace/skills/site_text_audit/task.py home
```

Для другого модуля:

```text
выполни:
/home/qifa/openclaw-env/bin/python /home/qifa/.openclaw/workspace/skills/site_text_audit/task.py help
```

---

## MCP-сервер

В проекте может использоваться MCP-обёртка `mcp_server.py`.

Проверка запуска:

```bash
/home/qifa/openclaw-env/bin/python mcp_server.py
```

Если процесс не завершается, это нормально: MCP-сервер работает в режиме ожидания клиента.

Остановить сервер можно через:

```text
Ctrl + C
```

Важно: наличие `mcp_server.py` не означает, что OpenClaw автоматически подключил MCP tool. MCP-сервер должен быть отдельно зарегистрирован в MCP-клиенте.

---

## Рекомендуемый порядок прогона

Для первичной проверки:

```bash
/home/qifa/openclaw-env/bin/python task.py home
/home/qifa/openclaw-env/bin/python task.py contacts
/home/qifa/openclaw-env/bin/python task.py legal
```

Для расширенной проверки:

```bash
/home/qifa/openclaw-env/bin/python task.py help
/home/qifa/openclaw-env/bin/python task.py news
/home/qifa/openclaw-env/bin/python task.py blog
/home/qifa/openclaw-env/bin/python task.py company
```

Для большого прогона:

```bash
/home/qifa/openclaw-env/bin/python task.py catalog
/home/qifa/openclaw-env/bin/python task.py product
/home/qifa/openclaw-env/bin/python task.py full_site
```

---

## Ограничения

- качество результата зависит от качества ответа GigaChat;
- возможны rate limits со стороны API;
- закрытые пользовательские разделы могут быть недоступны без авторизации;
- динамический JS-контент может извлекаться не полностью;
- большой прогон может занимать длительное время.

---

## Диагностика ошибок

### Ошибка `GIGACHAT_CREDENTIALS is not set`

Проверьте наличие `.env`:

```bash
cat .env
```

### Ошибка `401 Unauthorized`

Credentials неправильные или устарели.

### Ошибка `402 Payment Required`

Credentials приняты, но нет активной квоты или оплаты.

### Ошибка `429 Too Many Requests`

Достигнут лимит запросов. Нужно подождать или уменьшить частоту вызовов.

### Ошибка чтения `modules.json`

Проверьте JSON:

```bash
python -m json.tool modules.json
```

---

## Git

Перед коммитом убедитесь, что секреты и отчёты не попадут в репозиторий.

Рекомендуемый `.gitignore`:

```gitignore
.env
__pycache__/
*.pyc
reports/
*.xlsx
*.csv
```

---

## План развития

- асинхронный crawler;
- очередь задач;
- сохранение результатов в базу данных;
- веб-интерфейс для запуска аудитов;
- полноценное подключение MCP tool к OpenClaw;
- сравнение отчётов между прогонами;
- группировка ошибок по типам;
- поддержка пользовательских правил проверки.

---

## Автор

Irene
