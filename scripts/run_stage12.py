"""按当前数据清单顺序运行单目标 Stage 1/2。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


STEPS = ("stage1", "embedding", "dbscan", "merge")


def select_targets(
    project_root: Path,
    corpus: str,
    requested: list[str] | None,
) -> list[str]:
    manifest = json.loads(
        (project_root / "repos" / corpus / "dataset-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    key = "projects" if corpus == "project" else "targets"
    targets = [group["name"] for group in manifest[key]]
    if not requested:
        return targets
    missing = sorted(set(requested) - set(targets))
    if missing:
        raise ValueError(f"清单中不存在目标: {missing}")
    selected = set(requested)
    return [target for target in targets if target in selected]


def build_commands(
    corpus: str,
    target: str,
    steps: tuple[str, ...],
    *,
    device: str,
    batch_size: int,
) -> list[list[str]]:
    python = sys.executable
    base = Path("outputs") / corpus / target
    stage0 = base / "stage0" / "dataset.pkl"
    fragments = base / "stage1" / "fragments.pkl"
    embeddings = base / "stage2" / "embeddings.pkl"
    raw_clusters = base / "stage2" / "clusters-raw.pkl"
    commands = {
        "stage1": [
            python,
            "-m",
            "src.parser.fragment_builder",
            "--input",
            str(stage0),
            "--output",
            str(fragments),
            "--model",
            "unixcoder",
            "--local-files-only",
        ],
        "embedding": [
            python,
            "-m",
            "src.mining.code_embedding",
            "--input",
            str(fragments),
            "--output",
            str(embeddings),
            "--model",
            "unixcoder",
            "--device",
            device,
            "--batch-size",
            str(batch_size),
        ],
        "dbscan": [
            python,
            "-m",
            "src.mining.dbscan_tuning",
            "--input",
            str(embeddings),
            "--output",
            str(raw_clusters),
            "--report",
            str(base / "stage2" / "dbscan-tuning.json"),
        ],
        "merge": [
            python,
            "-m",
            "src.mining.cluster_merge",
            "--clusters",
            str(raw_clusters),
            "--embeddings",
            str(embeddings),
            "--output",
            str(base / "stage2" / "clusters.pkl"),
            "--report",
            str(base / "stage2" / "cluster-merge-report.json"),
        ],
    }
    return [commands[step] for step in steps]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", choices=("project", "library"), required=True)
    parser.add_argument("--target", action="append", help="目标名；可重复，省略时运行全部")
    parser.add_argument(
        "--steps",
        default=",".join(STEPS),
        help="逗号分隔：stage1,embedding,dbscan,merge",
    )
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()

    requested_steps = set(args.steps.split(","))
    unknown_steps = sorted(requested_steps - set(STEPS))
    if unknown_steps:
        raise ValueError(f"未知步骤: {unknown_steps}")
    steps = tuple(step for step in STEPS if step in requested_steps)
    project_root = Path(__file__).resolve().parents[1]
    targets = select_targets(project_root, args.corpus, args.target)
    environment = {
        **os.environ,
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }

    for target in targets:
        print(f"==> {args.corpus}/{target}: {','.join(steps)}", flush=True)
        for command in build_commands(
            args.corpus,
            target,
            steps,
            device=args.device,
            batch_size=args.batch_size,
        ):
            subprocess.run(
                command,
                cwd=project_root,
                env=environment,
                check=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
