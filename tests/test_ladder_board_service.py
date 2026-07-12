from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.core.ladder_board import (
    LADDER_BOARD_ACTOR,
    LADDER_BOARD_CODE_PREFIX,
    normalize_ladder_tier,
    normalize_ladder_medal_text,
    split_ladder_medals,
)
from app.data.database_handler import VideoDatabase
from app.services.ladder import LadderBoardService


class LadderBoardDatabaseStub:
    def __init__(self):
        self.saved_entries = []

    def save_ladder_entry(self, board_key, entity_type, entity_name, tier):
        self.saved_entries.append((board_key, entity_type, entity_name, tier))

    def list_ladder_entries(self, *_args):
        return [{'entity_name': '演员01', 'tier': 'S', 'medal': ''}]


class CountingLadderBoardService(LadderBoardService):
    def __init__(self, database):
        super().__init__(database)
        self.local_count_builds = 0

    def _build_local_counts(self, entity_type):
        self.local_count_builds += 1
        return [('演员01', 4), ('演员02', 3), ('演员03', 2)]


class HiddenDTierDatabaseStub:
    def save_ladder_entry(self, *_args):
        return None

    def list_ladder_entries(self, *_args):
        return [
            {'entity_name': 'ActorS', 'tier': 'S', 'medal': 'Rookie'},
            {'entity_name': 'ActorD', 'tier': 'D', 'medal': 'Archive'},
        ]


class HiddenDTierBoardService(LadderBoardService):
    def _build_local_counts(self, entity_type):
        return [('ActorS', 5), ('ActorD', 4), ('ActorC', 3)]


class ActorCandidatePriorityDatabaseStub:
    def list_ladder_entries(self, *_args):
        return [{'entity_name': 'RankedMasterpiece', 'tier': 'S', 'medal': ''}]

    def list_hidden_actors(self):
        return {'HiddenActor'}

    def list_videos(self):
        return [
            {'author': 'OldVideoMore'},
            {'author': 'OldVideoMore'},
            {'author': 'OldVideoMore'},
            {'author': 'OldVideoLess'},
            {'author': 'YoungVideoMore'},
            {'author': 'YoungVideoMore'},
        ]

    def list_actors(self, *_args, **_kwargs):
        return [
            {'name': 'OldVideoMore', 'raw_age': '45', 'age': '45'},
            {'name': 'OldVideoLess', 'raw_age': '46', 'age': '46'},
            {'name': 'OldNoVideoOlder', 'raw_age': '51', 'age': '51'},
            {'name': 'OldNoVideoYounger', 'raw_age': '43', 'age': '43'},
            {'name': 'BetaNoAge', 'raw_age': '', 'age': '未知'},
            {'name': 'AlphaNoAge', 'raw_age': '', 'age': '未知'},
            {'name': 'YoungVideoMore', 'raw_age': '30', 'age': '30'},
            {'name': 'YoungNoVideoOlder', 'raw_age': '40', 'age': '40'},
            {'name': 'YoungNoVideoYounger', 'raw_age': '28', 'age': '28'},
            {'name': 'HiddenActor', 'raw_age': '48', 'age': '48'},
        ]

    def list_masterpiece_ladder_actor_candidates(self):
        return [
            {'actor_name': 'RankedMasterpiece'},
            {'actor_name': 'HiddenActor'},
            {'actor_name': '暂无'},
            {'actor_name': 'MasterpieceUnranked'},
        ]


class ActorCandidateLimitDatabaseStub:
    def list_ladder_entries(self, *_args):
        return []

    def list_hidden_actors(self):
        return set()

    def list_videos(self):
        return []

    def list_actors(self, *_args, **_kwargs):
        return [
            {'name': f'Actor{index:03d}', 'raw_age': '', 'age': '未知'}
            for index in range(1, 201)
        ]

    def list_masterpiece_ladder_actor_candidates(self):
        return []


