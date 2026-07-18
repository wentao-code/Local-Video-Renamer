"""Human-readable status rules used by the rule fields viewer."""

from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    NO_VIDEO_DETAIL_STATUS,
    PENDING_STATUS,
    STATUS_REGISTRY,
    UNENRICHED_STATUS,
)


_LIBRARY_STATUS_DESCRIPTIONS = {
    UNENRICHED_STATUS: '尚未加入候选任务，或尚未执行补全。',
    NO_SEARCH_RESULTS_STATUS: '已经执行补全，但目标来源没有找到搜索结果。',
    NO_VIDEO_DETAIL_STATUS: '已经找到搜索结果，但详情字段仍不完整。',
    ENRICHED_STATUS: '已经找到搜索结果，要求的详情字段已完整保存。',
    FAILED_STATUS: '本次补全执行失败，等待后续重试。',
    PENDING_STATUS: '已经入选候选任务，等待领取或正在执行。',
}

LIBRARY_STATUS_RULES = tuple(
    (
        STATUS_REGISTRY[code]['display_code'],
        STATUS_REGISTRY[code]['label'],
        _LIBRARY_STATUS_DESCRIPTIONS[code],
        '天限阁、辛聚谷、补充任务',
    )
    for code in (
        UNENRICHED_STATUS,
        NO_SEARCH_RESULTS_STATUS,
        NO_VIDEO_DETAIL_STATUS,
        ENRICHED_STATUS,
        FAILED_STATUS,
        PENDING_STATUS,
    )
)


PROFILE_STATUS_RULES = (
    ('状态0', '资料完整', '生日、身高、胸围、罩杯、腰围、臀围均已具备。'),
    ('状态1', '无搜索结果', '来源页面没有找到该演员的有效搜索结果。'),
    ('状态2', '仅有搜索结果', '找到了演员，但生日、身高、三围、罩杯均缺失。'),
    ('状态3', '仅生日', '有生日，缺少身高、三围和罩杯。'),
    ('状态4', '仅三围', '有胸围、腰围、臀围，缺少生日、身高和罩杯。'),
    ('状态5', '仅身高', '有身高，缺少生日、三围和罩杯。'),
    ('状态6', '仅罩杯', '有罩杯，缺少生日、身高和三围。'),
    ('状态7', '生日和三围', '有生日及胸围、腰围、臀围，缺少身高和罩杯。'),
    ('状态8', '生日和身高', '有生日和身高，缺少三围和罩杯。'),
    ('状态9', '生日和罩杯', '有生日和罩杯，缺少身高和三围。'),
    ('状态10', '三围和身高', '有胸围、腰围、臀围及身高，缺少生日和罩杯。'),
    ('状态11', '三围和罩杯', '有胸围、腰围、臀围及罩杯，缺少生日和身高。'),
    ('状态12', '身高和罩杯', '有身高和罩杯，缺少生日和三围。'),
    ('状态13', '三围、身高和罩杯', '有胸围、腰围、臀围、身高和罩杯，缺少生日。'),
    ('状态14', '生日、身高和罩杯', '有生日、身高和罩杯，缺少三围。'),
    ('状态15', '生日、三围和罩杯', '有生日、胸围、腰围、臀围和罩杯，缺少身高。'),
    ('状态16', '生日、三围和身高', '有生日、胸围、腰围、臀围和身高，缺少罩杯。'),
    ('状态17', '保留状态', '当前状态计算逻辑未生成此状态，保留用于兼容历史数据。'),
    ('状态18', '未补全', '尚未执行并火或保木补全。'),
    ('状态19', '等待补全', '已经写入对应候选表，等待领取或正在执行。'),
    ('状态20', '失败待重试', '本次补全执行失败，已回到候选表等待再次补全。'),
)
