# TESTING — v7.4.2

## 1. Что проверяет тестовый комплект

Тесты разделены по рискам:

- pipeline / schema;
- native PPTX integrity;
- built-in templates;
- unknown-template rendering;
- audit;
- targeted repair;
- image retrieval reliability;
- text-to-image adapter/fallback;
- web resilience;
- route-level acceptance;
- regression cases.

## 2. Установка

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

## 3. Полный изолированный прогон

```bash
.venv/bin/python scripts/final_test_suite.py
```

Скрипт запускает renderer-heavy группы отдельными pytest-процессами, чтобы исключить накопление ресурсов между тяжёлыми тестами.

Ожидаемый охват релиза: **55 collected test cases**.

## 4. Быстрый smoke

```bash
.venv/bin/python scripts/pre_submission_check.py
.venv/bin/python scripts/smoke_offline.py
```

## 5. Route acceptance

```bash
.venv/bin/python scripts/app_route_acceptance.py
```

Этот режим использует offline LLM stub для проверки HTTP route, rendering и export paths без расходования внешнего API.

## 6. Live integration

Для реального end-to-end запуска нужен `.env` с рабочим `CLOUD_RU_API_KEY`. Live проверки не следует запускать автоматически в CI без контроля стоимости/лимитов API.

Для star-task:

```dotenv
IMAGE_MODE=text_to_image
HF_TOKEN=...
```

После этого нужен минимум один ручной live-run для подтверждения доступности внешнего image provider.

## 7. Что считать чистым результатом

Перед публикацией релиза необходимо получить:

1. `PASS` от `pre_submission_check.py`;
2. `PASS` всех групп `final_test_suite.py`;
3. успешный Docker `docker compose config`;
4. успешный локальный или Docker healthcheck;
5. один реальный demo-run с рабочим LLM endpoint;
6. проверку публичного Git-репозитория в режиме инкогнито.