class LadderBoardServiceTest(unittest.TestCase):
    def test_medal_text_normalizes_multiple_delimiters(self):
        medal_text = '年度新人，白金常青树\n封面女王；年度新人|传奇系列'

        self.assertEqual(
            split_ladder_medals(medal_text),
            ['年度新人', '白金常青树', '封面女王', '传奇系列'],
        )
        self.assertEqual(
            normalize_ladder_medal_text(medal_text),
            '年度新人\n白金常青树\n封面女王\n传奇系列',
        )

    def test_actor_candidates_include_all_available_when_below_188_after_selected_entries_are_excluded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.import_local_videos(
                [
                    {
                        'code': f'ABP-{index:03d}',
                        'storage_location': 'D:\\videos',
                        'size': '1GB',
                    }
                    for index in range(1, 26)
                ]
            )

            with closing(sqlite3.connect(db_path)) as conn:
                for index in range(1, 26):
                    conn.execute(
                        'UPDATE processed_videos SET author = ? WHERE code = ?',
                        (f'演员{index:02d}', f'ABP-{index:03d}'),
                    )
                conn.commit()

            service = LadderBoardService(db)
            service.admit_entry(LADDER_BOARD_ACTOR, '演员01', 'S')
            service.admit_entry(LADDER_BOARD_ACTOR, '演员02', 'A')
            board = service.get_board(LADDER_BOARD_ACTOR)

        self.assertEqual(len(board['candidates']), 23)
        self.assertEqual(board['candidates'][0]['entity_name'], '演员03')
        self.assertEqual(board['candidates'][-1]['entity_name'], '演员25')
        self.assertEqual([item['entity_name'] for item in board['selected']], ['演员01', '演员02'])

    def test_actor_candidates_follow_requested_priority_groups(self):
        service = LadderBoardService(ActorCandidatePriorityDatabaseStub())

        board = service.get_board(LADDER_BOARD_ACTOR)

        self.assertEqual(
            [item['entity_name'] for item in board['candidates']],
            [
                'MasterpieceUnranked',
                'OldVideoMore',
                'OldVideoLess',
                'OldNoVideoOlder',
                'OldNoVideoYounger',
                'AlphaNoAge',
                'BetaNoAge',
                'YoungVideoMore',
                'YoungNoVideoOlder',
                'YoungNoVideoYounger',
            ],
        )

    def test_actor_candidates_are_limited_to_188(self):
        service = LadderBoardService(ActorCandidateLimitDatabaseStub())

        board = service.get_board(LADDER_BOARD_ACTOR)

        self.assertEqual(len(board['candidates']), 188)
        self.assertEqual(board['candidates'][0]['entity_name'], 'Actor001')
        self.assertEqual(board['candidates'][-1]['entity_name'], 'Actor188')

    def test_database_lists_visible_unrated_masterpiece_actor_candidates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.executemany(
                    '''
                    INSERT INTO masterpiece_actor_details (masterpiece_code, actor_name)
                    VALUES (?, ?)
                    ''',
                    [
                        ('AAA-001', 'VisibleMasterpiece'),
                        ('AAA-002', 'RankedMasterpiece'),
                        ('AAA-003', 'HiddenMasterpiece'),
                    ],
                )
                conn.execute(
                    '''
                    INSERT INTO masterpiece_actor_basic_infos (masterpiece_code, actor_name)
                    VALUES (?, ?)
                    ''',
                    ('AAA-004', 'BasicInfoOnly'),
                )
                conn.executemany(
                    '''
                    INSERT INTO masterpiece_actors (actor_name, status, handle_mark)
                    VALUES (?, 0, ?)
                    ''',
                    [
                        ('VisibleMasterpiece', 0),
                        ('RankedMasterpiece', 0),
                        ('HiddenMasterpiece', 2),
                        ('BasicInfoOnly', 0),
                    ],
                )
                conn.commit()

            db.save_ladder_entry(LADDER_BOARD_ACTOR, 'actor', 'RankedMasterpiece', 'S')

            names = [
                row['actor_name']
                for row in db.list_masterpiece_ladder_actor_candidates()
            ]

        self.assertEqual(names, ['BasicInfoOnly', 'VisibleMasterpiece'])

    def test_code_prefix_selected_entries_keep_tier_and_medal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            db.import_local_videos(
                [
                    {'code': 'IPX-001', 'storage_location': 'D:\\videos', 'size': '1GB'},
                    {'code': 'IPX-002', 'storage_location': 'D:\\videos', 'size': '1GB'},
                    {'code': 'MIDV-001', 'storage_location': 'D:\\videos', 'size': '1GB'},
                ]
            )
            service = LadderBoardService(db)
            service.admit_entry(LADDER_BOARD_CODE_PREFIX, 'IPX', 'S')
            service.update_medal(LADDER_BOARD_CODE_PREFIX, 'IPX', '白金常青树，年度新人')
            board = service.get_board(LADDER_BOARD_CODE_PREFIX)

        self.assertEqual(len(board['selected']), 1)
        self.assertEqual(board['selected'][0]['entity_name'], 'IPX')
        self.assertEqual(board['selected'][0]['tier'], 'S')
        self.assertEqual(board['selected'][0]['medal'], '白金常青树\n年度新人')
        self.assertEqual(board['selected'][0]['medals'], ['白金常青树', '年度新人'])
        self.assertEqual(board['candidates'][0]['entity_name'], 'MIDV')

    def test_admit_entry_reuses_local_counts_for_validation_and_response(self):
        db = LadderBoardDatabaseStub()
        service = CountingLadderBoardService(db)

        board = service.admit_entry(LADDER_BOARD_ACTOR, '演员01', 'S')

        self.assertEqual(service.local_count_builds, 1)
        self.assertEqual(
            db.saved_entries,
            [(LADDER_BOARD_ACTOR, 'actor', '演员01', 'S')],
        )
        self.assertEqual(board['selected'][0]['entity_name'], '演员01')
        self.assertEqual(board['candidates'][0]['entity_name'], '演员02')


    def test_d_tier_entries_are_hidden_from_selected_rows(self):
        service = HiddenDTierBoardService(HiddenDTierDatabaseStub())

        board = service.get_board(LADDER_BOARD_ACTOR)

        self.assertEqual([item['entity_name'] for item in board['selected']], ['ActorS'])
        self.assertEqual(board['selected'][0]['tier'], 'S')
        self.assertEqual(board['candidates'][0]['entity_name'], 'ActorC')


if __name__ == '__main__':
    unittest.main()
