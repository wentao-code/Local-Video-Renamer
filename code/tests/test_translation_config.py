import json
from pathlib import Path

from app.core import translation_config


def test_dedicated_input_path_file_overrides_environment_setting(monkeypatch, tmp_path):
    config_path = tmp_path / 'translation_input_path.json'
    config_path.write_text(
        json.dumps({'input_dir': r'D:\Videos\Dedicated'}),
        encoding='utf-8',
    )
    monkeypatch.setattr(translation_config, 'TRANSLATION_INPUT_PATH_FILE', config_path)
    monkeypatch.setenv('TRANSLATION_INPUT_DIR', r'D:\Videos\Legacy')

    config = translation_config.TranslationConfig.from_environment()

    assert config.input_dir == Path(r'D:\Videos\Dedicated')


def test_environment_setting_remains_fallback_when_path_file_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        translation_config,
        'TRANSLATION_INPUT_PATH_FILE',
        tmp_path / 'translation_input_path.json',
    )
    monkeypatch.setenv('TRANSLATION_INPUT_DIR', r'D:\Videos\Legacy')

    config = translation_config.TranslationConfig.from_environment()

    assert config.input_dir == Path(r'D:\Videos\Legacy')
