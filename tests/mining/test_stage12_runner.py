import sys
import unittest
from pathlib import Path

from scripts.run_stage12 import build_commands, select_targets


class Stage12RunnerTests(unittest.TestCase):
    def test_selects_requested_targets_in_manifest_order(self):
        root = Path(__file__).resolve().parents[2]
        self.assertEqual(
            select_targets(root, "project", ["mosh", "btop"]),
            ["btop", "mosh"],
        )

    def test_builds_only_requested_steps(self):
        commands = build_commands(
            "library",
            "cli11",
            ("dbscan", "merge"),
            device="cpu",
            batch_size=8,
        )
        self.assertEqual(commands[0][0], sys.executable)
        self.assertIn("src.mining.dbscan_tuning", commands[0])
        self.assertIn("outputs/library/cli11/stage2/embeddings.pkl", commands[0])
        self.assertIn("src.mining.cluster_merge", commands[1])


if __name__ == "__main__":
    unittest.main()
