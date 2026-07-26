import tempfile
import unittest
from pathlib import Path

from src.common.run_checkpoint import RunCheckpoint


class RunCheckpointTests(unittest.TestCase):
    def test_checkpoint_resumes_only_identical_run_contract(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "run.sqlite3"
            metadata = {
                "stage": "idiom_judgment",
                "input_sha256": "abc",
                "model": "low",
            }
            with RunCheckpoint(
                path,
                metadata=metadata,
                resume=False,
            ) as checkpoint:
                checkpoint.save_record(0, {"status": "accepted"})

            with RunCheckpoint(
                path,
                metadata=metadata,
                resume=True,
            ) as checkpoint:
                self.assertEqual(
                    checkpoint.load_records(),
                    {0: {"status": "accepted"}},
                )

            with self.assertRaisesRegex(ValueError, "元数据"):
                RunCheckpoint(
                    path,
                    metadata={**metadata, "model": "different"},
                    resume=True,
                )
            with self.assertRaises(FileExistsError):
                RunCheckpoint(
                    path,
                    metadata=metadata,
                    resume=False,
                )


if __name__ == "__main__":
    unittest.main()
