import tempfile
import unittest
from pathlib import Path

from src.common.run_checkpoint import RunCheckpoint


class RunCheckpointTests(unittest.TestCase):
    def test_checkpoint_resumes_or_starts_fresh(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "run.sqlite3"
            with RunCheckpoint(
                path,
                resume=False,
            ) as checkpoint:
                checkpoint.save_record(0, {"status": "accepted"})

            with RunCheckpoint(
                path,
                resume=True,
            ) as checkpoint:
                self.assertEqual(
                    checkpoint.load_records(),
                    {0: {"status": "accepted"}},
                )

            with RunCheckpoint(path, resume=False) as checkpoint:
                self.assertEqual(checkpoint.load_records(), {})


if __name__ == "__main__":
    unittest.main()
