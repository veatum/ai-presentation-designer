# Матрица покрытия ТЗ — v7.4.2

| Требование кейса | Статус | Где смотреть |
|---|---|---|
| Импорт/декомпозиция шаблонов и контент-пакетов | ✅ | `core/template_parser.py`, `core/extract.py` |
| Генерация структуры и текста по брифу | ✅ | `core/llm.py`, `prompts/` |
| Таблицы и диаграммы | ✅ | `core/renderer.py`, `tests/` |
| Пиктограммы / простые визуальные элементы | 🟡 | renderer/layouts; сложный SmartArt не заявляется |
| Генерация изображений, star-task | 🟡 | `core/image_generation.py`; live-run требует HF token/provider |
| Версионирование skills/agents | ✅ | `skills/`, `skills/VERSIONS.md`, Git tag |
| Три варианта одной колоды | ✅ | `balanced`, `columns`, `editorial` |
| Три предоставленных шаблона | ✅ | `assets/templates/` |
| 9 вариантов для промежуточного VK showcase | ✅ | полный showcase matrix |
| Аудит как часть pipeline | ✅ | `core/audit.py`, `core/quality.py` |
| Пользователь выбирает проблемы для исправления | ✅ | UI findings + `/api/repair/{run_id}` |
| Экспорт HTML/PPTX/PDF | ✅ | `core/exporter.py` |
| PPTX не является одной картинкой | ✅ | native text/table/chart/image objects |
| 10–15 слайдов по умолчанию / заданному диапазону | ✅ | runtime validation |
| Время ≤5 минут | 🟡 | зависит от live provider; подтверждается реальным прогоном |
| Неизвестный шаблон | ✅ | runtime parser + renderer |
| Desktop web interface | ✅ | FastAPI + static HTML/JS |
| Chrome/Firefox/Safari/Yandex, macOS/Windows | 🟡 | требуется smoke-check в соответствующей среде |
| Python/Typescript stack | ✅ | Python/FastAPI/HTML/JS |
| README | ✅ | `README.md` |
| ARCHITECTURE | ✅ | `ARCHITECTURE.md` |
| MODELS + Hugging Face links | ✅ | `MODELS.md` |
| AUDIT | ✅ | `AUDIT.md` |
| Prompts/configs отдельно | ✅ | `prompts/`, `skills/`, `config/` |
| Public repository | ⬜ | выполнить перед отправкой |
| Fixed release/version | ⬜ | создать Git tag `v7.4.2-final` |
| Reproducible config-file setup | ✅ | `.env.example`, `START_WINDOWS.bat`, `START_MAC.sh`; Docker как дополнительный путь |
| Final 3 layout variants | ✅ technical | `examples/showcase/`; команда выбирает финальную колоду |
| VK Top-10 inference | ⬜ внешний ресурс | зависит от предоставленного VK endpoint |
| Pitch/video | ⬜ | сознательно готовятся командой отдельно |
