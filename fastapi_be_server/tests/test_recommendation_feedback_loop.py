import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from app.services.ai import recommendation_service
from app.schemas.ai_recommendation import PostAiSignalEventReqBody


class RecommendationFeedbackLoopUnitTest(unittest.IsolatedAsyncioTestCase):
    class _FakeNestedTransaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class _FakeDb:
        def begin_nested(self):
            return RecommendationFeedbackLoopUnitTest._FakeNestedTransaction()

    class _FakeMappingsResult:
        def __init__(self, rows):
            self._rows = rows

        def mappings(self):
            return self

        def all(self):
            return self._rows

    class _SignalResult:
        def __init__(self, *, scalar=None, row=None, lastrowid=None):
            self._scalar = scalar
            self._row = row
            self.lastrowid = lastrowid

        def scalar_one_or_none(self):
            return self._scalar

        def mappings(self):
            return self

        def one_or_none(self):
            return self._row

    class _SignalDb:
        def __init__(self, results):
            self._results = list(results)
            self.calls = []
            self.commit_count = 0
            self.rollback_count = 0

        async def execute(self, statement, params=None):
            self.calls.append((str(statement), params or {}))
            return self._results.pop(0)

        async def commit(self):
            self.commit_count += 1

        async def rollback(self):
            self.rollback_count += 1

    def test_user_facing_slot_title_uses_natural_goal_particle(self):
        title = recommendation_service._build_user_facing_slot_title(
            ["goal"],
            {"goal": {"여행": 1.0}},
            {},
        )

        self.assertEqual(title, "요즘 주인공의 목표가 '여행'인 작품을 좋아하나봐요")

    def test_websochat_asset_request_is_valid_but_not_a_taste_factor(self):
        body = PostAiSignalEventReqBody(
            product_id=1182,
            episode_id=27362,
            event_type="websochat_asset_request",
            event_payload={"episode_no": 51},
        )

        self.assertEqual(body.event_type, "websochat_asset_request")
        self.assertTrue(
            recommendation_service._should_skip_signal_factor_generation(
                body.event_type,
                body.event_payload or {},
            )
        )

    async def test_websochat_asset_request_uses_server_episode_no_and_deduplicates_by_episode(self):
        db = self._SignalDb(
            [
                self._SignalResult(scalar=1),
                self._SignalResult(scalar=1),
                self._SignalResult(scalar=1182),
                self._SignalResult(row={"episode_no": 51, "chat_asset_ready": 0}),
                self._SignalResult(scalar=None),
                self._SignalResult(lastrowid=901),
            ]
        )

        with patch.object(
            recommendation_service,
            "_get_user_id_by_kc",
            AsyncMock(return_value=100),
        ):
            result = await recommendation_service.post_signal_event(
                "kc-user",
                {
                    "product_id": 1182,
                    "episode_id": 27362,
                    "event_type": "websochat_asset_request",
                    "event_payload": {"episode_no": 999},
                },
                db,
            )

        self.assertEqual(result["message"], "AI 신호 이벤트가 저장되었습니다.")
        self.assertEqual(db.commit_count, 1)
        insert_sql, insert_params = db.calls[-1]
        self.assertIn("INSERT INTO tb_user_ai_signal_event", insert_sql)
        self.assertIn('"episode_no": 51', insert_params["event_payload"])
        duplicate_sql, duplicate_params = db.calls[-2]
        self.assertIn("INTERVAL 7 DAY", duplicate_sql)
        self.assertIn("FOR UPDATE", duplicate_sql)
        self.assertIn("demand.episode_id = :episode_id", duplicate_sql)
        self.assertEqual(duplicate_params["episode_id"], 27362)
        asset_readiness_sql = db.calls[-3][0]
        self.assertIn("p.price_type IN ('free', 'paid')", asset_readiness_sql)
        self.assertIn("p.status_code IN ('ongoing', 'end')", asset_readiness_sql)
        self.assertIn("FOR UPDATE", asset_readiness_sql)
        self.assertIn("FOR UPDATE", db.calls[-4][0])

    async def test_websochat_asset_request_rejects_already_prepared_episode(self):
        db = self._SignalDb(
            [
                self._SignalResult(scalar=1),
                self._SignalResult(scalar=1),
                self._SignalResult(scalar=1182),
                self._SignalResult(row={"episode_no": 51, "chat_asset_ready": 1}),
            ]
        )

        with (
            patch.object(
                recommendation_service,
                "_get_user_id_by_kc",
                AsyncMock(return_value=100),
            ),
            self.assertRaises(recommendation_service.CustomResponseException),
        ):
            await recommendation_service.post_signal_event(
                "kc-user",
                {
                    "product_id": 1182,
                    "episode_id": 27362,
                    "event_type": "websochat_asset_request",
                    "event_payload": {"episode_no": 51},
                },
                db,
            )

        self.assertEqual(db.commit_count, 0)
        self.assertEqual(len(db.calls), 4)

    async def test_websochat_asset_request_duplicate_does_not_insert_again(self):
        db = self._SignalDb(
            [
                self._SignalResult(scalar=1),
                self._SignalResult(scalar=1),
                self._SignalResult(scalar=1182),
                self._SignalResult(row={"episode_no": 51, "chat_asset_ready": 0}),
                self._SignalResult(scalar=1),
            ]
        )

        with patch.object(
            recommendation_service,
            "_get_user_id_by_kc",
            AsyncMock(return_value=100),
        ):
            result = await recommendation_service.post_signal_event(
                "kc-user",
                {
                    "product_id": 1182,
                    "episode_id": 27362,
                    "event_type": "websochat_asset_request",
                    "event_payload": {"episode_no": 51},
                },
                db,
            )

        self.assertEqual(result["message"], "웹소챗 자산 준비 요청이 이미 반영되었습니다.")
        self.assertEqual(db.commit_count, 0)
        self.assertEqual(db.rollback_count, 1)
        self.assertEqual(len(db.calls), 5)
        self.assertFalse(
            any("INSERT INTO tb_user_ai_signal_event" in sql for sql, _ in db.calls)
        )

    def test_user_facing_slot_title_joins_axis_clauses_naturally(self):
        title = recommendation_service._build_user_facing_slot_title(
            ["type", "job"],
            {
                "protagonist": {"성장형": 1.0},
                "job": {"공무원": 1.0},
            },
            {},
        )

        self.assertEqual(
            title,
            "요즘 주인공 유형이 '성장형'이고 주인공 직업이 '공무원'인 작품을 좋아하나봐요",
        )

    def test_user_facing_slot_title_uses_label_first_style_phrase(self):
        title = recommendation_service._build_user_facing_slot_title(
            ["style"],
            {"style": {"모험": 1.0}},
            {},
        )

        self.assertEqual(title, "요즘 '모험' 작풍의 작품을 좋아하나봐요")

    def test_allowed_axis_labels_load_from_deployed_batch_directory(self):
        original_cache = recommendation_service._ALLOWED_AXIS_LABELS_CACHE
        original_warned = recommendation_service._ALLOWED_AXIS_LABELS_WARNED
        original_cwd = Path.cwd()
        try:
            with TemporaryDirectory() as tmp_dir:
                batch_dir = Path(tmp_dir) / "batch"
                batch_dir.mkdir()
                (batch_dir / "allowed-labels-by-axis.json").write_text(
                    """{
  "세": ["현대"],
  "직": ["헌터"],
  "목": ["생존"],
  "능": ["마법"],
  "타": ["성장형"],
  "연": ["동료"],
  "작": ["통쾌"]
}""",
                    encoding="utf-8",
                )
                recommendation_service._ALLOWED_AXIS_LABELS_CACHE = None
                recommendation_service._ALLOWED_AXIS_LABELS_WARNED = False
                os.chdir(tmp_dir)

                labels = recommendation_service._load_allowed_axis_labels()

            self.assertIn("헌터", labels["job"])
            self.assertNotIn("헌터", labels["type"])
            self.assertIn("성장형", labels["type"])
        finally:
            os.chdir(original_cwd)
            recommendation_service._ALLOWED_AXIS_LABELS_CACHE = original_cache
            recommendation_service._ALLOWED_AXIS_LABELS_WARNED = original_warned

    async def test_product_metadata_loader_decodes_axis_label_scores(self):
        db = AsyncMock()
        db.execute.return_value = self._FakeMappingsResult(
            [
                {
                    "product_id": 123,
                    "protagonist_type_tags": '["환생", "성장형"]',
                    "axis_label_scores": (
                        '{"타": ['
                        '{"label": "환생", "score": 0.95}, '
                        '{"label": "성장형", "score": 0.55}'
                        "]}"
                    ),
                }
            ]
        )

        rows = await recommendation_service.get_all_product_ai_metadata(db)

        self.assertEqual(
            rows[0]["axis_label_scores"]["타"],
            [
                {"label": "환생", "score": 0.95},
                {"label": "성장형", "score": 0.55},
            ],
        )

    def test_product_axis_label_scores_weight_multi_label_taste_match(self):
        base_candidate = {
            "protagonist_type_tags": ["환생", "성장형"],
            "overall_confidence": 0.9,
        }
        lifecycle_strong = {
            **base_candidate,
            "axis_label_scores": {
                "타": [
                    {"label": "환생", "score": 0.95},
                    {"label": "성장형", "score": 0.55},
                ]
            },
        }
        lifecycle_weak = {
            **base_candidate,
            "axis_label_scores": {
                "타": [
                    {"label": "환생", "score": 0.55},
                    {"label": "성장형", "score": 0.95},
                ]
            },
        }
        factor_scores = {"protagonist": {"환생": 6.0}}

        strong_score = recommendation_service.score_taste_for_candidate(
            lifecycle_strong,
            {},
            factor_scores,
        )
        weak_score = recommendation_service.score_taste_for_candidate(
            lifecycle_weak,
            {},
            factor_scores,
        )

        self.assertGreater(strong_score, weak_score)

    def test_missing_product_axis_label_scores_preserves_legacy_match(self):
        score = recommendation_service.score_taste_for_candidate(
            {
                "protagonist_type_tags": ["환생", "성장형"],
                "overall_confidence": 0.9,
            },
            {},
            {"protagonist": {"환생": 6.0}},
        )

        self.assertEqual(score, 5.0)

    def test_product_axis_scores_cannot_inject_unselected_labels(self):
        score = recommendation_service.score_taste_for_candidate(
            {
                "protagonist_type_tags": ["환생", "성장형"],
                "overall_confidence": 0.9,
                "axis_label_scores": {
                    "타": [
                        {"label": "환생", "score": 0.9},
                        {"label": "성장형", "score": 0.6},
                        {"label": "빙의", "score": 1.0},
                    ]
                },
            },
            {},
            {"protagonist": {"빙의": 1.0}},
        )

        self.assertEqual(score, 0.0)

    async def test_update_ai_slot_feedback_flags_skips_unsupported_event(self):
        db = AsyncMock()

        await recommendation_service._update_ai_slot_feedback_flags(
            user_id=100,
            product_id=200,
            event_type="revisit_24h",
            db=db,
        )

        db.execute.assert_not_awaited()

    async def test_next_episode_click_without_ai_taste_entry_does_not_mark_click(self):
        db = AsyncMock()

        await recommendation_service._update_ai_slot_feedback_flags(
            user_id=100,
            product_id=200,
            event_type="next_episode_click",
            db=db,
        )

        self.assertEqual(db.execute.await_count, 1)
        executed_sql = str(db.execute.await_args_list[0].args[0])
        self.assertNotIn("SET target.clicked_yn = 'Y'", executed_sql)
        self.assertIn("SET target.continued_3ep_yn = 'Y'", executed_sql)

    async def test_next_episode_click_with_ai_taste_entry_marks_click_and_continued(self):
        db = AsyncMock()

        await recommendation_service._update_ai_slot_feedback_flags(
            user_id=100,
            product_id=200,
            event_type="next_episode_click",
            event_payload={"entry_source": "ai_taste_section"},
            db=db,
        )

        self.assertEqual(db.execute.await_count, 2)
        clicked_sql = str(db.execute.await_args_list[0].args[0])
        continued_sql = str(db.execute.await_args_list[1].args[0])
        self.assertIn("SET target.clicked_yn = 'Y'", clicked_sql)
        self.assertIn("tb_user_ai_signal_event seed", clicked_sql)
        self.assertIn("seed.event_type = 'taste_slot_click'", clicked_sql)
        self.assertIn("seed.created_date >= s.served_at", clicked_sql)
        self.assertIn("SET target.continued_3ep_yn = 'Y'", continued_sql)

    async def test_taste_slot_click_marks_click_only(self):
        db = AsyncMock()

        await recommendation_service._update_ai_slot_feedback_flags(
            user_id=100,
            product_id=200,
            event_type="taste_slot_click",
            event_payload={"source": "ai_taste_section"},
            db=db,
        )

        self.assertEqual(db.execute.await_count, 1)
        executed_sql = str(db.execute.await_args_list[0].args[0])
        self.assertIn("SET target.clicked_yn = 'Y'", executed_sql)

    async def test_product_detail_exit_generates_weak_factor_after_engagement_threshold(self):
        self.assertTrue(
            recommendation_service._should_skip_signal_factor_generation(
                "product_detail_view",
                {},
                active_seconds=60,
            )
        )
        self.assertTrue(
            recommendation_service._should_skip_signal_factor_generation(
                "product_detail_exit",
                {},
                active_seconds=5,
            )
        )
        self.assertFalse(
            recommendation_service._should_skip_signal_factor_generation(
                "product_detail_exit",
                {},
                active_seconds=15,
            )
        )
        self.assertLess(
            recommendation_service._compute_signal_factor_score_multiplier(
                "product_detail_exit",
                {},
                active_seconds=15,
            ),
            recommendation_service._compute_signal_factor_score_multiplier(
                "episode_view",
                {},
                active_seconds=15,
            ),
        )

    async def test_taste_recommendations_fill_to_three_sections_when_axes_available(self):
        profile = {
            "onboarding_moods": ["현대"],
            "recommendation_sections": [],
            "read_product_ids": [],
        }
        factor_scores = {
            "protagonist": {"성장형": 6.0},
            "material": {"마법": 6.0},
            "worldview": {"현대": 6.0},
            "style": {"통쾌": 6.0},
        }
        product_briefs = {
            1: {"product_id": 1, "title": "A", "author_nickname": "aa", "episode_count": 10},
            2: {"product_id": 2, "title": "B", "author_nickname": "bb", "episode_count": 10},
            3: {"product_id": 3, "title": "C", "author_nickname": "cc", "episode_count": 10},
        }

        def match_by_axes(_all_dna, axes, _profile, _excluded_ids, _factor_scores, limit=6):
            axis = axes[0]
            product_id = {"type": 1, "material": 2, "worldview": 3}.get(axis)
            return [{"product_id": product_id, "reason": axis}] if product_id else []

        with patch.object(recommendation_service, "_get_user_id_by_kc", AsyncMock(return_value=100)), \
            patch.object(recommendation_service, "_is_ai_onboarding_dismissed", AsyncMock(return_value=True)), \
            patch.object(recommendation_service, "get_user_taste_profile", AsyncMock(return_value=profile)), \
            patch.object(recommendation_service, "_get_recent_read_product_ids", AsyncMock(return_value=set())), \
            patch.object(recommendation_service, "get_all_product_ai_metadata", AsyncMock(return_value=[{"product_id": 1}])), \
            patch.object(recommendation_service, "_get_user_factor_scores", AsyncMock(return_value=factor_scores)), \
            patch.object(recommendation_service, "_get_user_total_signal_count", AsyncMock(return_value=3)), \
            patch.object(
                recommendation_service,
                "_build_dynamic_slot_sections",
                return_value=[{"dimension": "type", "reason": "", "axes": ["type"]}],
            ), \
            patch.object(recommendation_service, "_match_products_by_axes", side_effect=match_by_axes), \
            patch.object(recommendation_service, "_get_product_briefs", AsyncMock(return_value=product_briefs)), \
            patch.object(recommendation_service, "_save_ai_slot_serving_logs", AsyncMock()):
            result = await recommendation_service.get_taste_recommendations("kc-user", "N", self._FakeDb())

        self.assertEqual(len(result["sections"]), 3)
        self.assertEqual(
            [section["products"][0]["productId"] for section in result["sections"]],
            [1, 2, 3],
        )

    async def test_score_engagement_for_recommendation_prefers_strong_read_signals(self):
        strong = {
            "binge_rate": 0.72,
            "total_next_clicks": 18,
            "total_readers": 24,
            "dropoff_7d": 3,
            "reengage_rate": 0.28,
            "avg_speed_cpm": 920,
        }
        weak = {
            "binge_rate": 0.18,
            "total_next_clicks": 18,
            "total_readers": 24,
            "dropoff_7d": 14,
            "reengage_rate": 0.02,
            "avg_speed_cpm": 1450,
        }

        self.assertGreater(
            recommendation_service.score_engagement_for_recommendation(strong),
            recommendation_service.score_engagement_for_recommendation(weak),
        )

    async def test_match_products_by_axes_uses_engagement_as_tiebreaker(self):
        all_dna = [
            {
                "product_id": 1,
                "worldview_tags": ["현대"],
                "overall_confidence": 1.0,
                "count_hit": 9000,
                "premise": "약한 engagement",
                "binge_rate": 0.12,
                "total_next_clicks": 18,
                "total_readers": 24,
                "dropoff_7d": 15,
                "reengage_rate": 0.01,
                "avg_speed_cpm": 1400,
            },
            {
                "product_id": 2,
                "worldview_tags": ["현대"],
                "overall_confidence": 1.0,
                "count_hit": 800,
                "premise": "강한 engagement",
                "binge_rate": 0.68,
                "total_next_clicks": 18,
                "total_readers": 24,
                "dropoff_7d": 2,
                "reengage_rate": 0.22,
                "avg_speed_cpm": 910,
            },
        ]

        matched = recommendation_service._match_products_by_axes(
            all_dna,
            ["worldview"],
            {},
            set(),
            {"worldview": {"현대": 1.0}},
            limit=2,
        )

        self.assertEqual(matched[0]["product_id"], 2)

    async def test_build_preset_candidate_scores_prioritizes_taste_layer(self):
        profile = {
            "taste_tags": ["회귀", "정치"],
            "preferred_protagonist": {"전략가": 5},
            "preferred_mood": {"긴장감": 4},
            "preferred_pacing": "fast",
        }
        taste_fit = {
            "protagonist_type": "전략가",
            "mood": "긴장감",
            "pacing": "fast",
            "taste_tags": ["회귀", "정치"],
            "reading_rate": 0.42,
            "writing_count_per_week": 3.0,
            "count_hit": 400,
            "episode_count": 90,
            "evaluation_score": 7.0,
            "binge_rate": 0.22,
            "total_next_clicks": 12,
            "total_readers": 18,
            "dropoff_7d": 5,
            "reengage_rate": 0.05,
            "avg_speed_cpm": 930,
            "count_hit_indicator": 5,
            "count_bookmark_indicator": 2,
            "reading_rate_indicator": 0.01,
            "rank_indicator": 0,
            "current_rank": 0,
        }
        metric_fit = {
            "protagonist_type": "먼치킨",
            "mood": "유쾌함",
            "pacing": "slow",
            "taste_tags": ["학원"],
            "reading_rate": 0.75,
            "writing_count_per_week": 4.0,
            "count_hit": 50000,
            "episode_count": 180,
            "evaluation_score": 9.0,
            "binge_rate": 0.71,
            "total_next_clicks": 18,
            "total_readers": 24,
            "dropoff_7d": 2,
            "reengage_rate": 0.21,
            "avg_speed_cpm": 910,
            "count_hit_indicator": 150,
            "count_bookmark_indicator": 32,
            "reading_rate_indicator": 0.07,
            "rank_indicator": 8,
            "current_rank": 12,
        }

        taste_scores = recommendation_service._build_preset_candidate_scores(
            taste_fit,
            "good-schedule",
            profile,
        )
        metric_scores = recommendation_service._build_preset_candidate_scores(
            metric_fit,
            "good-schedule",
            profile,
        )

        self.assertGreater(taste_scores["taste_score"], metric_scores["taste_score"])
        self.assertGreater(taste_scores["total_score"], metric_scores["total_score"])

    async def test_build_preset_candidate_scores_uses_context_profile_when_profile_missing(self):
        context_profile = {
            "taste_tags": ["회귀", "정치"],
            "preferred_protagonist": {"전략가": 1.0},
            "preferred_mood": {"긴장감": 1.0},
            "preferred_pacing": "fast",
        }
        context_fit = {
            "protagonist_type": "전략가",
            "mood": "긴장감",
            "pacing": "fast",
            "taste_tags": ["회귀", "정치"],
            "reading_rate": 0.35,
            "writing_count_per_week": 3.0,
            "count_hit": 800,
            "episode_count": 90,
            "evaluation_score": 7.0,
            "binge_rate": 0.24,
            "total_next_clicks": 12,
            "total_readers": 18,
            "dropoff_7d": 4,
            "reengage_rate": 0.05,
            "avg_speed_cpm": 930,
            "count_hit_indicator": 8,
            "count_bookmark_indicator": 2,
            "reading_rate_indicator": 0.01,
            "rank_indicator": 0,
            "current_rank": 0,
        }
        no_context_fit = {
            **context_fit,
            "protagonist_type": "먼치킨",
            "mood": "유쾌함",
            "pacing": "slow",
            "taste_tags": ["학원"],
        }

        context_scores = recommendation_service._build_preset_candidate_scores(
            context_fit,
            "stacked-chapters",
            None,
            context_profile=context_profile,
        )
        no_context_scores = recommendation_service._build_preset_candidate_scores(
            no_context_fit,
            "stacked-chapters",
            None,
            context_profile=context_profile,
        )

        self.assertGreater(context_scores["context_score"], no_context_scores["context_score"])
        self.assertGreater(context_scores["total_score"], no_context_scores["total_score"])

    async def test_build_preset_candidate_scores_uses_factor_scores_even_without_profile(self):
        factor_scores = {
            "protagonist": {"성장형": 1.0},
            "worldview": {"현대": 1.0},
            "style": {"미스터리": 1.0},
        }
        taste_fit = {
            "protagonist_type_tags": ["성장형"],
            "worldview_tags": ["현대"],
            "axis_style_tags": ["미스터리"],
            "overall_confidence": 0.9,
            "reading_rate": 0.35,
            "writing_count_per_week": 3.0,
            "count_hit": 800,
            "episode_count": 90,
            "evaluation_score": 7.0,
            "binge_rate": 0.24,
            "total_next_clicks": 12,
            "total_readers": 18,
            "dropoff_7d": 4,
            "reengage_rate": 0.05,
            "avg_speed_cpm": 930,
            "count_hit_indicator": 8,
            "count_bookmark_indicator": 2,
            "reading_rate_indicator": 0.01,
            "rank_indicator": 0,
            "current_rank": 0,
        }
        metric_fit = {
            **taste_fit,
            "protagonist_type_tags": ["먼치킨"],
            "worldview_tags": ["이종족"],
            "axis_style_tags": ["밀리터리"],
            "reading_rate": 0.75,
            "writing_count_per_week": 4.0,
            "count_hit": 50000,
            "binge_rate": 0.71,
            "dropoff_7d": 2,
            "reengage_rate": 0.21,
            "count_hit_indicator": 150,
            "count_bookmark_indicator": 32,
            "reading_rate_indicator": 0.07,
            "rank_indicator": 8,
            "current_rank": 12,
        }

        taste_scores = recommendation_service._build_preset_candidate_scores(
            taste_fit,
            "good-schedule",
            None,
            factor_scores=factor_scores,
        )
        metric_scores = recommendation_service._build_preset_candidate_scores(
            metric_fit,
            "good-schedule",
            None,
            factor_scores=factor_scores,
        )

        self.assertGreater(taste_scores["taste_score"], metric_scores["taste_score"])
        self.assertGreater(taste_scores["total_score"], metric_scores["total_score"])

    async def test_ai_chat_preset_passes_context_to_ai_recommend(self):
        with patch.object(
            recommendation_service,
            "ai_recommend",
            AsyncMock(
                return_value={
                    "reason": "추천 사유",
                    "product": {"productId": 1},
                    "tasteMatch": {"protagonist": 0, "mood": 0, "pacing": 0},
                    "taste_match": {"protagonist": 0, "mood": 0, "pacing": 0},
                }
            ),
        ) as mocked_recommend:
            await recommendation_service.ai_chat(
                kc_user_id="kc-user",
                messages=[{"role": "user", "content": "회차 쌓인 작품 추천"}],
                context={"current_product_id": 326, "page_type": "product"},
                preset="stacked-chapters",
                exclude_ids=[],
                adult_yn="N",
                db=AsyncMock(),
            )

            self.assertEqual(
                mocked_recommend.await_args.kwargs["context"],
                {"current_product_id": 326, "page_type": "product"},
            )

    async def test_completed_preset_uses_status_code_filter(self):
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=self._FakeMappingsResult(
                [
                    {
                        "product_id": 777,
                        "title": "완결 추천작",
                        "status_code": "end",
                        "count_hit": 700,
                        "author_nickname": "작가C",
                        "episode_count": 120,
                        "cover_url": None,
                        "protagonist_type": "전략가",
                        "protagonist_desc": "",
                        "mood": "긴장감",
                        "pacing": "fast",
                        "premise": "완결 후보",
                        "hook": "",
                        "themes": [],
                        "taste_tags": ["회귀", "정치"],
                        "reading_rate": 0.41,
                        "writing_count_per_week": 0.0,
                        "binge_rate": 0.31,
                        "total_next_clicks": 11,
                        "total_readers": 16,
                        "dropoff_7d": 4,
                        "reengage_rate": 0.07,
                        "avg_speed_cpm": 920,
                        "evaluation_score": 7.0,
                        "count_hit_indicator": 2,
                        "count_bookmark_indicator": 1,
                        "reading_rate_indicator": 0.01,
                        "current_rank": 0,
                        "rank_indicator": 0,
                    }
                ]
            )
        )

        with patch.object(
            recommendation_service,
            "_generate_reason",
            AsyncMock(return_value="추천 사유"),
        ):
            result = await recommendation_service._preset_recommend(
                user_id=1,
                profile=None,
                factor_scores={},
                preset="completed",
                exclude_ids=[],
                adult_yn="N",
                db=db,
            )

        _, query_params = db.execute.await_args.args
        self.assertEqual(query_params["status_code_filter"], "end")
        self.assertEqual(result["product"]["productId"], 777)

    async def test_good_schedule_preset_fetches_broad_candidates_before_sampling(self):
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=self._FakeMappingsResult(
                [
                    {
                        "product_id": 888,
                        "title": "연재주기 추천작",
                        "status_code": "serial",
                        "count_hit": 700,
                        "author_nickname": "작가D",
                        "episode_count": 120,
                        "cover_url": None,
                        "protagonist_type": "성장형",
                        "protagonist_desc": "",
                        "mood": "긴장감",
                        "pacing": "fast",
                        "premise": "연재주기 후보",
                        "hook": "",
                        "themes": [],
                        "taste_tags": ["현대", "미스터리"],
                        "reading_rate": 0.41,
                        "writing_count_per_week": 4.0,
                        "binge_rate": 0.31,
                        "total_next_clicks": 11,
                        "total_readers": 16,
                        "dropoff_7d": 4,
                        "reengage_rate": 0.07,
                        "avg_speed_cpm": 920,
                        "evaluation_score": 7.0,
                        "count_hit_indicator": 2,
                        "count_bookmark_indicator": 1,
                        "reading_rate_indicator": 0.01,
                        "current_rank": 0,
                        "rank_indicator": 0,
                    }
                ]
            )
        )

        with patch.object(
            recommendation_service,
            "_generate_reason",
            AsyncMock(return_value="추천 사유"),
        ):
            result = await recommendation_service._preset_recommend(
                user_id=1,
                profile=None,
                factor_scores={},
                preset="good-schedule",
                exclude_ids=[],
                adult_yn="N",
                db=db,
            )

        query_sql = str(db.execute.await_args.args[0])
        self.assertIn("ORDER BY COALESCE(pti.writing_count_per_week, 0) DESC", query_sql)
        self.assertIn("LIMIT 80", query_sql)
        self.assertNotIn("RAND()", query_sql)
        self.assertEqual(result["product"]["productId"], 888)

    async def test_taste_recommendations_fill_dynamic_axis_before_legacy_section(self):
        profile = {
            "onboarding_picks": ["성장형"],
            "taste_tags": ["회귀", "마법"],
            "read_product_ids": [],
        }
        factor_scores = {
            "protagonist": {"성장형": 1.0},
            "material": {"마법": 1.0},
            "worldview": {"현대": 1.0},
        }
        dynamic_sections = [
            {
                "dimension": "type_material",
                "axes": ["type", "material"],
                "reason": "동적 슬롯",
            }
        ]
        legacy_sections = [
            {"dimension": "protagonist", "title": "당신 취향의 주인공", "reason": ""},
            {"dimension": "material", "title": "당신이 좋아할 설정", "reason": ""},
        ]
        brief_source = {
            101: {"product_id": 101, "title": "동적 추천작", "cover_url": None, "author_nickname": "작가A", "episode_count": 12},
            201: {"product_id": 201, "title": "보강 추천작", "cover_url": None, "author_nickname": "작가B", "episode_count": 15},
            301: {"product_id": 301, "title": "동적 축 보강작", "cover_url": None, "author_nickname": "작가C", "episode_count": 18},
        }

        async def get_product_briefs(product_ids, db):
            return {pid: brief_source[pid] for pid in product_ids if pid in brief_source}

        def match_products_by_axes(all_dna, axes, profile, excluded_ids, factor_scores, limit=6):
            if axes == ["type", "material"]:
                return [{"product_id": 101, "reason": "동적 매칭"}]
            if axes == ["worldview"]:
                return [{"product_id": 301, "reason": "동적 축 보강"}]
            return []

        def match_products_by_dimension(all_dna, dimension, profile, excluded_ids, taste_tags, factor_scores, limit=6):
            if dimension == "protagonist":
                return [{"product_id": 201, "reason": "legacy 보강"}]
            return []

        with (
            patch.object(recommendation_service, "_get_user_id_by_kc", AsyncMock(return_value=7)),
            patch.object(recommendation_service, "_is_ai_onboarding_dismissed", AsyncMock(return_value=True)),
            patch.object(recommendation_service, "get_user_taste_profile", AsyncMock(return_value=profile)),
            patch.object(recommendation_service, "_get_recent_read_product_ids", AsyncMock(return_value=set())),
            patch.object(
                recommendation_service,
                "get_all_product_ai_metadata",
                AsyncMock(return_value=[{"product_id": 101}, {"product_id": 201}, {"product_id": 301}]),
            ),
            patch.object(recommendation_service, "_get_user_factor_scores", AsyncMock(return_value=factor_scores)),
            patch.object(recommendation_service, "_get_user_total_signal_count", AsyncMock(return_value=3)),
            patch.object(recommendation_service, "_build_dynamic_slot_sections", return_value=dynamic_sections),
            patch.object(recommendation_service, "_resolve_recommendation_sections", return_value=legacy_sections),
            patch.object(recommendation_service, "_match_products_by_axes", side_effect=match_products_by_axes),
            patch.object(recommendation_service, "_match_products_by_dimension", side_effect=match_products_by_dimension),
            patch.object(recommendation_service, "_get_product_briefs", AsyncMock(side_effect=get_product_briefs)),
            patch.object(recommendation_service, "_save_ai_slot_serving_logs", AsyncMock()) as save_logs,
        ):
            result = await recommendation_service.get_taste_recommendations(
                "kc-user",
                "N",
                self._FakeDb(),
            )

        self.assertEqual(
            [section["dimension"] for section in result["sections"]],
            ["type_material", "worldview", "protagonist"],
        )
        self.assertEqual(result["sections"][0]["products"][0]["productId"], 101)
        self.assertEqual(result["sections"][1]["products"][0]["productId"], 301)
        self.assertEqual(result["sections"][2]["products"][0]["productId"], 201)
        self.assertEqual(len(save_logs.await_args.args[1]), 3)

    async def test_preset_recommend_uses_condition_first_fallback_when_no_taste_match(self):
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=self._FakeMappingsResult(
                [
                    {
                        "product_id": 777,
                        "title": "완결 추천작",
                        "status_code": "end",
                        "count_hit": 700,
                        "author_nickname": "작가C",
                        "episode_count": 120,
                        "cover_url": None,
                        "protagonist_type": "전략가",
                        "protagonist_desc": "",
                        "mood": "긴장감",
                        "pacing": "fast",
                        "premise": "완결 후보",
                        "hook": "",
                        "themes": [],
                        "taste_tags": ["회귀", "정치"],
                        "reading_rate": 0.41,
                        "writing_count_per_week": 0.0,
                        "binge_rate": 0.31,
                        "total_next_clicks": 11,
                        "total_readers": 16,
                        "dropoff_7d": 4,
                        "reengage_rate": 0.07,
                        "avg_speed_cpm": 920,
                        "evaluation_score": 7.0,
                        "count_hit_indicator": 2,
                        "count_bookmark_indicator": 1,
                        "reading_rate_indicator": 0.01,
                        "current_rank": 0,
                        "rank_indicator": 0,
                    }
                ]
            )
        )

        result = await recommendation_service._preset_recommend(
            user_id=1,
            profile={
                "taste_tags": ["학원"],
                "preferred_protagonist": {"먼치킨": 1.0},
                "preferred_mood": {"유쾌함": 1.0},
                "preferred_pacing": "slow",
                "read_product_ids": [],
            },
            factor_scores={},
            preset="completed",
            exclude_ids=[],
            adult_yn="N",
            db=db,
        )

        self.assertEqual(result["product"]["productId"], 777)
        self.assertIn("비슷한 독자들은", result["reason"])

    async def test_condition_first_fallback_prefers_stronger_preset_signal(self):
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=self._FakeMappingsResult(
                [
                    {
                        "product_id": 901,
                        "title": "연재주기 최적 후보",
                        "status_code": "serial",
                        "count_hit": 300,
                        "author_nickname": "작가E",
                        "episode_count": 70,
                        "cover_url": None,
                        "protagonist_type": "전략가",
                        "protagonist_desc": "",
                        "mood": "차분함",
                        "pacing": "fast",
                        "premise": "조건 최적",
                        "hook": "",
                        "themes": [],
                        "taste_tags": ["정치"],
                        "reading_rate": 0.46,
                        "writing_count_per_week": 4.5,
                        "binge_rate": 0.18,
                        "total_next_clicks": 5,
                        "total_readers": 11,
                        "dropoff_7d": 5,
                        "reengage_rate": 0.03,
                        "avg_speed_cpm": 980,
                        "evaluation_score": 6.0,
                        "count_hit_indicator": 1,
                        "count_bookmark_indicator": 0,
                        "reading_rate_indicator": 0.0,
                        "current_rank": 0,
                        "rank_indicator": 0,
                    },
                    {
                        "product_id": 902,
                        "title": "인기 높은 후보",
                        "status_code": "serial",
                        "count_hit": 50000,
                        "author_nickname": "작가F",
                        "episode_count": 70,
                        "cover_url": None,
                        "protagonist_type": "영웅",
                        "protagonist_desc": "",
                        "mood": "유쾌함",
                        "pacing": "fast",
                        "premise": "인기 우위",
                        "hook": "",
                        "themes": [],
                        "taste_tags": ["액션"],
                        "reading_rate": 0.29,
                        "writing_count_per_week": 3.0,
                        "binge_rate": 0.18,
                        "total_next_clicks": 5,
                        "total_readers": 11,
                        "dropoff_7d": 5,
                        "reengage_rate": 0.03,
                        "avg_speed_cpm": 980,
                        "evaluation_score": 6.0,
                        "count_hit_indicator": 1,
                        "count_bookmark_indicator": 0,
                        "reading_rate_indicator": 0.0,
                        "current_rank": 0,
                        "rank_indicator": 0,
                    },
                ]
            )
        )

        with patch.object(
            recommendation_service,
            "_pick_weighted_candidate",
            side_effect=lambda candidates, **kwargs: candidates[0],
        ):
            result = await recommendation_service._preset_recommend(
                user_id=1,
                profile={
                    "taste_tags": ["학원"],
                    "preferred_protagonist": {"먼치킨": 1.0},
                    "preferred_mood": {"미스터리": 1.0},
                    "preferred_pacing": "slow",
                    "read_product_ids": [],
                },
                factor_scores={"worldview": {"현대": 1.0}},
                preset="good-schedule",
                exclude_ids=[],
                adult_yn="N",
                db=db,
            )

        self.assertEqual(result["product"]["productId"], 901)
        self.assertIn("비슷한 독자들은", result["reason"])

    async def test_condition_first_fallback_prefers_stronger_cohort_score(self):
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=self._FakeMappingsResult(
                [
                    {
                        "product_id": 911,
                        "title": "유사 독자 반응 높은 후보",
                        "status_code": "serial",
                        "count_hit": 500,
                        "author_nickname": "작가G",
                        "episode_count": 80,
                        "cover_url": None,
                        "protagonist_type": "전략가",
                        "protagonist_desc": "",
                        "mood": "차분함",
                        "pacing": "fast",
                        "premise": "cohort 우위",
                        "hook": "",
                        "themes": [],
                        "taste_tags": ["정치"],
                        "reading_rate": 0.39,
                        "writing_count_per_week": 3.0,
                        "binge_rate": 0.11,
                        "total_next_clicks": 4,
                        "total_readers": 10,
                        "dropoff_7d": 6,
                        "reengage_rate": 0.02,
                        "avg_speed_cpm": 980,
                        "evaluation_score": 6.0,
                        "count_hit_indicator": 1,
                        "count_bookmark_indicator": 0,
                        "reading_rate_indicator": 0.0,
                        "current_rank": 0,
                        "rank_indicator": 0,
                    },
                    {
                        "product_id": 912,
                        "title": "조건 점수 높은 후보",
                        "status_code": "serial",
                        "count_hit": 9000,
                        "author_nickname": "작가H",
                        "episode_count": 80,
                        "cover_url": None,
                        "protagonist_type": "영웅",
                        "protagonist_desc": "",
                        "mood": "유쾌함",
                        "pacing": "fast",
                        "premise": "preset 우위",
                        "hook": "",
                        "themes": [],
                        "taste_tags": ["액션"],
                        "reading_rate": 0.52,
                        "writing_count_per_week": 4.0,
                        "binge_rate": 0.12,
                        "total_next_clicks": 4,
                        "total_readers": 10,
                        "dropoff_7d": 6,
                        "reengage_rate": 0.02,
                        "avg_speed_cpm": 980,
                        "evaluation_score": 6.0,
                        "count_hit_indicator": 1,
                        "count_bookmark_indicator": 0,
                        "reading_rate_indicator": 0.0,
                        "current_rank": 0,
                        "rank_indicator": 0,
                    },
                ]
            )
        )

        with (
            patch.object(
                recommendation_service,
                "_get_condition_first_cohort_scores",
                AsyncMock(return_value={911: 2.4, 912: 0.1}),
            ),
            patch.object(
                recommendation_service,
                "_pick_weighted_candidate",
                side_effect=lambda candidates, **kwargs: candidates[0],
            ),
        ):
            result = await recommendation_service._preset_recommend(
                user_id=1,
                profile={
                    "taste_tags": ["학원"],
                    "preferred_protagonist": {"먼치킨": 1.0},
                    "preferred_mood": {"미스터리": 1.0},
                    "preferred_pacing": "slow",
                    "read_product_ids": [],
                },
                factor_scores={"worldview": {"현대": 1.0}},
                preset="good-schedule",
                exclude_ids=[],
                adult_yn="N",
                db=db,
            )

        self.assertEqual(result["product"]["productId"], 911)
        self.assertIn("비슷한 독자들은", result["reason"])

    async def test_ai_chat_preset_falls_back_to_alternative_preset_on_404(self):
        with (
            patch.object(
                recommendation_service,
                "ai_recommend",
                AsyncMock(side_effect=[recommendation_service.CustomResponseException(status_code=404, message="조건 없음")]),
            ) as mocked_recommend,
            patch.object(
                recommendation_service,
                "_get_user_id_by_kc",
                AsyncMock(return_value=1),
            ),
            patch.object(
                recommendation_service,
                "get_user_taste_profile",
                AsyncMock(return_value=None),
            ),
            patch.object(
                recommendation_service,
                "_get_user_factor_scores",
                AsyncMock(return_value={}),
            ),
            patch.object(
                recommendation_service,
                "_build_relaxed_preset_fallback_result",
                AsyncMock(
                    return_value={
                        "reason": "완결작 조건으로 바로 맞는 작품이 적어서, 연독과 반응 지표가 안정적이에요.",
                        "reply": "완결작 조건으로 바로 맞는 작품이 적어서, 연독과 반응 지표가 안정적이에요.",
                        "product": {"productId": 999, "title": "대체 추천작", "matchReason": ""},
                        "tasteMatch": {"protagonist": 0.2, "mood": 0.1, "pacing": 0.0},
                        "taste_match": {"protagonist": 0.2, "mood": 0.1, "pacing": 0.0},
                    }
                ),
            ),
        ):
            result = await recommendation_service.ai_chat(
                kc_user_id="kc-user",
                messages=[{"role": "user", "content": "완결작 추천"}],
                context={"current_product_id": 326, "page_type": "product"},
                preset="completed",
                exclude_ids=[],
                adult_yn="N",
                db=AsyncMock(),
            )

        self.assertEqual(mocked_recommend.await_count, 1)
        self.assertEqual(result["product"]["productId"], 999)
        self.assertIn("완결작 조건으로 바로 맞는 작품이 적어서", result["reply"])

    async def test_ai_recommend_preset_falls_back_to_alternative_preset_on_404(self):
        with (
            patch.object(
                recommendation_service,
                "_get_user_id_by_kc",
                AsyncMock(return_value=1),
            ),
            patch.object(
                recommendation_service,
                "get_user_taste_profile",
                AsyncMock(return_value=None),
            ),
            patch.object(
                recommendation_service,
                "_get_user_factor_scores",
                AsyncMock(return_value={}),
            ),
            patch.object(
                recommendation_service,
                "_preset_recommend",
                AsyncMock(
                    side_effect=[
                        recommendation_service.CustomResponseException(status_code=404, message="조건 없음"),
                        {
                            "reason": "연독과 반응 지표가 안정적이에요.",
                            "product": {"productId": 888, "title": "대체 추천작", "matchReason": ""},
                            "tasteMatch": {"protagonist": 0.2, "mood": 0.1, "pacing": 0.0},
                            "taste_match": {"protagonist": 0.2, "mood": 0.1, "pacing": 0.0},
                        },
                    ]
                ),
            ) as mocked_preset,
        ):
            result = await recommendation_service.ai_recommend(
                kc_user_id="kc-user",
                query_text=None,
                preset="completed",
                exclude_ids=[],
                adult_yn="N",
                db=AsyncMock(),
                context={"page_type": "home"},
            )

        self.assertEqual(mocked_preset.await_count, 2)
        self.assertEqual(result["product"]["productId"], 888)
        self.assertIn("완결작 조건으로 바로 맞는 작품이 적어서", result["reason"])

    async def test_preset_recommend_excludes_context_anchor_product(self):
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=self._FakeMappingsResult(
                [
                    {
                        "product_id": 326,
                        "title": "퍼펙트 메이지",
                        "status_code": "serial",
                        "count_hit": 1000,
                        "author_nickname": "작가A",
                        "episode_count": 120,
                        "cover_url": None,
                        "protagonist_type": "전략가",
                        "protagonist_desc": "",
                        "mood": "긴장감",
                        "pacing": "fast",
                        "premise": "앵커 작품",
                        "hook": "",
                        "themes": [],
                        "taste_tags": ["회귀", "정치"],
                        "reading_rate": 0.5,
                        "writing_count_per_week": 3.0,
                        "binge_rate": 0.3,
                        "total_next_clicks": 10,
                        "total_readers": 14,
                        "dropoff_7d": 4,
                        "reengage_rate": 0.05,
                        "avg_speed_cpm": 930,
                        "evaluation_score": 7.0,
                        "count_hit_indicator": 3,
                        "count_bookmark_indicator": 1,
                        "reading_rate_indicator": 0.01,
                        "current_rank": 0,
                        "rank_indicator": 0,
                    },
                    {
                        "product_id": 999,
                        "title": "다른 추천작",
                        "status_code": "serial",
                        "count_hit": 900,
                        "author_nickname": "작가B",
                        "episode_count": 110,
                        "cover_url": None,
                        "protagonist_type": "전략가",
                        "protagonist_desc": "",
                        "mood": "긴장감",
                        "pacing": "fast",
                        "premise": "추천 대상",
                        "hook": "",
                        "themes": [],
                        "taste_tags": ["회귀", "정치"],
                        "reading_rate": 0.48,
                        "writing_count_per_week": 3.0,
                        "binge_rate": 0.29,
                        "total_next_clicks": 9,
                        "total_readers": 13,
                        "dropoff_7d": 4,
                        "reengage_rate": 0.04,
                        "avg_speed_cpm": 940,
                        "evaluation_score": 7.0,
                        "count_hit_indicator": 3,
                        "count_bookmark_indicator": 1,
                        "reading_rate_indicator": 0.01,
                        "current_rank": 0,
                        "rank_indicator": 0,
                    },
                ]
            )
        )

        with (
            patch.object(
                recommendation_service,
                "_get_preset_context_anchor",
                AsyncMock(
                    return_value={
                        "product_id": 326,
                        "title": "퍼펙트 메이지",
                        "protagonist_type": "전략가",
                        "mood": "긴장감",
                        "pacing": "fast",
                        "taste_tags": ["회귀", "정치"],
                    }
                ),
            ),
            patch.object(
                recommendation_service,
                "_generate_reason",
                AsyncMock(return_value="추천 사유"),
            ),
        ):
            result = await recommendation_service._preset_recommend(
                user_id=1,
                profile=None,
                factor_scores={},
                preset="stacked-chapters",
                exclude_ids=[],
                adult_yn="N",
                db=db,
                context={"current_product_id": 326},
            )

            self.assertEqual(result["product"]["productId"], 999)

    async def test_pick_weighted_candidate_is_not_fixed_top1(self):
        candidates = [
            {"product_id": 1, "_pick_weight": 1.0},
            {"product_id": 2, "_pick_weight": 1.0},
            {"product_id": 3, "_pick_weight": 1.0},
        ]

        selected = recommendation_service._pick_weighted_candidate(candidates, seed=900000)

        self.assertEqual(selected["product_id"], 3)


if __name__ == "__main__":
    unittest.main()
