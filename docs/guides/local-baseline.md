# CodeIdiomMine local development baseline

Last verified: 2026-07-17 (Asia/Shanghai)

This is the durable project memory for the existing implementation. It records observed facts and reproducible smoke tests; it is not a claim that the code implements the thesis proposals.

## Repository and host

- Working tree: `/Users/sophon/Codex/CodeIdiomMine`.
- Git branch/base: `master`, commit `260e7c2bc949b30b3745f934a9968432ab679af2`, aligned with `origin/master` before local initialization documentation.
- Initial tracked worktree: clean. `AGENTS.md` already existed as an untracked copy of the former root `CLAUDE.md`; it was updated during initialization rather than discarded.
- OS: macOS 26.5.2 (build 25F84), Darwin arm64, Apple Silicon.
- Command Line Tools: `/Library/Developer/CommandLineTools`; Apple clang 21.0.0.
- Available disk at initialization: about 42 GiB.
- Existing version tools: Homebrew at `/opt/homebrew/bin/brew`; no conda, pyenv, or uv on `PATH`.
- Existing system interpreter: `/usr/bin/python3` 3.9.6.
- No `.env` and no existing project venv were present.

The research documents are now organized under the version-controlled `docs/research/` directory:

- `docs/research/01_C++代码习语挖掘研究稿.md`
- `docs/research/03_面向代码可复用性增强的融合研究方案.md`
- `docs/research/Idiom_Mining_II.pdf`

Before the 2026-07-16 structure normalization, `doc/` was ignored, so the two Markdown research drafts were invisible to Git while the PDF happened to be tracked. The directory was first renamed to `docs/` and released from `.gitignore`; the final category names are `guides/` and the uncountable `research/`.

## Python selection

| Candidate | Assessment |
|---|---|
| macOS Python 3.9.6 | Source syntax is mostly compatible, but current Tree-sitter and AutoGen releases require at least 3.10. It is also an OS-managed interpreter and was rejected for project packages. |
| Python 3.11 | Mature and expected to work, but offers no compatibility advantage over 3.12 for this stack. |
| Python 3.12 | Selected. The complete parser, scientific, PyTorch, Transformers, and AutoGen stack resolved to native macOS arm64 wheels and passed imports and smoke tests. |
| Python 3.13 | Plausible, but newer than necessary for reproducing this unpinned 2026 codebase. No repository feature requires it. |
| Python 3.14 | Claimed by the pre-normalization `README.md` / `CLAUDE.md`, but not required by source. Local Homebrew reported no `python@3.14` formula. Although current PyTorch publishes a 3.14 arm64 wheel, choosing it would expose the rest of the unpinned stack to a newer compatibility surface without a project benefit. |

Final interpreter and environment:

- Homebrew formula: `python@3.12 3.12.10_1`.
- Interpreter: `/opt/homebrew/bin/python3.12` (resolves under `/opt/homebrew/opt/python@3.12/...`).
- Project venv: `/Users/sophon/Codex/CodeIdiomMine/.venv`.
- Venv Python: 3.12.10 arm64.
- Packaging tools: pip 26.1.2, setuptools 83.0.0, wheel 0.47.0.
- Initial creation command: `/opt/homebrew/bin/python3.12 -m venv venv`; the environment was relocated to `.venv` on 2026-07-17 as recorded below.
- The installation did not replace or relink `/usr/bin/python3`.
- No Python-version fallback occurred: the selected 3.12 environment installed every key dependency from a wheel. Python 3.14 was a rejected candidate, not a failed installation attempt.

Homebrew's automatic post-install cleanup removed the obsolete `/opt/homebrew/Cellar/tomcat/11.0.6` (3 files, about 16.3 KiB) and stale Homebrew caches. A follow-up check confirmed that Tomcat 11.0.7 remained installed and linked, with `/opt/homebrew/etc/tomcat` still used for configuration. No project file was affected.

The first in-sandbox pip attempt failed with `ProxyError: Operation not permitted`, as expected under network restrictions. Re-running the same venv-only installation with approved network access succeeded. This was a sandbox/network retry, not a package compatibility fallback.

