import unittest

from src.idiom_judgment.replay_judgment import replay_judgment_record


class JudgmentReplayTests(unittest.TestCase):
    def test_replay_uses_current_composite_policy_without_action_gate(self):
        record = {
            "status": "rejected",
            "rules": {
                "eligible_for_llm": True,
                "score": 80,
                "warnings": ["small_semantic_unit"],
                "evidence": {"semantic_action_count": 1},
            },
            "semantic": {
                "is_idiom": True,
                "semantic_score": 75,
                "reuse_score": 45,
                "reason": "短小但具有稳定意图。",
            },
            "smell": {
                "analysis_status": "completed",
                "risk_score": 0,
                "max_severity": "none",
                "categories": [],
                "findings": [],
                "reason": "未见可定位异味。",
            },
        }

        replayed = replay_judgment_record(record)

        self.assertEqual(replayed["status"], "accepted")
        self.assertEqual(replayed["scorecard"]["acceptance_threshold"], 60)
        self.assertEqual(replayed["rules"]["warnings"], [])
        self.assertEqual(replayed["rules"]["evidence"], {})
        self.assertFalse(replayed["smell_gate"]["rejected"])

    def test_replay_keeps_missing_agent_evidence_rejected(self):
        replayed = replay_judgment_record(
            {
                "status": "rejected",
                "rules": {
                    "eligible_for_llm": True,
                    "score": 80,
                    "warnings": [],
                    "evidence": {},
                },
                "semantic": None,
                "smell": None,
            }
        )

        self.assertEqual(replayed["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
