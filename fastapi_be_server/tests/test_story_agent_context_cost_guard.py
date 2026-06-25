import importlib.util
import io
import json
import sys
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest import TestCase
from unittest.mock import ANY, AsyncMock, patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_story_agent_context.py"


def load_module():
    module_name = "build_story_agent_context_under_test"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def signal_row(summary_id: int, episode_no: int, characters: list[dict]) -> dict:
    return {
        "summary_id": summary_id,
        "episode_from": episode_no,
        "source_hash": f"signal-{summary_id}",
        "summary_text": json.dumps(
            {
                "episode_no": episode_no,
                "mentioned_characters": characters,
                "cliffhanger_hooks": [],
            },
            ensure_ascii=False,
        ),
    }


def signal_character(
    *,
    character_key: str,
    display_name: str,
    aliases: list[str] | None = None,
    is_protagonist: bool = False,
    is_work_protagonist: bool | None = None,
    is_episode_focal: bool | None = None,
    is_first_person: bool = False,
    narration_names: list[str] | None = None,
    social_call_names: list[str] | None = None,
    persona_names: list[str] | None = None,
    real_names: list[str] | None = None,
    entity_kind: str = "person",
    role_in_episode: str = "support",
    voice_mode: str = "narration_only",
    scene_weight: str = "low",
    relation_edges: list[dict] | None = None,
    identity_claims: list[dict] | None = None,
) -> dict:
    return {
        "character_key": character_key,
        "display_name": display_name,
        "aliases": aliases or [display_name],
        "is_protagonist": is_protagonist,
        "is_work_protagonist": is_protagonist if is_work_protagonist is None else is_work_protagonist,
        "is_episode_focal": is_protagonist if is_episode_focal is None else is_episode_focal,
        "is_first_person": is_first_person,
        "narration_names": narration_names or [],
        "social_call_names": social_call_names or [],
        "persona_names": persona_names or [],
        "real_names": real_names or [],
        "entity_kind": entity_kind,
        "scene_weight": scene_weight,
        "role_in_episode": role_in_episode,
        "voice_mode": voice_mode,
        "action_tags": [],
        "affect_tags": [],
        "relation_edges": relation_edges or [],
        "identity_claims": identity_claims or [],
        "episode_no": 0,
    }


class FakeConnection:
    def __init__(self):
        self.commit_count = 0

    def commit(self):
        self.commit_count += 1


class FakeRowsCursor:
    def __init__(self, rows):
        self.rows = rows
        self.query = ""
        self.params = None

    def execute(self, query, params=None):
        self.query = query
        self.params = params

    def fetchall(self):
        return self.rows


@contextmanager
def fake_work_cursor(_conn):
    yield object()


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeOpenRouterClient:
    def __init__(self, content):
        self.content = content
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {"content": json.dumps(self.content, ensure_ascii=False)},
                        "finish_reason": "stop",
                    }
                ]
            }
        )


