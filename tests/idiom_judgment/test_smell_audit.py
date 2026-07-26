import pickle
import tempfile
import unittest
from pathlib import Path

from src.idiom_judgment.smell_audit import (
    build_smell_audit_payload,
    evaluate_smell_audit,
    select_stratified_audit_samples,
)
from src.idiom_judgment.smell_review_agent import _normalize_findings
from src.idiom_judgment.smell_taxonomy import (
    SMELL_TAXONOMY_SOURCES,
    SmellFinding,
    build_smell_gate,
    calculate_smell_risk_score,
)


def _finding(category, severity, confidence):
    return SmellFinding(
        category=category,
        severity=severity,
        confidence=confidence,
        evidence="可定位证据",
        impact="可复用风险",
        remediation="修复建议",
    )


def _smell(findings):
    return {
        "analysis_status": "completed",
        "risk_score": calculate_smell_risk_score(findings),
        "max_severity": (
            max(
                findings,
                key=lambda item: {
                    "low": 1,
                    "medium": 2,
                    "high": 3,
                    "critical": 4,
                }[item.severity],
            ).severity
            if findings
            else "none"
        ),
        "categories": sorted({item.category for item in findings}),
        "findings": [item.__dict__ for item in findings],
        "reason": "",
    }


class SmellTaxonomyAndAuditTests(unittest.TestCase):
    def test_taxonomy_sources_use_thesis_ids_without_changing_schema(self):
        expected = {
            "[E108]": "https://martinfowler.com/bliki/CodeSmell.html",
            "[E028]": "https://doi.org/10.1109/MSR59073.2023.00066",
            "[E109]": (
                "https://clang.llvm.org/extra/clang-tidy/checks/list.html"
            ),
            "[E110]": (
                "https://cmu-sei.github.io/secure-coding-standards/"
                "sei-cert-cpp-coding-standard/"
            ),
            "[E027]": "https://doi.org/10.1145/3691620.3695508",
        }
        self.assertEqual(len(SMELL_TAXONOMY_SOURCES), len(expected))
        for source in SMELL_TAXONOMY_SOURCES:
            self.assertEqual(set(source), {"name", "url", "role"})
            source_id = source["name"].split(maxsplit=1)[0]
            self.assertEqual(source["url"], expected[source_id])

    def test_invalid_finding_payload_is_not_treated_as_clean(self):
        findings, invalid = _normalize_findings(
            [
                {
                    "category": "error_handling",
                    "severity": "critical",
                    "confidence": 101,
                    "evidence": "空 catch",
                    "impact": "吞掉失败",
                    "remediation": "传播错误",
                }
            ]
        )
        self.assertEqual(findings, [])
        self.assertTrue(invalid)

    def test_risk_score_and_gate_are_independent_and_deterministic(self):
        high = [_finding("resource_lifetime", "high", 80)]
        self.assertEqual(calculate_smell_risk_score(high), 60)
        gate = build_smell_gate(
            analysis_status="completed",
            risk_score=60,
            max_severity="high",
            categories=["resource_lifetime"],
            finding_count=1,
        )
        self.assertTrue(gate["rejected"])
        self.assertEqual(gate["trigger_kind"], "risk_threshold")

        accumulated = [
            _finding("magic_literal", "medium", 100),
            _finding("interface_coupling", "medium", 100),
            _finding("dead_redundant_code", "medium", 100),
            _finding("control_flow_complexity", "medium", 100),
        ]
        self.assertEqual(calculate_smell_risk_score(accumulated), 60)
        failed = build_smell_gate(
            analysis_status="failed",
            risk_score=100,
            max_severity="none",
            categories=[],
            finding_count=0,
        )
        self.assertEqual(failed["trigger_kind"], "analysis_failure")

    def test_audit_reports_filter_and_per_category_accuracy(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            stage3_path = root / "judgment.pkl"
            stage4_path = root / "synthesis.pkl"
            stage3_findings = [
                _finding("error_handling", "critical", 90)
            ]
            stage3_smell = _smell(stage3_findings)
            stage3_gate = build_smell_gate(
                analysis_status="completed",
                risk_score=stage3_smell["risk_score"],
                max_severity="critical",
                categories=["error_handling"],
                finding_count=1,
            )
            with stage3_path.open("wb") as stream:
                pickle.dump(
                    {
                        "artifact_type": "idiom_judgment",
                        "project": "sample",
                        "accepted": [],
                        "rejected": [
                            {
                                "cluster_id": "1",
                                "status": "rejected",
                                "center_point": "work();",
                                "smell": stage3_smell,
                                "smell_gate": stage3_gate,
                                "smell_review_input": {
                                    "candidate_code": "work();",
                                    "related_examples": [],
                                    "deterministic_evidence": {},
                                },
                            }
                        ],
                    },
                    stream,
                )
            with stage4_path.open("wb") as stream:
                pickle.dump(
                    {
                        "artifact_type": "idiom_synthesis",
                        "project": "sample",
                        "accepted": [
                            {
                                "selected_candidate_ids": ["1", "2"],
                                "status": "accepted",
                                "center_point": "merge();",
                                "smell": _smell([]),
                                "smell_gate": build_smell_gate(
                                    analysis_status="completed",
                                    risk_score=0,
                                    max_severity="none",
                                    categories=[],
                                    finding_count=0,
                                ),
                                "smell_review_input": {
                                    "candidate_code": "merge();",
                                    "related_examples": ["void f() {}"],
                                    "deterministic_evidence": {},
                                },
                            }
                        ],
                        "rejected": [],
                    },
                    stream,
                )

            payload = build_smell_audit_payload(
                [stage3_path, stage4_path],
                limit=10,
            )
            self.assertEqual(payload["sampling"]["sample_count"], 2)
            self.assertEqual(
                payload["sampling"]["category_counts"]["error_handling"],
                1,
            )
            self.assertNotIn("predicted", payload["review_items"][0])
            self.assertNotIn("result_status", payload["review_items"][0])
            samples = {
                sample["stage"]: sample for sample in payload["samples"]
            }
            labels = {
                "labels": [
                    {
                        "audit_id": samples[3]["audit_id"],
                        "blocking_smell": True,
                        "categories": ["error_handling"],
                        "notes": "",
                    },
                    {
                        "audit_id": samples[4]["audit_id"],
                        "blocking_smell": True,
                        "categories": ["memory_lifetime"],
                        "notes": "",
                    },
                ]
            }
            report = evaluate_smell_audit(payload, labels)
            self.assertEqual(
                report["overall"]["confusion"],
                {"tp": 1, "fp": 0, "tn": 0, "fn": 1},
            )
            self.assertEqual(report["overall"]["filter_precision"], 1.0)
            self.assertEqual(report["overall"]["filter_recall"], 0.5)
            self.assertEqual(
                report["overall"]["categories"]["error_handling"]["f1"],
                1.0,
            )
            self.assertEqual(report["by_stage"]["3"]["filter_recall"], 1.0)
            self.assertEqual(report["by_stage"]["4"]["filter_recall"], 0.0)
            self.assertEqual(
                report["overall"]["categories"]["error_handling"]["family"],
                "correctness",
            )

    def test_small_stratified_sample_never_exceeds_limit(self):
        samples = []
        for index, trigger in enumerate(
            ["risk_threshold", "analysis_failure", "none"]
        ):
            samples.append(
                {
                    "audit_id": str(index),
                    "predicted": {
                        "categories": (
                            ["error_handling"]
                            if trigger != "analysis_failure"
                            else []
                        ),
                        "gate": {"trigger_kind": trigger},
                    },
                }
            )
        selected = select_stratified_audit_samples(
            samples,
            limit=1,
            seed="test",
        )
        self.assertEqual(len(selected), 1)


if __name__ == "__main__":
    unittest.main()
