from __future__ import annotations

import subprocess
from pathlib import Path

from app.core.translation_config import TranslationConfig


VIDEO_SUFFIXES = 'mp4,mkv,avi,mov,webm,flv,wmv'


class SubtitleGenerationService:
    def __init__(self, config: TranslationConfig):
        self.config = config

    def generate(self, video_paths):
        self.config.validate()
        normalized_paths = self._normalize_paths(video_paths)
        results = []
        runnable_paths = []
        for video_path in normalized_paths:
            if not video_path.is_file():
                results.append(self._failed_result(video_path, f'视频文件不存在: {video_path}'))
                continue
            runnable_paths.append(video_path)

        if runnable_paths:
            results.extend(self._run_infer(runnable_paths))
        success_count = sum(result['status'] == 'completed' for result in results)
        return {
            'results': results,
            'success_count': success_count,
            'failed_count': len(results) - success_count,
        }

    def _run_infer(self, video_paths):
        command = [
            str(self.config.infer_exe),
            f'--audio_suffixes={VIDEO_SUFFIXES}',
            f'--sub_formats={",".join(self.config.sub_formats)}',
            f'--device={self.config.device}',
        ]
        if self.config.overwrite:
            command.append('--overwrite')
        command.extend(str(path) for path in video_paths)
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.config.model_root),
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                check=False,
            )
        except OSError as exc:
            return [self._failed_result(path, str(exc)) for path in video_paths]

        if completed.returncode != 0:
            error = (str(completed.stderr or '').strip() or str(completed.stdout or '').strip()
                     or f'翻译模型退出码: {completed.returncode}')
            return [self._failed_result(path, error) for path in video_paths]

        results = []
        for path in video_paths:
            subtitle_paths = [path.with_suffix(f'.{suffix}') for suffix in self.config.sub_formats]
            missing = [str(target) for target in subtitle_paths if not target.is_file()]
            if missing:
                results.append(self._failed_result(path, f'字幕未生成: {", ".join(missing)}'))
                continue
            results.append({
                'video_path': str(path),
                'status': 'completed',
                'subtitle_paths': [str(target) for target in subtitle_paths],
                'error': '',
            })
        return results

    @staticmethod
    def _normalize_paths(video_paths):
        paths = []
        seen = set()
        for raw_path in video_paths or []:
            path = Path(str(raw_path or '').strip()).expanduser()
            if not str(path) or path in seen:
                continue
            seen.add(path)
            paths.append(path)
        return paths

    @staticmethod
    def _failed_result(path, error):
        return {
            'video_path': str(path),
            'status': 'failed',
            'subtitle_paths': [],
            'error': str(error or '字幕生成失败'),
        }