class StoryAgentContextCostGuardTest(IsolatedAsyncioTestCase):
    async def test_existing_episode_character_signal_reuses_without_llm_call(self):
        module = load_module()
        conn = FakeConnection()
        row = {
            "summary_id": 777,
            "scope_key": "episode:1001",
            "episode_from": 1,
            "source_hash": "episode-summary-hash",
            "summary_text": "[1화] 첫 만남\n주인공이 사건에 휘말린다.\n핵심: 주인공, 사건, 만남, 갈등, 선택, 후킹",
        }
        request_mock = AsyncMock(
            return_value={
                "mentioned_characters": [
                    {
                        "display_name": "주인공",
                        "is_protagonist": True,
                        "is_first_person": False,
                    }
                ],
                "cliffhanger_hooks": ["다음 사건의 단서가 남는다."],
            }
        )

        with patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "fetch_existing_summary", return_value={"summary_id": 123, "version_no": 1, "is_active": "Y"}), \
             patch.object(module, "activate_existing_summary") as activate_existing, \
             patch.object(module, "request_episode_character_signals_payload", request_mock):
            inserted, reused = await module.build_episode_character_signals_summaries(
                conn,
                product_id=687,
                episode_rows=[row],
                summary_client=object(),
                cleanup_missing_scopes=False,
            )

        self.assertEqual(inserted, 0)
        self.assertEqual(reused, 1)
        request_mock.assert_not_awaited()
        activate_existing.assert_called_once_with(ANY, 123, 687, "episode_character_signals", "episode:1001")
        self.assertEqual(conn.commit_count, 1)

    async def test_episode_character_signal_failure_deactivates_stale_scope(self):
        module = load_module()
        conn = FakeConnection()
        row = {
            "summary_id": 777,
            "scope_key": "episode:1001",
            "episode_from": 1,
            "source_hash": "episode-summary-hash-new",
            "summary_text": "[1화] 바뀐 회차\n주인공 후보가 바뀐다.\n핵심: 주인공, 후보, 변경",
        }
        request_mock = AsyncMock(side_effect=module.RequestError("upstream timeout"))

        with patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "fetch_existing_summary", return_value=None), \
             patch.object(module, "request_episode_character_signals_payload", request_mock), \
             patch.object(module, "deactivate_active_scope", return_value=1) as deactivate_scope:
            inserted, reused = await module.build_episode_character_signals_summaries(
                conn,
                product_id=687,
                episode_rows=[row],
                summary_client=object(),
                cleanup_missing_scopes=False,
            )

        self.assertEqual(inserted, 0)
        self.assertEqual(reused, 0)
        request_mock.assert_awaited_once()
        deactivate_scope.assert_called_once_with(
            ANY,
            product_id=687,
            summary_type="episode_character_signals",
            scope_key="episode:1001",
        )
        self.assertEqual(conn.commit_count, 1)

    async def test_episode_character_signals_defaults_to_deepseek_direct(self):
        module = load_module()
        client = FakeOpenRouterClient(
            {
                "episode_no": 1,
                "mentioned_characters": [
                    {
                        "display_name": "백이현",
                        "aliases": ["백이현"],
                        "is_protagonist": True,
                        "is_first_person": False,
                        "entity_kind": "person",
                        "scene_weight": "high",
                        "role_in_episode": "lead",
                        "voice_mode": "dialogue",
                        "action_tags": ["질문"],
                        "affect_tags": ["경계"],
                        "relation_edges": [],
                        "identity_claims": [],
                    }
                ],
                "cliffhanger_hooks": ["다음 선택이 남는다."],
            }
        )

        with patch.object(module.settings, "ANTHROPIC_API_KEY", "anthropic-key"), \
             patch.object(module, "RP_REASONING_MODEL", ""), \
             patch.object(module, "DEEPSEEK_API_KEY", "deepseek-key"), \
             patch.object(module, "DEEPSEEK_BASE_URL", "https://api.deepseek.com"), \
             patch.object(module, "RP_DEEPSEEK_FALLBACK_MODEL", "deepseek-v4-pro"):
            payload = await module.request_episode_character_signals_payload(
                client,
                row={"episode_no": 1, "title": "테스트", "episode_title": "1화"},
                summary_text="[1화] 테스트\n백이현이 경계하며 질문한다.\n핵심: 백이현, 경계, 질문, 선택, 사건, 단서",
            )

        self.assertEqual(payload["mentioned_characters"][0]["display_name"], "백이현")
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["url"], "https://api.deepseek.com/chat/completions")
        self.assertNotIn("api.anthropic.com", client.calls[0]["url"])
        self.assertEqual(client.calls[0]["json"]["model"], "deepseek-v4-pro")
        self.assertEqual(client.calls[0]["json"]["max_tokens"], module.EPISODE_CHARACTER_SIGNALS_MAX_OUTPUT_TOKENS)
        self.assertEqual(client.calls[0]["json"]["response_format"], {"type": "json_object"})
        call_messages = client.calls[0]["json"]["messages"]
        self.assertIn("JSON schema", call_messages[1]["content"])
        self.assertNotIn("라인 포맷", call_messages[1]["content"])
        self.assertEqual(client.calls[0]["headers"]["X-Title"], "LikeNovel Story Agent Episode Character Signals DeepSeek")

    def test_episode_character_signals_source_hash_uses_primary_model(self):
        module = load_module()

        with patch.object(module, "RP_REASONING_MODEL", ""), \
             patch.object(module, "RP_DEEPSEEK_FALLBACK_MODEL", "deepseek-v4-pro"):
            self.assertEqual(module.build_rp_reasoning_signature(), "deepseek|deepseek-v4-pro")

        with patch.object(module, "RP_REASONING_MODEL", "claude-sonnet-4-6"), \
             patch.object(module, "RP_REASONING_EFFORT", "medium"), \
             patch.object(module, "RP_REASONING_THINKING_DISPLAY", "omitted"):
            self.assertEqual(
                module.build_rp_reasoning_signature(),
                "anthropic|claude-sonnet-4-6|medium|omitted",
            )

    def test_provider_summary_reports_direct_deepseek_signal_path(self):
        module = load_module()

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "EPISODE_SUMMARY_MODEL", "deepseek/deepseek-v3.2"), \
             patch.object(module.settings, "ANTHROPIC_API_KEY", ""), \
             patch.object(module, "RP_REASONING_MODEL", ""), \
             patch.object(module, "DEEPSEEK_API_KEY", "deepseek-key"), \
             patch.object(module, "RP_DEEPSEEK_FALLBACK_MODEL", "deepseek-v4-pro"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "RP_OPENROUTER_PROVIDER_ONLY", "deepinfra,together"):
            line = module.build_storyctx_provider_summary_line()

        self.assertIn("episode_summary_provider=openrouter", line)
        self.assertIn("episode_summary_model=deepseek/deepseek-v3.2", line)
        self.assertIn("episode_character_signals_provider=deepseek", line)
        self.assertIn("episode_character_signals_model=deepseek-v4-pro", line)
        self.assertIn("rp_profile_provider=openrouter", line)
        self.assertIn("rp_profile_model=google/gemma-4-31b-it", line)
        self.assertIn("rp_openrouter_provider_only=deepinfra,together", line)

    def test_episode_summary_prompt_uses_episode_summary_input_cap(self):
        module = load_module()
        normalized_text = "가" * (module.EPISODE_SUMMARY_MAX_INPUT_CHARS + 50)

        prompt = module.build_episode_summary_user_prompt(
            {"title": "테스트 작품", "episode_no": 1, "episode_title": "1화 시작"},
            normalized_text,
        )

        source_text = prompt.split("원문:\n", 1)[1]
        self.assertEqual(len(source_text), module.EPISODE_SUMMARY_MAX_INPUT_CHARS)

    def test_episode_character_signal_prompt_requires_explicit_identity_claims(self):
        module = load_module()

        prompt = module.EPISODE_CHARACTER_SIGNALS_PROMPT

        self.assertIn("is_work_protagonist는 작품 전체 주인공일 때만 true", prompt)
        self.assertIn("is_episode_focal은 이 회차의 중심 인물이면 true", prompt)
        self.assertIn("social_call_names에는 다른 인물이 그 인물을 부르는 호칭", prompt)
        self.assertIn("persona_names에 넣고, 현실/전생/본명은 real_names", prompt)
        self.assertIn("호영이 조렌 테이머의 부활 중 빙의된 수호자", prompt)
        self.assertIn('target_label="조렌 테이머"', prompt)
        self.assertIn('claim_type="possessed_as"', prompt)
        self.assertIn("단순 직책, 소속, 가족/상하관계, 상태 설명, 같은 장면 등장은 identity_claims로 만들지 않는다", prompt)

    def test_print_summary_includes_provider_line_and_product_ids(self):
        module = load_module()
        results = module.build_empty_results()
        results["inserted_docs"] = 2
        results["inserted_episode_character_signals"] = 2
        results["products"] = [
            {
                "product_id": 687,
                "context_status": "processing",
                "ready_episode_count": 12,
                "total_episode_count": 20,
            }
        ]
        stdout = io.StringIO()

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "EPISODE_SUMMARY_MODEL", "deepseek/deepseek-v3.2"), \
             patch.object(module.settings, "ANTHROPIC_API_KEY", ""), \
             patch.object(module, "RP_REASONING_MODEL", ""), \
             patch.object(module, "DEEPSEEK_API_KEY", "deepseek-key"), \
             patch.object(module, "RP_DEEPSEEK_FALLBACK_MODEL", "deepseek-v4-pro"), \
             redirect_stdout(stdout):
            module.print_summary(results=results, apply=True)

        output = stdout.getvalue()
        self.assertIn("storyctx-provider", output)
        self.assertIn("episode_character_signals_provider=deepseek", output)
        self.assertIn("mode=apply product_ids=687 inserted_docs=2", output)
        self.assertIn("inserted_episode_character_signals=2", output)
        self.assertIn("product product_id=687 status=processing ready=12 total=20", output)

    async def test_rp_profile_uses_paid_gemma_openrouter_payload(self):
        module = load_module()
        client = FakeOpenRouterClient(
            {
                "speech_style": {"tone": ["차분한"], "formality": "반말", "sentence_length": "보통", "habit": [], "address": ""},
                "personality_core": ["경계심이 강함"],
                "baseline_attitude": "경계",
                "example_dialogues": ["그게 정말 가능하다고?"],
            }
        )

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "RP_OPENROUTER_PROVIDER_ONLY", "deepinfra,together"):
            payload = await module.request_rp_profile_payload(
                client,
                target={"display_name": "백이현", "aliases": ["백이현"]},
                dialogue_items=[{"kind": "dialogue", "context": "질문", "text": "그게 정말 가능하다고?", "example_score": 8}],
                summary_context_lines=["[1화] 백이현이 상황을 의심한다."],
            )

        self.assertEqual(payload["baseline_attitude"], "경계")
        self.assertEqual(len(client.calls), 1)
        request_json = client.calls[0]["json"]
        self.assertEqual(request_json["model"], "google/gemma-4-31b-it")
        self.assertEqual(
            request_json["provider"],
            {
                "only": ["deepinfra", "together"],
                "order": ["deepinfra", "together"],
                "allow_fallbacks": True,
            },
        )
        self.assertEqual(request_json["reasoning"], {"effort": "none", "exclude": True})
        self.assertEqual(request_json["response_format"], {"type": "json_object"})
        self.assertNotIn(":free", request_json["model"])

    async def test_rp_openrouter_rejects_free_model_variant_before_network_call(self):
        module = load_module()
        client = FakeOpenRouterClient({"characters": []})

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it:free"):
            with self.assertRaisesRegex(RuntimeError, "must not use :free"):
                await module.request_rp_character_plan_payload(
                    client,
                    episode_rows=[],
                    episode_texts_by_no={},
                )

        self.assertEqual(client.calls, [])

    async def test_rp_dialogue_request_uses_openrouter_payload_without_undefined_provider_helper(self):
        module = load_module()
        client = FakeOpenRouterClient(
            {
                "items": [
                    {
                        "episode_no": 1,
                        "kind": "dialogue",
                        "context": "문 앞",
                        "text": "나는 여기서 물러서지 않아.",
                        "speaker_label": "백이현",
                        "confidence": 0.95,
                    }
                ]
            }
        )

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "RP_OPENROUTER_PROVIDER_ONLY", "google"):
            items = await module.request_rp_dialogue_items(
                client,
                target={
                    "display_name": "백이현",
                    "reference_name": "백이현",
                    "aliases": ["백이현"],
                },
                normalized_text='<episode no="1">백이현이 말했다. "나는 여기서 물러서지 않아."</episode>',
            )

        self.assertEqual(
            items,
            [{"episode_no": 1, "kind": "dialogue", "context": "문 앞", "text": "나는 여기서 물러서지 않아.", "confidence": 0.95}],
        )
        self.assertEqual(
            client.calls[0]["json"]["provider"],
            {"only": ["google"], "order": ["google"], "allow_fallbacks": False},
        )

    async def test_rp_build_keeps_old_profiles_when_plan_targets_missing(self):
        module = load_module()
        conn = FakeConnection()

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "request_rp_character_plan_payload", AsyncMock(return_value={"characters": []})), \
             patch.object(module, "deactivate_missing_active_scopes") as deactivate_missing:
            counts = await module.build_rp_summaries(
                conn,
                product_id=687,
                episode_rows=[],
                episode_texts_by_no={},
                summary_client=object(),
            )

        self.assertEqual(counts, {"profile": (0, 0), "examples": (0, 0)})
        deactivate_missing.assert_not_called()
        self.assertEqual(conn.commit_count, 0)

    async def test_rp_build_does_not_fallback_to_plan_when_v3_inventory_has_no_targets(self):
        module = load_module()
        conn = FakeConnection()
        plan_mock = AsyncMock(
            return_value={
                "characters": [
                    {
                        "character_key": "named:legacy",
                        "display_name": "레거시",
                        "aliases": ["레거시"],
                        "is_protagonist": False,
                    }
                ]
            }
        )

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "request_rp_character_plan_payload", plan_mock), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "deactivate_missing_active_scopes") as deactivate_missing:
            counts = await module.build_rp_summaries(
                conn,
                product_id=687,
                episode_rows=[],
                episode_texts_by_no={},
                summary_client=object(),
                inventory_map={
                    "character:해설자": {
                        "canonical_character_key": "character:해설자",
                        "display_name": "해설자",
                        "entity_kind": "narrator",
                        "distinct_episode_count": 3,
                    }
                },
            )

        self.assertEqual(counts, {"profile": (0, 0), "examples": (0, 0)})
        plan_mock.assert_not_called()
        deactivate_missing.assert_not_called()
        self.assertEqual(conn.commit_count, 0)

    async def test_rp_build_uses_v3_inventory_targets_without_plan_call(self):
        module = load_module()
        conn = FakeConnection()
        episode_texts_by_no = {
            1: "\n".join(
                [
                    '백이현이 말했다. "나는 여기서 물러서지 않을 거야, 네 선택을 다시 확인해."',
                    '백이현이 낮게 물었다. "그 말이 사실이라면 지금 당장 증거를 보여 줘."',
                    '백이현은 고개를 저으며 말했다. "아직 끝난 게 아니야, 내가 직접 확인하겠어."',
                ]
            ),
            2: "\n".join(
                [
                    '백이현이 숨을 고르며 답했다. "겁먹을 시간은 없어, 먼저 사람들을 빼내."',
                    '백이현이 검을 세우며 말했다. "네가 막는다면 나도 돌아가지 않겠어."',
                    '백이현이 짧게 웃었다. "좋아, 이번엔 네 방식대로 움직여 보자."',
                ]
            ),
            3: "\n".join(
                [
                    '백이현이 문서를 접으며 말했다. "이 기록은 내가 맡을게, 누구에게도 넘기지 마."',
                    '백이현이 뒤돌아서며 말했다. "따라오지 마, 여기서부터는 내가 정리한다."',
                    '백이현이 조용히 말했다. "약속은 지킬 거야, 대신 너도 물러서지 마."',
                ]
            ),
        }
        profile_payload = {
            "speech_style": {"tone": "단호"},
            "personality_core": ["원칙적"],
            "baseline_attitude": "경계",
            "example_dialogues": [
                "나는 여기서 물러서지 않을 거야, 네 선택을 다시 확인해.",
                "겁먹을 시간은 없어, 먼저 사람들을 빼내.",
                "이 기록은 내가 맡을게, 누구에게도 넘기지 마.",
            ],
        }
        plan_mock = AsyncMock(return_value={"characters": []})
        profile_mock = AsyncMock(return_value=profile_payload)

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "request_rp_character_plan_payload", plan_mock), \
             patch.object(module, "request_rp_profile_payload", profile_mock), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "upsert_summary", side_effect=[({"summary_id": 1}, True), ({"summary_id": 2}, True)]), \
             patch.object(module, "deactivate_missing_active_scopes") as deactivate_missing:
            counts = await module.build_rp_summaries(
                conn,
                product_id=687,
                episode_rows=[],
                episode_texts_by_no=episode_texts_by_no,
                summary_client=object(),
                inventory_map={
                    "character:백이현": {
                        "canonical_character_key": "character:백이현",
                        "source_character_keys": ["protagonist:named:백이현", "named:백이현"],
                        "display_name": "백이현",
                        "aliases": ["백이현"],
                        "is_protagonist": True,
                        "distinct_episode_count": 3,
                        "voice_evidence_count": 9,
                        "evidence_episode_nos": [1, 2, 3],
                    }
                },
            )

        self.assertEqual(counts, {"profile": (1, 0), "examples": (1, 0)})
        plan_mock.assert_not_called()
        profile_mock.assert_awaited_once()
        expected_scope_keys = {"character:백이현", "protagonist:named:백이현", "named:백이현"}
        deactivate_missing.assert_any_call(ANY, 687, "character_rp_profile", expected_scope_keys)
        deactivate_missing.assert_any_call(ANY, 687, "character_rp_examples", expected_scope_keys)
        self.assertEqual(conn.commit_count, 2)

    async def test_delta_rp_build_uses_v3_inventory_without_plan_call(self):
        module = load_module()
        conn = FakeConnection()
        episode_texts_by_no = {
            1: "\n".join(
                [
                    '백이현이 말했다. "나는 여기서 물러서지 않을 거야, 네 선택을 다시 확인해."',
                    '백이현이 낮게 물었다. "그 말이 사실이라면 지금 당장 증거를 보여 줘."',
                    '백이현은 고개를 저으며 말했다. "아직 끝난 게 아니야, 내가 직접 확인하겠어."',
                ]
            ),
            2: "\n".join(
                [
                    '백이현이 숨을 고르며 답했다. "겁먹을 시간은 없어, 먼저 사람들을 빼내."',
                    '백이현이 검을 세우며 말했다. "네가 막는다면 나도 돌아가지 않겠어."',
                    '백이현이 짧게 웃었다. "좋아, 이번엔 네 방식대로 움직여 보자."',
                ]
            ),
            3: "\n".join(
                [
                    '백이현이 문서를 접으며 말했다. "이 기록은 내가 맡을게, 누구에게도 넘기지 마."',
                    '백이현이 뒤돌아서며 말했다. "따라오지 마, 여기서부터는 내가 정리한다."',
                    '백이현이 조용히 말했다. "약속은 지킬 거야, 대신 너도 물러서지 마."',
                ]
            ),
        }
        profile_payload = {
            "speech_style": {"tone": "단호"},
            "personality_core": ["원칙적"],
            "baseline_attitude": "경계",
            "example_dialogues": [
                "나는 여기서 물러서지 않을 거야, 네 선택을 다시 확인해.",
                "겁먹을 시간은 없어, 먼저 사람들을 빼내.",
                "이 기록은 내가 맡을게, 누구에게도 넘기지 마.",
            ],
        }
        plan_mock = AsyncMock(return_value={"characters": []})
        profile_mock = AsyncMock(return_value=profile_payload)

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "request_rp_character_plan_payload", plan_mock), \
             patch.object(module, "request_rp_profile_payload", profile_mock), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "upsert_summary", side_effect=[({"summary_id": 1}, True), ({"summary_id": 2}, True)]), \
             patch.object(module, "deactivate_active_scope", return_value=1) as deactivate_scope:
            counts = await module.build_rp_summaries_delta(
                conn,
                product_id=687,
                affected_scope_keys={"character:백이현", "protagonist:named:백이현"},
                episode_rows=[],
                episode_texts_by_no=episode_texts_by_no,
                summary_client=object(),
                inventory_map={
                    "character:백이현": {
                        "canonical_character_key": "character:백이현",
                        "source_character_keys": ["protagonist:named:백이현", "named:백이현"],
                        "display_name": "백이현",
                        "aliases": ["백이현"],
                        "is_protagonist": True,
                        "distinct_episode_count": 3,
                        "voice_evidence_count": 9,
                        "evidence_episode_nos": [1, 2, 3],
                    }
                },
                relation_map={},
            )

        self.assertEqual(counts["profile"], [1, 0])
        self.assertEqual(counts["examples"], [1, 0])
        plan_mock.assert_not_called()
        profile_mock.assert_awaited_once()
        self.assertEqual(counts["deactivated_profile_count"], 0)
        self.assertEqual(counts["deactivated_examples_count"], 0)
        deactivate_scope.assert_not_called()

    async def test_rp_build_preserves_keep_old_scope_when_another_v3_target_succeeds(self):
        module = load_module()
        conn = FakeConnection()
        episode_texts_by_no = {
            1: "\n".join(
                [
                    '백이현이 말했다. "나는 여기서 물러서지 않을 거야, 네 선택을 다시 확인해."',
                    '백이현이 낮게 물었다. "그 말이 사실이라면 지금 당장 증거를 보여 줘."',
                    '백이현은 고개를 저으며 말했다. "아직 끝난 게 아니야, 내가 직접 확인하겠어."',
                ]
            ),
            2: "\n".join(
                [
                    '백이현이 숨을 고르며 답했다. "겁먹을 시간은 없어, 먼저 사람들을 빼내."',
                    '백이현이 검을 세우며 말했다. "네가 막는다면 나도 돌아가지 않겠어."',
                    '백이현이 짧게 웃었다. "좋아, 이번엔 네 방식대로 움직여 보자."',
                ]
            ),
            3: "\n".join(
                [
                    '백이현이 문서를 접으며 말했다. "이 기록은 내가 맡을게, 누구에게도 넘기지 마."',
                    '백이현이 뒤돌아서며 말했다. "따라오지 마, 여기서부터는 내가 정리한다."',
                    '백이현이 조용히 말했다. "약속은 지킬 거야, 대신 너도 물러서지 마."',
                ]
            ),
            4: "김도윤은 말없이 장면 밖에 머물렀다.",
        }
        profile_payload = {
            "speech_style": {"tone": "단호"},
            "personality_core": ["원칙적"],
            "baseline_attitude": "경계",
            "example_dialogues": [
                "나는 여기서 물러서지 않을 거야, 네 선택을 다시 확인해.",
                "겁먹을 시간은 없어, 먼저 사람들을 빼내.",
                "이 기록은 내가 맡을게, 누구에게도 넘기지 마.",
            ],
        }

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "request_rp_character_plan_payload", AsyncMock(return_value={"characters": []})), \
             patch.object(module, "collect_llm_rp_dialogue_items", AsyncMock(return_value=[])), \
             patch.object(module, "request_rp_profile_payload", AsyncMock(return_value=profile_payload)), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "upsert_summary", side_effect=[({"summary_id": 1}, True), ({"summary_id": 2}, True)]), \
             patch.object(module, "deactivate_missing_active_scopes") as deactivate_missing:
            counts = await module.build_rp_summaries(
                conn,
                product_id=687,
                episode_rows=[],
                episode_texts_by_no=episode_texts_by_no,
                summary_client=object(),
                inventory_map={
                    "character:백이현": {
                        "canonical_character_key": "character:백이현",
                        "display_name": "백이현",
                        "aliases": ["백이현"],
                        "is_protagonist": True,
                        "distinct_episode_count": 3,
                        "voice_evidence_count": 9,
                        "evidence_episode_nos": [1, 2, 3],
                    },
                    "character:김도윤": {
                        "canonical_character_key": "character:김도윤",
                        "display_name": "김도윤",
                        "aliases": ["김도윤"],
                        "entity_kind": "person",
                        "distinct_episode_count": 1,
                        "voice_evidence_count": 1,
                        "evidence_episode_nos": [4],
                    },
                },
            )

        self.assertEqual(counts, {"profile": (1, 0), "examples": (1, 0)})
        expected_scope_keys = {"character:백이현", "character:김도윤"}
        deactivate_missing.assert_any_call(ANY, 687, "character_rp_profile", expected_scope_keys)
        deactivate_missing.assert_any_call(ANY, 687, "character_rp_examples", expected_scope_keys)

    async def test_rp_build_skips_cleanup_when_all_v3_targets_keep_old(self):
        module = load_module()
        conn = FakeConnection()

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "request_rp_character_plan_payload", AsyncMock(return_value={"characters": []})), \
             patch.object(module, "collect_llm_rp_dialogue_items", AsyncMock(return_value=[])), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "deactivate_missing_active_scopes") as deactivate_missing:
            counts = await module.build_rp_summaries(
                conn,
                product_id=687,
                episode_rows=[],
                episode_texts_by_no={1: "김도윤은 말없이 장면 밖에 머물렀다."},
                summary_client=object(),
                inventory_map={
                    "character:김도윤": {
                        "canonical_character_key": "character:김도윤",
                        "display_name": "김도윤",
                        "aliases": ["김도윤"],
                        "entity_kind": "person",
                        "distinct_episode_count": 1,
                        "voice_evidence_count": 1,
                        "evidence_episode_nos": [1],
                    }
                },
            )

        self.assertEqual(counts, {"profile": (0, 0), "examples": (0, 0)})
        deactivate_missing.assert_not_called()
        self.assertEqual(conn.commit_count, 0)

    async def test_rp_build_uses_gemma_exact_dialogue_when_rule_based_voice_is_not_ready(self):
        module = load_module()
        conn = FakeConnection()
        episode_texts_by_no = {
            1: '그는 고개를 들었다. "나는 여기서 물러서지 않아, 끝까지 확인하고 책임까지 지겠어." 잠시 뒤 다시 말했다. "네가 숨긴 기록부터 내 앞에 내놔, 판단은 그 다음에 하겠다."',
            2: '상대가 물러서자 그가 답했다. "겁먹을 시간은 없어, 먼저 사람들을 빼내고 문을 봉쇄해." 그리고 낮게 덧붙였다. "내가 맡을 테니 너는 문을 막아, 뒤는 돌아보지 마."',
            3: '침묵 끝에 목소리가 떨어졌다. "약속은 지킬 거야, 대신 너도 여기서 물러서지 마." 곧이어 이어졌다. "이 기록은 내가 맡을게, 누구에게도 넘기지 말고 기다려."',
            4: '마지막 문 앞에서 그가 웃었다. "좋아, 이번엔 네 방식대로 움직여 보자, 대신 신호는 내가 낸다." 숨을 고른 뒤 말했다. "따라오지 마, 여기서부터는 내가 정리하고 끝내겠다."',
        }
        llm_items = [
            {"episode_no": 1, "kind": "dialogue", "text": "나는 여기서 물러서지 않아, 끝까지 확인하고 책임까지 지겠어.", "confidence": 0.95},
            {"episode_no": 1, "kind": "dialogue", "text": "네가 숨긴 기록부터 내 앞에 내놔, 판단은 그 다음에 하겠다.", "confidence": 0.95},
            {"episode_no": 2, "kind": "dialogue", "text": "겁먹을 시간은 없어, 먼저 사람들을 빼내고 문을 봉쇄해.", "confidence": 0.95},
            {"episode_no": 2, "kind": "dialogue", "text": "내가 맡을 테니 너는 문을 막아, 뒤는 돌아보지 마.", "confidence": 0.95},
            {"episode_no": 3, "kind": "dialogue", "text": "약속은 지킬 거야, 대신 너도 여기서 물러서지 마.", "confidence": 0.95},
            {"episode_no": 3, "kind": "dialogue", "text": "이 기록은 내가 맡을게, 누구에게도 넘기지 말고 기다려.", "confidence": 0.95},
            {"episode_no": 4, "kind": "dialogue", "text": "좋아, 이번엔 네 방식대로 움직여 보자, 대신 신호는 내가 낸다.", "confidence": 0.95},
            {"episode_no": 4, "kind": "dialogue", "text": "따라오지 마, 여기서부터는 내가 정리하고 끝내겠다.", "confidence": 0.95},
        ]
        profile_payload = {
            "speech_style": {"tone": "단호"},
            "personality_core": ["책임감"],
            "baseline_attitude": "경계",
            "example_dialogues": [
                "나는 여기서 물러서지 않아, 끝까지 확인하고 책임까지 지겠어.",
                "겁먹을 시간은 없어, 먼저 사람들을 빼내고 문을 봉쇄해.",
                "따라오지 마, 여기서부터는 내가 정리하고 끝내겠다.",
            ],
        }
        plan_mock = AsyncMock(return_value={"characters": []})
        dialogue_mock = AsyncMock(return_value=llm_items)
        profile_mock = AsyncMock(return_value=profile_payload)
        self.assertTrue(module.is_strict_dialogue_item_set_ready(llm_items, ["백이현"]))

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "request_rp_character_plan_payload", plan_mock), \
             patch.object(module, "request_rp_dialogue_items", dialogue_mock), \
             patch.object(module, "request_rp_profile_payload", profile_mock), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "upsert_summary", side_effect=[({"summary_id": 1}, True), ({"summary_id": 2}, True)]), \
             patch.object(module, "deactivate_missing_active_scopes"):
            counts = await module.build_rp_summaries(
                conn,
                product_id=687,
                episode_rows=[],
                episode_texts_by_no=episode_texts_by_no,
                summary_client=object(),
                inventory_map={
                    "character:백이현": {
                        "canonical_character_key": "character:백이현",
                        "source_character_keys": ["protagonist:named:백이현"],
                        "display_name": "백이현",
                        "aliases": ["백이현"],
                        "is_protagonist": True,
                        "distinct_episode_count": 4,
                        "voice_evidence_count": 4,
                        "evidence_episode_nos": [1, 2, 3, 4],
                    }
                },
            )

        self.assertEqual(counts, {"profile": (1, 0), "examples": (1, 0)})
        plan_mock.assert_not_called()
        dialogue_mock.assert_awaited_once()
        profile_mock.assert_awaited_once()


