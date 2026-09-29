# SUBMISSION CHECKLIST — v7.4.2

## A. Репозиторий

- [ ] Репозиторий PUBLIC.
- [ ] Нет `.env` и реальных API keys.
- [ ] Нет локальных `outputs/` и логов.
- [ ] README отображается на главной странице.
- [ ] Создан Git tag `v7.4.2-final`.
- [ ] Сдаваемая версия после tag больше не меняется.
- [ ] Ссылка проверена в режиме инкогнито.

## B. Обязательные файлы

- [ ] `README.md`
- [ ] `ARCHITECTURE.md`
- [ ] `MODELS.md`
- [ ] `AUDIT.md`
- [ ] `prompts/`
- [ ] `skills/`
- [ ] `config/`
- [ ] `Dockerfile` / `docker-compose.yml` (опциональный Docker-путь, не обязательный по ТЗ)
- [ ] `.env.example`
- [ ] `requirements.txt`
- [ ] `requirements-dev.txt`
- [ ] `WINDOWS_SETUP.md`
- [ ] `tests/`
- [ ] `scripts/`
- [ ] `assets/templates/`

## C. Рекомендуемые материалы эксперта

- [ ] `TЗ_COVERAGE.md`
- [ ] `TESTING.md`
- [ ] `API.md`
- [ ] `SECURITY.md`
- [ ] `RELEASE_NOTES.md`
- [ ] `examples/showcase/`
- [ ] при необходимости отдельный 3×3 showcase archive для промежуточного сценария

## D. Clean run

```bash
python scripts/pre_submission_check.py
python scripts/final_test_suite.py
```

Docker (опционально):

```bash
docker compose config -q
docker compose up -d --build
curl http://127.0.0.1:8080/health
```

## E. Demo artifacts

- [ ] Одна колода → `balanced`.
- [ ] Одна колода → `columns`.
- [ ] Одна колода → `editorial`.
- [ ] При необходимости показаны 3 шаблона × 3 варианта.
- [ ] Есть хотя бы один прогон на ранее неизвестном шаблоне.
- [ ] Итоговая презентация для pitch подготовлена отдельно.
- [ ] Demo video подготовлено отдельно.

## F. Star-task / images

- [ ] Для обычной демонстрации retrieval работает.
- [ ] Если команда заявляет star-task text-to-image: `HF_TOKEN` настроен локально и выполнен live-run.
- [ ] В публичном репозитории токена нет.

## G. Перед дедлайном

- [ ] Все ссылки открываются без авторизации.
- [ ] Ссылки на репозиторий/материалы проверены в инкогнито.
- [ ] Указана именно final tag/version.
- [ ] На Windows проверен `START_WINDOWS.bat` и `WINDOWS_SETUP.md` при необходимости экспертной проверки.
- [ ] После 23:59 последняя зафиксированная версия остаётся доступной экспертам.
