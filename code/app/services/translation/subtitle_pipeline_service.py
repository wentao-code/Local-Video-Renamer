from __future__ import annotations

import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from app.core.app_logging import get_logger, get_task_id, log_context, new_run_id, new_task_id
from app.core.operation_timeout_settings import get_operation_timeout_seconds
from app.core.video_code import standardize_video_code
from app.services.parsers.code_prefix_entry_parser import extract_code
from app.services.translation.subtitle_preflight import VIDEO_SUFFIXES, classify_videos

LOGGER = get_logger(__name__)


class SubtitlePipelineService:
    """Run subtitle generation and soft-subtitle muxing as one sequential pipeline."""

    def __init__(self, subtitle_generation_service, soft_subtitle_generation_service):
        self.subtitle_generation_service = subtitle_generation_service
        self.soft_subtitle_generation_service = soft_subtitle_generation_service

    def run(
        self,
        input_dir=None,
        candidate_codes=None,
        candidate_run_id=None,
        manage_candidate_task=True,
    ):
        directory = self._resolve_input_dir(input_dir)
        selected_codes = self._normalize_candidate_codes(candidate_codes)
        directory_name = directory.name
        run_id = new_run_id('subtitle_pipeline', directory_name)
        task_id = get_task_id() or new_task_id()
        with log_context(run_id=run_id, task_id=task_id):
            LOGGER.info('字幕流水线任务开始 input_dir=%s', directory)
            preflight = classify_videos(directory)
            if selected_codes is not None:
                preflight['embedded'] = [
                    video for video in preflight['embedded']
                    if self._video_code(video) in selected_codes
                ]
                preflight['external'] = [
                    item for item in preflight['external']
                    if self._video_code(item['video']) in selected_codes
                ]
                preflight['none'] = [
                    video for video in preflight['none']
                    if self._video_code(video) in selected_codes
                ]
            embedded_count = len(preflight['embedded'])
            external_count = len(preflight['external'])
            missing_count = len(preflight['none'])
            LOGGER.info(
                '字幕流水线预检 embedded=%d external=%d missing=%d',
                embedded_count,
                external_count,
                missing_count,
            )
            if manage_candidate_task:
                self.subtitle_generation_service.update_candidate_task(
                    candidate_run_id,
                    status='running',
                    selected_codes=selected_codes,
                )
            external_organized = set()
            external_failures = []
            generation_results = []
            generation_success_count = 0
            generation_failed_count = 0
            generation_run_id = ''
            mux_results = []
            mux_success_count = 0
            mux_failed_count = 0
            mux_run_id = ''
            generation_statuses = {}
            hold = self._create_hold_dir(directory)
            try:
                jobs = [
                    ('external', item['video'], item) for item in preflight['external']
                ] + [
                    ('missing', video, None) for video in preflight['none']
                ]
                jobs.sort(key=lambda item: str(item[1]).casefold())
                for job_type, video, external_item in jobs:
                    code = self._video_code(video)
                    if job_type == 'external':
                        held_entry = self._move_to_hold(video, hold)
                        external_entry = {
                            'original': held_entry['original'],
                            'held': held_entry['held'],
                            'subtitle': external_item['subtitle'],
                        }
                        organized, failures = self._organize_external_videos(
                            directory,
                            [external_entry],
                        )
                        if organized:
                            external_organized.update(organized)
                            generation_statuses[code] = 'completed'
                        else:
                            external_failures.extend(failures)
                            generation_statuses[code] = 'failed'
                            self._restore_held([external_entry])
                        mux_target_ready = bool(organized)
                    else:
                        generation_item = self.subtitle_generation_service.generate_from_directory(
                            input_dir=input_dir,
                            candidate_codes={code},
                        )
                        generation_run_id = generation_item.get('run_id', '')
                        generation_results.extend(generation_item.get('results', []) or [])
                        generation_success_count += int(generation_item.get('success_count') or 0)
                        generation_failed_count += int(generation_item.get('failed_count') or 0)
                        generation_statuses.update({
                            self._video_code(item.get('video_path', '')): item.get('status', 'failed')
                            for item in generation_item.get('results', []) or []
                        })
                        mux_target_ready = generation_statuses.get(code) == 'completed'

                    if mux_target_ready:
                        mux_item = self.soft_subtitle_generation_service.generate_from_directory(
                            input_dir=str(directory),
                            candidate_codes={code},
                        )
                        mux_run_id = mux_item.get('run_id', '')
                        mux_results.extend(mux_item.get('results', []) or [])
                        mux_success_count += int(mux_item.get('success_count') or 0)
                        mux_failed_count += int(mux_item.get('failed_count') or 0)
                        if int(mux_item.get('failed_count') or 0) > 0:
                            generation_statuses[code] = 'failed'
                    self.subtitle_generation_service.update_candidate_task(
                        candidate_run_id,
                        result_statuses={code: generation_statuses.get(code, 'failed')},
                    )

                generation = {
                    'run_id': generation_run_id,
                    'input_dir': str(directory),
                    'video_count': generation_success_count + generation_failed_count,
                    'success_count': generation_success_count,
                    'failed_count': generation_failed_count,
                    'results': generation_results,
                } if generation_results or generation_success_count or generation_failed_count else None
                mux = {
                    'run_id': mux_run_id,
                    'input_dir': str(directory),
                    'directory_count': mux_success_count + mux_failed_count,
                    'success_count': mux_success_count,
                    'failed_count': mux_failed_count,
                    'results': mux_results,
                } if mux_results or mux_success_count or mux_failed_count else None
                task_status = 'completed' if not any(
                    value == 'failed' for value in generation_statuses.values()
                ) else 'completed_with_errors'
                if manage_candidate_task:
                    self.subtitle_generation_service.update_candidate_task(
                        candidate_run_id,
                        status=task_status,
                        result_statuses=generation_statuses,
                    )
            finally:
                shutil.rmtree(hold, ignore_errors=True)
            return self._build_result(
                run_id,
                task_id,
                generation,
                mux,
                {
                    'embedded_count': embedded_count,
                    'external_count': external_count,
                    'missing_count': missing_count,
                },
                external_organized,
                external_failures,
            )

    @staticmethod
    def _video_code(video_path):
        path = Path(video_path)
        return standardize_video_code(extract_code(path.stem) or path.stem)

    @staticmethod
    def _normalize_candidate_codes(candidate_codes):
        if candidate_codes is None:
            return None
        return {
            standardize_video_code(str(code or '').strip())
            for code in candidate_codes
            if str(code or '').strip()
        }

    def _resolve_input_dir(self, input_dir):
        if input_dir:
            return Path(input_dir).expanduser()
        config = getattr(self.subtitle_generation_service, 'config', None)
        configured = getattr(config, 'input_dir', None)
        if isinstance(configured, (str, Path)):
            return Path(configured).expanduser()
        soft_input = getattr(self.soft_subtitle_generation_service, 'input_dir', None)
        if isinstance(soft_input, (str, Path)):
            return Path(soft_input).expanduser()
        return Path('subtitles').expanduser()

    @staticmethod
    def _move_to_hold(video, hold):
        held = hold / video.name
        if held.exists():
            held = hold / f'{video.stem}_{uuid.uuid4().hex[:6]}{video.suffix}'
        shutil.move(str(video), str(held))
        return {'original': video, 'held': held}

    @staticmethod
    def _create_hold_dir(directory):
        hold = directory.parent / f'.subtitle_pipeline_hold_{uuid.uuid4().hex[:10]}'
        try:
            hold.mkdir(parents=False, exist_ok=False)
            return hold
        except OSError:
            pass
        return Path(tempfile.mkdtemp(prefix='subtitle_pipeline_hold_'))

    @staticmethod
    def _restore_held(entries):
        for entry in entries or []:
            held = Path(entry['held'])
            original = Path(entry['original'])
            try:
                if held.exists() and not original.exists():
                    held.rename(original)
                    LOGGER.info('暂存视频恢复完成 original=%s', original)
            except OSError:
                LOGGER.exception('暂存视频恢复失败 original=%s', original)

    def _organize_external_videos(self, directory, external_entries):
        organized = set()
        failures = []
        for entry in external_entries:
            video = Path(entry['original'])
            held = Path(entry['held'])
            subtitle = Path(entry['subtitle'])
            code = standardize_video_code(extract_code(video.stem) or video.stem)
            if not code:
                failures.append((video, '无法识别番号'))
                continue
            target_dir = directory / code
            if video.parent.name.upper() == code.upper():
                target_dir = video.parent
            target_vtt = target_dir / f'{code}.vtt'
            target_video = target_dir / video.name
            try:
                if target_dir.exists() and any(
                    path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES
                    for path in target_dir.iterdir()
                ):
                    raise FileExistsError(f'编号目录已有视频: {target_dir}')
                target_dir.mkdir(parents=True, exist_ok=True)
                self._convert_subtitle_to_vtt(subtitle, target_vtt)
                if target_video.exists():
                    raise FileExistsError(f'目标文件已存在: {target_video}')
                held.rename(target_video)
                LOGGER.info(
                    '外挂字幕视频整理完成 video=%s target=%s vtt=%s',
                    video,
                    target_video,
                    target_vtt,
                )
                organized.add(video)
            except Exception as exc:
                LOGGER.exception('外挂字幕视频整理失败 video=%s', video)
                failures.append((video, str(exc)))
        return organized, failures

    @staticmethod
    def _convert_subtitle_to_vtt(subtitle, target_vtt):
        if subtitle.suffix.lower() == '.vtt':
            if subtitle.resolve() == target_vtt.resolve():
                return target_vtt
            shutil.copyfile(subtitle, target_vtt)
            try:
                subtitle.unlink(missing_ok=True)
            except OSError:
                LOGGER.warning('外挂 vtt 原始文件清理失败 path=%s', subtitle)
            return target_vtt
        ffmpeg_exe = shutil.which('ffmpeg') or 'ffmpeg'
        completed = subprocess.run(
            [ffmpeg_exe, '-y', '-i', str(subtitle), '-c:s', 'webvtt', str(target_vtt)],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=False,
            timeout=get_operation_timeout_seconds('local_media_read'),
        )
        if completed.returncode != 0 or not target_vtt.is_file():
            detail = str(completed.stderr or completed.stdout or '').strip()[:200]
            raise RuntimeError(f'字幕转换失败: {detail}')
        try:
            subtitle.unlink(missing_ok=True)
        except OSError:
            LOGGER.warning('外挂字幕原始文件清理失败 path=%s', subtitle)
        return target_vtt

    @staticmethod
    def _build_result(run_id, task_id, generation, mux, preflight, external_organized, external_failures):
        embedded_count = int(preflight.get('embedded_count') or 0)
        external_count = int(preflight.get('external_count') or 0)
        missing_count = int(preflight.get('missing_count') or 0)
        generation_success = int((generation or {}).get('success_count') or 0)
        generation_failed = int((generation or {}).get('failed_count') or 0)
        mux_success = int((mux or {}).get('success_count') or 0)
        mux_failed = int((mux or {}).get('failed_count') or 0)
        external_organized_count = len(external_organized)
        external_failed_count = len(external_failures)
        if mux is None:
            if missing_count == 0 and external_count == 0 and embedded_count == 0:
                message = '输入目录中没有视频，未执行软字幕封装'
            elif missing_count == 0 and external_count == 0:
                message = '所有视频均已内嵌字幕，无需生成或封装'
            else:
                message = '没有需要生成或封装的字幕任务'
        else:
            message = (
                f'已内嵌字幕（跳过）{embedded_count} 个；'
                f'外挂字幕整理 {external_organized_count} 个（失败 {external_failed_count} 个）；'
                f'字幕生成 {generation_success} 成功、{generation_failed} 失败；'
                f'软字幕封装 {mux_success} 成功、{mux_failed} 失败'
            )
        return {
            'run_id': run_id,
            'task_id': task_id,
            'input_dir': str((generation or mux or {}).get('input_dir') or ''),
            'generation_run_id': str((generation or {}).get('run_id') or ''),
            'mux_run_id': str((mux or {}).get('run_id') or ''),
            'generation': generation,
            'mux': mux,
            'embedded_count': embedded_count,
            'external_count': external_count,
            'missing_count': missing_count,
            'external_organized_count': external_organized_count,
            'external_failed_count': external_failed_count,
            'skipped_count': generation_failed,
            'success_count': mux_success,
            'failed_count': mux_failed,
            'message': message,
        }
