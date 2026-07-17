# AGENTS.md

## Cross-project unified development contract

This repository and its sibling repository remain independent, but reusable infrastructure must follow the same contract. Before changing logging, LLM wrappers, AutoGen setup, directory roles, or test organization, read `docs/guides/shared-development-conventions.md` and update both repositories' shared files together.

Mandatory conventions:

- Use `repos/` for local source-repository inputs, `outputs/` for reproducible intermediates, `results/` for final artifacts, `logs/` for run logs, `tests/` for tests, and `docs/` for versioned documentation. Keep `repos/` ignored and untracked; do not add a duplicate `inputs/` alias.
- New logging imports use `from src.common.logging import get_logger`. One command writes all module logs to append-only `logs/<run-name>.log`; `src.logger` is compatibility-only.
- LLM code imports shared APIs from `src.llm`. Root `.env` loading, model tiers, GPT-5.6 metadata, client creation, JSON mode, schema validation, one-shot JSON repair, and client closure stay centralized there. Low tier is the only implicit default.
- Business prompts and explanatory fields use Chinese; retain English only for code, model/API names, necessary technical terms, and JSON field names. Structured calls build stable system prompts with `build_json_system_prompt(...)`, use native JSON mode plus explicit JSON Schema, and never use `[JSON]` or domain marker wrappers.
- AutoGen code uses `SingleThreadedAgentRuntime`, strong messages, `BaseRoutedAgent`, `register_agent(...)`, `default_agent_id(...)`, and a `start -> try/finally -> stop` lifecycle. Agents communicate through routed messages.
- Keep offline tests deterministic and free of downloads or paid calls. Real LLM tests require an explicit model, bounded call count, cost/privacy review, and separate smoke outputs.
- Run `.venv/bin/python scripts/check_shared_infrastructure.py --other ../<sibling>` after changing a shared file. The two projects may keep different verified Python minor versions and different domain packages.

This file applies to the entire `/Users/sophon/Codex/CodeIdiomMine` repository.

## Mission and scope

CodeIdiomMine mines recurring code idioms from C++ repositories. The current implementation uses Tree-sitter C++, pretrained-code embeddings, DBSCAN, and an AutoGen-based judgment/synthesis subsystem.

The immediate engineering baseline is the existing repository, not the proposed thesis implementation. The runtime and public CLIs are deliberately C++-only: do not reintroduce language selectors, non-C++ grammar dependencies, or language dispatch without explicit user authorization. Preserve the Tree-sitter C++ parser, DBSCAN clustering, Agent layout, data schemas, prompts, thresholds, and historical model settings unless the user explicitly authorizes a scoped change.

The following version-controlled research documents are required background, but they are not current implementation specifications:

- `docs/research/01_C++代码习语挖掘研究稿.md` — proposed C++ thesis route, experiments, baselines, ablations, and metrics.
- `docs/research/03_面向代码可复用性增强的融合研究方案.md` — thesis-level relationship between CodeIdiomMine and WPF2React. The two repositories remain independent and must not be merged merely because the thesis discusses both.

## Required reading and source of truth

Before changing behavior, read the relevant source plus:

1. `AGENTS.md` and `README.md`.
2. `docs/guides/shared-development-conventions.md` for the contract shared with WPF2React.
3. `docs/guides/local-baseline.md` for the verified local environment and evidence.
4. `docs/guides/repository-architecture.md` for repository-level architecture.
5. `docs/guides/agent-system.md` and `docs/guides/agent-contracts.md` for Agent design and modification contracts.
6. `docs/guides/testing.md` for the validation ladder and current commands.
7. The two research documents above when a task concerns thesis alignment.

When documentation conflicts, prefer verified source behavior, then the guides above. Record confirmed discrepancies in `docs/guides/local-baseline.md` instead of silently rewriting behavior.