class StoryAgentContextDeltaValidationTest(TestCase):
    def test_fetch_active_character_inventory_map_accepts_v3_summary_type(self):
        module = load_module()
        cur = object()

        with patch.object(
            module,
            "fetch_active_summary_rows",
            return_value=[
                {
                    "scope_key": "character:백이현",
                    "summary_text": '{"display_name":"백이현"}',
                }
            ],
        ) as fetch_rows:
            inventory = module.fetch_active_character_inventory_map(
                cur,
                product_id=687,
                summary_type="character_inventory_v3",
            )

        fetch_rows.assert_called_once_with(cur=cur, product_id=687, summary_type="character_inventory_v3")
        self.assertEqual(inventory, {"character:백이현": {"display_name": "백이현"}})

    def test_foundation_invariant_requires_character_inventory_v3(self):
        module = load_module()
        missing_v3_cursor = FakeRowsCursor(
            [
                {"summary_type": "episode_summary", "cnt": 3},
                {"summary_type": "episode_character_signals", "cnt": 3},
                {"summary_type": "character_inventory", "cnt": 1},
            ]
        )

        with self.assertRaisesRegex(ValueError, "character_inventory_v3=0"):
            module.assert_story_agent_foundation_invariants(missing_v3_cursor, product_id=687)

        ready_cursor = FakeRowsCursor(
            [
                {"summary_type": "episode_summary", "cnt": 3},
                {"summary_type": "episode_character_signals", "cnt": 3},
                {"summary_type": "character_inventory", "cnt": 1},
                {"summary_type": "character_inventory_v3", "cnt": 1},
            ]
        )
        module.assert_story_agent_foundation_invariants(ready_cursor, product_id=687)
        self.assertIn("character_inventory_v3", ready_cursor.query)

    def test_rp_target_quality_guard_rejects_generic_display_name(self):
        module = load_module()

        self.assertEqual(module.get_rp_target_skip_reason({"display_name": "지금"}), "generic_display_name")
        self.assertEqual(module.get_rp_target_skip_reason({"display_name": " 오늘 "}), "generic_display_name")
        self.assertEqual(module.get_rp_target_skip_reason({"display_name": "형"}), "generic_display_name")
        self.assertEqual(module.get_rp_target_skip_reason({"display_name": "왕"}), "generic_display_name")
        self.assertEqual(module.get_rp_target_skip_reason({"display_name": "백이현"}), "")
        self.assertEqual(module.get_rp_target_skip_reason({"display_name": "주인공", "aliases": ["나"]}), "generic_display_name")

    def test_rp_profile_requires_minimum_exact_examples(self):
        module = load_module()

        self.assertFalse(module.has_enough_rp_example_texts(["첫 번째", "두 번째"]))
        self.assertTrue(module.has_enough_rp_example_texts(["첫 번째", "두 번째", "세 번째"]))

    def test_dedupe_rp_dialogue_items_preserves_episode_no(self):
        module = load_module()

        deduped = module.dedupe_rp_dialogue_items(
            [
                {
                    "kind": "dialogue",
                    "context": "백이현",
                    "text": "그게 정말 가능하다고?",
                    "episode_no": 7,
                }
            ]
        )

        self.assertEqual(deduped[0]["episode_no"], 7)

    def test_speaker_anchor_match_requires_precise_name_boundary(self):
        module = load_module()

        self.assertTrue(module.has_speaker_anchor_match('백이현이 말했다. "간다."', ["백이현"]))
        self.assertTrue(module.has_speaker_anchor_match('반 아슬란은 대답했다. "물러서지 않는다."', ["반 아슬란"]))
        self.assertFalse(module.has_speaker_anchor_match('최신 트렌드를 설명했다. "이게 맞다."', ["렌"]))
        self.assertFalse(module.has_speaker_anchor_match('김백이현이 말했다. "간다."', ["백이현"]))
        self.assertTrue(module.has_speaker_anchor_match('렌이 말했다. "간다."', ["렌"], allow_single_char_anchors=True))
        self.assertFalse(module.has_speaker_anchor_match('최신 트렌드를 설명했다. "이게 맞다."', ["렌"], allow_single_char_anchors=True))

    def test_direct_voice_quality_requires_distributed_exact_dialogue(self):
        module = load_module()
        target = {
            "display_name": "백이현",
            "aliases": ["백이현"],
            "collection_rules": {
                "use_dialogue": True,
                "speaker_anchors": ["백이현"],
            },
        }
        episode_texts_by_no = {
            1: "\n".join(
                [
                    '백이현이 말했다. "나는 여기서 물러서지 않을 거야, 네 선택을 다시 확인해."',
                    '백이현이 낮게 물었다. "그 말이 사실이라면 지금 당장 증거를 보여 줘."',
                    '백이현은 고개를 저으며 말했다. "아직 끝난 게 아니야, 내가 직접 확인하겠어."',
                ]
            ),
            2: "\n".join(
                [
                    '백이현이 숨을 고르며 답했다. "겁먹을 시간은 없어, 먼저 사람들을 빼내."',
                    '백이현이 검을 세우며 말했다. "네가 막는다면 나도 돌아가지 않겠어."',
                    '백이현이 짧게 웃었다. "좋아, 이번엔 네 방식대로 움직여 보자."',
                ]
            ),
            3: "\n".join(
                [
                    '백이현이 문서를 접으며 말했다. "이 기록은 내가 맡을게, 누구에게도 넘기지 마."',
                    '백이현이 뒤돌아서며 말했다. "따라오지 마, 여기서부터는 내가 정리한다."',
                    '백이현이 조용히 말했다. "약속은 지킬 거야, 대신 너도 물러서지 마."',
                ]
            ),
        }

        quality = module.build_direct_voice_evidence_quality(target, episode_texts_by_no)

        self.assertEqual(quality["status"], "strict_dialogue_ready")
        self.assertTrue(quality["strict_chat_ready"])
        self.assertEqual(quality["dialogue"]["item_count"], 9)
        self.assertEqual(quality["dialogue"]["episode_count"], 3)
        self.assertGreaterEqual(quality["dialogue"]["example_count"], 3)
        self.assertLessEqual(quality["dialogue"]["max_episode_share"], 0.60)

    def test_direct_voice_quality_excludes_generic_display_label(self):
        module = load_module()
        target = {
            "display_name": "형",
            "aliases": ["형"],
            "collection_rules": {"speaker_anchors": ["형"]},
        }

        quality = module.build_direct_voice_evidence_quality(
            target,
            {
                1: '형이 말했다. "지금은 움직이면 안 돼."',
                2: '형이 답했다. "내가 먼저 확인하고 올게."',
                3: '형이 물었다. "너는 여기 남을 수 있겠어?"',
            },
        )

        self.assertEqual(quality["status"], "excluded_generic_label")
        self.assertFalse(quality["strict_chat_ready"])

    def test_dialogue_attribution_rejects_addressee_as_speaker(self):
        module = load_module()
        text = '철수가 백이현에게 말했다. "지금은 도망쳐야 해."'
        baek_target = {
            "display_name": "백이현",
            "aliases": ["백이현"],
            "collection_rules": {"speaker_anchors": ["백이현"]},
        }
        cheol_target = {
            "display_name": "철수",
            "aliases": ["철수"],
            "collection_rules": {"speaker_anchors": ["철수"]},
        }

        self.assertEqual(module.collect_rule_based_rp_dialogue_items(baek_target, text), [])
        self.assertEqual(len(module.collect_rule_based_rp_dialogue_items(cheol_target, text)), 1)

    def test_dialogue_attribution_does_not_use_next_line_as_speaker(self):
        module = load_module()
        text = "\n".join(
            [
                "철수가 말했다.",
                '"지금은 도망쳐야 해."',
                "백이현이 고개를 끄덕였다.",
            ]
        )
        baek_target = {
            "display_name": "백이현",
            "aliases": ["백이현"],
            "collection_rules": {"speaker_anchors": ["백이현"]},
        }
        cheol_target = {
            "display_name": "철수",
            "aliases": ["철수"],
            "collection_rules": {"speaker_anchors": ["철수"]},
        }

        self.assertEqual(module.collect_rule_based_rp_dialogue_items(baek_target, text), [])
        self.assertEqual(len(module.collect_rule_based_rp_dialogue_items(cheol_target, text)), 1)

    def test_dialogue_attribution_rejects_competing_speaker_match(self):
        module = load_module()
        text = '백이현이 말했다. 영희가 대답했다. "같이 가자."'
        target = {
            "display_name": "백이현",
            "aliases": ["백이현"],
            "collection_rules": {
                "speaker_anchors": ["백이현"],
                "competing_speaker_anchors": ["영희"],
            },
        }

        self.assertEqual(module.collect_rule_based_rp_dialogue_items(target, text), [])

    def test_direct_voice_quality_does_not_count_unanchored_first_person_quotes(self):
        module = load_module()
        target = {
            "display_name": "백이현",
            "aliases": ["백이현"],
            "is_protagonist": True,
            "is_first_person": True,
            "collection_rules": {
                "use_dialogue": True,
                "use_monologue": True,
                "speaker_anchors": ["백이현"],
            },
        }
        episode_texts_by_no = {
            1: "\n".join(
                [
                    '상대가 말했다. "나는 여기서 물러서지 않을 거야, 네 선택을 다시 확인해."',
                    '상대가 낮게 물었다. "그 말이 사실이라면 지금 당장 증거를 보여 줘."',
                    '상대는 고개를 저었다. "아직 끝난 게 아니야, 내가 직접 확인하겠어."',
                ]
            ),
            2: "\n".join(
                [
                    '상대가 숨을 고르며 답했다. "겁먹을 시간은 없어, 먼저 사람들을 빼내."',
                    '상대가 검을 세웠다. "네가 막는다면 나도 돌아가지 않겠어."',
                    '상대가 짧게 웃었다. "좋아, 이번엔 네 방식대로 움직여 보자."',
                ]
            ),
            3: "\n".join(
                [
                    '상대가 문서를 접었다. "이 기록은 내가 맡을게, 누구에게도 넘기지 마."',
                    '상대가 뒤돌아섰다. "따라오지 마, 여기서부터는 내가 정리한다."',
                    '상대가 조용히 말했다. "약속은 지킬 거야, 대신 너도 물러서지 마."',
                ]
            ),
        }

        quality = module.build_direct_voice_evidence_quality(target, episode_texts_by_no)

        self.assertEqual(quality["status"], "insufficient")
        self.assertFalse(quality["strict_chat_ready"])
        self.assertEqual(quality["dialogue"]["item_count"], 0)
        self.assertEqual(quality["monologue"]["item_count"], 0)

    def test_first_person_collection_does_not_collect_all_unattributed_quotes(self):
        module = load_module()
        target = {
            "display_name": "백이현",
            "aliases": ["백이현"],
            "is_protagonist": True,
            "is_first_person": True,
            "collection_rules": {
                "use_dialogue": True,
                "use_monologue": True,
                "speaker_anchors": ["백이현"],
            },
        }
        text = "\n".join(
            [
                '상대가 말했다. "나는 여기서 물러서지 않을 거야."',
                '백이현이 말했다. "나는 직접 확인하겠어."',
            ]
        )

        items = module.collect_rule_based_rp_dialogue_items(target, text)

        self.assertEqual([item["text"] for item in items], ["나는 직접 확인하겠어."])

    def test_inventory_rp_targets_exclude_generic_identity_labels(self):
        module = load_module()
        targets = module.build_inventory_rp_targets(
            {
                "character:형": {
                    "canonical_character_key": "character:형",
                    "display_name": "형",
                    "aliases": ["형"],
                    "is_protagonist": True,
                    "distinct_episode_count": 10,
                    "voice_evidence_count": 10,
                },
                "character:백이현": {
                    "canonical_character_key": "character:백이현",
                    "display_name": "백이현",
                    "aliases": ["백이현"],
                    "is_protagonist": True,
                    "distinct_episode_count": 10,
                    "voice_evidence_count": 10,
                },
            }
        )

        self.assertEqual([target["character_key"] for target in targets], ["character:백이현"])

    def test_direct_voice_quality_accepts_distributed_first_person_monologue(self):
        module = load_module()
        target = {
            "display_name": "백이현",
            "aliases": ["백이현"],
            "is_protagonist": True,
            "is_first_person": True,
            "collection_rules": {
                "use_dialogue": True,
                "use_monologue": True,
                "speaker_anchors": ["백이현"],
            },
        }
        episode_texts_by_no = {
            1: "\n".join(
                [
                    "나는 아직 이 싸움의 끝을 보지 못했다. 물러서면 모두가 같은 함정에 빠질 것이다. 그래서 먼저 발을 옮겼다.",
                    "내가 먼저 움직여야 한다고 판단했다. 누군가를 기다리기에는 시간이 너무 적었다. 망설이면 늦는다.",
                ]
            ),
            2: "\n".join(
                [
                    "난 그들의 침묵이 더 위험하다고 느꼈다. 말하지 않는 쪽이 늘 더 많은 것을 숨겼다. 그래서 더 파고들었다.",
                    "내게 남은 선택지는 많지 않았다. 그래도 여기서 멈추면 아무것도 지킬 수 없었다. 끝까지 확인해야 했다.",
                ]
            ),
            3: "\n".join(
                [
                    "내 마음은 이미 답을 알고 있었다. 겁이 나도 뒤로 물러설 수는 없었다. 그게 내가 택한 길이었다.",
                    "내 판단이 틀렸다면 책임도 내가 져야 한다. 그래서 마지막 문을 직접 열었다. 누구에게도 미룰 수 없었다.",
                ]
            ),
        }

        quality = module.build_direct_voice_evidence_quality(target, episode_texts_by_no)

        self.assertEqual(quality["status"], "strict_monologue_ready")
        self.assertTrue(quality["strict_chat_ready"])
        self.assertEqual(quality["monologue"]["item_count"], 6)
        self.assertEqual(quality["monologue"]["episode_count"], 3)
        self.assertGreaterEqual(quality["monologue"]["total_chars"], 300)

    def test_delta_rp_refresh_is_opt_in_cli_flag(self):
        module = load_module()

        with patch.object(sys, "argv", ["build_story_agent_context.py", "--build-mode", "delta", "--product-id", "687"]):
            args = module.parse_args()
        self.assertFalse(args.refresh_rp)
        self.assertFalse(module.should_refresh_delta_rp(args))

        with patch.object(
            sys,
            "argv",
            [
                "build_story_agent_context.py",
                "--build-mode",
                "delta",
                "--product-id",
                "687",
                "--refresh-rp",
            ],
        ):
            args = module.parse_args()
        self.assertTrue(args.refresh_rp)
        self.assertTrue(module.should_refresh_delta_rp(args))

    def test_delta_cli_accepts_max_delta_episode_cap(self):
        module = load_module()

        with patch.object(
            sys,
            "argv",
            [
                "build_story_agent_context.py",
                "--build-mode",
                "delta",
                "--product-id",
                "687",
                "--max-delta-episodes",
                "5",
            ],
        ):
            args = module.parse_args()

        self.assertEqual(args.max_delta_episodes, 5)

    def test_target_queries_include_paid_ongoing_products(self):
        module = load_module()

        args = SimpleNamespace(product_ids=[], episode_ids=[], episode_nos=[], limit=0)
        query, params = module.build_target_query(args=args, use_epub_fallback=False)

        self.assertEqual(params, [])
        self.assertIn("p.price_type IN ('free', 'paid')", query)
        self.assertIn("p.status_code = 'ongoing'", query)
        self.assertIn("pe.open_yn = 'Y'", query)
        self.assertNotIn("p.price_type = 'free'", query)

    def test_total_episode_count_matches_paid_ongoing_scope(self):
        module = load_module()

        class FakeCursor:
            def __init__(self):
                self.query = ""
                self.params = None

            def execute(self, query, params):
                self.query = query
                self.params = params

            def fetchone(self):
                return {"total_episode_count": 7}

        cur = FakeCursor()
        count = module.fetch_total_episode_count(cur, product_id=1101)

        self.assertEqual(count, 7)
        self.assertEqual(cur.params, (1101,))
        self.assertIn("p.price_type IN ('free', 'paid')", cur.query)
        self.assertIn("p.status_code = 'ongoing'", cur.query)
        self.assertNotIn("p.price_type = 'free'", cur.query)


