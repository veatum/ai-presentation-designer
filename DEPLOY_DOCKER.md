# Optional Docker deployment

Docker не является обязательным требованием ТЗ. Финальная сдача требует воспроизводимый сетап и запуск конфигурацией; для этого достаточно обычного Python-окружения и `.env.example`. Docker оставлен как дополнительный, более изолированный способ запуска на Linux/VPS и на машинах с Docker Desktop.

## 1. Когда использовать Docker

Используйте Docker, если нужно:

- одинаковое окружение на разных машинах;
- запуск на Linux VPS;
- не устанавливать LibreOffice и часть системных зависимостей вручную.

Для локальной проверки жюри Docker не обязателен. Windows-инструкция находится в [WINDOWS_SETUP.md](WINDOWS_SETUP.md).

## 2. Что нужно для Linux/VPS

- Ubuntu 24.04 LTS или другой современный Linux;
- 4 vCPU;
- 8 GB RAM минимум, 16 GB желательно для тяжёлых PPTX/PDF-задач;
- 40+ GB SSD;
- Docker Engine + Docker Compose plugin.

GPU не требуется: генерация текста выполняется через Cloud.ru Foundation Models API, а рендеринг идёт на CPU/RAM.

## 3. Запуск

```bash
cp .env.example .env
nano .env

# заполнить
CLOUD_RU_API_KEY=YOUR_REAL_CLOUD_RU_KEY

docker compose up -d --build
```

Проверка:

```bash
docker compose ps
curl http://127.0.0.1:8080/health
```

Интерфейс:

```text
http://SERVER_IP:8080
```

Не помещайте ключ в `Dockerfile`, исходный код или `docker-compose.yml`.

## 4. Данные

`./outputs` монтируется в `/app/outputs`, поэтому результаты сохраняются после пересоздания контейнера.

## 5. Обновление / остановка

```bash
docker compose up -d --build
docker compose stop
docker compose start
```

## 6. Публичный VPS

VPS также не обязателен для сдачи. Если сервис всё же публикуется в Интернет, перед внешним доступом рекомендуется reverse proxy + HTTPS, а также аутентификация и rate limiting.