On 2026-07-17, `venv/` was moved to `.venv/` without reinstalling dependencies. `/opt/homebrew/bin/python3.12 -m venv --upgrade .venv` refreshed the standard environment metadata, and 26 generated scripts that still contained the old absolute prefix were rewritten to the new prefix. `.venv/bin/python` reports `sys.prefix=/Users/sophon/Codex/CodeIdiomMine/.venv`, direct `.venv/bin/pip` works, no old prefix remains under `.venv/bin`, and `pip check` still reports no broken requirements.

## Dependency state

Installed from `requirements.txt` plus the source-required omissions:

```bash
.venv/bin/python -m pip install -r requirements.txt \
  autogen-core 'autogen-ext[openai]' python-dotenv
```

`autogen-ext[openai]` was used instead of the bare package because the code imports `autogen_ext.models.openai.OpenAIChatCompletionClient`.

Key resolved versions:

- pandas 3.0.3, NumPy 2.5.1
- Tree-sitter 0.26.0; required C++ grammar 0.23.4. The initialized venv also still contains the former Python 0.25.0, Java 0.23.5, and JavaScript 0.25.0 grammar packages, but the C++-only code and `requirements.txt` no longer use or require them.
- PyTorch 2.13.0, Transformers 5.13.1
- scikit-learn 1.9.0, scikit-optimize 0.10.2, SciPy 1.18.0
- autogen-core 0.7.5, autogen-ext 0.7.5, OpenAI SDK 2.45.0
- python-dotenv 1.2.2

`.venv/bin/python -m pip check` reports `No broken requirements found`. The complete exact snapshot is `requirements-local.lock`; it was not regenerated for the C++-only source change because no installed package was added, removed, or upgraded.

PyTorch is built with MPS support but `torch.backends.mps.is_available()` returned `False` in this execution environment; CUDA is also unavailable. More importantly, current `CodeEmbedder` only auto-selects CUDA or CPU, so the verified existing path is CPU even on Apple Silicon.

The UniXcoder download populated approximately 738 MiB under `/Users/sophon/.cache/huggingface`. No Hugging Face token was configured; the download used anonymous access.

## Documentation management

- On 2026-07-16, root documentation was reduced to `README.md` and `AGENTS.md`; secondary material first moved to `docs/development/`, and research material first moved to `docs/research/`.
- On 2026-07-17, development documents became the collection `docs/guides/`; research material uses the uncountable category `docs/research/`. `docs/README.md` remains the canonical documentation index.
- The root `README.md`, architecture guide, and testing guide were rewritten to remove stale top-level module paths, direct-script commands, conda/Python 3.14 assumptions, `log/` paths, CodeLLaMA-default claims, and nonexistent editable-install instructions.
- Source package names now follow semantic Python conventions: `agents`, `common`, `evaluation`, `llm`, `mining`, `parser`, and `utils`. Runtime artifact collections remain `repos`, `outputs`, `results`, and `logs`.
- `tests/` now mirrors all seven `src/` packages and contains offline `unittest` coverage rather than empty placeholders. `src/`, `cpp/`, and `.venv/` remain intentional non-collection conventions.
- The research drafts link to `docs/references/英文文献库.md` and `docs/references/中文文献库.md`, neither of which exists in this checkout. Their links remain unresolved and are documented rather than replaced with fabricated bibliography content.
- `requirements.txt` keeps broad lower bounds for scientific/parser packages and now declares the verified AutoGen OpenAI stack plus python-dotenv. The C++-only simplification removed the unused Python, Java, and JavaScript grammar requirements.

## C++-only simplification

On 2026-07-16 the user explicitly replaced the multilingual runtime surface with a C++-only one. The change intentionally preserves the established C++ algorithms, filters, paths, prompts, thresholds, and artifact schemas while removing language dispatch:

