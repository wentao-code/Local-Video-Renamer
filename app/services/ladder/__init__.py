"""Ladder-board service entrypoints.

Import from here for ladder board persistence/views and video ladder-tag
enrichment helpers.
"""

from app.services.ladder.ladder_board_service import LadderBoardService
from app.services.ladder.video_ladder_tag_service import VideoLadderTagService


__all__ = [
    'LadderBoardService',
    'VideoLadderTagService',
]
