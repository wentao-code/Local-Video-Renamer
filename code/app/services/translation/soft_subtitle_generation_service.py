from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from app.core.app_logging import get_logger, log_context, new_run_id
from app.core.video_code import standardize_video_code
from app.services.parsers.code_prefix_entry_parser import extract_code

LOGGER = get_logger(__name__)
DEFAULT_SOFT_SUBTITLE_MUX_TIMEOUT_SECONDS = 900.0


class SoftSubtitleGenerationService:
    """Mux generated VTT subtitles into MP4 containers without re-encoding video."""

    def __init__(self, input_dir, ffmpeg_exe='ffmpeg', timeout_seconds=None):
        self.input_dir = Path(input_dir).expanduser()
        self.ffmpeg_exe = str(ffmpeg_exe or 'ffmpeg')
        self.timeout_seconds = (
            float(timeout_seconds)
            if timeout_seconds is not None
            else DEFAULT_SOFT_SUBTITLE_MUX_TIMEOUT_SECONDS
        )
        self._run_lock = threading.Lock()

    def generate_from_directory(self, input_dir=None):
        directory = Path(input_dir or self.input_dir).expanduser()
        run_id = new_run_id('soft_subtitle_generation', directory.name)
        if not self._run_lock.acquire(blocking=False):
            LOGGER.warning('软字幕生成任务已在运行，跳过本次请求 directory=%s', directory)
            return self._occupied_result(directory, run_id)
        try:
            with log_context(run_id=run_id):
                directory.mkdir(parents=True, exist_ok=True)
                results = []
                for item in sorted(directory.iterdir()):
                    if not item.is_dir():
                        continue
                    result = self._mux_numbered_directory(item)
                    if result is not None:
                        results.append(result)

                success_count = sum(result['status'] == 'completed' for result in results)
                failed_count = sum(result['status'] == 'failed' for result in results)
                return {
                    'run_id': run_id,
                    'input_dir': str(directory),
                    'directory_count': len(results),
                    'success_count': success_count,
                    'failed_count': failed_count,
                    'results': results,
                }
        finally:
            self._run_lock.release()

    def _mux_numbered_directory(self, directory):
        code = standardize_video_code(extract_code(directory.name) or directory.name)
        if not code:
            return None

        self._cleanup_stale_temporary_outputs(directory)

        subtitle = next(
            (
                path
                for path in directory.iterdir()
                if path.is_file() and path.name.casefold() == f'{code}.vtt'.casefold()
            ),
            None,
        )
        videos = [
            path
            for path in directory.iterdir()
            if path.is_file()
            and path.suffix.casefold() == '.mp4'
            and not path.stem.casefold().endswith(('.softsub', '.softsub.tmp'))
            and standardize_video_code(extract_code(path.stem) or '') == code
        ]
        if subtitle is None and not videos:
            return None
        if subtitle is None:
            return self._failed_result(directory, '缺少编号对应的 VTT 字幕文件')
        if len(videos) != 1:
            return self._failed_result(directory, f'匹配到 {len(videos)} 个编号对应的 MP4 视频文件')

        video = videos[0]
        output = video.with_name(f'{video.stem}.softsub.mp4')
        temporary_output = video.with_name(f'{video.stem}.softsub.tmp.mp4')
        if output.exists():
            return self._failed_result(directory, f'软字幕文件已存在: {output.name}')
        if temporary_output.exists():
            return self._failed_result(directory, f'软字幕临时文件已存在: {temporary_output.name}')

        command = [
            self.ffmpeg_exe,
            '-nostdin',
            '-y',
            '-i', str(video),
            '-i', str(subtitle),
            '-map', '0',
            '-map', '1:0',
            '-c', 'copy',
            '-c:s', 'mov_text',
            '-metadata:s:s:0', 'language=jpn',
            '-metadata:s:s:0', 'title=Japanese',
            str(temporary_output),
        ]
        LOGGER.info('软字幕封装开始 directory=%s video=%s subtitle=%s output=%s', directory, video, subtitle, output)
        try:
            completed = subprocess.run(
                command,
                cwd=str(directory),
                text=True,
                encoding='utf-8',
                errors='replace',
                check=False,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            self._discard_temporary_output(temporary_output)
            detail = str(getattr(exc, 'stderr', None) or '').strip()
            message = f'FFmpeg 封装超时（{self.timeout_seconds:g} 秒）'
            if detail:
                message += f': {detail}'
            return self._failed_result(directory, message)
        except OSError as exc:
            return self._failed_result(directory, f'FFmpeg 启动失败: {exc}')

        if completed.returncode != 0 or not temporary_output.is_file():
            self._discard_temporary_output(temporary_output)
            detail = str(completed.stderr or completed.stdout or '').strip()
            return self._failed_result(directory, f'FFmpeg 封装失败，退出码={completed.returncode}: {detail}')

        temporary_output.replace(output)
        LOGGER.info('软字幕封装完成 directory=%s output=%s', directory, output)
        return {
            'directory': str(directory),
            'video_path': str(video),
            'subtitle_path': str(subtitle),
            'output_path': str(output),
            'status': 'completed',
            'error': '',
        }

    @staticmethod
    def _occupied_result(directory, run_id):
        error = '已有软字幕生成任务正在运行，请等待其完成'
        return {
            'run_id': run_id,
            'input_dir': str(directory),
            'directory_count': 1,
            'success_count': 0,
            'failed_count': 1,
            'occupied': True,
            'message': error,
            'results': [
                {
                    'directory': str(directory),
                    'video_path': '',
                    'subtitle_path': '',
                    'output_path': '',
                    'status': 'failed',
                    'error': error,
                }
            ],
        }

    @staticmethod
    def _cleanup_stale_temporary_outputs(directory):
        for path in directory.iterdir():
            if not path.is_file():
                continue
            if not path.name.casefold().endswith('.softsub.tmp.mp4'):
                continue
            try:
                path.unlink()
                LOGGER.info('软字幕清理陈旧临时文件 directory=%s path=%s', directory, path)
            except OSError:
                LOGGER.warning('软字幕陈旧临时文件清理失败 directory=%s path=%s', directory, path)

    @staticmethod
    def _discard_temporary_output(temporary_output):
        try:
            temporary_output.unlink(missing_ok=True)
        except OSError:
            LOGGER.warning('软字幕临时文件清理失败 path=%s', temporary_output)

    @staticmethod
    def _failed_result(directory, error):
        LOGGER.error('软字幕封装失败 directory=%s error=%s', directory, error)
        return {
            'directory': str(directory),
            'video_path': '',
            'subtitle_path': '',
            'output_path': '',
            'status': 'failed',
            'error': str(error),
        }