- `src/common/node_kinds.py` now exposes only the fixed C++ function/block/statement sets.
- `ASTParser()` and `FileScanner()` take no language argument; the parser always loads `tree-sitter-cpp`, and the scanner retains the previous C++ extensions and test filtering behavior.
- `parse_repository`, `get_pros_src_and_embedding`, and `generate_embeddings` no longer accept a language parameter.
- parser, embedding, and evaluation CLIs no longer expose `--language`; evaluation is provided as `evaluate_cpp` and still writes `"language": "cpp"` in `eval.json` for schema continuity.
- `repos/cpp`, `outputs/cpp`, and `results/cpp` remain fixed existing path contracts rather than dynamic language namespaces.
- Agent system prompts and deterministic score/merge rules were not changed.

This is a scope simplification of the verified implementation, not an implementation of the proposed Clang/HDBSCAN/four-stage thesis system. Reintroducing another language now requires an explicitly approved architecture change.

## Semantic directory and test normalization

On 2026-07-17 the user explicitly authorized a repository-wide public path migration. An initial pass mechanically pluralized every source package:

- `src/{agent,common,eval,llm,mining,parser}` became `src/{agents,commons,evaluators,llms,miners,parsers}`; relative imports, public module CLIs, logger examples, docs, and defaults were updated together.
- `repo/`, `output/`, and `result/` became `repos/`, `outputs/`, and `results/`; existing ignored corpora and artifacts were moved rather than regenerated.
- `docs/development/` and `docs/research/` temporarily became `docs/guides/` and `docs/researches/`.
- Local artifact collections were normalized to `outputs/baselines/`, `results/baseline-stubs/`, `outputs/cpp/readables/`, and `outputs/cpp/records/`.
- The project environment became `.venv/`, as detailed in the Python section above.
- A mirrored seven-package `tests/` tree was added with deterministic tests for parser/scanner behavior, DBSCAN schema, score thresholds, metrics, message building, response parsing, and artifact export.

The blanket plural interpretation was subsequently corrected in the same task sequence. The final public packages are `src/{agents,common,evaluation,llm,mining,parser,utils}` and the mirrored `tests/{agents,common,evaluation,llm,mining,parser,utils}`. `docs/researches/` returned to the idiomatic uncountable `docs/research/`. This preserves plural names where they describe genuine collections (`agents`, `utils`, `guides`) and uses singular process/domain names elsewhere.

After this correction, `pip check`, `compileall`, combined imports of all seven packages, all seven public CLI help entries, and the complete 21-test offline suite passed. `tests/mining/test_mining.py` was renamed with its process package. No compatibility aliases for the mechanically plural package paths were retained, so stale imports fail instead of silently preserving the wrong public naming.

The first test run passed 14 of 15 tests. The only failure was an incorrect new assertion that expected `(69.9, 100)` to fail the established `high >= 70 and low >= 50` rule; the rule correctly returned true. The test input was corrected to `(69.9, 69.9)` without changing business logic. The final result is recorded after the full validation run.

Final validation passed all 15 tests, `compileall` for both `src` and `tests`, combined imports of all seven public packages, and every renamed CLI help entry. Parser, embedding, and evaluation still expose no language selector. The existing `runpy` warnings remain limited to eager package imports. The full local readable projection was regenerated from the existing PKL files, and its manifest now records `.venv`, `outputs/cpp`, `results/cpp`, and `outputs/cpp/readables` consistently.

## Current corpus and pipeline

`repos/cpp` is about 67 MiB and contains three source snapshots, not nested Git repositories:

| Project | Files selected by current `FileScanner()` |
|---|---:|
| envoy | 2,924 |
| qBittorrent | 465 |
| react-native | 1,415 |
| Total | 4,804 |

The scanner count applies the current path/name filtering and is smaller than the 7,078 C/C++-extension files found without that filtering. `TrafficMonitor`, listed in the research plan, is absent.

Verified data flow:

```text
repos/cpp/<project>/...
  -> dataset.pkl
  -> embeddings.pkl
  -> clusters.pkl
  -> {repo}_idiom.pkl
  -> {repo}_idiom_syn.pkl
  -> eval.json
```

The exact schemas and command forms are recorded in `AGENTS.md` and current source.

## Baseline checks and results

### Static/import/CLI checks

