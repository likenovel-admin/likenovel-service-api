import json
import unittest

from app.services.websochat import websochat_context_loader


class _FakeMappings:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return _FakeMappings(self._rows)


class _FakeScopeDb:
    """Returns summary/signal rows per summary_type, like the real SQL filters."""

    def __init__(self, *, plot_rows, signal_rows):
        self._plot_rows = plot_rows
        self._signal_rows = signal_rows
        self.queries: list[str] = []
        self.params_list: list[dict] = []

    async def execute(self, statement, params=None):
        query = str(statement)
        self.queries.append(query)
        self.params_list.append(dict(params or {}))
        if "summary_type = 'episode_summary'" in query:
            return _FakeResult(self._plot_rows)
        return _FakeResult(self._signal_rows)


def _signal_row(episode_no: int, mentioned: list[dict], hooks: list[str] | None = None) -> dict:
    payload = {
        "episode_no": episode_no,
        "mentioned_characters": mentioned,
        "cliffhanger_hooks": hooks or [],
    }
    return {
        "episodeFrom": episode_no,
        "episodeTo": episode_no,
        "summaryText": json.dumps(payload, ensure_ascii=False),
    }


def _character(
    key: str,
    display_name: str,
    *,
    episode_no: int,
    edges: list[dict] | None = None,
    voice_mode: str = "dialogue",
) -> dict:
    return {
        "character_key": key,
        "display_name": display_name,
        "entity_kind": "person",
        "aliases": [],
        "voice_mode": voice_mode,
        "scene_weight": "high",
        "action_tags": ["대화"],
        "relation_edges": edges or [],
    }


class WebsochatScopeContextAggregationTests(unittest.IsolatedAsyncioTestCase):
    async def _load(self, *, signal_rows, read_episode_to=30):
        db = _FakeScopeDb(
            plot_rows=[
                {"episodeFrom": 29, "episodeTo": 30, "summaryText": "최근 줄거리 한 줄."},
            ],
            signal_rows=signal_rows,
        )
        context = await websochat_context_loader.load_websochat_scope_context(
            product_id=1182,
            read_episode_to=read_episode_to,
            latest_episode_no=read_episode_to,
            db=db,
        )
        return context, db

    async def test_character_seen_only_in_early_episodes_is_aggregated(self):
        # 가희 appears only in episodes 2-3; rows arrive newest-first like the SQL.
        rows = [
            _signal_row(
                30,
                [_character("character:아델리트", "아델리트", episode_no=30)],
            ),
        ]
        for episode_no in range(29, 4, -1):
            rows.append(
                _signal_row(
                    episode_no,
                    [_character("character:아델리트", "아델리트", episode_no=episode_no)],
                )
            )
        rows.append(
            _signal_row(
                3,
                [
                    _character(
                        "character:가희",
                        "가희",
                        episode_no=3,
                        edges=[{"target_key": "character:주인", "target_label": "주인", "relation_tag": "계약"}],
                    )
                ],
            )
        )
        rows.append(
            _signal_row(
                2,
                [_character("character:가희", "가희", episode_no=2)],
            )
        )

        context, _ = await self._load(signal_rows=rows)

        names = [item["display_name"] for item in context["characters"]]
        self.assertIn("가희", names)
        self.assertIn("아델리트", names)
        relation_pairs = [
            (item["source_display_name"], item["target_display_name"])
            for item in context["relations"]
        ]
        self.assertIn(("가희", "주인"), relation_pairs)

    async def test_display_name_comes_from_latest_seen_episode(self):
        rows = [
            _signal_row(
                29,
                [_character("character:레이븐", "레이븐", episode_no=29)],
            ),
            _signal_row(
                5,
                [_character("character:레이븐", "회색 늑대", episode_no=5)],
            ),
        ]

        context, _ = await self._load(signal_rows=rows, read_episode_to=30)

        by_key = {item["display_name"] for item in context["characters"]}
        self.assertIn("레이븐", by_key)
        self.assertNotIn("회색 늑대", by_key)

    async def test_signal_scan_uses_widened_window_and_keeps_read_boundary(self):
        db = _FakeScopeDb(plot_rows=[], signal_rows=[])
        await websochat_context_loader.load_websochat_scope_context(
            product_id=1182,
            read_episode_to=30,
            latest_episode_no=30,
            db=db,
        )

        signals_params = None
        for query, params in zip(db.queries, db.params_list):
            if "summary_type = 'episode_character_signals'" in query:
                signals_params = params
                self.assertIn("episode_to <= :read_episode_to", query)
                self.assertIn("LIMIT :limit", query)
        self.assertIsNotNone(signals_params)
        self.assertEqual(
            signals_params["limit"],
            websochat_context_loader.WEBSOCHAT_SCOPE_SIGNAL_SCAN_LIMIT,
        )
        self.assertGreater(
            websochat_context_loader.WEBSOCHAT_SCOPE_SIGNAL_SCAN_LIMIT,
            websochat_context_loader.WEBSOCHAT_SCOPE_SUMMARY_LIMIT,
        )

    async def test_scope_context_message_renders_early_character(self):
        rows = [
            _signal_row(
                30,
                [_character("character:아델리트", "아델리트", episode_no=30)],
            ),
            _signal_row(
                3,
                [_character("character:가희", "가희", episode_no=3)],
            ),
        ]
        context, _ = await self._load(signal_rows=rows)

        message = websochat_context_loader.build_websochat_scope_context_message_for_subtype(
            context, "character_axis", query_text="가희 누구야?"
        )

        self.assertIn("가희", message)


if __name__ == "__main__":
    unittest.main()
