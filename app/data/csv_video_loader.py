import csv
from pathlib import Path

from app.core.filename_rules import clean_video_title, normalize_text_spacing
from app.core.video_models import VideoMetadata


def load_video_database(csv_path):
    csv_path = Path(csv_path)
    video_db = {}

    if not csv_path.exists():
        raise FileNotFoundError(f'未找到 CSV 数据库文件: {csv_path}')

    with csv_path.open(mode='r', encoding='utf-8-sig', errors='ignore', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row.get('系列名称', '').strip()
            author = normalize_text_spacing(row.get('演员', ''))
            raw_name = row.get('名称', '').strip()
            duration = row.get('时长(可读)', '').strip()
            size = row.get('大小(GB)', '').strip()

            if not code:
                continue

            normalized_code = code.upper()
            video_db[normalized_code] = VideoMetadata(
                code=normalized_code,
                title=clean_video_title(code, author, raw_name),
                author=author,
                duration=duration,
                size=size,
            )
    return video_db
