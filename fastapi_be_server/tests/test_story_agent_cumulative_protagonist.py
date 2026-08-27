import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_story_agent_context.py"


def load_module():
    module_name = "build_story_agent_cumulative_protagonist_under_test"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    previous_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as temp_dir:
        Path(temp_dir, "logs", "data").mkdir(parents=True, exist_ok=True)
        Path(temp_dir, "logs", "error").mkdir(parents=True, exist_ok=True)
        os.chdir(temp_dir)
        try:
            spec.loader.exec_module(module)
        finally:
            os.chdir(previous_cwd)
    return module


story = load_module()


def character_item(
    character_key,
    display_name,
    *,
    work_protagonist=False,
    role_in_episode="lead",
    scene_weight="high",
    voice_mode="dialogue",
):
    return {
        "character_key": character_key,
        "display_name": display_name,
        "entity_kind": "person",
        "real_names": [display_name],
        "role_in_episode": role_in_episode,
        "scene_weight": scene_weight,
        "voice_mode": voice_mode,
        "is_work_protagonist": "Y" if work_protagonist else "N",
        "episode_focal": "Y" if work_protagonist else "N",
    }


def signal_row(episode_no, items):
    payload = {"episode_no": episode_no, "mentioned_characters": items}
    return {
        "summary_id": 1000 + episode_no,
        "summary_type": "episode_character_signals",
        "scope_key": f"episode:{episode_no}",
        "episode_from": episode_no,
        "episode_to": episode_no,
        "source_hash": f"hash:{episode_no}",
        "summary_text": json.dumps(payload, ensure_ascii=False),
    }


def anonymous_protagonist_item(*, first_person=True):
    return {
        "character_key": "protagonist:generic",
        "display_name": "나(주인공)",
        "entity_kind": "stable_role",
        "real_names": [],
        "role_in_episode": "lead",
        "scene_weight": "high",
        "voice_mode": "monologue" if first_person else "narration_only",
        "is_work_protagonist": "Y",
        "episode_focal": "Y",
        "is_first_person": "Y" if first_person else "N",
    }


def build_conflicting_opening_signal_rows(total_episodes=30, protagonist_episodes=26):
    """1~3화에 주인공 주장이 겹쳐 오프닝 판정이 실패하지만,
    누적으로는 차우진이 압도적인 작품을 재현한다."""
    rows = []
    for episode_no in (1, 2, 3):
        rows.append(
            signal_row(
                episode_no,
                [
                    character_item("character:차우진", "차우진", work_protagonist=True),
                    character_item("character:곽두칠", "곽두칠", work_protagonist=True),
                ],
            )
        )
    for episode_no in range(4, total_episodes + 1):
        items = [
            character_item(
                "character:차우진",
                "차우진",
                work_protagonist=episode_no <= protagonist_episodes,
            ),
            character_item(
                "character:서지환",
                "서지환",
                work_protagonist=False,
                role_in_episode="counterpart",
                scene_weight="medium",
            ),
        ]
        rows.append(signal_row(episode_no, items))
    return rows