- `.venv/bin/python -m compileall -q src`: passed.
- Imports of `src.common`, `src.parser`, `src.mining`, `src.agents`, `src.evaluation`, `src.llm`, and `src.utils`: passed.
- Instantiation of the fixed C++ Tree-sitter parser: passed.
- `--help` passed for parser, embedding, clustering, judgment, synthesis, evaluation, and pkl-to-CSV modules.
- Current package `__init__.py` files eagerly import public symbols. Running the same modules via `python -m` consequently emits `RuntimeWarning: ... found in sys.modules ... prior to execution`. Entries still completed successfully. This is a source observation, not fixed during initialization.

One concurrent first-import attempt appeared stuck in a deep `transformers -> sklearn` import and was interrupted after roughly 40 seconds. Individual sequential imports then completed normally (approximately 0.07 s NumPy, 0.92 s PyTorch, 1.08 s scikit-learn, 0.70 s AutoGen, 3.21 s Transformers), and the combined sequential package import completed in about 3.33 s. This was classified as concurrent cold-start contention, not a dependency failure.

### C++-only post-change validation

The C++-only API and CLI change was revalidated on 2026-07-16:

- `.venv/bin/python -m pip check`: passed with `No broken requirements found`; pip also printed the existing sandbox cache-ownership warning and disabled its cache for that command.
- `.venv/bin/python -m compileall -q src`: passed.
- Combined imports of all public packages passed. `ASTParser()` initialized `tree-sitter-cpp`; introspected signatures confirmed that `ASTParser`, `FileScanner`, parser, embedding, and evaluation APIs no longer accept a language selector.
- `--help` passed for parser, embedding, and evaluation, and none exposed `--language`. The known eager-import `runpy` warnings remain unchanged.
- Temporary validation root: `/private/tmp/codeidiommine-cpp-only.XLiBRB/`. The first fixture attempt used broken symlinks because `packages/react-native/` was omitted from the React Native source path; the parser therefore reported both files missing and wrote a valid zero-file dataset. After correcting only the temporary symlinks, the same command parsed 1 synthetic project, 2 C++ files, and 4 functions with the expected dataset schema.
- A deterministic dummy embedder selected 2 snippets, wrote the existing embedding schema, and default DBSCAN produced one two-member cluster with no noise. No model download or network request occurred.
- The fixed evaluation CLI consumed `outputs/baselines/cpp/dataset.pkl` and `results/baseline-stubs/cpp/sample_idiom.pkl`, reproduced `IC=0.25`, `ISP=0.0`, `F1=0.0`, `avg_idiom_size=731.0`, and retained `"language": "cpp"` in the temporary `eval.json`.
- No real Agent or paid API call was made.

### Minimal C++ parser

Input used two symlinks to tracked React Native files:

- `ReactCommon/cxxreact/MethodCall.cpp`
- `ReactCommon/cxxreact/JSBundleType.cpp`

Results:

- 1 synthetic project, 2 source files, 4 parsed functions.
- `dataset.pkl`: DataFrame shape `(1, 4)` with the expected columns.
- Durable artifact: `outputs/baselines/cpp/dataset.pkl` (about 74 KiB).

### Embedding and clustering

A deterministic dummy embedder first verified snippet filtering and the pickle/DBSCAN path without network. With `min_nodes=10`, `min_ast_num=5`, and `min_project_size=1`, it selected 2 snippets and formed one DBSCAN cluster.

The real existing embedding path was then run with `microsoft/unixcoder-base`, `--device cpu`, and `--min-project-size 1`:

- Model download/cache: approximately 738 MiB in the resolved Hugging Face stack.
- Output: 2 CPU tensors, each shape `(1, 768)`.
- First networked run loaded the model, completed inference, and wrote the pickle, but the process then waited in `threading._shutdown` for more than 30 seconds. Interrupting only the shutdown wait produced `KeyboardInterrupt` in `threading.py`; the command's artifact was intact.
- A second run using the populated cache with `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` exited normally. The shutdown wait was therefore classified as a first-download cleanup event, not a recurring embedding failure.
- Real default DBSCAN (`eps=0.5`, `min_samples=2`) produced 1 cluster with 2 members and no noise.
- Durable artifacts: `outputs/baselines/cpp/embeddings.pkl` (about 10 KiB) and `outputs/baselines/cpp/clusters.pkl` (about 3.9 KiB).

