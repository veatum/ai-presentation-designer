# Windows setup

Это основной сценарий запуска AI Presentation Designer на Windows без Docker.

## 1. Требования

- Windows 10/11;
- Python 3.11 или новее;
- интернет-доступ для установки Python-зависимостей и обращения к Cloud.ru API;
- LibreOffice — только если нужны PDF/preview export.

## 2. Установка Python

Установите Python 3.11+ с python.org. В установщике включите **Add Python to PATH**.

Проверьте в PowerShell:

```powershell
py -3 --version
```

## 3. Подготовка проекта

Откройте PowerShell в каталоге репозитория:

```powershell
cd C:\path\to\ai-presentation-designer
```

Создайте виртуальное окружение:

```powershell
py -3 -m venv .venv
```

Установите зависимости:

```powershell
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 4. Переменные окружения

Создайте `.env` из шаблона:

```powershell
Copy-Item .env.example .env
```

Откройте `.env` и укажите реальный ключ:

```dotenv
CLOUD_RU_API_KEY=YOUR_REAL_KEY
CLOUD_RU_BASE_URL=https://foundation-models.api.cloud.ru/v1
```

`.env` не добавляется в Git.

Для text-to-image режим включается отдельно через `IMAGE_MODE=text_to_image` и требует `HF_TOKEN`. По умолчанию используется `IMAGE_MODE=retrieve`.

## 5. LibreOffice

Установите LibreOffice, если нужны PDF/preview export. После установки желательно добавить каталог с `soffice.exe` в `PATH`.

Проверка:

```powershell
where.exe soffice
```

Если `soffice` не найден, `.pptx` всё равно может создаваться; недоступными будут операции, которые используют LibreOffice.

## 6. Запуск приложения

Самый простой вариант:

```powershell
.\START_WINDOWS.bat
```

Или вручную:

```powershell
.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8090
```

Откройте в браузере:

```text
http://127.0.0.1:8090
```

Поддерживаемые браузеры по ТЗ: актуальная и предыдущая версии Chrome, Firefox, Safari, Яндекс Браузера; для Windows локально используйте Chrome/Firefox/Яндекс Браузер.

## 7. Проверка API

В PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:8090/health
Invoke-RestMethod http://127.0.0.1:8090/api/version
```

## 8. Остановка

В окне, где запущен Uvicorn, нажмите `Ctrl+C`.

## 9. Частые проблемы

### `py` или `python` не найден

Переустановите Python с включённым **Add Python to PATH** и перезапустите PowerShell.

### Не хватает Python-пакета

Повторите:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Не задан Cloud.ru key

Проверьте `.env` и наличие строки `CLOUD_RU_API_KEY=...`. После изменения `.env` перезапустите сервер.

### PDF/preview не создаётся

Проверьте `where.exe soffice` и установку LibreOffice.

### Порт 8090 занят

Остановите процесс, который использует порт, либо запустите Uvicorn на другом порту и откройте соответствующий URL.
