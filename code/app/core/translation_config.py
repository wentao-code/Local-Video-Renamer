from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.app_config import get_setting


DEFAULT_TRANSLATION_MODEL_ROOT = Path(r'D:\software\software_for_chickenrice')
DEFAULT_TRANSLATION_DEVICE = 'cuda'
DEFAULT_TRANSLATION_SUB_FORMATS = ('srt', 'vtt', 'lrc')
SUPPORTED_TRANSLATION_SUB_FORMATS = frozenset(('srt', 'vtt', 'lrc', 'txt'))


def _parse_bool(value, default=False):
    if value is None or str(value).strip() == '':
        return bool(default)
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


@dataclass(frozen=True)
class TranslationConfig:
    model_root: Path
    infer_exe: Path
    device: str = DEFAULT_TRANSLATION_DEVICE
    sub_formats: tuple[str, ...] = DEFAULT_TRANSLATION_SUB_FORMATS
    overwrite: bool = False

    @classmethod
    def from_environment(cls, env_path=None):
        model_root = Path(
            get_setting(
                'TRANSLATION_MODEL_ROOT',
                str(DEFAULT_TRANSLATION_MODEL_ROOT),
                env_path=env_path,
            )
        ).expanduser()
        infer_exe = Path(
            get_setting(
                'TRANSLATION_INFER_EXE',
                str(model_root / 'infer.exe'),
                env_path=env_path,
            )
        ).expanduser()
        raw_formats = get_setting(
            'TRANSLATION_SUB_FORMATS',
            ','.join(DEFAULT_TRANSLATION_SUB_FORMATS),
            env_path=env_path,
        )
        formats = tuple(
            item.strip().lower().lstrip('.')
            for item in str(raw_formats or '').split(',')
            if item.strip()
        )
        if not formats:
            formats = DEFAULT_TRANSLATION_SUB_FORMATS
        unsupported = sorted(set(formats) - SUPPORTED_TRANSLATION_SUB_FORMATS)
        if unsupported:
            raise ValueError(f'不支持的字幕格式: {", ".join(unsupported)}')
        return cls(
            model_root=model_root,
            infer_exe=infer_exe,
            device=str(get_setting('TRANSLATION_DEVICE', DEFAULT_TRANSLATION_DEVICE, env_path=env_path)).strip()
            or DEFAULT_TRANSLATION_DEVICE,
            sub_formats=formats,
            overwrite=_parse_bool(get_setting('TRANSLATION_OVERWRITE', 'false', env_path=env_path)),
        )

    def validate(self):
        if not self.model_root.is_dir():
            raise FileNotFoundError(f'翻译模型目录不存在: {self.model_root}')
        if not self.infer_exe.is_file():
            raise FileNotFoundError(f'翻译模型入口不存在: {self.infer_exe}')
        if not self.device:
            raise ValueError('翻译模型设备不能为空')
        if not self.sub_formats:
            raise ValueError('至少需要配置一种字幕格式')
        return self
