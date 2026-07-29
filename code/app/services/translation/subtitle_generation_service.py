from __future__ import annotations

import os
import json
import shutil
import subprocess
import tempfile
from time import perf_counter
from pathlib import Path

from app.core.app_logging import get_logger, log_context, new_run_id
from app.core.translation_config import TranslationConfig
from app.services.parsers.code_prefix_entry_parser import extract_code


VIDEO_SUFFIXES = frozenset(('.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.wmv'))
VIDEO_SUFFIX_ARGUMENT = 'mp4,mkv,avi,mov,webm,flv,wmv'
LOGGER = get_logger(__name__)


class SubtitleGenerationService:
    """Generate subtitles for every supported video under one fixed directory."""

    def __init__(self, config: TranslationConfig):
        self.config = config

    def generate_from_directory(self, input_dir=None):
        directory = Path(input_dir or self.config.input_dir).expanduser()
        run_id = new_run_id('subtitle_generation', directory.name)
        started_at = perf_counter()
        with log_context(run_id=run_id):
            LOGGER.info(
                '字幕生成任务开始 input_dir=%s model_root=%s infer_exe=%s device=%s sub_formats=%s overwrite=%s',
                directory,
                self.config.model_root,
                self.config.infer_exe,
                self.config.device,
                ','.join(self.config.sub_formats),
                self.config.overwrite,
            )
            try:
                self.config.validate()
                directory.mkdir(parents=True, exist_ok=True)
            except Exception:
                LOGGER.exception('字幕生成任务初始化失败 input_dir=%s', directory)
                raise

            video_paths = self._find_videos(directory)
            LOGGER.info('字幕生成发现视频 video_count=%d videos=%s', len(video_paths), [str(path) for path in video_paths])
            if not video_paths:
                LOGGER.warning('字幕生成任务结束：固定目录中没有支持的视频文件 input_dir=%s duration_ms=%.3f', directory, (perf_counter() - started_at) * 1000)
                return {
                    'run_id': run_id,
                    'input_dir': str(directory),
                    'video_count': 0,
                    'results': [],
                    'success_count': 0,
                    'failed_count': 0,
                    'message': '固定字幕目录中没有支持的视频文件',
                }
            prepared_paths, rename_entries, manifest_path, preparation_failures = self._prepare_video_names(
                video_paths,
                run_id,
            )
            try:
                results = preparation_failures + self._run_infer(
                    directory,
                    prepared_paths,
                    organize=False,
                )
            finally:
                self._restore_video_names(rename_entries, manifest_path)
            results = self._restore_result_paths(results, rename_entries)
            results = self._organize_completed_results(results)
            success_count = sum(result['status'] == 'completed' for result in results)
            failed_count = len(results) - success_count
            LOGGER.info(
                '字幕生成任务结束 input_dir=%s video_count=%d success_count=%d failed_count=%d duration_ms=%.3f',
                directory,
                len(video_paths),
                success_count,
                failed_count,
                (perf_counter() - started_at) * 1000,
            )
            return {
                'run_id': run_id,
                'input_dir': str(directory),
                'video_count': len(video_paths),
                'results': results,
                'success_count': success_count,
                'failed_count': failed_count,
            }

    def _run_infer(self, directory, video_paths, organize=True):
        command = [
            str(self.config.infer_exe),
            f'--audio_suffixes={VIDEO_SUFFIX_ARGUMENT}',
            f'--sub_formats={",".join(self.config.sub_formats)}',
            f'--device={self.config.device}',
        ]
        if self.config.overwrite:
            command.append('--overwrite')
        command.append(str(directory))
        process_env = os.environ.copy()
        process_env.update({
            'PYTHONIOENCODING': 'utf-8',
            'PYTHONUTF8': '1',
        })
        creation_flags = getattr(subprocess, 'CREATE_NEW_CONSOLE', 0x10)
        LOGGER.info('字幕模型进程启动 cwd=%s command=%s video_count=%d console=new', self.config.model_root, command, len(video_paths))
        started_at = perf_counter()
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.config.model_root),
                text=True,
                encoding='utf-8',
                errors='replace',
                env=process_env,
                creationflags=creation_flags,
                check=False,
            )
        except OSError as exc:
            LOGGER.exception('字幕模型进程启动失败 cwd=%s command=%s', self.config.model_root, command)
            return [self._failed_result(path, str(exc)) for path in video_paths]

        LOGGER.info(
            '模型进程结束 returncode=%s duration_ms=%.3f stdout=%s stderr=%s',
            completed.returncode,
            (perf_counter() - started_at) * 1000,
            self._output_summary(completed.stdout),
            self._output_summary(completed.stderr),
        )

        process_warning = ''
        if completed.returncode != 0:
            process_warning = (
                f'模型进程非正常退出，退出码={completed.returncode}; '
                f'stderr={self._output_summary(completed.stderr)}'
            )
            LOGGER.warning('%s，继续检查字幕文件', process_warning)

        results = []
        for path in video_paths:
            subtitle_paths = [path.with_suffix(f'.{suffix}') for suffix in self.config.sub_formats]
            missing = [str(target) for target in subtitle_paths if not target.is_file()]
            if missing:
                error = f'字幕未生成: {", ".join(missing)}'
                if process_warning:
                    error = f'{process_warning}; {error}'
                LOGGER.error('视频字幕文件缺失 video_path=%s expected=%s missing=%s error=%s', path, subtitle_paths, missing, error)
                results.append(self._failed_result(path, error))
                continue
            if organize:
                try:
                    organized_video, organized_subtitles = self._organize_files(path, subtitle_paths)
                except OSError as exc:
                    LOGGER.exception('视频和字幕归档失败 video_path=%s subtitle_paths=%s', path, subtitle_paths)
                    results.append(self._failed_result(path, f'视频和字幕归档失败: {exc}'))
                    continue
                LOGGER.info('视频和字幕归档完成 video_path=%s organized_video=%s subtitle_paths=%s', path, organized_video, organized_subtitles)
            else:
                organized_video, organized_subtitles = path, subtitle_paths
            result = {
                'video_path': str(organized_video),
                'status': 'completed',
                'subtitle_paths': [str(target) for target in organized_subtitles],
                'error': '',
            }
            if process_warning:
                result['warning'] = process_warning
                LOGGER.warning('字幕文件完整，忽略模型收尾退出码 video_path=%s warning=%s', path, process_warning)
            results.append(result)
        return results

    def _prepare_video_names(self, video_paths, run_id):
        entries = []
        prepared_paths = []
        failures = []
        manifest_path = None
        for path in video_paths:
            code = extract_code(path.stem) or path.stem
            temporary_path = path.with_name(f'{code}{path.suffix}')
            if temporary_path == path:
                prepared_paths.append(path)
                continue
            if temporary_path.exists():
                LOGGER.error('临时视频名称冲突 original_path=%s temporary_path=%s', path, temporary_path)
                failures.append(self._failed_result(path, f'临时文件名已存在: {temporary_path}'))
                continue
            path.rename(temporary_path)
            entries.append({'original_path': str(path), 'temporary_path': str(temporary_path)})
            prepared_paths.append(temporary_path)

        if entries:
            handle, raw_manifest_path = tempfile.mkstemp(
                prefix=f'subtitle_generation_{run_id}_',
                suffix='.json',
            )
            os.close(handle)
            manifest_path = Path(raw_manifest_path)
            manifest_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding='utf-8')
            LOGGER.info('视频临时改名完成 manifest=%s entries=%s', manifest_path, entries)
        return prepared_paths, entries, manifest_path, failures

    @staticmethod
    def _restore_video_names(entries, manifest_path):
        for entry in reversed(entries or []):
            original_path = Path(entry['original_path'])
            temporary_path = Path(entry['temporary_path'])
            try:
                if temporary_path.exists() and not original_path.exists():
                    temporary_path.rename(original_path)
                LOGGER.info('视频原名恢复完成 original_path=%s', original_path)
            except OSError:
                LOGGER.exception('视频和字幕原名恢复失败 original_path=%s temporary_path=%s', original_path, temporary_path)
        if manifest_path:
            try:
                Path(manifest_path).unlink(missing_ok=True)
            except OSError:
                LOGGER.exception('字幕临时映射文件清理失败 manifest=%s', manifest_path)

    @staticmethod
    def _restore_result_paths(results, entries):
        path_map = {entry['temporary_path']: entry['original_path'] for entry in entries or []}
        restored = []
        for result in results:
            item = dict(result)
            temporary_video = str(item.get('video_path', '') or '')
            original_video = path_map.get(temporary_video, temporary_video)
            item['video_path'] = original_video
            restored.append(item)
        return restored

    def _organize_completed_results(self, results):
        organized = []
        for result in results:
            if result.get('status') != 'completed':
                organized.append(result)
                continue
            path = Path(result['video_path'])
            subtitles = [Path(path) for path in result.get('subtitle_paths', [])]
            try:
                organized_video, organized_subtitles = self._organize_files(path, subtitles)
            except OSError as exc:
                LOGGER.exception('视频和字幕归档失败 video_path=%s subtitle_paths=%s', path, subtitles)
                organized.append(self._failed_result(path, f'视频和字幕归档失败: {exc}'))
                continue
            LOGGER.info('视频和字幕归档完成 video_path=%s organized_video=%s subtitle_paths=%s', path, organized_video, organized_subtitles)
            item = dict(result)
            item['video_path'] = str(organized_video)
            item['subtitle_paths'] = [str(target) for target in organized_subtitles]
            organized.append(item)
        return organized

    @staticmethod
    def _organize_files(video_path, subtitle_paths):
        """Put one video and subtitles under a folder named by its full video code."""
        folder_name = extract_code(video_path.stem) or video_path.stem
        if video_path.parent.name.upper() == folder_name.upper():
            return video_path, subtitle_paths

        target_dir = video_path.parent / folder_name
        target_paths = [target_dir / video_path.name]
        target_paths.extend(target_dir / subtitle_path.name for subtitle_path in subtitle_paths)
        if any(target.exists() for target in target_paths):
            raise FileExistsError(f'目标文件已存在: {target_dir}')

        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(video_path), str(target_paths[0]))
        for source, target in zip(subtitle_paths, target_paths[1:]):
            shutil.move(str(source), str(target))
        return target_paths[0], target_paths[1:]

    @staticmethod
    def _find_videos(directory):
        return sorted(
            path for path in directory.rglob('*')
            if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES
        )

    @staticmethod
    def _output_summary(value, limit=4000):
        text = str(value or '').strip()
        if len(text) <= limit:
            return text or '<empty>'
        return f'{text[:limit]}...<truncated chars={len(text) - limit}>'

    @staticmethod
    def _failed_result(path, error):
        return {
            'video_path': str(path),
            'status': 'failed',
            'subtitle_paths': [],
            'error': str(error or '字幕生成失败'),
        }
