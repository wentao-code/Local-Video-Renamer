from app.core.windows_filename_sanitizer import sanitize_windows_extension, sanitize_windows_filename_part


def build_video_filename_stem(metadata):
    code = sanitize_windows_filename_part(metadata.code or '', fallback='无码')
    title = sanitize_windows_filename_part(metadata.title or '', fallback=code)
    author = sanitize_windows_filename_part(metadata.author or '', fallback='')

    if author:
        return f'【{code}】-{title}-{{{author}}}'
    return f'【{code}】-{title}'


def build_video_filename(metadata, extension):
    return build_video_filename_stem(metadata) + sanitize_windows_extension(extension)