class CumulativeWorkProtagonistFallbackTest(unittest.TestCase):
    def test_opening_rejects_one_named_claim_after_anonymous_non_pov_claims(self):
        """1101: 단발성 네아보다 누적 근거가 압도적인 원유성을 우선한다."""
        signal_rows = [
            signal_row(1, [anonymous_protagonist_item(first_person=False)]),
            signal_row(2, [anonymous_protagonist_item(first_person=False)]),
            signal_row(
                3,
                [character_item("protagonist:named:네아", "네아", work_protagonist=True)],
            ),
            *[
                signal_row(
                    episode_no,
                    [
                        character_item(
                            "protagonist:named:원유성",
                            "원유성",
                            work_protagonist=True,
                        )
                    ],
                )
                for episode_no in range(4, 11)
            ],
        ]
        base_rows = story.aggregate_character_inventory_v3_rows(
            signal_rows,
            protagonist_resolution=story._unresolved_opening_work_protagonist_resolution(
                "resolver_base_inventory"
            ),
        )

        opening = story._build_opening_work_protagonist_resolution(signal_rows, base_rows)

        self.assertEqual(opening.get("decision"), "UNRESOLVED")
        self.assertIsNone(opening.get("work_protagonist_key"))

    def test_opening_keeps_one_named_claim_without_strong_competitor(self):
        """누적 반증이 없으면 기존 단일 오프닝 실명 판정을 유지한다."""
        signal_rows = [
            signal_row(1, [anonymous_protagonist_item(first_person=False)]),
            signal_row(2, [anonymous_protagonist_item(first_person=False)]),
            signal_row(
                3,
                [
                    character_item(
                        "protagonist:named:이해일",
                        "이해일",
                        work_protagonist=True,
                    )
                ],
            ),
        ]
        base_rows = story.aggregate_character_inventory_v3_rows(
            signal_rows,
            protagonist_resolution=story._unresolved_opening_work_protagonist_resolution(
                "resolver_base_inventory"
            ),
        )

        opening = story._build_opening_work_protagonist_resolution(signal_rows, base_rows)

        self.assertEqual(opening.get("decision"), "RESOLVED")
        self.assertEqual(opening.get("work_protagonist_key"), "character:이해일")

    def test_opening_keeps_full_name_when_cumulative_candidate_is_shorter(self):
        """1107: 누적 축약명이 기존 오프닝 풀네임을 밀어내지 않는다."""
        signal_rows = [
            signal_row(1, [anonymous_protagonist_item(first_person=False)]),
            signal_row(2, [anonymous_protagonist_item(first_person=False)]),
            signal_row(
                3,
                [
                    character_item(
                        "protagonist:named:도미닉가르시아",
                        "도미닉 가르시아",
                        work_protagonist=True,
                    )
                ],
            ),
            *[
                signal_row(
                    episode_no,
                    [
                        character_item(
                            "protagonist:named:도미닉",
                            "도미닉",
                            work_protagonist=True,
                        )
                    ],
                )
                for episode_no in range(4, 11)
            ],
        ]
        base_rows = story.aggregate_character_inventory_v3_rows(
            signal_rows,
            protagonist_resolution=story._unresolved_opening_work_protagonist_resolution(
                "resolver_base_inventory"
            ),
        )

        opening = story._build_opening_work_protagonist_resolution(signal_rows, base_rows)

        self.assertEqual(opening.get("decision"), "RESOLVED")
        self.assertEqual(
            opening.get("work_protagonist_key"),
            "character:도미닉가르시아",
        )

    def test_opening_treats_bare_honorific_as_role_not_identity(self):
        """1235: 도련님은 별도 인물이 아니라 진 프라흐의 호칭 근거다."""
        signal_rows = [
            signal_row(
                1,
                [
                    character_item(
                        "protagonist:named:진프라흐",
                        "진 프라흐",
                        work_protagonist=True,
                    )
                ],
            ),
            signal_row(
                2,
                [
                    character_item(
                        "protagonist:named:도련님",
                        "도련님",
                        work_protagonist=True,
                    )
                ],
            ),
            signal_row(
                3,
                [
                    character_item(
                        "protagonist:named:진프라흐",
                        "진 프라흐",
                        work_protagonist=True,
                    )
                ],
            ),
        ]
        base_rows = story.aggregate_character_inventory_v3_rows(
            signal_rows,
            protagonist_resolution=story._unresolved_opening_work_protagonist_resolution(
                "resolver_base_inventory"
            ),
        )

        opening = story._build_opening_work_protagonist_resolution(signal_rows, base_rows)

        self.assertEqual(opening.get("decision"), "RESOLVED")
        self.assertEqual(opening.get("work_protagonist_key"), "character:진프라흐")

    def test_opening_does_not_replace_dominant_possessed_identity(self):
        """빙의 전 이름보다 이후 누적된 빙의 대상의 정체성을 유지한다."""
        possessed_protagonist = character_item(
            "protagonist:named:이사육",
            "이사육",
            work_protagonist=True,
        )
        possessed_protagonist["real_names"] = []
        possessed_protagonist["aliases"] = ["이사육"]
        possessed_protagonist["narration_names"] = ["이사육"]
        possessed_protagonist["persona_names"] = ["야율천"]
        possessed_protagonist["identity_claims"] = [
            {
                "claim_type": "possessed_as",
                "target_key": "named:야율천",
                "target_label": "야율천",
                "normalized_target_label": "야율천",
                "evidence": "",
            }
        ]
        signal_rows = [
            signal_row(
                1,
                [
                    possessed_protagonist,
                    character_item("named:야율천", "야율천"),
                ],
            ),
            signal_row(
                2,
                [
                    character_item(
                        "protagonist:named:소궁주",
                        "소궁주",
                        work_protagonist=True,
                    )
                ],
            ),
            signal_row(3, [anonymous_protagonist_item(first_person=False)]),
            *[
                signal_row(
                    episode_no,
                    [
                        character_item(
                            "protagonist:named:야율천",
                            "야율천",
                            work_protagonist=True,
                        )
                    ],
                )
                for episode_no in range(4, 11)
            ],
        ]
        base_rows = story.aggregate_character_inventory_v3_rows(
            signal_rows,
            protagonist_resolution=story._unresolved_opening_work_protagonist_resolution(
                "resolver_base_inventory"
            ),
        )

        opening = story._build_opening_work_protagonist_resolution(signal_rows, base_rows)
        cumulative = story._build_cumulative_work_protagonist_resolution(
            base_rows,
            total_signal_episodes=story.count_distinct_signal_episode_nos(signal_rows),
        )

        self.assertEqual(opening.get("decision"), "UNRESOLVED")
        self.assertEqual(cumulative.get("work_protagonist_key"), "character:야율천")

    def test_opening_allows_named_reveal_when_every_claim_is_first_person(self):
        """1인칭 화자의 이름이 3화에 처음 드러나는 정상 케이스는 유지한다."""
        named_protagonist = character_item(
            "protagonist:named:김유성",
            "김유성",
            work_protagonist=True,
        )
        named_protagonist["is_first_person"] = "Y"
        signal_rows = [
            signal_row(1, [anonymous_protagonist_item()]),
            signal_row(2, [anonymous_protagonist_item()]),
            signal_row(3, [named_protagonist]),
        ]
        base_rows = story.aggregate_character_inventory_v3_rows(
            signal_rows,
            protagonist_resolution=story._unresolved_opening_work_protagonist_resolution(
                "resolver_base_inventory"
            ),
        )

        opening = story._build_opening_work_protagonist_resolution(signal_rows, base_rows)

        self.assertEqual(opening.get("decision"), "RESOLVED")
        self.assertEqual(opening.get("work_protagonist_key"), "character:김유성")

    def test_cumulative_links_first_person_evidence_to_full_name_variant_family(self):
        """1223: 나/덕영/하덕영의 주인공 근거를 하덕영 자산으로 모은다."""
        signal_rows = [
            signal_row(
                1,
                [
                    character_item(
                        "protagonist:named:하얀여우",
                        "하얀 여우",
                        work_protagonist=True,
                    )
                ],
            ),
            signal_row(2, [anonymous_protagonist_item()]),
            signal_row(
                3,
                [character_item("protagonist:named:덕영", "덕영", work_protagonist=True)],
            ),
            signal_row(
                4,
                [character_item("named:하덕영", "하덕영", work_protagonist=False)],
            ),
            signal_row(5, []),
            signal_row(6, [anonymous_protagonist_item()]),
            signal_row(
                7,
                [character_item("protagonist:named:하덕영", "하덕영", work_protagonist=True)],
            ),
            signal_row(
                8,
                [
                    character_item(
                        "protagonist:named:하선생님",
                        "하 선생님",
                        work_protagonist=True,
                    )
                ],
            ),
            signal_row(
                9,
                [character_item("protagonist:named:하덕영", "하덕영", work_protagonist=True)],
            ),
            signal_row(10, [anonymous_protagonist_item()]),
        ]

        inventory = story.aggregate_character_inventory_v3_rows(signal_rows)
        main_rows = [row for row in inventory if row.get("work_role") == "main_protagonist"]

        self.assertEqual([row.get("display_name") for row in main_rows], ["하덕영"])
        self.assertEqual(
            main_rows[0].get("work_protagonist_evidence", {}).get("episode_count"),
            6,
        )
        self.assertFalse(
            any(row.get("canonical_character_key") == "character:나(주인공)" for row in inventory)
        )

    def test_cumulative_does_not_attach_first_person_to_one_unlinked_real_name(self):
        """교차 시점처럼 익명 화자와 실명 하나만 있으면 자동 연결하지 않는다."""
        signal_rows = [
            signal_row(
                1,
                [
                    character_item("character:남우진", "남우진", work_protagonist=True),
                    character_item("character:송하늘", "송하늘", work_protagonist=True),
                ],
            ),
            signal_row(2, [anonymous_protagonist_item()]),
            signal_row(3, [anonymous_protagonist_item()]),
            signal_row(
                4,
                [character_item("character:남우진", "남우진", work_protagonist=True)],
            ),
            signal_row(5, [anonymous_protagonist_item()]),
            signal_row(
                6,
                [character_item("character:남우진", "남우진", work_protagonist=True)],
            ),
            signal_row(7, [anonymous_protagonist_item()]),
            signal_row(8, [anonymous_protagonist_item()]),
        ]

        inventory = story.aggregate_character_inventory_v3_rows(signal_rows)

        self.assertFalse(
            any(row.get("work_role") == "main_protagonist" for row in inventory)
        )

    def test_cumulative_does_not_merge_persona_name_variants(self):
        """빙의 주인공과 원래 몸 주인은 표시명이 비슷해도 합산하지 않는다."""
        rows = [
            {
                "canonical_character_key": "character:방호영",
                "display_name": "조렌 테이머",
                "aliases": ["조렌 테이머"],
                "real_names": ["방호영"],
                "persona_names": ["조렌 테이머"],
                "evidence_episode_nos": [1, 4, 6],
                "work_protagonist_evidence": {"episode_count": 3},
                "first_person_evidence": {"episode_count": 0},
                "identity_conflict_reasons": [],
                "display_safety": {"status": "pass"},
            },
            {
                "canonical_character_key": "character:조렌",
                "display_name": "조렌 테이머 변방백",
                "aliases": ["조렌 테이머 변방백"],
                "real_names": ["조렌"],
                "persona_names": ["조렌 테이머 변방백"],
                "evidence_episode_nos": [3, 5, 7],
                "work_protagonist_evidence": {"episode_count": 3},
                "first_person_evidence": {"episode_count": 0},
                "identity_conflict_reasons": [],
                "display_safety": {"status": "pass"},
            },
            {
                "canonical_character_key": "character:나(주인공)",
                "display_name": "나(주인공)",
                "evidence_episode_nos": [2, 8, 9],
                "work_protagonist_evidence": {"episode_count": 3},
                "first_person_evidence": {"episode_count": 3},
            },
        ]

        resolution = story._build_cumulative_work_protagonist_resolution(
            rows,
            total_signal_episodes=9,
        )

        self.assertEqual(resolution.get("decision"), "UNRESOLVED")

    def test_opening_resolution_fails_on_conflicting_claimants(self):
        signal_rows = build_conflicting_opening_signal_rows()
        base_rows = story.aggregate_character_inventory_v3_rows(
            signal_rows,
            protagonist_resolution=story._unresolved_opening_work_protagonist_resolution(
                "resolver_base_inventory"
            ),
        )
        opening = story._build_opening_work_protagonist_resolution(signal_rows, base_rows)
        self.assertEqual(opening.get("decision"), "UNRESOLVED")
        self.assertEqual(opening.get("reason_code"), "conflicting_opening_claimants")

    def test_cumulative_fallback_resolves_dominant_protagonist(self):
        signal_rows = build_conflicting_opening_signal_rows()
        base_rows = story.aggregate_character_inventory_v3_rows(
            signal_rows,
            protagonist_resolution=story._unresolved_opening_work_protagonist_resolution(
                "resolver_base_inventory"
            ),
        )
        resolution = story._build_cumulative_work_protagonist_resolution(
            base_rows,
            total_signal_episodes=30,
        )
        self.assertEqual(resolution.get("decision"), "RESOLVED")
        self.assertEqual(resolution.get("reason_code"), "cumulative_role_dominance")
        self.assertEqual(resolution.get("work_protagonist_key"), "character:차우진")
        self.assertEqual(resolution.get("confidence"), "medium")

    def test_inventory_marks_dominant_row_as_main_protagonist(self):
        signal_rows = build_conflicting_opening_signal_rows()
        rows = story.aggregate_character_inventory_v3_rows(signal_rows)
        mains = [
            row
            for row in rows
            if str(row.get("work_role") or "") == "main_protagonist"
        ]
        self.assertEqual([str(row.get("display_name") or "") for row in mains], ["차우진"])

    def test_fallback_skips_when_evidence_is_too_thin(self):
        """주인공 근거가 최소 화수에 못 미치면 확정하지 않는다."""
        signal_rows = build_conflicting_opening_signal_rows(
            total_episodes=30, protagonist_episodes=3
        )
        base_rows = story.aggregate_character_inventory_v3_rows(
            signal_rows,
            protagonist_resolution=story._unresolved_opening_work_protagonist_resolution(
                "resolver_base_inventory"
            ),
        )
        resolution = story._build_cumulative_work_protagonist_resolution(
            base_rows,
            total_signal_episodes=30,
        )
        self.assertEqual(resolution.get("decision"), "UNRESOLVED")

    def test_fallback_skips_when_top_is_not_dominant(self):
        """1위와 2위가 접전이면 임의로 고르지 않는다."""
        rows = []
        for episode_no in (1, 2, 3):
            rows.append(
                signal_row(
                    episode_no,
                    [
                        character_item("character:혜성", "혜성", work_protagonist=True),
                        character_item("character:아현", "아현", work_protagonist=True),
                    ],
                )
            )
        for episode_no in range(4, 21):
            rows.append(
                signal_row(
                    episode_no,
                    [
                        character_item(
                            "character:혜성", "혜성", work_protagonist=episode_no <= 12
                        ),
                        character_item(
                            "character:아현", "아현", work_protagonist=episode_no <= 11
                        ),
                    ],
                )
            )
        base_rows = story.aggregate_character_inventory_v3_rows(
            rows,
            protagonist_resolution=story._unresolved_opening_work_protagonist_resolution(
                "resolver_base_inventory"
            ),
        )
        resolution = story._build_cumulative_work_protagonist_resolution(
            base_rows,
            total_signal_episodes=20,
        )
        self.assertEqual(resolution.get("decision"), "UNRESOLVED")
        self.assertEqual(resolution.get("reason_code"), "cumulative_evidence_not_dominant")

    def test_fallback_rejects_generic_display_name_candidate(self):
        """'주인공' 같은 보통명사 후보는 확정 대상에서 제외한다."""
        rows = []
        for episode_no in (1, 2, 3):
            rows.append(
                signal_row(
                    episode_no,
                    [
                        character_item("character:주인공", "주인공", work_protagonist=True),
                        character_item("character:김태식", "김태식", work_protagonist=True),
                    ],
                )
            )
        for episode_no in range(4, 25):
            rows.append(
                signal_row(
                    episode_no,
                    [
                        character_item(
                            "character:주인공", "주인공", work_protagonist=episode_no <= 20
                        ),
                    ],
                )
            )
        base_rows = story.aggregate_character_inventory_v3_rows(
            rows,
            protagonist_resolution=story._unresolved_opening_work_protagonist_resolution(
                "resolver_base_inventory"
            ),
        )
        resolution = story._build_cumulative_work_protagonist_resolution(
            base_rows,
            total_signal_episodes=24,
        )
        self.assertEqual(resolution.get("decision"), "UNRESOLVED")

    def test_fallback_rejects_duplicate_canonical_key_candidate(self):
        """identity가 분열된 dup 행은 누적 근거가 많아도 주인공으로 승격하지 않는다."""
        rows = [
            {
                "canonical_character_key": "character:오레오:dup:d0c8e351",
                "display_name": "오레오",
                "aliases": ["오레오"],
                "real_names": [],
                "persona_names": [],
                "evidence_episode_nos": list(range(1, 10)),
                "work_protagonist_evidence": {"episode_count": 9},
                "identity_conflict_reasons": ["duplicate_canonical_key"],
                "display_safety": {"status": "pass"},
            },
            {
                "canonical_character_key": "character:신데렐라",
                "display_name": "신데렐라",
                "aliases": ["신데렐라"],
                "real_names": [],
                "persona_names": [],
                "evidence_episode_nos": [1, 2, 3],
                "work_protagonist_evidence": {"episode_count": 3},
                "identity_conflict_reasons": [],
                "display_safety": {"status": "pass"},
            },
        ]

        resolution = story._build_cumulative_work_protagonist_resolution(
            rows,
            total_signal_episodes=10,
        )

        self.assertEqual(resolution.get("decision"), "UNRESOLVED")

    def test_opening_resolution_still_wins_when_available(self):
        """오프닝 판정이 성공하면 누적 폴백이 개입하지 않는다."""
        rows = []
        for episode_no in (1, 2, 3):
            rows.append(
                signal_row(
                    episode_no,
                    [character_item("character:레이너", "레이너", work_protagonist=True)],
                )
            )
        for episode_no in range(4, 26):
            rows.append(
                signal_row(
                    episode_no,
                    [
                        character_item(
                            "character:레이너", "레이너", work_protagonist=episode_no <= 15
                        ),
                    ],
                )
            )
        base_rows = story.aggregate_character_inventory_v3_rows(
            rows,
            protagonist_resolution=story._unresolved_opening_work_protagonist_resolution(
                "resolver_base_inventory"
            ),
        )
        opening = story._build_opening_work_protagonist_resolution(rows, base_rows)
        self.assertEqual(opening.get("decision"), "RESOLVED")
        self.assertEqual(opening.get("reason_code"), "opening_role_continuity")

    def test_fallback_preserves_unresolved_reason_code_from_earlier_stage(self):
        """앞 단계 진단 사유를 누적 판정 사유로 덮어쓰지 않는다."""
        signal_rows = build_conflicting_opening_signal_rows(
            total_episodes=30, protagonist_episodes=3
        )
        base_rows = story.aggregate_character_inventory_v3_rows(
            signal_rows,
            protagonist_resolution=story._unresolved_opening_work_protagonist_resolution(
                "resolver_base_inventory"
            ),
        )
        opening = story._unresolved_opening_work_protagonist_resolution(
            "conflicting_opening_claimants"
        )
        resolution = story._build_cumulative_work_protagonist_resolution(
            base_rows,
            total_signal_episodes=30,
            unresolved_fallback=opening,
        )
        self.assertEqual(resolution.get("decision"), "UNRESOLVED")
        self.assertEqual(resolution.get("reason_code"), "conflicting_opening_claimants")

    def test_fallback_does_not_replace_locked_protagonist_with_alias_row(self):
        """이미 확정된 주인공이 있으면 축약형 파편으로 갈아타지 않는다."""
        signal_rows = build_conflicting_opening_signal_rows()
        base_rows = story.aggregate_character_inventory_v3_rows(
            signal_rows,
            protagonist_resolution=story._unresolved_opening_work_protagonist_resolution(
                "resolver_base_inventory"
            ),
        )
        locked_rows = [
            {
                "canonical_character_key": "character:차우진행정관",
                "display_name": "차우진 행정관",
                "work_role": "main_protagonist",
            }
        ]
        resolution = story._build_cumulative_work_protagonist_resolution(
            base_rows,
            total_signal_episodes=30,
            locked_protagonist_rows=locked_rows,
        )
        self.assertEqual(resolution.get("decision"), "UNRESOLVED")
        self.assertEqual(
            resolution.get("reason_code"),
            "cumulative_evidence_conflicts_with_locked_protagonist",
        )

    def test_fallback_still_fires_when_locked_row_is_the_same_identity(self):
        """확정 주인공과 같은 인물이면 누적 폴백이 정상 발동한다."""
        signal_rows = build_conflicting_opening_signal_rows()
        base_rows = story.aggregate_character_inventory_v3_rows(
            signal_rows,
            protagonist_resolution=story._unresolved_opening_work_protagonist_resolution(
                "resolver_base_inventory"
            ),
        )
        locked_rows = [
            {
                "canonical_character_key": "character:차우진",
                "display_name": "차우진",
                "work_role": "main_protagonist",
            }
        ]
        resolution = story._build_cumulative_work_protagonist_resolution(
            base_rows,
            total_signal_episodes=30,
            locked_protagonist_rows=locked_rows,
        )
        self.assertEqual(resolution.get("decision"), "RESOLVED")
        self.assertEqual(resolution.get("work_protagonist_key"), "character:차우진")

    def test_resolver_supplied_cumulative_resolution_respects_locked_protagonist(self):
        """배치 경로처럼 판정이 미리 주어져도 locked 가드가 적용된다."""
        signal_rows = build_conflicting_opening_signal_rows()
        locked_rows = [
            {
                "canonical_character_key": "character:차우진행정관",
                "display_name": "차우진 행정관",
                "work_role": "main_protagonist",
            }
        ]
        supplied = {
            "schema_version": story.WORK_PROTAGONIST_RESOLUTION_FORMAT_VERSION,
            "decision": "RESOLVED",
            "work_protagonist_key": "character:차우진",
            "work_protagonist_keys": ["character:차우진"],
            "confidence": "medium",
            "reason_code": "cumulative_role_dominance",
            "rationale": "누적 근거 우위",
            "rejected": [],
            "safety_flags": {
                "requires_identity_merge": False,
                "selected_candidate_eligible": True,
                "multiple_plausible_main_candidates": False,
            },
        }
        rows = story.aggregate_character_inventory_v3_rows(
            signal_rows,
            protagonist_resolution=supplied,
            locked_protagonist_rows=locked_rows,
        )
        promoted = [
            str(row.get("display_name") or "")
            for row in rows
            if str(row.get("work_role") or "") == "main_protagonist"
        ]
        self.assertNotIn("차우진", promoted)

    def test_resolver_supplied_opening_resolution_is_not_guarded(self):
        """오프닝 판정 결과는 locked 가드로 무효화하지 않는다."""
        signal_rows = build_conflicting_opening_signal_rows()
        supplied = {
            "schema_version": story.WORK_PROTAGONIST_RESOLUTION_FORMAT_VERSION,
            "decision": "RESOLVED",
            "work_protagonist_key": "character:차우진",
            "work_protagonist_keys": ["character:차우진"],
            "confidence": "high",
            "reason_code": "opening_role_continuity",
            "rationale": "첫 3화 연속",
            "rejected": [],
            "safety_flags": {
                "requires_identity_merge": False,
                "selected_candidate_eligible": True,
                "multiple_plausible_main_candidates": False,
            },
        }
        rows = story.aggregate_character_inventory_v3_rows(
            signal_rows,
            protagonist_resolution=supplied,
            locked_protagonist_rows=[
                {
                    "canonical_character_key": "character:차우진행정관",
                    "display_name": "차우진 행정관",
                    "work_role": "main_protagonist",
                }
            ],
        )
        promoted = [
            str(row.get("display_name") or "")
            for row in rows
            if str(row.get("work_role") or "") == "main_protagonist"
        ]
        self.assertIn("차우진", promoted)

if __name__ == "__main__":
    unittest.main()