At initialization, full `repos/cpp` embedding had not yet been attempted. The later full-corpus run below supersedes that deferral while retaining the minimal artifacts as smoke-test fixtures.

### Full three-project parser, embedding, and clustering run

On 2026-07-16 the existing three-project corpus was processed through the real parser, cached UniXcoder model, and DBSCAN pipeline. The run intentionally stopped before Agent judgment, so it made no LLM request, incurred no API cost, and disclosed no snippets to an LLM endpoint.

Input scope used the established `FileScanner` contract over `repos/cpp`: 2,924 Envoy files, 465 qBittorrent files, and 1,415 React Native files (4,804 total). The existing test/cache/VCS path filters were preserved.

Parser command:

```bash
.venv/bin/python -m src.parser.repo2data \
  --input repos/cpp --output outputs/cpp/dataset.pkl
```

Parser results and a post-run AST audit:

| Project | Scanned files | Files with functions | Function roots | AST nodes | `ERROR` nodes | Candidate snippets |
|---|---:|---:|---:|---:|---:|---:|
| envoy | 2,924 | 2,848 | 17,274 | 3,037,215 | 3,922 | 15,056 |
| qBittorrent | 465 | 448 | 4,737 | 696,497 | 521 | 3,623 |
| react-native | 1,415 | 1,149 | 6,484 | 716,154 | 742 | 3,062 |
| Total | 4,804 | 4,445 | 28,495 | 4,449,866 | 5,185 | 21,741 |

Every extracted function source was non-empty. `ERROR` nodes were about 0.12% of all traversed nodes, so no parser-rule change was needed. The resulting `outputs/cpp/dataset.pkl` has the required `(3, 4)` DataFrame schema and is 547,821,374 bytes.

Sequential CPU benchmarking projected roughly 20 minutes for 21,741 snippets. `CodeEmbedder.get_embeddings` was therefore added as a schema-preserving batch path: it groups similar source lengths to reduce padding, restores original order, and retains one `(1, hidden_size)` CPU tensor per snippet. Batch size 8 improved the sampled throughput from roughly 18–26 snippets/s to about 41 snippets/s. Real single/batch comparison passed `torch.allclose(atol=1e-5, rtol=1e-4)`; the existing `get_embedding` API and test doubles that only implement it remain supported.

Full embedding command, using the populated cache with network disabled:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
.venv/bin/python -m src.mining.code_embedding \
  --input outputs/cpp/dataset.pkl --output outputs/cpp/embeddings.pkl \
  --model unixcoder --device cpu --min-project-size 100 --batch-size 8
```

The real `microsoft/unixcoder-base` run produced 15,056, 3,623, and 3,062 embeddings respectively (21,741 total). All tensors are finite CPU tensors with shape `(1, 768)`; source, embedding, info counts, and project labels align. `outputs/cpp/embeddings.pkl` has the required `(3, 4)` schema and is 554,078,318 bytes. No model download or fallback occurred.

Default DBSCAN was run first as the required baseline:

```bash
.venv/bin/python -m src.mining.clustering \
  --input outputs/cpp/embeddings.pkl --output outputs/cpp/clusters.pkl \
  --eps 0.5 --min-samples 2
```

It produced only 3, 5, and 4 clusters of size at least 3 for Envoy, qBittorrent, and React Native. The largest clusters contained 14,893/15,056, 3,534/3,623, and 2,944/3,062 candidates, showing that `eps=0.5` collapsed roughly 96%–99% of each project into one cluster. This failed the requested five-cluster threshold for Envoy and React Native. The artifact was retained as `outputs/cpp/clusters-default-eps0.5-min2.pkl`.

A deterministic global `eps` sweep with `min_samples=3` diagnosed the scale without invoking the 50-call Bayesian optimizer:

| `eps` | Envoy: clusters / covered / largest | qBittorrent: clusters / covered / largest | React Native: clusters / covered / largest |
|---:|---:|---:|---:|
| 0.20 | 847 / 5,042 / 434 | 197 / 1,037 / 52 | 140 / 979 / 84 |
| 0.25 | 839 / 7,482 / 1,707 | 219 / 1,646 / 456 | 175 / 1,449 / 155 |
| 0.30 | 585 / 10,143 / 7,177 | 181 / 2,307 / 1,263 | 149 / 1,869 / 727 |

`eps=0.25` was selected as a common balance: about 45%–50% coverage, largest-cluster shares of about 5%–13%, and many clusters meeting the frequency threshold. `eps=0.20` covered only about 29%–34%; at `eps=0.30`, the largest Envoy cluster already held 47.7% of all candidates.

Final clustering command:

```bash
.venv/bin/python -m src.mining.clustering \
  --input outputs/cpp/embeddings.pkl --output outputs/cpp/clusters.pkl \
  --eps 0.25 --min-samples 3
