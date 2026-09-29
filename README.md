# AI Presentation Designer — v7.4.2

AI-сервис для создания редактируемых презентаций по текстовому брифу и загруженному PPTX-шаблону. Проект ориентирован на воспроизводимый локальный запуск на macOS/Windows. Docker сохранён как дополнительный способ запуска и деплоя; он не является обязательным условием сдачи и не требуется для обычной проверки проекта.

`brief / sources → research → deck plan → content → template parsing → rendering → audit → user-selected repair → export`

## Демо на GitHub Pages

[Открыть демо](https://veatum.github.io/ai-presentation-designer/).

[Полная версия на VPS](https://139.100.239.187) — открытый доступ на время хакатона.
Описание установки и обновления: [deploy/vps/README.md](deploy/vps/README.md).

На Pages опубликованы интерфейс и три готовых PPTX-примера. Генерация новых
презентаций, исследование и исправление слайдов требуют Python-сервера и на
GitHub Pages не выполняются. В демо загрузка файлов и поля формы отключены.
Для полной версии используйте локальный запуск или Docker, описанные ниже.

Pages публикуется из корня ветки `main`. `index.html` открывает интерфейс в
режиме демо; `.nojekyll` отключает обработку исходников через Jekyll.
При обычном запуске Python-приложения интерфейс продолжает работать с его API.

## 1. Что делает проект

- принимает краткий текстовый бриф;
- принимает контент-пакет и пользовательские документы;
- исследует веб-источники и сохраняет реальные URL как источники;
- строит структуру будущей колоды до этапа верстки;
- разбирает PPTX-шаблон во время выполнения и извлекает его размеры, layouts, placeholders, шрифты и палитру;
- переносит единый семантический план на три варианта композиции: `balanced`, `columns`, `editorial`;
- поддерживает три встроенных шаблона контент-пакета;
- создаёт нативные редактируемые PPTX-объекты: текст, таблицы, диаграммы и изображения;
- выполняет детерминированный аудит готового PPTX;
- показывает найденные замечания пользователю и исправляет только выбранные findings;
- экспортирует PPTX, PDF и HTML при наличии LibreOffice;
- поддерживает два режима изображений: retrieval из Openverse/Wikimedia Commons и опциональный text-to-image через Hugging Face.

## 2. Что соответствует кейсу

Подробная матрица находится в [TЗ_COVERAGE.md](TЗ_COVERAGE.md).

Ключевые элементы решения:

| Требование | Реализация |
|---|---|
| Парсинг шаблона | `core/template_parser.py` |
| Планирование колоды | `core/llm.py` + `prompts/` |
| Генерация содержания | `core/llm.py` + `prompts/` |
| Верстка | `core/renderer.py` |
| Аудит физического PPTX | `core/audit.py` |
| Семантический/content QA | `core/quality.py` + LLM stages |
| Выборочный repair | `app.py` + `core/llm.py` |
| Изображения | `core/image_research.py`, `core/image_generation.py` |
| Экспорт | `core/exporter.py` |
| Тесты | `tests/`, `scripts/final_test_suite.py` |
| Воспроизводимый запуск | `.env.example`, `START_MAC.sh` / `START_WINDOWS.bat`, `requirements.txt`; Docker — опционально |

## 3. Требования к окружению

### Локально

- Python 3.11+
- LibreOffice — нужен для PDF/preview export
- доступ к Cloud.ru Foundation Models API для генерации текста;
- для optional text-to-image: `HF_TOKEN`.

### Docker (опционально)

Docker-образ содержит Python-зависимости и LibreOffice и даёт максимально изолированный способ запуска. Для сдачи проекта Docker **не обязателен**: эксперт может запустить проект обычным Python-окружением на Windows/macOS.

## 4. Быстрый запуск через Docker (опционально)

```bash
cp .env.example .env
```

Заполнить минимум:

```dotenv
CLOUD_RU_API_KEY=your_key
```

Запустить:

```bash
docker compose up -d --build
```

Проверить:

```bash
curl http://127.0.0.1:8080/health
```

Открыть в браузере:

```text
http://127.0.0.1:8080
```

Полная инструкция: [DEPLOY_DOCKER.md](DEPLOY_DOCKER.md).

## 5. Локальный запуск без Docker — основной путь для Windows/macOS

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8090
```

macOS: `START.command` / `START_MAC.sh`.

Windows: `START_WINDOWS.bat`.

### 5.1 Windows — пошаговый запуск

1. Установите Python 3.11+ с официального сайта Python и при установке включите **Add Python to PATH**.
2. Установите LibreOffice, если нужны PDF/preview. Для нативного `.pptx`-экспорта LibreOffice не требуется.
3. Скопируйте репозиторий на Windows и откройте `cmd` или PowerShell в корне проекта.
4. Скопируйте `.env.example` в `.env` и укажите `CLOUD_RU_API_KEY`.
5. Запустите `START_WINDOWS.bat` двойным кликом или из терминала. Скрипт создаст `.venv`, установит зависимости и запустит сервер.
6. Откройте `http://127.0.0.1:8090`.

Ручной запуск, если автоматический `.bat` не используется:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8090
```

Полная Windows-инструкция: [WINDOWS_SETUP.md](WINDOWS_SETUP.md).


## 6. Переменные окружения

### Обязательные для LLM

```dotenv
CLOUD_RU_API_KEY=
CLOUD_RU_BASE_URL=https://foundation-models.api.cloud.ru/v1
CLOUD_RU_OUTPUT_FORMAT=json_object
```

### Генерация

```dotenv
CLOUD_RU_DISABLE_THINKING=true
CLOUD_RU_API_TIMEOUT=150
CLOUD_RU_API_RETRIES=2
GENERATION_TIMEOUT_SECONDS=290
MAX_LLM_CALLS=20
DEFAULT_SLIDES=10
MAX_SLIDES=15
```

### Web research

```dotenv
WEB_FALLBACK_ENABLED=true
```

### Изображения

```dotenv
IMAGE_MODE=retrieve
IMAGE_MODEL=black-forest-labs/FLUX.1-schnell
IMAGE_PROVIDER=auto
HF_TOKEN=
```

`IMAGE_MODE=retrieve` — поиск и подбор изображений.

`IMAGE_MODE=text_to_image` — optional text-to-image. Нужен `HF_TOKEN`. При отсутствии токена приложение сохраняет рабочий retrieval fallback и выдаёт предупреждение.

### Runtime

```dotenv
HOST=127.0.0.1
PORT=8090
RENDER_FONT=Arial
```

В Docker Compose host/port переопределяются на `0.0.0.0:8080`; это актуально только для опционального Docker-запуска.

## 7. Источники и веб-исследование

Поддерживаются пользовательские PDF, DOCX, TXT, MD, CSV и JSON до 20 МБ на файл.

Веб-исследование сохраняет реальные загруженные страницы, URL и дату обращения. Поисковый snippet не считается доказательством. Числа и существенные тезисы проходят через claims/source checks.

Если пользователь запрашивает библиографию в формате ГОСТ, приложение использует только доступные реквизиты и не должно придумывать отсутствующие поля.

## 8. Варианты верстки

Один семантический план используется для трёх вариантов:

- `balanced` — сбалансированная композиция;
- `columns` — колоночная композиция;
- `editorial` — редакционная композиция.

Внутренний VK-режим позволяет получить 3 шаблона × 3 варианта = 9 PPTX на одном содержании.

## 9. Аудит и выборочный repair

Аудит выполняется после сохранения PPTX и проверяет физический результат файла. В интерфейсе пользователь видит findings и сам выбирает, какие из них передать в repair.

Endpoint выборочного исправления:

```text
POST /api/repair/{run_id}
```

с полем:

```text
selected_issues=<JSON array>
```

Невыбранные findings не должны попадать в targeted repair payload.

Подробности: [AUDIT.md](AUDIT.md).

## 10. Экспорт

Приложение создаёт:

- `.pptx` — редактируемый PowerPoint;
- `.pdf` — через LibreOffice;
- `.html` — HTML-представление;
- preview PNG — для части результатов/диагностики.

PPTX не выгружается единой растровой картинкой.

## 11. Модели

Основная текстовая модель:

- `Qwen/Qwen3-32B` через Cloud.ru Foundation Models API.

Опциональная text-to-image модель:

- `black-forest-labs/FLUX.1-schnell` через Hugging Face Inference Providers.

Полная информация и ссылки на Hugging Face: [MODELS.md](MODELS.md).

## 12. Структура репозитория

```text
.
├── app.py                         # FastAPI application / API routes
├── core/                          # бизнес-логика и pipeline layers
├── config/                        # конфиги вариантов и runtime-конфигурация
├── prompts/                       # отдельные LLM prompts
├── skills/                        # отдельные skill/agent policies + versions
├── assets/templates/              # три предоставленных PPTX-шаблона
├── examples/                      # showcase и примеры для проверки
├── handoff/                       # design-system handoff и layout registry
├── scripts/                       # acceptance / smoke / release checks
├── tests/                         # automated tests
├── static/                        # web UI
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── requirements-dev.txt
├── .env.example
└── документация *.md
```

## 13. Документы для эксперта

### Обязательные

- [README.md](README.md) — установка, окружение, ограничения;
- [ARCHITECTURE.md](ARCHITECTURE.md) — архитектура и границы слоёв;
- [MODELS.md](MODELS.md) — модели, назначение, требования и Hugging Face;
- [AUDIT.md](AUDIT.md) — тесты и область покрытия;
- `prompts/` — все основные prompts отдельными файлами;
- `skills/` — skill/agent policies отдельными файлами;
- `config/` — конфигурации вариантов и поведения.

### Рекомендуемые для сдачи

- [TЗ_COVERAGE.md](TЗ_COVERAGE.md) — матрица выполнения требований;
- [TESTING.md](TESTING.md) — как воспроизводить тесты;
- [API.md](API.md) — основные HTTP endpoints;
- [SECURITY.md](SECURITY.md) — секреты, публичный репозиторий и безопасный deploy;
- [SUBMISSION_CHECKLIST.md](SUBMISSION_CHECKLIST.md) — финальный чек-лист;
- [PUBLISH_GITHUB.md](PUBLISH_GITHUB.md) — публикация и Git tag;
- [RELEASE_NOTES.md](RELEASE_NOTES.md) — изменения текущего релиза;
- `examples/showcase/` — одна колода в трёх вариантах;
- полный 3×3 showcase можно хранить отдельно от основного release archive, чтобы не раздувать публичный репозиторий бинарными файлами.

## 14. Тесты

Установить dev-зависимости:

```bash
python -m pip install -r requirements-dev.txt
```

Запустить основной изолированный набор:

```bash
python scripts/final_test_suite.py
```

Проверить структуру публичного релиза:

```bash
python scripts/pre_submission_check.py
```

На релизе `v7.4.2` в тестовый набор входят 55 собранных test cases.

## 15. Ограничения

- SmartArt и полностью произвольные фирменные композиции не заявляются как 100% автоматически воспроизводимые.
- Live latency зависит от внешнего LLM/API-провайдера; целевой лимит колоды по кейсу нужно подтверждать реальным прогоном.
- Полная матрица browser compatibility не является автоматизированным CI-тестом и требует smoke-проверки в окружении команды.
- Text-to-image зависит от внешнего inference provider и токена.
- Для команд Top-10 обязательный VK inference должен использоваться на предоставленной VK инфраструктуре; Cloud.ru не заменяет это отдельное условие.
- Приложение рассчитано на один рабочий процесс и одно одновременное задание; production-scale orchestration не является целью этого релиза.

## 16. Безопасность публикации

`.env`, `.venv`, `outputs/`, логи и локальные cache-файлы должны оставаться вне Git. Перед сдачей открыть публичный репозиторий в режиме инкогнито и проверить, что код и документы видны без авторизации.

---

**Release:** `7.4.2-final`  
**Pitch deck и demo video:** сознательно не входят в этот репозиторий как часть текущей подготовки.
