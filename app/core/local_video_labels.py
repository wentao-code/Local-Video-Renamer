IMPORT_REQUIRED_STATUS = '待导入'
ENRICHMENT_REQUIRED_STATUS = '待补全'
RENAME_REQUIRED_STATUS = '待重命名'
NORMALIZED_STATUS = '已规范'

IMPORT_REQUIRED_PREVIEW = '待导入数据库'
ENRICHMENT_REQUIRED_PREVIEW = '数据库无标题，待补全'

RENAME_SKIPPED_MESSAGE = '数据库缺少标题，未重命名'
ALREADY_NORMALIZED_MESSAGE = '已规范，无需修改'
TARGET_EXISTS_MESSAGE = '目标文件已存在'
RENAME_COMPLETED_MESSAGE = '完成'


def build_preview_name(new_name, exists_in_db, can_rename):
    if not exists_in_db:
        return IMPORT_REQUIRED_PREVIEW
    if not can_rename:
        return ENRICHMENT_REQUIRED_PREVIEW
    return new_name


def build_row_status(needs_rename, exists_in_db, can_rename):
    if not exists_in_db:
        return IMPORT_REQUIRED_STATUS
    if not can_rename:
        return ENRICHMENT_REQUIRED_STATUS
    if needs_rename:
        return RENAME_REQUIRED_STATUS
    return NORMALIZED_STATUS
