from __future__ import annotations

import os
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from time import perf_counter
from pathlib import Path

from app.core.app_logging import get_logger, get_task_id, log_context, new_run_id, new_task_id
from app.core.project_paths import SUBTITLE_GENERATION_RECORD_FILE, SUBTITLE_GENERATION_TASK_DIR
from app.core.translation_config import TranslationConfig
from app.core.video_code import standardize_video_code
from app.services.parsers.code_prefix_entry_parser import extract_code
from app.services.translation.subtitle_preflight import probe_subtitle_stream_count


VIDEO_SUFFIXES = frozenset(('.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.wmv'))
VIDEO_SUFFIX_ARGUMENT = 'mp4,mkv,avi,mov,webm,flv,wmv'
LOGGER = get_logger(__name__)


class SubtitleGenerationService:
    """Generate subtitles for every supported video under one fixed directory."""

    def __init__(self, config: TranslationConfig, record_file=None, task_dir=None):
        self.config = config
        self.record_file = Path(record_file or SUBTITLE_GENERATION_RECORD_FILE).expanduser()
        self.task_dir = Path(task_dir or SUBTITLE_GENERATION_TASK_DIR).expanduser()

    def generate_from_directory(self, input_dir=None, candidate_codes=None):
        directory = Path(input_dir or self.config.input_dir).expanduser()
        selected_codes = self._normalize_candidate_codes(candidate_codes)
        run_id = new_run_id('subtitle_generation', directory.name)
        task_id = get_task_id() or new_task_id()
        started_at = perf_counter()
        with log_context(run_id=run_id, task_id=task_id):
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

            all_video_paths = self._find_videos(directory)
            if selected_codes is not None:
                all_video_paths = [
                    path for path in all_video_paths
                    if standardize_video_code(extract_code(path.stem) or path.stem) in selected_codes
                ]
            records = self._load_records()
            directory_record = records.get('directories', {}).get(str(directory.resolve()), {})
            video_records = directory_record.get('videos', {}) if isinstance(directory_record, dict) else {}
            recorded_count = 0
            video_paths = []
            for path in all_video_paths:
                video_code = extract_code(path.stem) or path.stem
                record_entry = video_records.get(video_code)
                if isinstance(record_entry, dict) and self._record_entry_completed(record_entry):
                    recorded_count += 1
                if not self._has_complete_subtitles(path, record_entry=record_entry):
                    video_paths.append(path)
            skipped_count = len(all_video_paths) - len(video_paths)
            LOGGER.info(
                '字幕生成发现视频 discovered_count=%d candidate_count=%d skipped_complete_count=%d recorded_count=%d',
                len(all_video_paths),
                len(video_paths),
                skipped_count,
                recorded_count,
            )
            if not video_paths:
                LOGGER.warning('字幕生成任务结束：固定目录中没有支持的视频文件 input_dir=%s duration_ms=%.3f', directory, (perf_counter() - started_at) * 1000)
                return {
                    'run_id': run_id,
                    'task_id': task_id,
                    'input_dir': str(directory),
                    'video_count': 0,
                    'discovered_video_count': len(all_video_paths),
                    'skipped_count': skipped_count,
                    'recorded_count': recorded_count,
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
            results = self._organize_completed_results(
                results,
                on_completed=lambda result: self._record_completed_video(directory, result),
            )
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
                'task_id': task_id,
                'input_dir': str(directory),
                'video_count': len(video_paths),
                'discovered_video_count': len(all_video_paths),
                'skipped_count': skipped_count,
                'recorded_count': recorded_count,
                'results': results,
                'success_count': success_count,
                'failed_count': failed_count,
            }

    def prepare_candidates(self, input_dir=None):
        directory = Path(input_dir or self.config.input_dir).expanduser()
        run_id = new_run_id('subtitle_candidates', directory.name)
        task_id = get_task_id() or new_task_id()
        with log_context(run_id=run_id, task_id=task_id):
            self.config.validate()
            directory.mkdir(parents=True, exist_ok=True)
            all_video_paths = self._find_videos(directory)
            records = self._load_records()
            directory_record = records.get('directories', {}).get(str(directory.resolve()), {})
            video_records = directory_record.get('videos', {}) if isinstance(directory_record, dict) else {}
            candidates = []
            for path in all_video_paths:
                video_code = extract_code(path.stem) or path.stem
                record_entry = video_records.get(video_code)
                if probe_subtitle_stream_count(path) > 0:
                    continue
                external_subtitle = self._find_external_subtitle(path)
                candidates.append({
                    'video_code': video_code,
                    'video_path': str(path),
                    'status': 'pending',
                    'reason': '已有外挂字幕，等待软字幕封装' if external_subtitle else '无内嵌字幕和完整外挂字幕，需要生成字幕',
                    'has_embedded_subtitle': False,
                    'has_external_subtitle': bool(external_subtitle),
                })
            payload = {
                'version': 1,
                'run_id': run_id,
                'task_id': task_id,
                'status': 'pending_confirmation',
                'created_at': datetime.now(timezone.utc).isoformat(),
                'input_dir': str(directory),
                'candidates': candidates,
                'candidate_count': len(candidates),
            }
            task_file = self.task_dir / f'{run_id}.json'
            self._save_json_atomic(task_file, payload)
            LOGGER.info('字幕候选任务文件已生成 task_file=%s candidate_count=%d', task_file, len(candidates))
            return {
                'run_id': run_id,
                'task_id': task_id,
                'task_file': str(task_file),
                'input_dir': str(directory),
                'candidate_count': len(candidates),
                'candidates': candidates,
            }

    @staticmethod
    def _normalize_candidate_codes(candidate_codes):
        if candidate_codes is None:
            return None
        return {
            standardize_video_code(str(code or '').strip())
            for code in candidate_codes
            if str(code or '').strip()
        }

    def update_candidate_task(self, run_id, *, status=None, selected_codes=None, result_statuses=None):
        if not run_id:
            return None
        task_file = self.task_dir / f'{str(run_id).strip()}.json'
        if not task_file.is_file():
            LOGGER.warning('字幕候选任务文件不存在 run_id=%s task_file=%s', run_id, task_file)
            return None
        try:
            payload = json.loads(task_file.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            LOGGER.exception('字幕候选任务文件读取失败 task_file=%s', task_file)
            return None
        selected = self._normalize_candidate_codes(selected_codes)
        result_map = {
            standardize_video_code(str(code or '').strip()): str(value or '').strip()
            for code, value in dict(result_statuses or {}).items()
            if str(code or '').strip()
        }
        for candidate in payload.get('candidates', []):
            code = str(candidate.get('video_code', '') or '').strip()
            normalized_code = standardize_video_code(code)
            if selected is not None and normalized_code not in selected and candidate.get('status') == 'pending':
                candidate['status'] = 'cancelled'
            if normalized_code in result_map:
                candidate['status'] = result_map[normalized_code]
        if status:
            payload['status'] = str(status)
        elif result_map:
            candidate_statuses = {
                str(candidate.get('status', '') or '').strip().lower()
                for candidate in payload.get('candidates', [])
            }
            terminal_statuses = {'completed', 'failed', 'cancelled'}
            if candidate_statuses and candidate_statuses.issubset(terminal_statuses):
                payload['status'] = (
                    'completed_with_errors' if 'failed' in candidate_statuses else 'completed'
                )
        payload['updated_at'] = datetime.now(timezone.utc).isoformat()
        self._save_json_atomic(task_file, payload)
        return payload

    @staticmethod
    def _find_external_subtitle(video_path):
        from app.services.translation.subtitle_preflight import find_external_subtitle

        return find_external_subtitle(video_path)

    def _run_infer(self, directory, video_paths, organize=True):
        command = [
            str(self.config.infer_exe),
            f'--audio_suffixes={VIDEO_SUFFIX_ARGUMENT}',
            f'--sub_formats={",".join(self.config.sub_formats)}',
            f'--device={self.config.device}',
        ]
        if self.config.overwrite:
            command.append('--overwrite')
        process_env = os.environ.copy()
        process_env.update({
            'PYTHONIOENCODING': 'utf-8',
            'PYTHONUTF8': '1',
        })
        creation_flags = getattr(subprocess, 'CREATE_NEW_CONSOLE', 0x10)
        results = []
        for path in video_paths:
            video_command = [*command, str(path)]
            LOGGER.info(
                '字幕模型进程启动 cwd=%s command=%s video_count=1 timeout_seconds=%s',
                self.config.model_root,
                video_command,
                self.config.video_timeout_seconds,
            )
            started_at = perf_counter()
            try:
                completed = subprocess.run(
                    video_command,
                    cwd=str(self.config.model_root),
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    env=process_env,
                    creationflags=creation_flags,
                    check=False,
                    timeout=self.config.video_timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                duration_ms = (perf_counter() - started_at) * 1000
                LOGGER.exception(
                    '单视频字幕生成超时 video_path=%s timeout_seconds=%s duration_ms=%.3f',
                    path,
                    self.config.video_timeout_seconds,
                    duration_ms,
                )
                results.append(self._failed_result(path, f'单视频字幕生成超时: {self.config.video_timeout_seconds} 秒'))
                continue
            except OSError as exc:
                LOGGER.exception('字幕模型进程启动失败 cwd=%s command=%s', self.config.model_root, video_command)
                results.append(self._failed_result(path, str(exc)))
                continue

            LOGGER.info(
                '模型进程结束 video_path=%s returncode=%s duration_ms=%.3f stdout=%s stderr=%s',
                path,
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
                LOGGER.warning('%s，继续检查字幕文件 video_path=%s', process_warning, path)

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

    def _organize_completed_results(self, results, on_completed=None):
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
            if on_completed:
                on_completed(item)
        return organized

    def _load_records(self):
        if not self.record_file.is_file():
            return {'version': 1, 'directories': {}}
        try:
            payload = json.loads(self.record_file.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            LOGGER.exception('字幕生成记录读取失败，使用空记录 record_file=%s', self.record_file)
            return {'version': 1, 'directories': {}}
        if not isinstance(payload, dict) or not isinstance(payload.get('directories'), dict):
            LOGGER.warning('字幕生成记录格式无效，使用空记录 record_file=%s', self.record_file)
            return {'version': 1, 'directories': {}}
        return payload

    def _record_completed_video(self, directory, result):
        path = Path(result['video_path'])
        video_code = extract_code(path.stem) or path.stem
        records = self._load_records()
        directory_key = str(directory.resolve())
        directory_record = records.setdefault('directories', {}).setdefault(directory_key, {'videos': {}})
        video_records = directory_record.setdefault('videos', {})
        video_records[video_code] = {
            'status': 'completed',
            'subtitle_generation_status': 'completed',
            'video_path': str(path),
            'subtitle_paths': list(result.get('subtitle_paths', [])),
            'completed_at': datetime.now(timezone.utc).isoformat(),
        }
        self._save_records(records)
        LOGGER.info('字幕生成完成记录已写入 video_code=%s video_path=%s record_file=%s', video_code, path, self.record_file)

    def _save_records(self, payload):
        self._save_json_atomic(self.record_file, payload)

    @staticmethod
    def _save_json_atomic(target_path, payload):
        target_path = Path(target_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            handle, raw_path = tempfile.mkstemp(
                prefix=f'{target_path.stem}_',
                suffix='.tmp',
                dir=str(target_path.parent),
            )
            temporary_path = Path(raw_path)
            with os.fdopen(handle, 'w', encoding='utf-8', newline='\n') as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, target_path)
        except OSError:
            LOGGER.exception('字幕 JSON 记录写入失败 record_file=%s', target_path)
            if temporary_path:
                temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _record_entry_completed(record_entry):
        return str(
            record_entry.get('subtitle_generation_status', record_entry.get('status', ''))
            or ''
        ).strip().lower() == 'completed'

    def _has_complete_subtitles(self, video_path, record_entry=None):
        if probe_subtitle_stream_count(video_path) > 0:
            LOGGER.info('视频已包含内嵌字幕流，跳过字幕生成 video_path=%s', video_path)
            return True
        has_external_subtitles = all(
            video_path.with_suffix(f'.{suffix}').is_file()
            for suffix in self.config.sub_formats
        )
        if has_external_subtitles:
            LOGGER.info('视频外挂字幕文件完整，跳过字幕生成 video_path=%s', video_path)
        elif isinstance(record_entry, dict) and self._record_entry_completed(record_entry):
            LOGGER.info(
                '字幕完成记录已过期，实际字幕不完整，重新加入候选 video_path=%s',
                video_path,
            )
        return has_external_subtitles

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
