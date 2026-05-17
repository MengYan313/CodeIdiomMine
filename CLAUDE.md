# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CodeIdiomMine mines recurring "code idioms / programming patterns" from C++/Python/Java/JS repositories and synthesizes code templates, using an LLM + multi-agent (AutoGen) pipeline. Python 3.14, conda env `cim`, default LLM `gpt-4o-mini`.

`README.md` describes an older top-level layout (no `src/`, `agent/`, `eval/`) and is partially outdated — trust the code and `src/agent/README.md` over it. `doc/专利初稿.md` and `doc/项目准备与面试问答.md` are reference-only background; the code (which heavily cites "说明书 7.2/7.3/7.4") is the source of truth and may diverge from them.

## Running things

**Everything runs as a module from the repo root** (`/home/wenxinyao/zju-pro/CodeIdiomMine`). All modules use relative imports with no `sys.path` hacks, so `python src/.../x.py` fails with `ImportError: attempted relative import`. Always:

```bash
conda activate cim
cd /home/wenxinyao/zju-pro/CodeIdiomMine
python -m src.<pkg>.<module> [args]      # e.g. python -m src.parser.repo2data --help
```

Each module file ends with a comment showing its exact foreground / `nohup` command. Agent-stage modules can also be run standalone for self-test (e.g. `python -m src.agent.semantic_clarity_agent`).