class StoryAgentCharacterInventoryV3Test(TestCase):
    def test_inventory_v3_merges_named_and_protagonist_prefix_for_same_character(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:란",
                        display_name="란",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="named:란",
                        display_name="란",
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
            signal_row(
                3,
                3,
                [
                    signal_character(
                        character_key="protagonist:named:란",
                        display_name="란",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(len(inventory), 1)
        character = inventory[0]
        self.assertEqual(character["display_name"], "란")
        self.assertEqual(set(character["source_character_keys"]), {"named:란", "protagonist:named:란"})
        self.assertEqual(character["distinct_episode_count"], 3)
        self.assertEqual(character["episode_focal_evidence"]["episode_count"], 2)
        self.assertEqual(character["work_role"], "main_protagonist")
        self.assertTrue(character["is_protagonist"])
        self.assertEqual(character["protagonist_confidence"], "high")
        self.assertEqual(character["classification_status"], "AUTO_RESOLVED")
        self.assertEqual(character["rp_signal_quality"]["status"], "summary_ready")
        self.assertEqual(character["rp_signal_quality"]["evidence_source"], "episode_summary_voice_mode")
        self.assertFalse(character["rp_signal_quality"]["strict_chat_ready"])
        self.assertFalse(character["rp_signal_quality"]["needs_review"])

    def test_episode_character_signal_normalization_preserves_names_and_strict_booleans(self):
        module = load_module()
        payload = {
            "episode_no": 1,
            "mentioned_characters": [
                {
                    "display_name": "성아",
                    "aliases": ["성아", "소야"],
                    "is_protagonist": "false",
                    "is_first_person": "true",
                    "entity_kind": "person",
                    "scene_weight": "high",
                    "role_in_episode": "lead",
                    "voice_mode": "dialogue",
                    "action_tags": [],
                    "affect_tags": [],
                    "relation_edges": [],
                    "identity_claims": [
                        {
                            "target_label": "소야",
                            "claim_type": "alias_of",
                            "evidence": "성아는 소야로도 불린다",
                        }
                    ],
                }
            ],
            "cliffhanger_hooks": [],
        }

        normalized = module.normalize_episode_character_signals_payload(payload, episode_no=1)
        character = normalized["mentioned_characters"][0]

        self.assertEqual(module.normalize_signal_entity_label("성아"), "성아")
        self.assertEqual(module.normalize_signal_entity_label("소야"), "소야")
        self.assertEqual(character["character_key"], "named:성아")
        self.assertFalse(character["is_protagonist"])
        self.assertFalse(character["is_work_protagonist"])
        self.assertFalse(character["is_episode_focal"])
        self.assertFalse(character["is_first_person"])
        self.assertEqual(
            character["identity_claims"],
            [
                {
                    "target_label": "소야",
                    "target_key": "named:성아",
                    "normalized_target_label": "소야",
                    "claim_type": "alias_of",
                    "evidence": "성아는 소야로도 불린다",
                }
            ],
        )

    def test_episode_character_signal_normalize_splits_work_protagonist_from_episode_focal(self):
        module = load_module()
        payload = {
            "episode_no": 2,
            "mentioned_characters": [
                {
                    "display_name": "조연",
                    "aliases": ["조연"],
                    "is_protagonist": False,
                    "is_work_protagonist": False,
                    "is_episode_focal": True,
                    "is_first_person": False,
                    "narration_names": ["조연"],
                    "social_call_names": ["조연님"],
                    "persona_names": [],
                    "real_names": [],
                    "entity_kind": "person",
                    "scene_weight": "high",
                    "role_in_episode": "lead",
                    "voice_mode": "dialogue",
                    "action_tags": [],
                    "affect_tags": [],
                    "relation_edges": [],
                    "identity_claims": [],
                }
            ],
            "cliffhanger_hooks": [],
        }

        normalized = module.normalize_episode_character_signals_payload(payload, episode_no=2)
        character = normalized["mentioned_characters"][0]

        self.assertFalse(character["is_protagonist"])
        self.assertFalse(character["is_work_protagonist"])
        self.assertTrue(character["is_episode_focal"])
        self.assertEqual(character["character_key"], "named:조연")
        self.assertEqual(character["narration_names"], ["조연"])
        self.assertEqual(character["social_call_names"], ["조연님"])

    def test_inventory_v3_marks_dominant_long_running_top_character_as_protagonist(self):
        module = load_module()
        rows = []
        for episode_no in range(1, 51):
            characters = [
                signal_character(
                    character_key="protagonist:named:존" if episode_no <= 12 else "named:존",
                    display_name="존",
                    is_protagonist=episode_no <= 12,
                    role_in_episode="lead" if episode_no <= 30 else "support",
                    voice_mode="dialogue" if episode_no <= 30 else "narration_only",
                    scene_weight="high" if episode_no <= 30 else "medium",
                )
            ]
            if episode_no <= 16:
                characters.append(
                    signal_character(
                        character_key="named:요한",
                        display_name="요한",
                        role_in_episode="support",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                )
            rows.append(signal_row(episode_no, episode_no, characters))

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(inventory[0]["display_name"], "존")
        self.assertGreaterEqual(inventory[0]["protagonist_evidence"]["score"], 0.40)
        self.assertLess(inventory[0]["protagonist_evidence"]["score"], 0.50)
        self.assertEqual(inventory[0]["work_role"], "main_protagonist")
        self.assertTrue(inventory[0]["is_protagonist"])

    def test_inventory_v3_does_not_attach_generic_first_person_to_top_named_candidate(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:first_person",
                        display_name="나",
                        aliases=["나"],
                        is_protagonist=True,
                        is_first_person=True,
                        role_in_episode="lead",
                        voice_mode="monologue",
                        scene_weight="high",
                    ),
                    signal_character(
                        character_key="named:백이현",
                        display_name="백이현",
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="named:백이현",
                        display_name="백이현",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        by_display_name = {row["display_name"]: row for row in inventory}

        self.assertIn("나", by_display_name)
        self.assertIn("백이현", by_display_name)
        self.assertEqual(by_display_name["나"]["source_character_keys"], ["protagonist:first_person"])
        self.assertEqual(by_display_name["나"]["identity_status"], "UNRESOLVED")
        self.assertIn("unresolved_generic_first_person", by_display_name["나"]["identity_conflict_reasons"])
        self.assertFalse(by_display_name["나"]["is_protagonist"])
        self.assertEqual(by_display_name["나"]["protagonist_confidence"], "low")
        self.assertEqual(by_display_name["백이현"]["source_character_keys"], ["named:백이현"])

    def test_inventory_v3_keeps_related_named_characters_split(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:모어",
                        display_name="모어",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                        relation_edges=[
                            {
                                "target_key": "named:란",
                                "target_label": "란",
                                "relation_tag": "대립",
                                "direction": "to_target",
                            }
                        ],
                    ),
                    signal_character(
                        character_key="named:란",
                        display_name="란",
                        role_in_episode="counterpart",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                ],
            )
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertIn({"protagonist:named:모어"}, source_sets)
        self.assertIn({"named:란"}, source_sets)
        self.assertNotIn({"protagonist:named:모어", "named:란"}, source_sets)
        self.assertTrue(all(row["identity_status"] != "CONFLICT" for row in inventory))
        self.assertTrue(all(row["identity_conflict_reasons"] == [] for row in inventory))

    def test_inventory_v3_canonical_key_uses_resolved_display_name_not_short_alias(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:반아슬란",
                        display_name="반 아슬란",
                        aliases=["반 아슬란", "반"],
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                        identity_claims=[
                            {
                                "target_label": "반",
                                "claim_type": "alias_of",
                                "evidence": "반 아슬란은 반으로도 불린다",
                            }
                        ],
                    )
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="named:반",
                        display_name="반",
                        aliases=["반"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
            signal_row(
                3,
                3,
                [
                    signal_character(
                        character_key="named:반",
                        display_name="반",
                        aliases=["반"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(inventory[0]["display_name"], "반 아슬란")
        self.assertEqual(inventory[0]["canonical_character_key"], "character:반아슬란")

    def test_inventory_v3_merges_focal_full_name_and_short_name_variants(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:남기준",
                        display_name="남기준",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="protagonist:named:기준",
                        display_name="기준",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
            signal_row(
                3,
                3,
                [
                    signal_character(
                        character_key="protagonist:named:기준",
                        display_name="기준",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        main_rows = [row for row in inventory if row["work_role"] == "main_protagonist"]
        self.assertEqual(len(main_rows), 1)
        self.assertEqual(main_rows[0]["display_name"], "남기준")
        self.assertEqual(main_rows[0]["canonical_character_key"], "character:남기준")
        self.assertEqual(
            set(main_rows[0]["source_character_keys"]),
            {"protagonist:named:남기준", "protagonist:named:기준"},
        )
        self.assertEqual(main_rows[0]["episode_focal_evidence"]["episode_count"], 3)

    def test_inventory_v3_does_not_merge_name_variants_when_same_episode_cannot_linked(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:한도윤",
                        display_name="한도윤",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                        relation_edges=[
                            {
                                "target_key": "named:도윤",
                                "target_label": "도윤",
                                "relation_tag": "대립",
                                "direction": "to_target",
                            }
                        ],
                    ),
                    signal_character(
                        character_key="named:도윤",
                        display_name="도윤",
                        is_protagonist=True,
                        role_in_episode="counterpart",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="protagonist:named:한도윤",
                        display_name="한도윤",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertIn({"protagonist:named:한도윤"}, source_sets)
        self.assertIn({"named:도윤"}, source_sets)
        self.assertNotIn({"protagonist:named:한도윤", "named:도윤"}, source_sets)

    def test_inventory_v3_does_not_hard_merge_avatar_identity_claim(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="named:조렌테이머",
                        display_name="조렌 테이머",
                        aliases=["조렌 테이머", "조렌"],
                        role_in_episode="counterpart",
                        voice_mode="dialogue",
                        scene_weight="medium",
                    ),
                    signal_character(
                        character_key="protagonist:named:방호영",
                        display_name="방호영",
                        aliases=["방호영", "호영"],
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="narration_only",
                        scene_weight="high",
                    ),
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="protagonist:named:호영",
                        display_name="호영",
                        aliases=["호영", "조렌 테이머", "수호자"],
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                        identity_claims=[
                            {
                                "target_label": "조렌 테이머",
                                "claim_type": "avatar_name_of",
                                "evidence": "호영이 게임 속에서 조렌 테이머로 불린다",
                            }
                        ],
                    )
                ],
            ),
            signal_row(
                3,
                3,
                [
                    signal_character(
                        character_key="protagonist:named:조렌테이머",
                        display_name="조렌 테이머",
                        aliases=["조렌 테이머", "변방백"],
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                        relation_edges=[
                            {
                                "target_key": "named:호영",
                                "target_label": "호영",
                                "relation_tag": "동행",
                                "direction": "mutual",
                            }
                        ],
                    ),
                    signal_character(
                        character_key="named:호영",
                        display_name="호영",
                        aliases=["호영"],
                        role_in_episode="support",
                        voice_mode="dialogue",
                        scene_weight="medium",
                    ),
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertTrue(
            any(
                {"protagonist:named:방호영", "protagonist:named:호영", "named:호영"} <= source_set
                for source_set in source_sets
            )
        )
        self.assertTrue(
            any(
                {"named:조렌테이머", "protagonist:named:조렌테이머"} <= source_set
                for source_set in source_sets
            )
        )
        self.assertFalse(
            any(
                {
                    "named:조렌테이머",
                    "named:호영",
                    "protagonist:named:방호영",
                    "protagonist:named:조렌테이머",
                    "protagonist:named:호영",
                } <= source_set
                for source_set in source_sets
            )
        )

    def test_inventory_v3_social_persona_name_wins_chat_display_without_changing_identity_seed(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:호영",
                        display_name="호영",
                        aliases=["방호영", "호영"],
                        is_protagonist=True,
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        narration_names=["호영"],
                        social_call_names=["조렌 테이머"],
                        persona_names=["조렌 테이머"],
                        real_names=["방호영"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                        identity_claims=[
                            {
                                "target_label": "조렌 테이머",
                                "claim_type": "avatar_name_of",
                                "evidence": "호영은 이 세계에서 조렌 테이머로 불린다",
                            }
                        ],
                    )
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="protagonist:named:호영",
                        display_name="호영",
                        aliases=["호영"],
                        is_protagonist=True,
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        narration_names=["호영"],
                        social_call_names=["조렌 테이머"],
                        persona_names=["조렌 테이머"],
                        real_names=["방호영"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        main_rows = [row for row in inventory if row["work_role"] == "main_protagonist"]

        self.assertEqual(len(main_rows), 1)
        self.assertEqual(main_rows[0]["display_name"], "조렌 테이머")
        self.assertEqual(main_rows[0]["display_name_source"], "social_call_names")
        self.assertEqual(main_rows[0]["canonical_character_key"], "character:호영")
        self.assertEqual(main_rows[0]["social_call_names"], ["조렌 테이머"])
        self.assertEqual(main_rows[0]["persona_names"], ["조렌 테이머"])
        self.assertEqual(main_rows[0]["real_names"], ["방호영"])
        self.assertIn("호영", main_rows[0]["aliases"])

    def test_inventory_v3_social_role_call_does_not_replace_resolved_real_name_display(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="protagonist:named:백이현",
                        display_name="백이현",
                        aliases=["백이현"],
                        is_protagonist=True,
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        narration_names=["백이현", "이현"],
                        social_call_names=["영웅"],
                        persona_names=["백이현", "영웅"],
                        real_names=["백이현"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        main_rows = [row for row in inventory if row["work_role"] == "main_protagonist"]

        self.assertEqual(len(main_rows), 1)
        self.assertEqual(main_rows[0]["canonical_character_key"], "character:백이현")
        self.assertEqual(main_rows[0]["display_name"], "백이현")
        self.assertNotEqual(main_rows[0]["display_name"], "영웅")
        self.assertEqual(main_rows[0]["display_safety"], {"status": "pass", "reason": "resolved_named_identity"})
        self.assertTrue(main_rows[0]["public_chat_eligible"])
        self.assertTrue(main_rows[0]["public_slot_eligible"])

    def test_inventory_v3_social_role_call_does_not_replace_identity_display_without_claim(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="protagonist:named:산군",
                        display_name="산군",
                        aliases=["산군"],
                        is_protagonist=True,
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        narration_names=["산군", "대전사"],
                        social_call_names=["대전사"],
                        persona_names=["산군", "대전사"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        main_rows = [row for row in inventory if row["work_role"] == "main_protagonist"]

        self.assertEqual(len(main_rows), 1)
        self.assertEqual(main_rows[0]["canonical_character_key"], "character:산군")
        self.assertEqual(main_rows[0]["display_name"], "산군")
        self.assertNotEqual(main_rows[0]["display_name"], "대전사")
        self.assertTrue(main_rows[0]["public_chat_eligible"])

    def test_inventory_v3_contextual_social_call_does_not_replace_identity_display_name(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="protagonist:named:전귀",
                        display_name="전귀",
                        is_protagonist=True,
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        narration_names=["전귀"],
                        social_call_names=["재미있는 놈"],
                        persona_names=["전귀"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        main_rows = [row for row in inventory if row["work_role"] == "main_protagonist"]

        self.assertEqual(len(main_rows), 1)
        self.assertEqual(main_rows[0]["display_name"], "전귀")
        self.assertEqual(main_rows[0]["display_name_source"], "persona_names")
        self.assertIn("재미있는 놈", main_rows[0]["social_call_names"])

    def test_inventory_v3_non_blocking_identity_conflicts_do_not_block_clear_main(self):
        module = load_module()
        rows = [
            {
                "display_name": "이시혁",
                "identity_status": "CONFLICT",
                "identity_conflict_reasons": ["unresolved_generic_first_person", "duplicate_canonical_key"],
                "is_generic_display_name": False,
                "distinct_episode_count": 8,
                "work_protagonist_evidence": {"episode_count": 8},
                "episode_focal_evidence": {"episode_count": 8},
                "first_person_evidence": {"episode_count": 2},
                "episode_role_counts": {"lead": 8},
                "scene_weight_counts": {"high": 8},
                "voice_mode_counts": {"dialogue": 8},
            },
            {
                "display_name": "조연",
                "identity_status": "RESOLVED_NAMED",
                "identity_conflict_reasons": [],
                "is_generic_display_name": False,
                "distinct_episode_count": 3,
                "work_protagonist_evidence": {"episode_count": 1},
                "episode_focal_evidence": {"episode_count": 1},
                "first_person_evidence": {"episode_count": 0},
                "episode_role_counts": {"lead": 1},
                "scene_weight_counts": {"high": 1},
                "voice_mode_counts": {"dialogue": 1},
            },
        ]

        module._classify_character_inventory_v3_rows(rows, total_signal_episodes=8)

        self.assertEqual(rows[0]["work_role"], "main_protagonist")
        self.assertEqual(rows[0]["classification_status"], "AUTO_RESOLVED")
        self.assertEqual(rows[0]["review_reasons"], [])
        self.assertEqual(rows[0]["rp_signal_quality"]["status"], "summary_ready")
        self.assertEqual(rows[0]["display_safety"], {"status": "pass", "reason": "resolved_named_identity"})
        self.assertTrue(rows[0]["public_chat_eligible"])

    def test_inventory_v3_episode_focal_non_protagonist_does_not_beat_work_protagonist(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="named:회차주역",
                        display_name="회차주역",
                        is_protagonist=False,
                        is_work_protagonist=False,
                        is_episode_focal=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                    signal_character(
                        character_key="protagonist:named:주인공명",
                        display_name="주인공명",
                        is_protagonist=True,
                        is_work_protagonist=True,
                        is_episode_focal=False,
                        is_first_person=True,
                        role_in_episode="support",
                        voice_mode="monologue",
                        scene_weight="medium",
                    ),
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="named:회차주역",
                        display_name="회차주역",
                        is_protagonist=False,
                        is_work_protagonist=False,
                        is_episode_focal=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                    signal_character(
                        character_key="protagonist:named:주인공명",
                        display_name="주인공명",
                        is_protagonist=True,
                        is_work_protagonist=True,
                        is_episode_focal=False,
                        is_first_person=True,
                        role_in_episode="support",
                        voice_mode="monologue",
                        scene_weight="medium",
                    ),
                ],
            ),
            signal_row(
                3,
                3,
                [
                    signal_character(
                        character_key="named:회차주역",
                        display_name="회차주역",
                        is_protagonist=False,
                        is_work_protagonist=False,
                        is_episode_focal=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        main_rows = [row for row in inventory if row["work_role"] == "main_protagonist"]

        self.assertEqual(len(main_rows), 1)
        self.assertEqual(main_rows[0]["display_name"], "주인공명")
        self.assertEqual(main_rows[0]["work_protagonist_evidence"]["episode_count"], 2)
        self.assertNotEqual(main_rows[0]["display_name"], "회차주역")

    def test_inventory_v3_does_not_merge_avatar_alias_without_identity_claim(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:호영",
                        display_name="호영",
                        aliases=["호영", "조렌 테이머"],
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                    signal_character(
                        character_key="named:조렌테이머",
                        display_name="조렌 테이머",
                        aliases=["조렌 테이머"],
                        role_in_episode="counterpart",
                        voice_mode="dialogue",
                        scene_weight="medium",
                    ),
                ],
            )
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertIn({"protagonist:named:호영"}, source_sets)
        self.assertIn({"named:조렌테이머"}, source_sets)
        self.assertNotIn({"protagonist:named:호영", "named:조렌테이머"}, source_sets)

    def test_inventory_v3_does_not_merge_substring_role_like_label_without_identity_claim(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:우미",
                        display_name="우미",
                        aliases=["우미", "도우미"],
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                    signal_character(
                        character_key="named:도우미",
                        display_name="도우미",
                        aliases=["도우미"],
                        role_in_episode="support",
                        voice_mode="dialogue",
                        scene_weight="medium",
                    ),
                ],
            )
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertIn({"protagonist:named:우미"}, source_sets)
        self.assertIn({"named:도우미"}, source_sets)
        self.assertNotIn({"protagonist:named:우미", "named:도우미"}, source_sets)

    def test_inventory_v3_title_claim_never_creates_identity_bridge(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="named:펜데",
                        display_name="펜데",
                        aliases=["펜데"],
                        identity_claims=[
                            {
                                "target_label": "영주권 소지자",
                                "claim_type": "title_of",
                                "evidence": "펜데가 자신은 영주권 소지자라고 말했다",
                            }
                        ],
                    ),
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="named:영주권소지자",
                        display_name="영주권 소지자",
                        aliases=["영주권 소지자"],
                    ),
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertIn({"named:펜데"}, source_sets)
        self.assertIn({"named:영주권소지자"}, source_sets)
        self.assertNotIn({"named:펜데", "named:영주권소지자"}, source_sets)

    def test_inventory_v3_relation_phrase_claim_never_creates_identity_bridge(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="named:아셔",
                        display_name="아셔",
                        aliases=["아셔"],
                        identity_claims=[
                            {
                                "target_label": "이안의 아이",
                                "claim_type": "same_person_as",
                                "evidence": "황제가 이 아이는 이안의 아이이다라고 말했다",
                            }
                        ],
                    ),
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="named:이안의아이",
                        display_name="이안의 아이",
                        aliases=["이안의 아이"],
                    ),
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertIn({"named:아셔"}, source_sets)
        self.assertIn({"named:이안의아이"}, source_sets)
        self.assertNotIn({"named:아셔", "named:이안의아이"}, source_sets)

    def test_inventory_v3_real_name_variant_claim_merges_when_unconflicted(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="named:현태",
                        display_name="현태",
                        aliases=["현태"],
                        identity_claims=[
                            {
                                "target_label": "서현태",
                                "claim_type": "real_name_of",
                                "evidence": "현태의 풀네임이 서현태로 언급됨",
                            }
                        ],
                    ),
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="named:서현태",
                        display_name="서현태",
                        aliases=["서현태"],
                    ),
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertIn({"named:현태", "named:서현태"}, source_sets)

    def test_inventory_v3_non_variant_real_name_claim_does_not_merge(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="named:발리우스",
                        display_name="발리우스",
                        aliases=["발리우스"],
                        identity_claims=[
                            {
                                "target_label": "노이티에",
                                "claim_type": "real_name_of",
                                "evidence": "수신인 노이티에가 자신의 친아버지임을 알았다",
                            }
                        ],
                    ),
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="named:노이티에",
                        display_name="노이티에",
                        aliases=["노이티에"],
                    ),
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertIn({"named:발리우스"}, source_sets)
        self.assertIn({"named:노이티에"}, source_sets)
        self.assertNotIn({"named:발리우스", "named:노이티에"}, source_sets)

    def test_inventory_v3_name_with_ui_syllable_is_not_treated_as_possessive_phrase(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="named:백의",
                        display_name="백의",
                        aliases=["백의"],
                        identity_claims=[
                            {
                                "target_label": "백의검",
                                "claim_type": "codename_of",
                                "evidence": "백의가 백의검이라는 별호로도 불린다",
                            }
                        ],
                    ),
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="named:백의검",
                        display_name="백의검",
                        aliases=["백의검"],
                    ),
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertIn({"named:백의", "named:백의검"}, source_sets)

    def test_inventory_v3_display_name_prefers_non_generic_alias_identity(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:first_person",
                        display_name="나",
                        aliases=["유아"],
                        is_protagonist=True,
                        is_first_person=True,
                        role_in_episode="lead",
                        voice_mode="monologue",
                        scene_weight="high",
                    )
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="named:유아",
                        display_name="유아",
                        aliases=["유아"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(inventory[0]["display_name"], "유아")
        self.assertEqual(inventory[0]["canonical_character_key"], "character:유아")

    def test_inventory_v3_duplicate_canonical_keys_are_conflicted_and_suffixed(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="named:설총:a",
                        display_name="설총",
                        aliases=["설총"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                        relation_edges=[
                            {
                                "target_key": "named:설총:b",
                                "target_label": "설총",
                                "relation_tag": "대립",
                                "direction": "to_target",
                            }
                        ],
                    ),
                    signal_character(
                        character_key="named:설총:b",
                        display_name="설총",
                        aliases=["설총"],
                        role_in_episode="counterpart",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                ],
            )
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        keys = [row["canonical_character_key"] for row in inventory]

        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(key.startswith("character:설총:dup:") for key in keys))
        self.assertTrue(all(row["identity_status"] == "CONFLICT" for row in inventory))
        self.assertTrue(all("duplicate_canonical_key" in row["identity_conflict_reasons"] for row in inventory))

    def test_inventory_v3_does_not_bridge_cannot_linked_characters_through_aliases(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:설총",
                        display_name="설총",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                    signal_character(
                        character_key="named:득구",
                        display_name="득구",
                        role_in_episode="counterpart",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="named:별칭혼합",
                        display_name="별칭혼합",
                        aliases=["설총", "득구"],
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
            signal_row(
                3,
                3,
                [
                    signal_character(
                        character_key="protagonist:named:설총",
                        display_name="설총",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertNotIn({"protagonist:named:설총", "named:득구", "named:별칭혼합"}, source_sets)
        self.assertTrue(all(not ({"protagonist:named:설총", "named:득구"} <= set(row["source_character_keys"])) for row in inventory))
        self.assertTrue(all("AMBIGUOUS_ALIAS_BRIDGE" not in row["identity_conflict_reasons"] for row in inventory))

    def test_inventory_v3_marks_ambiguous_top_candidates_for_review(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:설총",
                        display_name="설총",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="protagonist:named:설총",
                        display_name="설총",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
            signal_row(
                3,
                3,
                [
                    signal_character(
                        character_key="protagonist:named:득구",
                        display_name="득구",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
            signal_row(
                4,
                4,
                [
                    signal_character(
                        character_key="protagonist:named:득구",
                        display_name="득구",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual([row for row in inventory if row["work_role"] == "main_protagonist"], [])
        top_rows = [row for row in inventory if row["protagonist_evidence"]["rank"] <= 2]
        self.assertEqual(len(top_rows), 2)
        self.assertTrue(all("AMBIGUOUS_TOP_CANDIDATES" in row["review_reasons"] for row in top_rows))
        self.assertTrue(all(not row["is_protagonist"] for row in top_rows))
        self.assertTrue(all(row["protagonist_confidence"] == "low" for row in top_rows))
        self.assertTrue(all(row["rp_signal_quality"]["needs_review"] for row in top_rows))

    def test_inventory_v3_public_chat_gate_keeps_stable_role_internal_only(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="named:대전사",
                        display_name="대전사",
                        aliases=["대전사"],
                        entity_kind="stable_role",
                        is_episode_focal=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["identity_status"], "RESOLVED_STABLE_ROLE")
        self.assertEqual(inventory[0]["display_safety"], {"status": "review", "reason": "stable_role_identity"})
        self.assertFalse(inventory[0]["public_chat_eligible"])
        self.assertEqual(
            module.build_inventory_rp_targets({inventory[0]["canonical_character_key"]: inventory[0]}),
            [],
        )

    def test_inventory_v3_public_chat_gate_rejects_ordinal_title_display_name(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="named:제일황자",
                        display_name="제 일 황자",
                        aliases=["제 일 황자"],
                        persona_names=["제 일 황자"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["display_name"], "제 일 황자")
        self.assertEqual(inventory[0]["display_safety"], {"status": "fail", "reason": "role_or_relation_label"})
        self.assertFalse(inventory[0]["public_chat_eligible"])
        self.assertFalse(inventory[0]["public_slot_eligible"])

    def test_inventory_v3_public_chat_gate_rejects_collective_role_display_name(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="named:공작부부",
                        display_name="공작부부",
                        aliases=["공작부부"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["display_name"], "공작부부")
        self.assertEqual(inventory[0]["display_safety"], {"status": "fail", "reason": "role_or_relation_label"})
        self.assertFalse(inventory[0]["public_chat_eligible"])
        self.assertFalse(inventory[0]["public_slot_eligible"])

    def test_inventory_v3_public_chat_gate_rejects_possessive_relation_display_name(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="named:아셔의어머니",
                        display_name="아셔의어머니",
                        aliases=["아셔의 어머니"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["display_safety"], {"status": "fail", "reason": "role_or_relation_label"})
        self.assertFalse(inventory[0]["public_chat_eligible"])
        self.assertFalse(inventory[0]["public_slot_eligible"])

    def test_inventory_v3_public_chat_gate_rejects_descriptor_display_name(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="named:키큰남자",
                        display_name="키큰남자",
                        aliases=["키 큰 남자"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["display_safety"], {"status": "fail", "reason": "role_or_relation_label"})
        self.assertFalse(inventory[0]["public_chat_eligible"])
        self.assertFalse(inventory[0]["public_slot_eligible"])

    def test_inventory_v3_public_chat_gate_keeps_named_title_display_name(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="named:아서교수",
                        display_name="아서 교수",
                        aliases=["아서 교수", "아서"],
                        social_call_names=["아서 교수"],
                        persona_names=["아서 교수"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["display_name"], "아서 교수")
        self.assertEqual(inventory[0]["display_safety"], {"status": "pass", "reason": "resolved_named_identity"})
        self.assertTrue(inventory[0]["public_chat_eligible"])
        self.assertTrue(inventory[0]["public_slot_eligible"])

    def test_inventory_v3_resolves_two_to_one_protagonist_evidence(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:하남재",
                        display_name="하남재",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                    signal_character(
                        character_key="named:퍼틴",
                        display_name="퍼틴",
                        role_in_episode="support",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="protagonist:named:퍼틴",
                        display_name="퍼틴",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                    signal_character(
                        character_key="named:하남재",
                        display_name="하남재",
                        role_in_episode="support",
                        voice_mode="dialogue",
                        scene_weight="medium",
                    ),
                ],
            ),
            signal_row(
                3,
                3,
                [
                    signal_character(
                        character_key="protagonist:named:하남재",
                        display_name="하남재",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                    signal_character(
                        character_key="named:퍼틴",
                        display_name="퍼틴",
                        role_in_episode="support",
                        voice_mode="dialogue",
                        scene_weight="medium",
                    ),
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        main_rows = [row for row in inventory if row["work_role"] == "main_protagonist"]

        self.assertEqual(len(main_rows), 1)
        self.assertEqual(main_rows[0]["display_name"], "하남재")
        self.assertEqual(main_rows[0]["episode_focal_evidence"]["episode_count"], 2)
        self.assertTrue(main_rows[0]["is_protagonist"])
        self.assertEqual(main_rows[0]["protagonist_confidence"], "high")

    def test_inventory_v3_uses_stable_observation_ids_without_summary_id(self):
        module = load_module()
        rows = [
            {
                "episode_id": 101,
                "episode_from": 1,
                "source_hash": "episode-101",
                "summary_text": json.dumps(
                    {
                        "episode_no": 1,
                        "mentioned_characters": [
                            signal_character(character_key="named:클레어", display_name="클레어"),
                            signal_character(
                                character_key="protagonist:named:렌",
                                display_name="렌",
                                is_protagonist=True,
                                role_in_episode="lead",
                                voice_mode="dialogue",
                                scene_weight="high",
                            ),
                        ],
                        "cliffhanger_hooks": [],
                    },
                    ensure_ascii=False,
                ),
            },
            {
                "episode_id": 102,
                "episode_from": 2,
                "source_hash": "episode-102",
                "summary_text": json.dumps(
                    {
                        "episode_no": 2,
                        "mentioned_characters": [
                            signal_character(
                                character_key="protagonist:named:렌",
                                display_name="렌",
                                is_protagonist=True,
                                role_in_episode="lead",
                                voice_mode="dialogue",
                                scene_weight="high",
                            ),
                            signal_character(character_key="named:의사", display_name="의사"),
                        ],
                        "cliffhanger_hooks": [],
                    },
                    ensure_ascii=False,
                ),
            },
            {
                "episode_id": 103,
                "episode_from": 3,
                "source_hash": "episode-103",
                "summary_text": json.dumps(
                    {
                        "episode_no": 3,
                        "mentioned_characters": [
                            signal_character(
                                character_key="protagonist:named:렌",
                                display_name="렌",
                                is_protagonist=True,
                                role_in_episode="lead",
                                voice_mode="dialogue",
                                scene_weight="high",
                            ),
                            signal_character(character_key="named:의사", display_name="의사"),
                        ],
                        "cliffhanger_hooks": [],
                    },
                    ensure_ascii=False,
                ),
            },
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        main_rows = [row for row in inventory if row["work_role"] == "main_protagonist"]

        self.assertEqual(len(main_rows), 1)
        self.assertEqual(main_rows[0]["display_name"], "렌")
        self.assertEqual(main_rows[0]["identity_status"], "RESOLVED_NAMED")
        self.assertNotIn("cannot_link_name_conflict", main_rows[0]["review_reasons"])

    def test_delta_candidate_filter_limits_rows_per_product_by_episode_no(self):
        module = load_module()
        rows = [
            {"product_id": 687, "episode_id": 103, "episode_no": 3},
            {"product_id": 687, "episode_id": 101, "episode_no": 1},
            {"product_id": 687, "episode_id": 102, "episode_no": 2},
            {"product_id": 687, "episode_id": 104, "episode_no": 4},
        ]

        with patch.object(module, "build_open_add_episode_id_set", return_value={101, 102, 103, 104}), \
             patch.object(module, "build_sync_repair_episode_id_set", return_value=set()):
            filtered = module.filter_delta_candidate_rows(object(), rows, max_delta_episodes=2)

        self.assertEqual([row["episode_no"] for row in filtered], [1, 2])
        self.assertEqual([row["_delta_reason"] for row in filtered], ["open_add", "open_add"])

    def test_delta_mode_allows_product_only_apply_for_internal_changed_row_filtering(self):
        module = load_module()
        args = SimpleNamespace(
            build_mode="delta",
            limit=0,
            product_ids=[687],
            episode_ids=None,
            episode_nos=None,
            max_delta_episodes=0,
        )

        module.validate_delta_args(args)

    def test_unchanged_touched_rp_scope_is_not_rebuilt_when_profile_and_examples_exist(self):
        module = load_module()
        signal_row = {
            "summary_id": 10,
            "source_hash": "signal-hash",
            "summary_text": """
            {
              "episode_no": 1,
              "mentioned_characters": [
                {
                  "character_key": "protagonist:named:hero",
                  "display_name": "주인공",
                  "relation_edges": []
                }
              ]
            }
            """,
        }
        inventory = {
            "protagonist:named:hero": {
                "character_key": "protagonist:named:hero",
                "display_name": "주인공",
                "is_protagonist": True,
                "distinct_episode_count": 3,
            }
        }
        profile_map = {"protagonist:named:hero": {"source_hash": "profile-hash"}}
        examples_map = {"protagonist:named:hero": {"source_hash": "examples-hash"}}

        affected = module.compute_rp_affected_scope_keys(
            old_inventory_map=inventory,
            new_inventory_map=inventory,
            old_relation_map={},
            new_relation_map={},
            old_touched_signal_rows=[signal_row],
            new_touched_signal_rows=[signal_row],
            old_profile_map=profile_map,
            old_examples_map=examples_map,
        )

        self.assertEqual(affected, set())

    def test_missing_rp_outputs_are_rebuilt_even_when_inventory_is_unchanged(self):
        module = load_module()
        signal_row = {
            "summary_id": 10,
            "source_hash": "signal-hash",
            "summary_text": """
            {
              "episode_no": 1,
              "mentioned_characters": [
                {
                  "character_key": "protagonist:named:hero",
                  "display_name": "주인공",
                  "relation_edges": []
                }
              ]
            }
            """,
        }
        inventory = {
            "protagonist:named:hero": {
                "character_key": "protagonist:named:hero",
                "display_name": "주인공",
                "is_protagonist": True,
                "distinct_episode_count": 3,
            }
        }

        affected = module.compute_rp_affected_scope_keys(
            old_inventory_map=inventory,
            new_inventory_map=inventory,
            old_relation_map={},
            new_relation_map={},
            old_touched_signal_rows=[signal_row],
            new_touched_signal_rows=[signal_row],
            old_profile_map={},
            old_examples_map={},
        )

        self.assertEqual(affected, {"protagonist:named:hero"})

    def test_changed_rp_inventory_is_rebuilt(self):
        module = load_module()
        signal_row = {
            "summary_id": 10,
            "source_hash": "signal-hash",
            "summary_text": """
            {
              "episode_no": 1,
              "mentioned_characters": [
                {
                  "character_key": "protagonist:named:hero",
                  "display_name": "주인공",
                  "relation_edges": []
                }
              ]
            }
            """,
        }
        old_inventory = {
            "protagonist:named:hero": {
                "character_key": "protagonist:named:hero",
                "display_name": "주인공",
                "is_protagonist": True,
                "distinct_episode_count": 3,
            }
        }
        new_inventory = {
            "protagonist:named:hero": {
                "character_key": "protagonist:named:hero",
                "display_name": "주인공",
                "is_protagonist": True,
                "distinct_episode_count": 4,
            }
        }
        profile_map = {"protagonist:named:hero": {"source_hash": "profile-hash"}}
        examples_map = {"protagonist:named:hero": {"source_hash": "examples-hash"}}

        affected = module.compute_rp_affected_scope_keys(
            old_inventory_map=old_inventory,
            new_inventory_map=new_inventory,
            old_relation_map={},
            new_relation_map={},
            old_touched_signal_rows=[signal_row],
            new_touched_signal_rows=[signal_row],
            old_profile_map=profile_map,
            old_examples_map=examples_map,
        )

        self.assertEqual(affected, {"protagonist:named:hero"})

    def test_v3_inventory_source_keys_drive_delta_rp_scope_resolution(self):
        module = load_module()
        signal_row = {
            "summary_id": 10,
            "source_hash": "signal-hash",
            "summary_text": """
            {
              "episode_no": 1,
              "mentioned_characters": [
                {
                  "character_key": "protagonist:named:hero",
                  "display_name": "백이현",
                  "relation_edges": []
                }
              ]
            }
            """,
        }
        inventory = {
            "character:백이현": {
                "canonical_character_key": "character:백이현",
                "source_character_keys": ["protagonist:named:hero"],
                "display_name": "백이현",
                "is_protagonist": True,
                "distinct_episode_count": 3,
            }
        }

        self.assertEqual(
            module.compute_rp_affected_scope_keys(
                old_inventory_map=inventory,
                new_inventory_map=inventory,
                old_relation_map={},
                new_relation_map={},
                old_touched_signal_rows=[signal_row],
                new_touched_signal_rows=[signal_row],
                old_profile_map={"character:백이현": {"source_hash": "profile-hash"}},
                old_examples_map={"character:백이현": {"source_hash": "examples-hash"}},
            ),
            set(),
        )
        self.assertEqual(
            module.compute_rp_affected_scope_keys(
                old_inventory_map=inventory,
                new_inventory_map=inventory,
                old_relation_map={},
                new_relation_map={},
                old_touched_signal_rows=[signal_row],
                new_touched_signal_rows=[signal_row],
                old_profile_map={},
                old_examples_map={},
            ),
            {"character:백이현"},
        )
        self.assertEqual(
            module.compute_rp_affected_scope_keys(
                old_inventory_map=inventory,
                new_inventory_map=inventory,
                old_relation_map={},
                new_relation_map={},
                old_touched_signal_rows=[signal_row],
                new_touched_signal_rows=[signal_row],
                old_profile_map={"protagonist:named:hero": {"source_hash": "legacy-profile-hash"}},
                old_examples_map={"protagonist:named:hero": {"source_hash": "legacy-examples-hash"}},
            ),
            {"character:백이현", "protagonist:named:hero"},
        )

    def test_v3_relation_only_change_marks_canonical_rp_scope_affected(self):
        module = load_module()
        signal_row = {
            "summary_id": 10,
            "source_hash": "signal-hash",
            "summary_text": """
            {
              "episode_no": 1,
              "mentioned_characters": [
                {
                  "character_key": "protagonist:named:hero",
                  "display_name": "백이현",
                  "relation_edges": [
                    {"target_key": "named:rival", "relation_tag": "대립", "direction": "to_target"}
                  ]
                }
              ]
            }
            """,
        }
        inventory = {
            "character:백이현": {
                "canonical_character_key": "character:백이현",
                "source_character_keys": ["protagonist:named:hero"],
                "display_name": "백이현",
                "is_protagonist": True,
                "distinct_episode_count": 3,
            }
        }
        old_relation_map = {
            "protagonist:named:hero=>named:rival": {
                "relation_key": "protagonist:named:hero=>named:rival",
                "source_key": "protagonist:named:hero",
                "target_key": "named:rival",
                "relation_tags": ["경계"],
            }
        }
        new_relation_map = {
            "protagonist:named:hero=>named:rival": {
                "relation_key": "protagonist:named:hero=>named:rival",
                "source_key": "protagonist:named:hero",
                "target_key": "named:rival",
                "relation_tags": ["대립"],
            }
        }

        affected = module.compute_rp_affected_scope_keys(
            old_inventory_map=inventory,
            new_inventory_map=inventory,
            old_relation_map=old_relation_map,
            new_relation_map=new_relation_map,
            old_touched_signal_rows=[signal_row],
            new_touched_signal_rows=[signal_row],
            old_profile_map={"character:백이현": {"source_hash": "profile-hash"}},
            old_examples_map={"character:백이현": {"source_hash": "examples-hash"}},
        )

        self.assertEqual(affected, {"character:백이현"})

    def test_canonical_relation_map_resolves_legacy_source_key_for_v3_rp_context(self):
        module = load_module()
        relation_map = {
            "protagonist:named:hero": [
                {
                    "relation_key": "protagonist:named:hero=>named:rival",
                    "source_key": "protagonist:named:hero",
                    "target_key": "named:rival",
                    "target_display_name": "라이벌",
                    "dominant_relation_tags": ["대립"],
                    "distinct_episode_count": 3,
                    "latest_seen_episode_no": 8,
                }
            ]
        }
        inventory_map = {
            "character:백이현": {
                "canonical_character_key": "character:백이현",
                "source_character_keys": ["protagonist:named:hero"],
                "display_name": "백이현",
            }
        }

        canonical_map = module.build_canonical_relation_inventory_map(
            relation_map=relation_map,
            inventory_map=inventory_map,
        )
        lines = module.build_rp_relation_context_lines(
            character_key="character:백이현",
            relation_map=canonical_map,
        )

        self.assertEqual(list(canonical_map.keys()), ["character:백이현"])
        self.assertEqual(lines, ["- 대상: 라이벌 | 관계 태그: 대립 | 반복 화수: 3 | 최근: 8화"])

    def test_changed_rp_relation_context_is_rebuilt(self):
        module = load_module()
        signal_row = {
            "summary_id": 10,
            "source_hash": "signal-hash",
            "summary_text": """
            {
              "episode_no": 1,
              "mentioned_characters": [
                {
                  "character_key": "protagonist:named:hero",
                  "display_name": "주인공",
                  "relation_edges": [
                    {
                      "target_key": "named:rival",
                      "relation_tag": "대립",
                      "direction": "to_target"
                    }
                  ]
                },
                {
                  "character_key": "named:rival",
                  "display_name": "라이벌",
                  "relation_edges": []
                }
              ]
            }
            """,
        }
        inventory = {
            "protagonist:named:hero": {
                "character_key": "protagonist:named:hero",
                "display_name": "주인공",
                "is_protagonist": True,
                "distinct_episode_count": 3,
            },
            "named:rival": {
                "character_key": "named:rival",
                "display_name": "라이벌",
                "entity_kind": "person",
                "distinct_episode_count": 3,
            },
        }
        old_relation_map = {
            "protagonist:named:hero=>named:rival": {
                "relation_key": "protagonist:named:hero=>named:rival",
                "source_key": "protagonist:named:hero",
                "target_key": "named:rival",
                "relation_tags": ["경계"],
            }
        }
        new_relation_map = {
            "protagonist:named:hero=>named:rival": {
                "relation_key": "protagonist:named:hero=>named:rival",
                "source_key": "protagonist:named:hero",
                "target_key": "named:rival",
                "relation_tags": ["대립"],
            }
        }
        profile_map = {
            "protagonist:named:hero": {"source_hash": "profile-hash"},
            "named:rival": {"source_hash": "profile-hash"},
        }
        examples_map = {
            "protagonist:named:hero": {"source_hash": "examples-hash"},
            "named:rival": {"source_hash": "examples-hash"},
        }

        affected = module.compute_rp_affected_scope_keys(
            old_inventory_map=inventory,
            new_inventory_map=inventory,
            old_relation_map=old_relation_map,
            new_relation_map=new_relation_map,
            old_touched_signal_rows=[signal_row],
            new_touched_signal_rows=[signal_row],
            old_profile_map=profile_map,
            old_examples_map=examples_map,
        )

        self.assertEqual(affected, {"protagonist:named:hero", "named:rival"})
