# PUBLISH_GITHUB — v7.4.2

## 1. Создать публичный репозиторий

Создайте пустой **public** repository на GitHub/GitLab.

Не добавляйте `.env` и не коммитьте API tokens.

## 2. Инициализировать Git

```bash
git init
git add .
git status
git commit -m "Release v7.4.2"
git branch -M main
```

## 3. Подключить remote

```bash
git remote add origin <PUBLIC_REPOSITORY_URL>
git push -u origin main
```

## 4. Зафиксировать сдаваемую версию

```bash
git tag -a v7.4.2-final -m "Final hackathon submission"
git push origin v7.4.2-final
```

После фиксации не меняйте содержимое сдаваемого tag.

## 5. Инкогнито-проверка

Откройте repository URL в приватном окне браузера без входа в GitHub/GitLab.

Проверьте:

- README;
- исходный код;
- `prompts/`;
- `skills/`;
- `config/`;
- шаблоны;
- документацию;
- examples.

## 6. Если используете VPS

VPS не является обязательным элементом воспроизводимого release path. Для Docker deploy используйте [DEPLOY_DOCKER.md](DEPLOY_DOCKER.md).