Pipeline (each stage consumes the previous stage's pickle):

```bash
python -m src.parser.repo2data    --input repo/cpp --output output/cpp/dataset.pkl --language cpp
python -m src.mining.code_embedding --input output/cpp/dataset.pkl --output output/cpp/embeddings.pkl --model unixcoder
python -m src.mining.clustering   --input output/cpp/embeddings.pkl --output output/cpp/clusters.pkl   # --optimize for Bayesian DBSCAN tuning
python -m src.agent.idiom_judgement --input output/cpp/clusters.pkl --output-dir result/cpp [--limit 5 -q]
python -m src.agent.idiom_synthesis --input-dir result/cpp --output-dir result/cpp
python -m src.eval.idiom_metrics  --language cpp
```

`src/utils/pkl2csv.py` converts any stage's `.pkl` to `.csv` for inspection.

There is no build step and no test runner wired up: `tests/` currently contains only `fixtures/` and stale `.pyc` files (no runnable `.py` sources in the tree).

## Configuration

Repo-root `.env` (gitignored) supplies `OPENAI_API_KEY` and `OPENAI_BASE_URL`; entry modules auto-load it via `python-dotenv`. Agent stages raise `RuntimeError` if `OPENAI_API_KEY` is unset. `requirements.txt` omits the AutoGen stack — also install: `pip install autogen-core autogen-ext python-dotenv`.

Logging: `src/logger.py::get_logger(__name__)` → console at INFO (message-only format), file at DEBUG written to `logs/<full.module.name>.log`. **File handlers use `mode='w'`, so each run overwrites that module's log.** `logs/`, `output/`, `result/`, `doc/`, `.env` are all gitignored (pipeline artifacts never enter the repo).

## Architecture

### Data flow (pickle schemas matter)

Stages pass `pandas`/`list` pickles whose exact shapes other stages depend on:

- **dataset.pkl** — DataFrame `project`, `cppFile` (2D project→file paths; column name is historical, language-agnostic), `func_ast` (3D project→file→function; each function = depth-first list of node_info dicts), `func_src` (3D, same shape, source strings). node_info key fields: `depth`, `extent` (`"sl-sc-el-ec"`, 1-based lines / 0-based cols), `kind` (tree-sitter type), `code_snippet` (comments/blank lines stripped), `ast_num` (direct child count).
- **embeddings.pkl** — DataFrame `pros_name`, `pros_src` (2D), `pros_emb` (2D `torch.Tensor`, mean-pooled, CPU), `pros_info` (2D; each elem `[pro_name, file_name, extent_root, node_info]`).
- **clusters.pkl** — `list[{pros_name, clusters: DataFrame}]`; DataFrame cols `label, center_point, else_point, cluster_size, center_point_info, infos, loc_label` where `loc_label = "{proj}-{file}-{extent_root}"`.
- **{repo}_idiom.pkl** — `list[{center_point, info, cnt, avg_ast_num, loc_label}]`.
- **{repo}_idiom_syn.pkl** — `list[{center_point, loc_label, info, source_infos, cnt, avg_ast_num, merge_rounds, synthesis_trace}]`.
- **eval.json** — per-project + summary `IC` / `ISP` (leave-one-out) / `F1` / `avg_idiom_size`.

### Multi-language extension point

`src/common/node_kinds.py` maps each language to func/block/stmt tree-sitter node-type sets. Adding a language means editing three places consistently: `node_kinds.py` (the maps), `ast_parser._init_parser` (load the `tree_sitter_<lang>` grammar), and `file_scanner.LANGUAGE_EXTENSIONS` (extensions). The scanner skips dirs containing `test/__pycache__/.git/.svn` and filenames containing `test` (except for Python).

### Agent subsystem (`src/agent/`)

Built directly on **`autogen_core`** (not `autogen_agentchat`): `RoutedAgent` + `@message_handler` with strongly-typed `@dataclass` Request/Result; `SingleThreadedAgentRuntime`; agents registered via `register_factory(name, lambda: Agent(model_client))` and addressed via `AgentId(name, key="default")`. Model client is `autogen_ext`'s `OpenAIChatCompletionClient`; all calls use `temperature=0.0`. Every agent prompts for a `[JSON]...[/JSON]` block parsed by `src/utils/response_parser.py::extract_tag_content`, with a safe default + logged warning on parse failure. See `src/agent/README.md` for the full design rationale and **`src/agent/CLAUDE.md`** for the post-refactor shared-infra contract.

Shared boilerplate lives in **`src/agent/_base.py`**: `load_project_env()` (idempotent `.env` load), `create_model_client(model)`, `JsonLLMAgent` (RoutedAgent base owning `_model_client`/`_system_message`; `await self.ask_json(prompt)` does temperature-0 call → `[JSON]` extract → `json.loads` → `None` on failure), and `run_agent_selftest(...)` (replaces the per-file `__main__` harnesses). Each of the 5 agents now only declares its system prompt, builds the user prompt, and maps the dict (or `None` → per-agent defaults) to its result dataclass — prompts, score thresholds and default values are unchanged from before the refactor.

Two subsystems intentionally use **separate runtimes**:

- **Judgement** (`judge_pipeline.py::CodeIdiomPipeline`, "说明书 7.2"): `semantic_clarity_agent` + `syntax_logic_agent` run in parallel via `asyncio.gather`, then `idiom_judge_agent` synthesizes. **Critical:** the final `is_idiom` is NOT the LLM's answer — it is decided by `idiom_judge_agent.patent_programming_pattern_valid(semantic_score, syntax_score)` (higher score ≥ 70 AND lower ≥ 50). When the rule disagrees with the LLM, confidence becomes the mean of the two scores and the raw LLM verdict is kept as `final_judgment["llm_is_idiom"]`. `quiet=True` suppresses step logging for reuse during synthesis. Lifecycle: `initialize()` / `evaluate(code)` / `shutdown()`.
- **Synthesis** (`idiom_synthesis.py`, "说明书 7.3 + 7.4"): its own runtime with `planning_synthesis_agent` + `code_assembly_agent`, PLUS a second `CodeIdiomPipeline(quiet=True)` for post-merge re-judgement. Per `loc_label` group (≥ 2 entries), anchored on the first entry, it loops up to `MAX_SYNTHESIS_ITERATIONS` (= 3): plan which candidate indices to merge → assemble → re-judge; on invalid it stops and keeps the last valid merge; a group with no successful merge produces no record.

`src/llm/` (`LLMConfig`, `LLMClient`, `MessageBuilder`, …) is a separate AutoGen wrapper that the judgement/synthesis agents do **not** use — they call `autogen_ext` directly. Do not conflate the two when modifying agents.