Choose directory names by semantic role and established Python conventions, not by a blanket plural rule. The source packages are `agents`, `common`, `evaluation`, `llm`, `mining`, `parser`, and `utils`; `agents` and `utils` are intentionally plural, while process/domain packages remain singular. `research` is uncountable. Collection/artifact roots remain the conventional `tests`, `repos`, `outputs`, `results`, `logs`, and `guides`. Keep `src` as the conventional source-root abbreviation, `cpp` as a language qualifier, and `.venv` as the requested virtual-environment convention. Test subdirectories must mirror the seven `src` packages exactly.

## Local Python environment

- Host: Apple Silicon macOS (`arm64`).
- System Python: `/usr/bin/python3` 3.9.6. Never modify it or install project packages into it.
- Selected interpreter: Homebrew Python 3.12.10 at `/opt/homebrew/bin/python3.12`.
- Project environment: `/Users/sophon/Codex/CodeIdiomMine/.venv`.
- Activate with `source .venv/bin/activate`, or call `.venv/bin/python` explicitly.
- Create the environment, if missing, with `/opt/homebrew/bin/python3.12 -m venv .venv`.
- `requirements.txt` is the install policy for both the C++ pipeline and Agent stack; keep `autogen-ext[openai]` (not the bare extra-less package) because the shared client imports the OpenAI adapter.
- `requirements-local.lock` is the exact 2026-07-15 environment snapshot. Do not treat it as an upstream dependency policy without user approval; update it only after a deliberate environment change and successful validation.

Python 3.12 was selected for mature arm64 wheels across the full existing stack. Python 3.14 was mentioned by pre-normalization repository docs but was not selected: the local Homebrew installation has no `python@3.14` formula, and the repository has no feature requiring 3.14. See `docs/guides/local-baseline.md` for the candidate comparison and evidence.

## Running the repository

Run everything as a module from the repository root. Direct execution such as `python src/parser/repo2data.py` breaks relative imports.

```bash
.venv/bin/python -m src.parser.repo2data \
  --input repos/cpp --output outputs/cpp/dataset.pkl

.venv/bin/python -m src.mining.code_embedding \
  --input outputs/cpp/dataset.pkl --output outputs/cpp/embeddings.pkl \
  --model unixcoder

.venv/bin/python -m src.mining.clustering \
  --input outputs/cpp/embeddings.pkl --output outputs/cpp/clusters.pkl

.venv/bin/python -m src.agents.idiom_judgement \
  --input outputs/cpp/clusters.pkl --output-dir results/cpp

.venv/bin/python -m src.agents.idiom_synthesis \
  --input-dir results/cpp --output-dir results/cpp

.venv/bin/python -m src.evaluation.idiom_metrics
```

`src/utils/pkl2csv.py` is available as `.venv/bin/python -m src.utils.pkl2csv ...`.

## Validation ladder

Use the cheapest relevant checks first:

1. `.venv/bin/python -m pip check`.
2. `.venv/bin/python -m compileall -q src`.
3. `.venv/bin/python -m unittest discover -s tests -t . -v`.
4. Import the affected packages and run the affected module's `--help` entry.
5. Use a minimal repository input before processing `repos/cpp` in full.
6. Reuse the cached UniXcoder model when possible. A clean machine downloads roughly 738 MB into the Hugging Face cache in the currently resolved stack.
7. Run DBSCAN on minimal embeddings before enabling `--optimize` (50 Bayesian-optimization calls).
8. Agent smoke tests may use deterministic fake model clients to verify routing and schemas. Real judgment/synthesis requires `OPENAI_API_KEY` and makes paid network calls; state model, call count, likely cost, and privacy implications before running.

The repository has an offline `unittest` suite under `tests/`. Its subdirectories mirror `src/`; keep tests deterministic and free of model downloads or paid API calls by default.

## Sensitive information and external services

