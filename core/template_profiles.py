from __future__ import annotations
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / 'assets' / 'templates'

# These are the three bundled VK dataset templates. We intentionally keep real
# slides from the source decks rather than rebuilding them from scratch.
BUILTIN_TEMPLATES: dict[str, dict[str, Any]] = {
    'vk_tech': {
        'id': 'vk_tech',
        'name': 'VK Tech',
        'filename': 'vk_tech_template.pptx',
        'description': 'Технологичный корпоративный шаблон VK Tech: титул, разделитель, контент, метрики, графики, финал.',
    },
    'vk_workspace': {
        'id': 'vk_workspace',
        'name': 'VK WorkSpace',
        'filename': 'vk_workspace_template_03.pptx',
        'description': 'Корпоративный шаблон VK WorkSpace: кейсы, карточки, показатели, графики, таймлайн, CTA и финал.',
    },
    'vk_education': {
        'id': 'vk_education',
        'name': 'VK Education',
        'filename': 'vk_education_template.pptx',
        'description': 'Образовательный шаблон VK Education: разделы, объяснения, фактоиды, две колонки, таблицы, графики, финал.',
    },
}


def builtin_template_path(template_id: str) -> Path:
    item = BUILTIN_TEMPLATES.get(template_id)
    if not item:
        raise KeyError(f'Unknown built-in template: {template_id}')
    path = TEMPLATES / item['filename']
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def builtin_catalog() -> list[dict[str, Any]]:
    return [
        {k: v for k, v in item.items() if k != 'curated_indices'}
        for item in BUILTIN_TEMPLATES.values()
    ]
