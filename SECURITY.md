# SECURITY — v7.4.2

## Секреты

Никогда не коммитьте:

- `.env`;
- `CLOUD_RU_API_KEY`;
- `HF_TOKEN`;
- любые другие provider tokens.

Для репозитория используется `.env.example` без реальных значений.

## Публичный репозиторий

Перед публикацией:

```bash
git status --short
git grep -n "CLOUD_RU_API_KEY=" -- ':!*.md'
```

Проверьте также историю Git, если ключ когда-либо был локально закоммичен.

## Generated outputs

`outputs/` исключён из Git. На публичном сервере не рекомендуется напрямую публиковать каталог результатов без reverse proxy/authentication.

## Input files

Загружаемые документы обрабатываются приложением локально. Не загружайте в демонстрационный run секретные или персональные документы.

## Network / SSRF

URL загрузки веб-источников проходят application-level validation. Включён отдельный regression test `ssrf_rejected`.

## Docker

Контейнер запускается не под root-пользователем. LibreOffice используется только внутри контейнера для export/preview.

## Reporting

Для командного проекта любые реальные уязвимости следует сначала исправить перед публикацией публичного репозитория. Не помещайте credentials или приватные API responses в issue/commit history.
