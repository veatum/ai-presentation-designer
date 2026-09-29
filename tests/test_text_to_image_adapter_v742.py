import sys
import types
from pathlib import Path

from PIL import Image


def test_text_to_image_adapter_writes_image(tmp_path, monkeypatch):
    calls = {}

    class FakeClient:
        def __init__(self, **kwargs):
            calls['init'] = kwargs

        def text_to_image(self, **kwargs):
            calls['generate'] = kwargs
            return Image.new('RGB', (512, 300), (120, 140, 160))

    fake_hf = types.ModuleType('huggingface_hub')
    fake_hf.InferenceClient = FakeClient
    monkeypatch.setitem(sys.modules, 'huggingface_hub', fake_hf)
    monkeypatch.setenv('HF_TOKEN', 'test-token')
    monkeypatch.setenv('IMAGE_MODEL', 'black-forest-labs/FLUX.1-schnell')
    monkeypatch.setenv('IMAGE_PROVIDER', 'auto')

    import core.image_generation as gen

    output = tmp_path / 'generated.jpg'
    info = gen.generate_image('professional technology illustration', output)

    assert output.exists() and output.stat().st_size > 0
    assert info['source'] == 'Hugging Face Inference Providers'
    assert info['model'] == 'black-forest-labs/FLUX.1-schnell'
    assert calls['init']['api_key'] == 'test-token'
    assert calls['generate']['model'] == 'black-forest-labs/FLUX.1-schnell'
    assert calls['generate']['width'] == 1344
    assert calls['generate']['height'] == 756


def test_text_to_image_collection_falls_back_without_token(tmp_path, monkeypatch):
    monkeypatch.delenv('HF_TOKEN', raising=False)

    import core.image_research as research

    monkeypatch.setattr(research, 'search_images', lambda *args, **kwargs: [])
    monkeypatch.setattr(research, 'search_wikimedia', lambda *args, **kwargs: [])

    plan = {
        'slides': [
            {'number': 2, 'kind': 'content', 'title': 'Тема', 'subtitle': 'Подзаголовок', 'points': ['Контент']}
        ]
    }
    result = research.collect_images(
        'Бриф', plan, tmp_path, max_images=1, budget_seconds=1, mode='text_to_image'
    )

    assert result['mode'] == 'text_to_image'
    assert result['items'] == []
    assert any('HF_TOKEN' in warning for warning in result['warnings'])
