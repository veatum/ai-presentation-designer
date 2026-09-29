# MODELS — v7.4.2

## 1. Текстовая модель

### Qwen/Qwen3-32B

**Провайдер:** Cloud.ru Foundation Models API  
**Назначение:**

- архитектура колоды;
- генерация текста;
- критика;
- редактура;
- фактологическая проверка;
- targeted repair.

**Hugging Face:**
https://huggingface.co/Qwen/Qwen3-32B

На текущей странице модели Hugging Face указан `Apache-2.0` как лицензия модели.

**Runtime:** модель не хранится внутри репозитория; приложение обращается к внешнему API.

**Конфигурация:**

```dotenv
CLOUD_RU_API_KEY=
CLOUD_RU_BASE_URL=https://foundation-models.api.cloud.ru/v1
CLOUD_RU_OUTPUT_FORMAT=json_object
```

## 2. Text-to-image

### black-forest-labs/FLUX.1-schnell

**Назначение:** optional text-to-image иллюстрации для star-task.

**Hugging Face:**
https://huggingface.co/black-forest-labs/FLUX.1-schnell

**Параметры:** 12B. Hugging Face model card указывает `Apache-2.0` и возможность использования через Inference Providers.

**Включение:**

```dotenv
IMAGE_MODE=text_to_image
IMAGE_MODEL=black-forest-labs/FLUX.1-schnell
IMAGE_PROVIDER=auto
HF_TOKEN=...
```

Без `HF_TOKEN` приложение использует retrieval fallback и фиксирует предупреждение.

## 3. Изображения без генеративной модели

По умолчанию:

1. Openverse;
2. fallback — Wikimedia Commons.

Это retrieval, а не text-to-image. Источник изображения сохраняется в metadata.

## 4. Модельный контракт

Ни одна модель не должна считаться источником истины сама по себе. Числа и существенные утверждения должны проходить source/claim checks; физический результат PPTX проходит отдельный deterministic audit.

## 5. VK Top-10

Для команд, вошедших в Top-10, ТЗ устанавливает отдельное требование использования предоставленного VK inference. Эта инфраструктура не заменяется Cloud.ru и должна быть отражена в финальной конфигурации команды после получения endpoint/доступа от организаторов.

## 6. Системные требования

### LLM

Для текущей архитектуры собственное железо под Qwen не требуется: используется внешний API. Требования к CPU/RAM/GPU зависят от Cloud.ru endpoint.

### Text-to-image

В текущем варианте image generation также выполняется через внешний inference provider. Локальный GPU для FLUX не является обязательным.

### Render/export

Для PDF/preview нужен LibreOffice. Dockerfile уже включает LibreOffice Impress и portable fonts.