- `.env` is ignored and currently contains local intermediary credentials plus `OPENAI_MODEL_LOW=gpt-5.6-luna`, `OPENAI_MODEL_MEDIUM=gpt-5.6-terra`, and `OPENAI_MODEL_HIGH=gpt-5.6-sol`. Never print, commit, or copy secret values or endpoint values into logs or documentation; keep only placeholders in `.env.example`.
- Current code defaults exclusively to `OPENAI_MODEL_LOW`; the medium and high tiers are configured but must not be selected without an explicit later task.
- Treat source snippets sent to an LLM endpoint as external disclosure. Confirm the endpoint and scope before using non-public code.
- Explain download size and runtime before downloading a new embedding model. Do not download CodeLLaMA or run full-repository embeddings/parameter optimization without explicit scope.

## Confirmed architecture and data contracts

- Parser output `dataset.pkl`: DataFrame columns `project`, `cppFile`, `func_ast`, `func_src`. `cppFile` remains the historical C++ path field.
- Embedding output `embeddings.pkl`: DataFrame columns `pros_name`, `pros_src`, `pros_emb`, `pros_info`; embeddings are CPU `torch.Tensor` objects.
- Clustering output `clusters.pkl`: list of `{pros_name, clusters}`; cluster DataFrame columns are `label`, `center_point`, `else_point`, `cluster_size`, `center_point_info`, `infos`, `loc_label`.
- Judgment output `{repo}_idiom.pkl`: records with `center_point`, `info`, `cnt`, `avg_ast_num`, `loc_label`.
- Synthesis output `{repo}_idiom_syn.pkl`: adds `source_infos`, `merge_rounds`, and `synthesis_trace`.
- Evaluation output `eval.json`: per-project and summary `IC`, `ISP`, `F1`, `avg_idiom_size`.

The Agent subsystem uses `autogen_core` directly. Judgment runs semantic and syntax agents concurrently, then calls the judge agent. Final `is_idiom` is determined by `patent_programming_pattern_valid`: the higher score must be at least 70 and the lower at least 50. The raw LLM verdict is explanatory only. Synthesis uses a separate runtime and a second quiet judgment pipeline; it performs at most three merge rounds and retains only successful merges.

`src/llm/` owns the shared configuration, model-client factory, strict JSON parsing, lightweight schema validation, and one-shot LLM repair. The judgment/synthesis path consumes its raw AutoGen client while `src/agents/` retains all C++ idiom prompts, domain schemas, thresholds, and orchestration.

## Local artifacts and known observations

- Durable minimal C++ parser/real-UniXcoder/DBSCAN artifacts are under ignored `outputs/baselines/cpp/`.
- Fake-client Agent/evaluation artifacts are under ignored `results/baseline-stubs/cpp/` and are never research results.
- The bounded real-LLM smoke used only synthetic snippets. Inputs and readable evidence are under ignored `outputs/llm-smoke/`; judgment, synthesis input, and synthesis output are under ignored `results/llm-smoke/`. These prove endpoint wiring and schemas only and are not research results.
- All modules in one command append to ignored `logs/<run-name>.log`; importing sibling packages no longer truncates prior evidence. Use `APP_LOG_NAME` or `run_name=` only when automatic entry-point naming is insufficient.
- Running several `python -m` entries emits a `runpy` warning because package `__init__.py` files eagerly import the same target modules. The entries still passed the baseline tests; do not fix this without a requested source change.

Full commands, versions, outcomes, blockers, and research differences are maintained in `docs/guides/local-baseline.md`. Update that file when a later task changes the verified baseline.

## Change discipline

- Preserve user changes and inspect Git status before and after work.
- Do not modify algorithms, prompts, score thresholds, pickle schemas, or corpus filtering just to make a smoke test pass.
- Do not use the research drafts to infer a broad refactor. Thesis alignment starts only when the user specifies a concrete scope.
- Save commands, versions, input scope, output paths, and failures for every experiment. Keep mock/stub artifacts clearly labeled.
- Do not commit, push, or stage files unless the user requests it.
