# API — v7.4.2

HTTP API приложения реализовано в `app.py`.

## Основные endpoints

| Method | Path | Назначение |
|---|---|---|
| GET | `/` | web UI |
| GET | `/health` | healthcheck |
| GET | `/api/version` | версия приложения |
| GET | `/api/templates` | доступные шаблоны |
| GET | `/api/diagnostics` | безопасная диагностика без раскрытия ключей |
| POST | `/api/generate` | генерация презентаций |
| POST | `/api/revise/{run_id}` | общая пользовательская ревизия |
| POST | `/api/repair/{run_id}` | targeted repair по выбранным audit findings |
| GET | `/api/file/{run_id}/{filename}` | выдача сгенерированного файла |
| GET | `/api/bundle/{run_id}` | ZIP с результатами run |

## `/api/generate`

Принимает multipart form-data. Основные поля:

- `brief` — текстовый бриф;
- `slides` — желаемое количество слайдов;
- `include_vk_templates` — использовать три встроенных шаблона;
- `include_images` — включить изображения;
- `sources` — пользовательские файлы;
- дополнительные image/template inputs — согласно текущему UI.

## `/api/repair/{run_id}`

Принимает:

```text
selected_issues=<JSON array>
```

Пример:

```json
[
  {
    "slide": 4,
    "severity": "major",
    "problem": "Блок выходит за правую границу",
    "fix": "Уменьшить ширину блока и выровнять по сетке"
  }
]
```

Пользователь может передать несколько selected findings одним запросом. Пустой список отклоняется.

## `/health`

Минимальный healthcheck для Docker:

```text
GET /health
```

Docker использует этот endpoint в `HEALTHCHECK`.

## `/api/file/{run_id}/{filename}`

Для защиты от path traversal сервер выдаёт только файлы с ожидаемыми именами `presentation_*` и разрешёнными расширениями.