```

Final results:

| Project | Clusters with size ≥ 3 | Covered candidates | Noise | Largest cluster |
|---|---:|---:|---:|---:|
| envoy | 839 | 7,482 | 7,574 | 1,707 |
| qBittorrent | 219 | 1,646 | 1,977 | 456 |
| react-native | 175 | 1,449 | 1,613 | 155 |

Every final cluster has size at least 3. The expected seven cluster columns, member counts, `else_point` counts, non-empty centers, and project/location metadata all passed validation. `outputs/cpp/clusters.pkl` is 7,218,515 bytes. Nonzero log snapshots are under `outputs/cpp/records/`; these ignored artifacts are local evidence, not committed research results.

### Readable artifact projections

The pipeline pickle files remain canonical because JSON/CSV cannot efficiently preserve nested AST records, cluster membership, and `torch.Tensor` types. `src/utils/export_artifacts.py` now generates disposable JSON analysis views without changing any pipeline schema.

The full-corpus views were generated with:

```bash
.venv/bin/python -m src.utils.export_artifacts \
  --input-dir outputs/cpp --output-dir outputs/cpp/readables \
  --limit 100 --cluster-top 100 --text-limit 2000 --vector-head 8 \
  --cluster-eps 0.25 --cluster-min-samples 3
```

`dataset.summary.json`, `embeddings.summary.json`, and `clusters.summary.json` cover the complete inputs. `dataset.preview.json` and `embeddings.preview.json` contain 100 records each; `clusters.top100.json` contains 100 size-ranked clusters per project (300 total). Source text is capped at 2,000 characters with an explicit truncation flag. Embedding previews retain shape, dtype, device, L2 norm, and the first eight values rather than serializing all 768 dimensions.

All six stage JSON files plus `manifest.json` passed strict JSON parsing with no `NaN`. Preview limits, text limits, per-project ranks, descending cluster order, input metadata, and the known full-pipeline counts were verified. The generated directory is under ignored `outputs/cpp/readables/`; it includes a short `README.md` and is not a pipeline input or committed research result.

The same exporter also supports optional `judgment` and `synthesis` stages by scanning `*_idiom.pkl` and `*_idiom_syn.pkl` under `--result-dir`. This path was validated against the ignored deterministic fake-client artifacts: one judgment record and one synthesis record exported with their existing fields, counts, merge round, source-info sample, and JSON-safe synthesis trace. No real Agent or LLM call was made for this validation.

### Agent judgment and synthesis

- Installed AutoGen 0.7.5 successfully ran the repository's `RoutedAgent`, `message_handler`, `SingleThreadedAgentRuntime`, `register_factory`, and `AgentId` APIs.
- 初始基线的 deterministic in-memory fake model 返回了当时协议下的有效结构化响应；当前协议已升级为原生 JSON mode、schema 校验和单次修复。该基线验证了：
  - semantic/syntax parallel evaluation and the deterministic 90/90 `is_idiom=True` gate;
  - batch judgment from the real minimal cluster to a one-record `sample_idiom.pkl` with the expected schema;
  - planning, code assembly, post-merge judgment, one successful merge round, and `sample_idiom_syn.pkl` with the expected schema.
- These are wiring/schema checks only. Artifacts are clearly labeled under `results/baseline-stubs/cpp/` and are not model-quality or research results.
- During the initial baseline, with `OPENAI_API_KEY` explicitly absent, both real judgment and real synthesis CLIs exited 1 with `RuntimeError: 未设置 OPENAI_API_KEY 环境变量，请先配置` before paid calls.
- The initial fake-client validation made no real LLM request. A later bounded real smoke is recorded below.

#### 2026-07-17 GPT-5.6 Luna real smoke

The local ignored `.env` now contains intermediary credentials and three explicit model tiers: `OPENAI_MODEL_LOW=gpt-5.6-luna`, `OPENAI_MODEL_MEDIUM=gpt-5.6-terra`, and `OPENAI_MODEL_HIGH=gpt-5.6-sol`. `.env.example` records the same key names without secrets. All current default call paths resolve only `OPENAI_MODEL_LOW`; medium and high are stored for later explicit work.

OpenAI's [current model guidance](https://developers.openai.com/api/docs/guides/latest-model) identifies Luna as the low-cost/high-volume tier, Terra as the balanced tier, and Sol as the highest-capability tier; the [Luna model page](https://developers.openai.com/api/docs/models/gpt-5.6-luna) lists Chat Completions support. Installed AutoGen 0.7.5 predates these model identifiers and otherwise raises `model_info is required`; the shared client factories therefore supply the documented GPT-5 capabilities without changing prompts, score gates, schemas, or algorithms.

The smoke sent synthetic short C++ only; no repository source was disclosed. The first direct attempt failed before reaching the endpoint because the execution sandbox denied outbound connections. Re-running with approved network access succeeded, so this was not an endpoint or dependency fallback.

Results:

- Independent `src.llm` wrapper: one request, default model reported `gpt-5.6-luna`, exact response `LLM_SMOKE_OK`.
- Judgment CLI: one synthetic `delete_and_null` candidate, three calls (semantic and syntax in parallel, then judge), one accepted record, confidence `96.0`, and the expected five-field schema at `results/llm-smoke/judgement/llm-smoke_idiom.pkl`.
- Synthesis CLI: two related synthetic snippets in one location group, five calls (planning, assembly, then three-call post-merge judgment), one retained synthesis record, `merge_rounds=1`, `cnt=4`, one trace entry, and `post_merge_valid=True` at `results/llm-smoke/synthesis/llm-smoke_idiom_syn.pkl`.
- Total real requests: nine. Actual intermediary billing was not exposed by the client, so no exact charge is claimed; the scope was deliberately limited to one short direct prompt and two short synthetic code workflows.
- Readable JSON evidence was exported under `outputs/llm-smoke/readables/{judgement,synthesis}/`. All smoke artifacts remain ignored and are not model-quality or thesis results.

After the configuration change, `pip check`, `compileall`, both Agent `--help` entries, and the complete offline suite passed. After cross-project infrastructure alignment the suite has 25 tests, including the four shared logging/LLM/registration contract tests. The known `runpy` warning on the synthesis module remains non-blocking.

### Evaluation

The real evaluation CLI consumed the minimal dataset and fake-client judgment output and wrote `results/baseline-stubs/cpp/eval.json`:

- `IC=0.25`, `ISP=0.0`, `F1=0.0`, `avg_idiom_size=731.0`, `idiom_count=1`.
- The values are only an entry/schema smoke test. ISP is zero because the synthetic dataset has one project and the evaluator uses other projects as the leave-one-out training idiom set.

## Logs and evidence caveat

Before the cross-project infrastructure unification, source wrote module logs to `logs/<full.module.name>.log` with `mode='w'`; package imports could therefore truncate earlier evidence. The historical stage snapshots remain under `outputs/baselines/records/{parsers,embeddings,clusterings,evaluations}/` and `outputs/baselines/records/logs/`. Current code instead appends every module in one command to `logs/<run-name>.log` through `src/common/logging.py`, so the earlier truncation caveat applies only to the recorded baseline runs.

## Existing implementation versus research documents

The differences below are recorded background, not current defects to fix automatically:

- Current code is now C++-only and therefore aligned with the research language boundary, but remains Tree-sitter-only; the proposed empirical research uses Clang primary with Tree-sitter fallback.
- Current extraction selects function/block/statement AST nodes subject to size/child thresholds. It does not implement the proposed fixed three-level plus L-CSDC dual track, capability masks, compile-database handling, or dependency metadata.
- Current embedding is mean-pooled pretrained-model output only. It has no AST structural vector or optional dependency summary.
- Current clustering uses DBSCAN with optional Bayesian tuning, not proposed HDBSCAN layered by source/granularity.
- Current code has no Stage 3 cluster alignment, AST anti-unification, typed placeholders, or binding-preserving abstraction.
- Current judgment uses semantic, syntax/logic, and judge Agents with a deterministic two-score gate. It has no independent code-smell Agent, three-way manual review, deterministic parser evidence, or Clang validation.
- Current synthesis groups by `loc_label`, asks an LLM to plan/assemble, and re-judges for at most three rounds. It does not enforce the proposed AST-aware static relation triggers, binding rules, or syntax-only validation.
- Current evaluation implements IC, leave-one-project-out ISP, their F1, and average AST size using extent coverage plus normalized substring matching. It does not implement the proposed Raw/V metrics, OY, IV, Cost, HVIP@K, ALR@K, VIY@K, confidence intervals, baselines, or formal train/development/test isolation.
- Haggis-CPP, LLM-Direct, AST-Frequent, thesis ablations, human labeling, and formal experiment manifests are proposals only and are absent.
- The fusion document defines a shared thesis perspective with WPF2React, not a code, data, or repository merge.

## 2026-07-17 cross-project infrastructure alignment

Reusable engineering infrastructure was aligned with WPF2React without changing the C++ parser/mining algorithms, prompts, score thresholds, pickle schemas, synthesis rounds, or evaluation definitions:

- `src/common/logging.py`, `src/llm/`, and `src/agents/base.py` now implement the same logging, model configuration/client, and AutoGen registration contracts in both repositories.
- The C++ judgment/synthesis path now obtains its raw AutoGen client from `src.llm.client`; its domain-specific JSON parsing, safe fallbacks, and independent runtimes remain in `src/agents/`.
- Runtime registration uses `register_agent` / `default_agent_id`, which preserve the existing `register_factory` and `key="default"` behavior.
- `scripts/check_shared_infrastructure.py` hashes the intentionally shared files, and `tests/common/test_shared_infrastructure.py` verifies the contract offline.
- The shared rules are versioned in `docs/guides/shared-development-conventions.md`; `repos/`, `outputs/`, `results/`, `logs/`, `tests/`, and `docs/` have the same semantic roles in both repositories.
- Post-change verification passed `pip check`, `compileall` for `src/tests/scripts`, all 25 offline tests, and the 13-file cross-repository hash check. No model download or LLM request was made.

## Current blockers and deferred work

1. The intermediary endpoint, credential loading, Luna direct wrapper, judgment, and synthesis paths have passed a nine-request synthetic smoke. Full-corpus paid Agent evaluation remains deliberately deferred because its cost, source disclosure scope, and research validity require a separate explicit run plan.
2. Full-corpus parser, CPU UniXcoder, and DBSCAN completed successfully on the current three snapshots. Re-running remains a high-cost experiment and should preserve the recorded corpus scope and parameters.
3. Formal thesis experiments are not authorized yet and require explicit scope, pinned corpora/commits, baselines, metrics, and secrets/cost decisions.
4. Reproducibility is improved by `requirements-local.lock`; the official `requirements.txt` remains broad for scientific packages but now includes the Agent stack. The obsolete non-C++ grammar requirements have been removed.
5. CLI `runpy` warnings from eager package imports remain non-blocking. The former eager-import log truncation issue was removed by the append-only run logger during cross-project infrastructure alignment.

## Recommended next decision

Before algorithmic work, choose one bounded follow-up:

1. Extend the offline tests with fake-client end-to-end judgment/synthesis fixtures; or
2. Pin and rationalize official dependencies based on this verified environment; or
3. Define a small, versioned Agent evaluation fixture before spending on a larger model-quality run; or
4. Start one explicitly scoped thesis-alignment change from `docs/research/01_C++代码习语挖掘研究稿.md`.

Do not rerun full-repository embedding, start paid Agent evaluation, or begin thesis refactoring by default.
