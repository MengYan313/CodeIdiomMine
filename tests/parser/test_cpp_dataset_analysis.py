from __future__ import annotations

import json
from pathlib import Path
import unittest

from scripts.analyze_cpp_dataset import (
    _apply_dataset_classification,
    _average_rank_percentiles,
)


class DatasetClassificationTests(unittest.TestCase):
    @staticmethod
    def _project(
        slug: str,
        value: int,
        *,
        status: str = "保留",
        domain: str = "领域甲",
    ) -> dict:
        return {
            "slug": slug,
            "selection": {"status": status},
            "classification": {"primary_domain": domain},
            "parse": {
                "analysis": {
                    "source": {
                        "effective_line_count": value,
                        "selected_file_count": value,
                    },
                    "candidates": {"function": value},
                }
            },
        }

    def test_average_rank_percentiles_use_average_rank_for_ties(self) -> None:
        result = _average_rank_percentiles(
            {"a": 10, "b": 20, "c": 20, "d": 40}
        )

        self.assertEqual(
            result,
            {"a": 0.0, "b": 0.5, "c": 0.5, "d": 1.0},
        )

    def test_classification_is_nearly_equal_frequency(self) -> None:
        projects = [
            self._project(f"project-{index}", index + 1)
            for index in range(6)
        ]
        policy = {
            "primary_domain": {"categories": ["领域甲"]},
            "analysis_complexity": {
                "indicators": [
                    "effective_line_count",
                    "selected_file_count",
                    "candidate_count",
                ]
            },
        }

        _apply_dataset_classification(projects, policy)

        tiers = [
            project["classification"]["analysis_complexity"]["tier"]
            for project in projects[:6]
        ]
        self.assertEqual(tiers, ["低", "低", "中", "中", "高", "高"])
        self.assertEqual(
            projects[0]["classification"]["analysis_complexity"][
                "indicator_values"
            ],
            {
                "effective_line_count": 1,
                "selected_file_count": 1,
                "candidate_count": 1,
            },
        )

    def test_classification_rejects_undeclared_primary_domain(self) -> None:
        with self.assertRaisesRegex(ValueError, "主领域"):
            _apply_dataset_classification(
                [self._project("project", 1, domain="领域乙")],
                {
                    "primary_domain": {"categories": ["领域甲"]},
                    "analysis_complexity": {
                        "indicators": [
                            "effective_line_count",
                            "selected_file_count",
                            "candidate_count",
                        ]
                    },
                },
            )

    def test_frozen_manifest_contains_selected_15_plus_15_groups(self) -> None:
        root = Path(__file__).resolve().parents[2]
        selection = json.loads(
            (
                root / "docs/research/cpp-dataset-selection.json"
            ).read_text(encoding="utf-8")
        )
        manifest = json.loads(
            (
                root / "docs/research/cpp-dataset-manifest.json"
            ).read_text(encoding="utf-8")
        )
        selected_projects = {
            project["name"]
            for project in selection["project"]["selected"]
        }
        selected_libraries = {
            library["name"]
            for library in selection["library"]
        }
        manifest_projects = {
            group["name"]
            for group in manifest["groups"]
            if group["type"] == "Project"
        }
        manifest_libraries = {
            group["name"]
            for group in manifest["groups"]
            if group["type"] == "Library"
        }

        self.assertEqual(len(selected_projects), 15)
        self.assertEqual(len(selected_libraries), 15)
        self.assertEqual(selected_projects, manifest_projects)
        self.assertEqual(selected_libraries, manifest_libraries)
        self.assertEqual(manifest["summary"]["group_count"], 30)


if __name__ == "__main__":
    unittest.main()
