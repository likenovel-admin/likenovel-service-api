"""Comment policy and persistence boundary regression tests; no provider calls."""

import unittest
from contextlib import asynccontextmanager
from dataclasses import replace
from unittest.mock import AsyncMock

from app.services.ai import reader_agent_comment_policy as policy
from app.services.ai import reader_agent_action_service as actions
from app.services.ai import reader_agent_decision_service as decisions


class CommentPolicyTest(unittest.TestCase):
    def test_cohort_is_stable_per_reader_and_work_and_approximately_ten_percent(self):
        readers = range(1, 10001)
        regular = [user for user in readers if policy.is_regular_commenter(user, 200)]
        self.assertTrue(900 <= len(regular) <= 1100, len(regular))
        self.assertEqual(regular, [u for u in readers if policy.is_regular_commenter(u, 200)])
        self.assertNotEqual(regular, [u for u in readers if policy.is_regular_commenter(u, 201)])

    def test_regular_reader_starts_then_keeps_a_consistent_greeting(self):
        user = next(u for u in range(1, 1000) if policy.is_regular_commenter(u, 200))
        first = policy.choose_comment(user, 200, 1, first_read=True, finished=False)
        self.assertIsNotNone(first)
        selected = [policy.choose_comment(user, 200, ep, first_read=False, finished=False)
                    for ep in range(2, 10002)]
        posted = [choice for choice in selected if choice is not None]
        self.assertTrue(7700 <= len(posted) <= 8300, len(posted))
        self.assertEqual({choice[0] for choice in posted}, {first[0]})
        self.assertEqual({choice[1] for choice in posted}, {first[1]})

    def test_quiet_reader_sometimes_comments_and_reread_does_not_reroll(self):
        user = next(u for u in range(1, 1000) if not policy.is_regular_commenter(u, 200))
        choices = [policy.choose_comment(user, 200, ep, first_read=False, finished=False)
                   for ep in range(1, 10001)]
        self.assertTrue(60 <= sum(c is not None for c in choices) <= 140)
        for ep, choice in enumerate(choices, 1):
            self.assertEqual(choice, policy.choose_comment(user, 200, ep, first_read=False, finished=False))

    def test_choices_are_bounded_and_finished_work_never_expects_next_episode(self):
        for user in range(1, 1001):
            choice = policy.choose_comment(user, 200, 300, first_read=True, finished=True)
            if choice is not None:
                content, delay = choice
                self.assertIn(content, policy.COMMENT_TEXTS)
                self.assertLessEqual(len(content), 30)
                self.assertNotIn(content, ("다음화 기대됩니다.", "계속 볼게요."))
                self.assertTrue(600 <= delay <= 21600)

    def test_repetition_uses_the_public_comment_order(self):
        for content in policy.REPEATABLE_GREETINGS:
            self.assertFalse(policy.is_repeated_comment(content, [content]))
            self.assertTrue(policy.is_repeated_comment(content, [content, content]))
            self.assertFalse(policy.is_repeated_comment(content, [content, "다른 댓글"]))
        for content in set(policy.COMMENT_TEXTS) - set(policy.REPEATABLE_GREETINGS):
            self.assertTrue(policy.is_repeated_comment(content, [content]))
            self.assertFalse(policy.is_repeated_comment(content, ["다른 댓글", content]))

    def test_comment_scope_ignores_text_but_not_episode(self):
        scope = dict(agent_id=1, user_id=2, product_id=3, episode_id=4, action_type="comment")
        self.assertEqual(decisions.build_active_action_scope_key(**scope, target_value="건필하세요."),
                         decisions.build_active_action_scope_key(**scope, target_value="감사합니다."))
        other = {**scope, "episode_id": 5}
        self.assertNotEqual(decisions.build_active_action_scope_key(**scope, target_value="건필하세요."),
                            decisions.build_active_action_scope_key(**other, target_value="건필하세요."))


class Result:
    def __init__(self, rows=(), rowcount=1):
        self.rows = list(rows)
        self.rowcount = rowcount

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalar(self):
        return next(iter(self.rows[0].values())) if self.rows else 0

    def scalar_one(self):
        return self.scalar()


class CommentActionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.action = actions.ReaderQueuedAction(10, 1, 2, 200, 300, "comment", "건필하세요.", 20)

    def db_for_comment(self, *, episode=None, due_age=0, duplicate=False,
                       recent_ai=(), recent_public=(), read=True, profile=True, inserted=1):
        db = AsyncMock()
        base_episode = {"product_id": 200, "comment_open_yn": "Y", "finished": 0, "count_hit": 50}
        db.execute.side_effect = [
            Result([{**base_episode, **(episode or {})}]),
            Result([{"due_age": due_age}]),
            Result([{"read_count": int(read)}]),
            Result([{"comment_id": 99}] if duplicate else []),
            Result(recent_ai),
            Result([{"content": text} for text in recent_public]),
            Result([{"profile_id": 501}] if profile else []),
            Result(rowcount=inserted),
            Result(),
        ]
        return db

    async def test_open_read_episode_inserts_exact_text(self):
        db = self.db_for_comment()
        result = await actions._apply_comment_action(self.action, db)
        self.assertTrue(result.applied)
        inserts = [c for c in db.execute.await_args_list if "insert into tb_product_comment" in str(c.args[0])]
        self.assertEqual(len(inserts), 1)
        self.assertEqual(inserts[0].args[1]["content"], "건필하세요.")

    async def test_closed_episode_never_inserts(self):
        db = self.db_for_comment(episode={"comment_open_yn": "N"})
        result = await actions._apply_comment_action(self.action, db)
        self.assertEqual(result.reason, "comment_closed")
        self.assertEqual(db.execute.await_count, 1)

    async def test_delayed_backlog_expires_instead_of_catching_up(self):
        db = self.db_for_comment(due_age=301)
        result = await actions._apply_comment_action(self.action, db)
        self.assertEqual(result.reason, "comment_expired")
        self.assertEqual(db.execute.await_count, 2)

    async def test_reader_who_dropped_work_does_not_post_delayed_comment(self):
        db = self.db_for_comment(episode={"reader_state": "dropped"})
        result = await actions._apply_comment_action(self.action, db)
        self.assertEqual(result.reason, "product_dropped")
        self.assertEqual(db.execute.await_count, 1)

    async def test_finished_work_rejects_queued_next_episode_expectation(self):
        db = self.db_for_comment(episode={"finished": 1})
        result = await actions._apply_comment_action(replace(self.action, target_value="다음화 기대됩니다."), db)
        self.assertEqual(result.reason, "comment_finished_work")

    async def test_barely_viewed_episode_does_not_get_a_comment(self):
        # A comment under a near-zero view count reads as fake, so skip it.
        for count_hit in (0, 1, policy.COMMENT_MIN_EPISODE_VIEW_COUNT - 1):
            with self.subTest(count_hit=count_hit):
                db = self.db_for_comment(episode={"count_hit": count_hit})
                result = await actions._apply_comment_action(self.action, db)
                self.assertEqual(result.reason, "comment_view_count_too_low")
                self.assertEqual(db.execute.await_count, 1)

    async def test_minimum_view_count_boundary_allows_the_comment(self):
        db = self.db_for_comment(episode={"count_hit": policy.COMMENT_MIN_EPISODE_VIEW_COUNT})
        result = await actions._apply_comment_action(self.action, db)
        self.assertTrue(result.applied)

    async def test_final_insert_expiry_does_not_update_episode_count(self):
        db = self.db_for_comment(inserted=0)
        result = await actions._apply_comment_action(self.action, db)
        self.assertEqual(result.reason, "comment_expired")
        self.assertFalse(any("update tb_product_episode" in str(c.args[0]) for c in db.execute.await_args_list))

    async def test_missing_profile_does_not_insert(self):
        db = self.db_for_comment(profile=False)
        result = await actions._apply_comment_action(self.action, db)
        self.assertEqual(result.reason, "profile_not_found")
        self.assertFalse(any("insert into tb_product_comment" in str(c.args[0]) for c in db.execute.await_args_list))

    async def test_queue_uses_work_delay_without_midnight_clipping(self):
        user = next(u for u in range(1, 1000) if policy.is_regular_commenter(u, 200))
        action = replace(self.action, action_type="read", user_id=user)
        db = AsyncMock()
        db.execute.side_effect = [Result([{"comment_open_yn": "Y", "read_episode_count": 1, "finished": 0}]), Result()]
        await actions._enqueue_comment_after_read(action, db)
        statement, params = db.execute.await_args.args
        choice = policy.choose_comment(user, 200, 300, first_read=True, finished=False)
        self.assertEqual((params["content"], params["delay"]), choice)
        self.assertIn("timestampadd(second, :delay, current_timestamp)", str(statement))
        self.assertNotIn("least(", str(statement).lower())
        self.assertNotIn("current_date", str(statement).lower())

    async def test_queue_skips_closed_comments_even_for_regular_reader(self):
        user = next(u for u in range(1, 1000) if policy.is_regular_commenter(u, 200))
        db = AsyncMock()
        db.execute.side_effect = [Result([{"comment_open_yn": "N", "read_episode_count": 1, "finished": 0}])]
        await actions._enqueue_comment_after_read(replace(self.action, action_type="read", user_id=user), db)
        self.assertEqual(db.execute.await_count, 1)

    async def test_future_comment_cannot_be_applied_early(self):
        result = await actions._apply_comment_action(self.action, self.db_for_comment(due_age=-1))
        self.assertEqual(result.reason, "comment_not_due")

    async def test_same_reader_episode_is_lifetime_deduplicated(self):
        result = await actions._apply_comment_action(self.action, self.db_for_comment(duplicate=True))
        self.assertEqual(result.reason, "already_in_target_state")

    async def test_unread_episode_is_rejected(self):
        result = await actions._apply_comment_action(self.action, self.db_for_comment(read=False))
        self.assertEqual(result.reason, "episode_not_read")

    async def test_rolling_cap_and_spacing_boundaries(self):
        cases = [([{"age_seconds": 1800}, {"age_seconds": 3600}], True, "applied"),
                 ([{"age_seconds": 1799}], False, "comment_interval_limit"),
                 ([{"age_seconds": 1800}, {"age_seconds": 7200}, {"age_seconds": 86399}], False, "comment_24h_limit")]
        for recent, applied, reason in cases:
            with self.subTest(recent=recent):
                result = await actions._apply_comment_action(self.action, self.db_for_comment(recent_ai=recent))
                self.assertEqual((result.applied, result.reason), (applied, reason))

    async def test_consecutive_greetings_and_contextual_comments(self):
        for text, recent in [("건필하세요.", ["건필하세요."] * 2),
                             ("다음화 기대됩니다.", ["다음화 기대됩니다."])]:
            result = await actions._apply_comment_action(replace(self.action, target_value=text),
                                                         self.db_for_comment(recent_public=recent))
            self.assertEqual(result.reason, "comment_repeated")

    async def test_invalid_text_never_queries_database(self):
        db = AsyncMock()
        with self.assertRaises(actions.InvalidReaderActionError):
            await actions._apply_comment_action(replace(self.action, target_value="자의적인 새 문장"), db)
        db.execute.assert_not_awaited()

    async def test_worker_skips_lock_contention_without_rescheduling_comment(self):
        db = AsyncMock()

        @asynccontextmanager
        async def transaction():
            yield

        db.begin = transaction
        db.execute.side_effect = [Result([{"lock_acquired": 0}]), Result()]
        result = await actions.process_claimed_action(self.action, db, worker_id="comment-test")
        self.assertEqual(result.reason, "comment_lock_busy")
        statement, params = db.execute.await_args.args
        self.assertIn("set status = 'skipped'", str(statement))
        self.assertNotIn("available_at =", str(statement))
        self.assertEqual(params["skip_reason"], "comment_lock_busy")


if __name__ == "__main__":
    unittest.main()
