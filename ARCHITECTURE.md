# ARCHITECTURE — v7.4.2

## 1. Общая схема

```text
User / Browser
      │
      ▼
FastAPI + static HTML/JS
      │
      ├── brief + uploads
      │
      ▼
Input / Extraction
      │
      ├── web research
      ├── local files
      └── source normalization
      │
      ▼
Template Parser
      │
      ├── slide size
      ├── layouts / placeholders
      ├── typography tokens
      └── color tokens
      │
      ▼
LLM Orchestration
      │
      ├── architect
      ├── writer
      ├── critic
      ├── fact verification
      └── targeted repair
      │
      ▼
Semantic SlideBatch
      │
      ▼
Renderer
      │
      ├── balanced
      ├── columns
      └── editorial
      │
      ▼
Native PPTX
      │
      ├── deterministic audit
      ├── PDF/HTML export
      └── user-selected repair loop
```

## 2. Границы слоёв

### API / UI — `app.py`

Отвечает за HTTP API, загрузку файлов, orchestration верхнего уровня, выдачу результатов и взаимодействие с UI.

### Extraction — `core/extract.py`

Извлекает текст и табличные/структурные сведения из пользовательских PDF, DOCX, TXT, MD, CSV и JSON.

### Web research — `core/web_research.py`

Получает реальные веб-страницы. Search snippets используются только как навигационный материал и не должны становиться доказательством факта.

### Template parsing — `core/template_parser.py`

Читает фактический PPTX и извлекает:

- размер слайда;
- layouts;
- placeholders;
- геометрию существующих элементов;
- шрифты;
- цвета;
- связанные layout tokens.

Эта информация используется renderer-ом, чтобы не быть жёстко привязанным к трём предоставленным шаблонам.

### LLM — `core/llm.py`

Единый текстовый LLM-stage через Cloud.ru. Архитектура, writer, critic, fact-check, revision и targeted repair получают отдельные prompts из `prompts/`.

### Quality — `core/quality.py`

Проверяет source/claim integrity, контентные ограничения, библиографию и смысловые QA-шаги.

### Renderer — `core/renderer.py`

Получает семантический план и конкретный template specification. Renderer не должен зависеть от результата другого варианта. Один план → три render variants.

### Audit — `core/audit.py`

Повторно открывает готовый PPTX и проверяет именно физический результат файла. Это важно: audit не должен считать внутренний JSON-план доказательством того, что итоговый слайд реально корректен.

### Images — `core/image_research.py`, `core/image_generation.py`

`image_research.py` — retrieval из Openverse/Wikimedia Commons и подготовка metadata.

`image_generation.py` — optional text-to-image adapter через Hugging Face Inference Providers. По умолчанию не активен.

### Export — `core/exporter.py`

Работает с LibreOffice для PDF/preview и с HTML output layer.

## 3. Почему один семантический план и три renderer variants

Сначала формируется единый смысловой `SlideBatch`. Затем этот же план рендерится в:

- `balanced`;
- `columns`;
- `editorial`.

Так варианты отличаются композиционно, но не должны расходиться по фактам и ключевому содержанию.

## 4. User-selected repair

После генерации каждый читаемый PPTX проходит audit.

```text
Audit findings
      ↓
UI: checkboxes / selected findings
      ↓
POST /api/repair/{run_id}
      ↓
validate + normalize selected findings
      ↓
targeted repair
      ↓
re-render
      ↓
re-audit
```

Сервис отклоняет пустой selection и передаёт в repair только нормализованные выбранные finding objects.

## 5. Детерминированный и недетерминированный QA

### Детерминированный

Основан на структуре PPTX: координаты, размеры, шрифты, цвета, число объектов, структура таблиц/диаграмм и т. п.

### Недетерминированный

Смысловые проверки LLM: соответствие тезиса источникам, финальная фактологическая проверка, связность содержания и некоторые content QA.

Оба слоя нужны вместе: LLM не заменяет физический audit, а физический audit не доказывает истинность текста.

## 6. Данные и артефакты одного run

Каждый запуск получает отдельный `run_id` и директорию в `outputs/runs/`.

Типовые артефакты:

```text
plan.json
sources.json
templates.json
images.json
generation_settings.json
results.json
presentation_*_audit.json
presentation_*.pptx
presentation_*.pdf
presentation_*.html
generation_trace.json
```

## 7. Воспроизводимость

Проект воспроизводится через:

- фиксированный `requirements.txt`/ограничения версий;
- Dockerfile;
- docker-compose.yml;
- `.env.example`;
- отдельные prompts и skills;
- Git tag релиза.

## 8. Ограничения архитектуры

- Один рабочий процесс / одно одновременное задание.
- Внешний LLM/API latency может влиять на время генерации.
- Произвольный сложный SmartArt не обещается как fully automatic.
- Browser matrix и внешний VK inference требуют отдельной проверки в соответствующей среде.
