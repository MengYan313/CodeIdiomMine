"""Check that the reusable infrastructure matches another project checkout."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


SHARED_PATHS = (
    ".env.example",
    "src/common/logging.py",
    "src/common/model_config.py",
    "src/logger.py",
    "src/llm/__init__.py",
    "src/llm/agent.py",
    "src/llm/client.py",
    "src/llm/config.py",
    "src/llm/message.py",
    "src/llm/utils.py",
    "src/agents/base.py",
    "tests/common/test_shared_infrastructure.py",
    "docs/guides/shared-development-conventions.md",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--other", type=Path, required=True)
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    other_root = args.other.expanduser().resolve()
    mismatches = []

    for relative_path in SHARED_PATHS:
        local_path = project_root / relative_path
        other_path = other_root / relative_path
        if not local_path.is_file() or not other_path.is_file():
            mismatches.append(f"missing: {relative_path}")
        elif sha256(local_path) != sha256(other_path):
            mismatches.append(f"different: {relative_path}")

    if mismatches:
        print("shared_infrastructure_ok=False")
        for mismatch in mismatches:
            print(mismatch)
        return 1

    print(f"shared_infrastructure_ok=True files={len(SHARED_PATHS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
