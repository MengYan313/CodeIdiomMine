# CodeIdiomMine 本地开发基线

最后验证：2026-07-26（Asia/Shanghai）

本文是现有实现的长期项目事实记录，保存已经观察到的事实和可复现的冒烟测试；它不表示当前代码已经实现论文研究稿中的方案。

## 仓库与主机

- 工作树：`/Users/sophon/Codex/CodeIdiomMine`。
- Git 分支与基准：`master`，提交 `260e7c2bc949b30b3745f934a9968432ab679af2`；编写本地初始化文档前与 `origin/master` 对齐。
- 初始受跟踪工作树干净。`AGENTS.md` 当时已作为原根目录 `CLAUDE.md` 的未跟踪副本存在；初始化时更新了该文件，没有将其丢弃。
- 操作系统：macOS 26.5.2（build 25F84），Darwin arm64，Apple Silicon。
- 命令行工具：`/Library/Developer/CommandLineTools`；Apple clang 21.0.0。
- 初始化时可用磁盘空间约 42 GiB。
- 已有版本工具：Homebrew 位于 `/opt/homebrew/bin/brew`；`PATH` 中没有 conda、pyenv 或 uv。
- 已有系统解释器：`/usr/bin/python3` 3.9.6。
- 当时不存在 `.env`，也没有项目虚拟环境。

研究文档现已整理到纳入版本控制的 `docs/research/` 目录：

- `docs/research/01_C++代码习语挖掘研究稿.md`
- `docs/research/03_面向代码可复用性增强的融合研究方案.md`
- `docs/research/Idiom_Mining_II.pdf`

在 2026-07-16 结构规范化之前，`doc/` 被忽略，导致两份 Markdown 研究稿对 Git 不可见，而 PDF 恰好已被跟踪。该目录先更名为 `docs/` 并从 `.gitignore` 的忽略范围中移除；最终分类目录为 `guides/` 和不可数形式 `research/`。

## Python 版本选择

| 候选版本 | 评估 |
|---|---|
| macOS Python 3.9.6 | 源码语法大体兼容，但当前 Tree-sitter 和 AutoGen 版本至少要求 Python 3.10；它还是操作系统管理的解释器，因此不用于安装项目包。 |
| Python 3.11 | 生态成熟，预计可用，但对本技术栈不比 3.12 更具兼容优势。 |
| Python 3.12 | 最终选用。完整的解析器、科学计算、PyTorch、Transformers 和 AutoGen 技术栈均解析到原生 macOS arm64 wheel，并通过导入和冒烟测试。 |
| Python 3.13 | 理论上可用，但对于复现这个未锁定依赖的 2026 年代码库而言没有必要；仓库功能均不要求该版本。 |
| Python 3.14 | 结构规范化前的 `README.md` / `CLAUDE.md` 曾声称使用该版本，但源码并不要求。本地 Homebrew 没有 `python@3.14` formula。虽然当前 PyTorch 发布了 3.14 arm64 wheel，但选择该版本只会让其余未锁定技术栈面对更新的兼容面，并无项目收益。 |

最终解释器和环境：

- Homebrew formula：`python@3.12 3.12.10_1`。
- 解释器：`/opt/homebrew/bin/python3.12`（解析到 `/opt/homebrew/opt/python@3.12/...` 下）。
- 项目虚拟环境：`/Users/sophon/Codex/CodeIdiomMine/.venv`。
- 虚拟环境 Python：3.12.10 arm64。
- 打包工具：pip 26.1.2、setuptools 83.0.0、wheel 0.47.0。
- 初始创建命令：`/opt/homebrew/bin/python3.12 -m venv venv`；该环境于 2026-07-17 迁移到 `.venv`，详见后文记录。
- 安装没有替换或重新链接 `/usr/bin/python3`。
- 没有发生 Python 版本回退：选定的 3.12 环境从 wheel 安装了所有关键依赖。Python 3.14 是被否决的候选版本，不是一次失败的安装尝试。

Homebrew 安装后的自动清理移除了过时的 `/opt/homebrew/Cellar/tomcat/11.0.6`（3 个文件，约 16.3 KiB）和陈旧的 Homebrew 缓存。后续检查确认 Tomcat 11.0.7 仍已安装并正确链接，配置仍使用 `/opt/homebrew/etc/tomcat`；没有项目文件受影响。

第一次在沙箱内执行 pip 时，因网络限制按预期失败并报告 `ProxyError: Operation not permitted`。获得网络访问批准后，在同一虚拟环境中重新执行安装成功。这是沙箱/网络重试，不是包兼容性回退。

2026-07-17，在不重装依赖的情况下将 `venv/` 移到 `.venv/`。`/opt/homebrew/bin/python3.12 -m venv --upgrade .venv` 刷新了标准环境元数据，并将 26 个仍含旧绝对前缀的生成脚本改写为新前缀。`.venv/bin/python` 报告 `sys.prefix=/Users/sophon/Codex/CodeIdiomMine/.venv`，直接调用 `.venv/bin/pip` 正常，`.venv/bin` 中不再残留旧前缀，`pip check` 仍未发现损坏的依赖关系。

## 依赖状态

安装内容包括 `requirements.txt` 及源码需要但原文件遗漏的依赖：

```bash
.venv/bin/python -m pip install -r requirements.txt \
  autogen-core 'autogen-ext[openai]' python-dotenv
```

使用 `autogen-ext[openai]` 而不是不带 extra 的基础包，因为代码会导入 `autogen_ext.models.openai.OpenAIChatCompletionClient`。

解析得到的关键版本：

- pandas 3.0.3, NumPy 2.5.1
- Tree-sitter 0.26.0；必需的 C++ grammar 为 0.23.4。初始化后的虚拟环境仍包含早先安装的 Python 0.25.0、Java 0.23.5 和 JavaScript 0.25.0 grammar 包，但仅支持 C++ 的代码和 `requirements.txt` 已不再使用或要求它们。
- PyTorch 2.13.0, Transformers 5.13.1
- scikit-learn 1.9.0, scikit-optimize 0.10.2, SciPy 1.18.0
- hdbscan 0.8.44
- autogen-core 0.7.5, autogen-ext 0.7.5, OpenAI SDK 2.45.0
- python-dotenv 1.2.2

`.venv/bin/python -m pip check` 报告 `No broken requirements found`。完整精确快照保存在 `requirements-local.lock`；仅支持 C++ 的源码变更没有增加、删除或升级已安装包，因此没有重新生成该文件。

PyTorch 构建时包含 MPS 支持，但在当前执行环境中 `torch.backends.mps.is_available()` 返回 `False`；CUDA 也不可用。更重要的是，当前 `CodeEmbedder` 只会自动选择 CUDA 或 CPU，因此即使在 Apple Silicon 上，已验证的现有路径仍是 CPU。

UniXcoder 下载内容在 `/Users/sophon/.cache/huggingface` 下占约 738 MiB。未配置 Hugging Face token，下载使用匿名访问。

## 文档管理

- 2026-07-16，根目录文档精简为 `README.md` 和 `AGENTS.md`；二级资料最初移入 `docs/development/`，研究资料最初移入 `docs/research/`。
- 2026-07-17，开发文档归入集合目录 `docs/guides/`；研究资料使用不可数分类目录 `docs/research/`。`docs/README.md` 始终是规范文档索引。
- 根 `README.md`、架构指南和测试指南经过重写，移除了过时的顶级模块路径、直接执行脚本的命令、conda/Python 3.14 假设、`log/` 路径、默认使用 CodeLLaMA 的说法，以及不存在的 editable install 说明。
- 源码包名现遵循语义和 Python 约定：`agents`、`common`、`evaluation`、`llm`、`mining`、`parser` 和 `utils`。运行产物集合目录仍为 `repos`、`outputs`、`results` 和 `logs`。
- `tests/` 现在镜像七个 `src/` 包，并包含离线 `unittest` 覆盖，而不是空占位目录。`src/`、`cpp/` 和 `.venv/` 有意保留为非集合惯例名称。
- 2026-07-26，确认同级 thesis 仓库的中英文文献库为所有关联项目唯一文献事实
  来源；本仓库不建立副本。两份研究稿的链接已改为直接指向
  `../../../thesis/references/`，运行时异味来源只保存 thesis 稳定编号、名称和
  官方 URL。
- `requirements.txt` 为科学计算和解析器包保留宽泛的版本下限，并已声明验证过的 AutoGen OpenAI 技术栈和 python-dotenv。仅支持 C++ 的简化移除了未使用的 Python、Java 和 JavaScript grammar 依赖。
- 2026-07-18，项目自有文档明确统一使用中文，并与 WPF2React 对齐为 `docs/guides/`、`docs/research/` 和小写 kebab-case 文件名；评估指标、baseline 与本地基线分别固定为 `evaluation-metrics.md`、`baselines.md` 和 `local-baseline.md`。

## 仅支持 C++ 的简化

2026-07-16，用户明确将多语言运行接口改为仅支持 C++。该变更移除了语言分派，同时有意保留既有 C++ 算法、过滤规则、路径、提示词、阈值和产物 Schema：

- `src/common/node_kinds.py` 现在只暴露固定的 C++ 函数、块和语句节点集合。
- `ASTParser()` 和 `FileScanner()` 不再接收语言参数；解析器始终加载 `tree-sitter-cpp`，扫描器保留原有 C++ 扩展名和测试文件过滤行为。
- `parse_repository`、`get_pros_src_and_embedding` 和 `generate_embeddings` 不再接收语言参数。
- 解析、嵌入和评估 CLI 不再暴露 `--language`；评估入口为 `evaluate_cpp`，并为保持 Schema 连续性继续在 `eval.json` 中写入 `"language": "cpp"`。
- `repos`、`outputs/cpp` 和 `results/cpp` 继续作为固定路径合同，而不是动态语言命名空间。
- Agent 系统提示词和确定性评分/合并规则未改变。

这是对当时已验证实现的范围简化；当时尚未实现研究稿所提
Clang/HDBSCAN/四阶段系统。现在重新引入其他语言仍需要获得明确批准并进行
架构变更。

## 目录语义与测试规范化

2026-07-17，用户明确授权了仓库级公共路径迁移。第一轮曾机械地把所有源码包改成复数：

- `src/{agent,common,eval,llm,mining,parser}` 变为 `src/{agents,commons,evaluators,llms,miners,parsers}`；相对导入、公共模块 CLI、日志示例、文档和默认值同时更新。
- `repo/`、`output/` 和 `result/` 变为 `repos/`、`outputs/` 和 `results/`；已有的忽略语料和产物直接迁移，没有重新生成。
- `docs/development/` 和 `docs/research/` 曾临时变为 `docs/guides/` 和 `docs/researches/`。
- 本地产物集合规范为 `outputs/baselines/`、`results/baseline-stubs/`、`outputs/cpp/readables/` 和 `outputs/cpp/records/`。
- 项目环境变为 `.venv/`，详见前文 Python 部分。
- 新增镜像七个包的 `tests/` 目录树，加入针对解析器/扫描器行为、DBSCAN Schema、评分阈值、指标、消息构造、响应解析和产物导出的确定性测试。

随后在同一任务序列中纠正了机械复数化。最终公共包为 `src/{agents,common,evaluation,llm,mining,parser,utils}`，对应测试包为 `tests/{agents,common,evaluation,llm,mining,parser,utils}`。`docs/researches/` 恢复为符合惯例的不可数形式 `docs/research/`。真实集合使用复数（`agents`、`utils`、`guides`），流程或领域名称使用单数。

纠正后，`pip check`、`compileall`、七个包的组合导入、七个公共 CLI 帮助入口和完整的 21 项离线测试全部通过。`tests/mining/test_mining.py` 随流程包一起更名。没有为机械复数路径保留兼容别名，因此陈旧导入会直接失败，不会静默延续错误的公共命名。

首次测试通过 15 项中的 14 项。唯一失败来自一条错误的新断言：它认为 `(69.9, 100)` 不应通过既有 `high >= 70 and low >= 50` 规则，但该规则正确返回真。测试输入改为 `(69.9, 69.9)`，业务逻辑没有修改。完整验证后的最终结果记录如下。

最终验证通过全部 15 项测试、`src` 与 `tests` 的 `compileall`、七个公共包的组合导入，以及每个更名后的 CLI 帮助入口。解析、嵌入和评估仍不暴露语言选择器。现有 `runpy` 警告仍仅与包的预先导入有关。使用现有 PKL 文件重新生成了完整本地可读投影，其 manifest 现在一致记录 `.venv`、`outputs/cpp`、`results/cpp` 和 `outputs/cpp/readables`。

## 三项目历史语料与流水线

以下内容记录 2026-07-16 的三项目基线。当时输入位于已删除的旧分组目录 `repos/cpp/`，包含三个非 Git 源码快照；2026-07-24 结构重构后，正式固定版本仓库已平铺到 `repos/`，当前数据集组成以 `repos/README.md` 和数据集清单为准。

| 项目 | 当前 `FileScanner()` 选中的文件数 |
|---|---:|
| envoy | 2,924 |
| qBittorrent | 465 |
| react-native | 1,415 |
| 合计 | 4,804 |

扫描器计数应用了当前路径/名称过滤，因此小于不经过这些过滤时找到的 7,078 个 C/C++ 扩展名文件。研究方案中列出的 `TrafficMonitor` 不在本地语料中。

已验证的数据流：

```text
repos/<project>/...
  -> dataset.pkl
  -> embeddings.pkl
  -> clusters.pkl
  -> {repo}_idiom.pkl
  -> {repo}_idiom_syn.pkl
  -> eval.json
```

精确 Schema 记录在仓库架构中；当前启动命令见各功能模块 README。

## 基线检查与结果

### 静态检查、导入与 CLI 检查

- `.venv/bin/python -m compileall -q src`：通过。
- 导入 `src.common`、`src.parser`、`src.mining`、`src.agents`、`src.evaluation`、`src.llm` 和 `src.utils`：通过。
- 实例化固定的 C++ Tree-sitter 解析器：通过。
- 解析、嵌入、聚类、判断、合成、评估和 PKL 转 CSV 模块的 `--help`：通过。
- 当前包的 `__init__.py` 会预先导入公共符号，因此通过 `python -m` 运行同一模块时会发出 `RuntimeWarning: ... found in sys.modules ... prior to execution`。入口仍能成功执行；这是源码行为记录，初始化期间未处理。

一次并发冷启动导入似乎卡在深层 `transformers -> sklearn` 导入中，约 40 秒后被中断。随后各依赖串行导入正常完成（NumPy 约 0.07 秒、PyTorch 0.92 秒、scikit-learn 1.08 秒、AutoGen 0.70 秒、Transformers 3.21 秒），组合串行包导入约 3.33 秒完成。因此将该现象归类为并发冷启动竞争，而不是依赖失败。

### 仅支持 C++ 变更后的验证

2026-07-16 重新验证了仅支持 C++ 的 API 与 CLI 变更：

- `.venv/bin/python -m pip check`：通过并报告 `No broken requirements found`；pip 同时输出已有的沙箱缓存所有权警告，并为该命令禁用缓存。
- `.venv/bin/python -m compileall -q src`：通过。
- 所有公共包组合导入通过。`ASTParser()` 成功初始化 `tree-sitter-cpp`；签名检查确认 `ASTParser`、`FileScanner` 以及解析、嵌入、评估 API 都不再接收语言选择器。
- 解析、嵌入和评估入口的 `--help` 均通过，且都不暴露 `--language`。已知的预先导入 `runpy` 警告保持不变。
- 临时验证根目录：`/private/tmp/codeidiommine-cpp-only.XLiBRB/`。第一次 fixture 尝试因 React Native 源路径遗漏 `packages/react-native/` 而生成损坏的符号链接；解析器因此报告两个文件缺失，并写入合法的零文件数据集。只修正临时符号链接后，同一命令解析了 1 个合成项目、2 个 C++ 文件和 4 个函数，Schema 符合预期。
- 确定性假嵌入器选出 2 个片段，写入既有嵌入 Schema；默认 DBSCAN 生成 1 个包含两个成员且无噪声的簇。没有模型下载或网络请求。
- 固定评估 CLI 读取 `outputs/baselines/cpp/dataset.pkl` 和 `results/baseline-stubs/cpp/sample_idiom.pkl`，复现 `IC=0.25`、`ISP=0.0`、`F1=0.0`、`avg_idiom_size=731.0`，并在临时 `eval.json` 中保留 `"language": "cpp"`。
- 没有真实 Agent 或付费 API 调用。

### 最小 C++ 解析器验证

输入使用两个指向已跟踪 React Native 文件的符号链接：

- `ReactCommon/cxxreact/MethodCall.cpp`
- `ReactCommon/cxxreact/JSBundleType.cpp`

结果：

- 1 个合成项目、2 个源文件、4 个解析函数。
- `dataset.pkl`：DataFrame 形状为 `(1, 4)`，列符合预期。
- 长期保留产物：`outputs/baselines/cpp/dataset.pkl`（约 74 KiB）。

### 嵌入与聚类

首先使用确定性假嵌入器在无网络条件下验证片段过滤与 pickle/DBSCAN 路径。设置 `min_nodes=10`、`min_ast_num=5` 和 `min_project_size=1` 后，选出 2 个片段并形成 1 个 DBSCAN 簇。

随后使用 `microsoft/unixcoder-base`、`--device cpu` 和 `--min-project-size 1` 运行真实既有嵌入路径：

- 模型下载/缓存：解析后的 Hugging Face 技术栈约占 738 MiB。
- 输出：2 个 CPU tensor，每个形状为 `(1, 768)`。
- 第一次联网运行加载模型、完成推理并写入 pickle，但进程随后在 `threading._shutdown` 等待超过 30 秒。仅中断关闭等待后，`threading.py` 抛出 `KeyboardInterrupt`；命令产物保持完整。
- 第二次使用已有缓存并设置 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` 时正常退出。因此，将该关闭等待归类为首次下载清理事件，而不是持续出现的嵌入故障。
- 真实默认 DBSCAN（`eps=0.5`、`min_samples=2`）生成 1 个包含两个成员且无噪声的簇。
- 长期保留产物：`outputs/baselines/cpp/embeddings.pkl`（约 10 KiB）和 `outputs/baselines/cpp/clusters.pkl`（约 3.9 KiB）。

初始化时尚未尝试完整三项目语料嵌入。后文的历史全语料运行取代了这一延期状态，同时保留最小产物作为冒烟测试 fixture。

### 三项目完整解析、嵌入与聚类运行

2026-07-16，使用真实解析器、已缓存 UniXcoder 模型和 DBSCAN 流水线处理现有三个项目的语料。运行有意在 Agent 判断前停止，因此没有 LLM 请求、API 成本或向 LLM 端点披露片段。

输入范围对当时的三个源码快照应用既有 `FileScanner` 合同：Envoy 2,924 个文件、qBittorrent 465 个文件、React Native 1,415 个文件，共 4,804 个。该运行是历史证据，不是当前 26 项正式数据集的启动说明。

解析结果及运行后的 AST 审计：

| 项目 | 扫描文件数 | 含函数文件数 | 函数根节点数 | AST 节点数 | `ERROR` 节点数 | 候选片段数 |
|---|---:|---:|---:|---:|---:|---:|
| envoy | 2,924 | 2,848 | 17,274 | 3,037,215 | 3,922 | 15,056 |
| qBittorrent | 465 | 448 | 4,737 | 696,497 | 521 | 3,623 |
| react-native | 1,415 | 1,149 | 6,484 | 716,154 | 742 | 3,062 |
| 合计 | 4,804 | 4,445 | 28,495 | 4,449,866 | 5,185 | 21,741 |

所有提取的函数源码均非空。当时只按已保存函数 AST 统计到约 0.12% 的
`ERROR`，并据此暂定无需修改解析规则。2026-07-23 的全源文件字节覆盖审计发现，
旧函数根混入类、声明器和模板壳，且未入数据集的源码异常没有进入这个分母；
因此该历史结论已由下文 Parser v2 基线取代。生成的
`outputs/cpp/dataset.pkl` 具有要求的 `(3, 4)` DataFrame Schema，大小为
547,821,374 字节。

CPU 串行基准估算处理 21,741 个片段约需 20 分钟，因此新增保持 Schema 的批处理路径 `CodeEmbedder.get_embeddings`：按相近源码长度分组以减少 padding，恢复原始顺序，并为每个片段保留一个 `(1, hidden_size)` CPU tensor。批大小 8 将采样吞吐从约 18～26 片段/秒提高到约 41 片段/秒。真实单条/批量比较通过 `torch.allclose(atol=1e-5, rtol=1e-4)`；既有 `get_embedding` API 以及只实现该 API 的测试替身仍受支持。

使用已有缓存并禁用网络的完整嵌入命令：

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
.venv/bin/python -m src.mining.code_embedding \
  --input outputs/cpp/dataset.pkl --output outputs/cpp/embeddings.pkl \
  --model unixcoder --device cpu --min-project-size 100 --batch-size 8
```

真实 `microsoft/unixcoder-base` 运行分别生成 15,056、3,623 和 3,062 个嵌入，共 21,741 个。所有 tensor 都是有限值 CPU tensor，形状为 `(1, 768)`；源码、嵌入、信息计数和项目标签相互对齐。`outputs/cpp/embeddings.pkl` 具有要求的 `(3, 4)` Schema，大小为 554,078,318 字节。没有发生模型下载或回退。

首先按要求运行默认 DBSCAN 基线：

```bash
.venv/bin/python -m src.mining.clustering \
  --input outputs/cpp/embeddings.pkl --output outputs/cpp/clusters.pkl \
  --eps 0.5 --min-samples 2
```

对 Envoy、qBittorrent 和 React Native，分别只生成 3、5 和 4 个大小至少为 3 的簇。最大簇分别包含 14,893/15,056、3,534/3,623 和 2,944/3,062 个候选，说明 `eps=0.5` 将各项目约 96%～99% 的候选压入单个簇。Envoy 和 React Native 未达到要求的五簇阈值。该产物保留为 `outputs/cpp/clusters-default-eps0.5-min2.pkl`。

使用 `min_samples=3` 执行确定性的全局 `eps` 扫描，在不调用 50 次贝叶斯优化的情况下诊断尺度：

| `eps` | Envoy：簇数 / 覆盖数 / 最大簇 | qBittorrent：簇数 / 覆盖数 / 最大簇 | React Native：簇数 / 覆盖数 / 最大簇 |
|---:|---:|---:|---:|
| 0.20 | 847 / 5,042 / 434 | 197 / 1,037 / 52 | 140 / 979 / 84 |
| 0.25 | 839 / 7,482 / 1,707 | 219 / 1,646 / 456 | 175 / 1,449 / 155 |
| 0.30 | 585 / 10,143 / 7,177 | 181 / 2,307 / 1,263 | 149 / 1,869 / 727 |

选择 `eps=0.25` 作为公共折中：覆盖率约 45%～50%，最大簇占比约 5%～13%，且有大量簇达到频率阈值。`eps=0.20` 仅覆盖约 29%～34%；`eps=0.30` 时 Envoy 最大簇已占全部候选的 47.7%。

最终聚类命令：

```bash
.venv/bin/python -m src.mining.clustering \
  --input outputs/cpp/embeddings.pkl --output outputs/cpp/clusters.pkl \
  --eps 0.25 --min-samples 3
```

最终结果：

| 项目 | 大小 ≥ 3 的簇数 | 被覆盖候选数 | 噪声数 | 最大簇大小 |
|---|---:|---:|---:|---:|
| envoy | 839 | 7,482 | 7,574 | 1,707 |
| qBittorrent | 219 | 1,646 | 1,977 | 456 |
| react-native | 175 | 1,449 | 1,613 | 155 |

每个最终簇的大小都至少为 3。预期的七个簇字段、成员计数、`else_point` 计数、非空中心点及项目/位置元数据全部通过验证。`outputs/cpp/clusters.pkl` 大小为 7,218,515 字节。非空日志快照位于 `outputs/cpp/records/`；这些被忽略的产物是本地证据，不是提交的研究结果。

### 可读产物投影

流水线中的 pickle 文件仍是规范产物，因为 JSON/CSV 无法高效保存嵌套 AST 记录、簇成员关系和 `torch.Tensor` 类型。`src/utils/export_artifacts.py` 现在可以在不改变任何流水线 Schema 的情况下生成可丢弃的 JSON 分析视图。

使用以下命令生成全语料视图：

```bash
.venv/bin/python -m src.utils.export_artifacts \
  --input-dir outputs/cpp --output-dir outputs/cpp/readables \
  --limit 100 --cluster-top 100 --text-limit 2000 --vector-head 8 \
  --cluster-eps 0.25 --cluster-min-samples 3
```

`dataset.summary.json`、`embeddings.summary.json` 和 `clusters.summary.json` 覆盖完整输入。`dataset.preview.json` 与 `embeddings.preview.json` 各含 100 条记录；`clusters.top100.json` 每个项目包含按大小排序的 100 个簇，共 300 个。源码文本上限为 2,000 个字符，并带明确截断标记。嵌入预览保存形状、dtype、device、L2 范数和前八个值，不会序列化全部 768 维。

六个阶段 JSON 文件与 `manifest.json` 均通过严格 JSON 解析，不含 `NaN`。预览上限、文本上限、项目内排名、簇降序、输入元数据和已知全流水线计数均通过验证。生成目录位于被忽略的 `outputs/cpp/readables/` 下，其中含简短 `README.md`；它既不是流水线输入，也不是提交的研究结果。

同一导出器还可通过扫描 `--result-dir` 下的 `*_idiom.pkl` 和 `*_idiom_syn.pkl` 支持可选的 `judgment`、`synthesis` 阶段。已使用被忽略的确定性假客户端产物验证该路径：导出 1 条判断记录和 1 条合成记录，保留既有字段、计数、合并轮次、来源信息样本和可安全写入 JSON 的合成轨迹。验证没有真实 Agent 或 LLM 调用。

### Agent 判断与合成

- 已安装的 AutoGen 0.7.5 成功运行仓库使用的 `RoutedAgent`、`message_handler`、`SingleThreadedAgentRuntime`、`register_factory` 和 `AgentId` API。
- 初始基线的确定性内存假模型返回了当时协议下的有效结构化响应；当前协议已升级为原生 JSON mode、Schema 校验和单次修复。该基线验证了：
  - 语义/语法并行评估及确定性的 90/90 `is_idiom=True` 门控；
  - 从真实最小簇执行批量判断，生成具有预期 Schema、包含一条记录的 `sample_idiom.pkl`；
  - 规划、代码组装、合并后判断、一次成功合并，以及具有预期 Schema 的 `sample_idiom_syn.pkl`。
- 这些仅是连线和 Schema 检查。产物在 `results/baseline-stubs/cpp/` 下明确标记，不属于模型质量结果或研究结果。
- 初始基线中明确不设置 `OPENAI_API_KEY` 时，真实判断和真实合成 CLI 都在付费调用前以退出码 1 结束，并报告 `RuntimeError: 未设置 OPENAI_API_KEY 环境变量，请先配置`。
- 初始假客户端验证没有真实 LLM 请求。后文记录了有界真实冒烟测试。

#### 2026-07-17 GPT-5.6 Luna 真实冒烟测试

本地被忽略的 `.env` 现包含中转服务凭据和三个明确模型档位：`OPENAI_MODEL_LOW=gpt-5.6-luna`、`OPENAI_MODEL_MEDIUM=gpt-5.6-terra` 和 `OPENAI_MODEL_HIGH=gpt-5.6-sol`。`.env.example` 记录相同键名但不含秘密。当前所有默认调用路径只解析 `OPENAI_MODEL_LOW`；中、高档仅为后续明确任务保留。

OpenAI 的[当前模型指南](https://developers.openai.com/api/docs/guides/latest-model)将 Luna 定位为低成本/高吞吐档、Terra 定位为平衡档、Sol 定位为最高能力档；[Luna 模型页面](https://developers.openai.com/api/docs/models/gpt-5.6-luna)列出了 Chat Completions 支持。已安装的 AutoGen 0.7.5 早于这些模型标识，否则会抛出 `model_info is required`；因此共享客户端工厂补充文档规定的 GPT-5 能力元数据，没有改变提示词、评分门控、Schema 或算法。

冒烟测试只发送简短合成 C++，没有披露仓库源码。第一次直接尝试因执行沙箱禁止出站连接而在到达端点前失败；获得网络访问批准后重试成功，因此这不是端点或依赖回退。

结果：

- 独立 `src.llm` 封装：1 次请求，默认模型报告为 `gpt-5.6-luna`，精确响应为 `LLM_SMOKE_OK`。
- 判断 CLI：1 个合成 `delete_and_null` 候选，3 次调用（语义与语法并行，随后判断），接受 1 条记录，置信度 `96.0`；`results/llm-smoke/judgement/llm-smoke_idiom.pkl` 具有预期五字段 Schema。
- 合成 CLI：同一位置组中的 2 个相关合成片段，5 次调用（规划、组装，再进行 3 次合并后判断），保留 1 条合成记录；`results/llm-smoke/synthesis/llm-smoke_idiom_syn.pkl` 中 `merge_rounds=1`、`cnt=4`、含 1 条轨迹且 `post_merge_valid=True`。
- 真实请求总数：9。客户端未暴露中转服务实际账单，因此不声称精确费用；范围有意限制为 1 条简短直接提示和 2 条简短合成代码工作流。
- 可读 JSON 证据导出到 `outputs/llm-smoke/readables/{judgement,synthesis}/`。所有冒烟产物均保持忽略，不属于模型质量结果或论文结果。

配置变更后，`pip check`、`compileall`、两个 Agent 的 `--help` 入口和完整离线测试均通过。跨项目基础设施对齐后，测试套件共 25 项，其中包括 4 项共享日志/LLM/注册合同测试。合成模块已知的 `runpy` 警告不影响运行。

### 评估

真实评估 CLI 读取最小数据集和假客户端判断输出，写入 `results/baseline-stubs/cpp/eval.json`：

- `IC=0.25`、`ISP=0.0`、`F1=0.0`、`avg_idiom_size=731.0`、`idiom_count=1`。
- 这些值只用于入口和 Schema 冒烟测试。ISP 为零，是因为合成数据集只有一个项目，而评估器使用其他项目作为留一法训练习语集合。

上述数值描述旧评估器，仅保留作历史证据。下文修正后的指标验证已取代其结论：旧 `info[2]` 查询衡量的是所在函数范围，因此 `avg_idiom_size=731.0` 表示完整函数，而不是候选子树。

#### 2026-07-18 指标修正与冻结 Top100 语料模拟

规范指标定义固定在[评估指标规范](evaluation-metrics.md)中；本节只记录已验证实现与实验性证据。

评估器修正过程没有模型下载或 LLM 请求：

- 候选覆盖率和大小使用 `info[3].extent`；`info[2]` 为向后兼容继续表示所在函数范围；
- DBSCAN 代表点选择现在使用一个质心查询所有成员，不再固定选择第 0 个成员；
- 判断和合成产物保留全部 `source_infos`；新解析的 AST 节点记录 `subtree_size`，但不改变历史 `ast_num` 语义；
- 每个留一项目折都为 IC 和 ISP 使用同一个训练习语集合；匹配时抽象标识符和字面量，但保留 C++ 关键字、运算符和候选节点类型；
- 评估报告 `IC_macro`、`IC_micro`、二者算术平均得到的最终 `IC`、精确匹配/总数、ISP，以及基于最终 IC 计算的 F1；
- 每个簇对应一种习语，每个 `source_infos` 成员对应一个习语实例；习语库统计报告种类数、平均簇大小、平均唯一文件支持数，以及对所有可测成员计算的簇宏平均 AvgAST；
- 默认 CLI 路径现使用文档规定的复数根目录 `outputs/` 和 `results/`。

已有 `outputs/cpp/readables/clusters.top100.json` 仅作为被忽略的 `results/evaluation-mock/cpp/` 下的冻结语料 manifest。构建器读取 manifest 中的 `project/label` 集合，但忽略历史 `rank`；生成产物和评估输出均不含 rank，也不计算排名/Top-K 指标。Mock 构建器保留完整簇成员并增加 `mock_provenance`；没有候选经过 LLM 判断。随后使用确定性的 80/20 文件划分，将每个选中簇成员仅作为证据 oracle，以验证公式和范围并集：

| 仓库 | IC_macro | IC_micro | IC | ISP | F1 |
|---|---:|---:|---:|---:|---:|
| Envoy | 0.0981 | 0.1847 | 0.1414 | 0.5729 | 0.2268 |
| qBittorrent | 0.0672 | 0.1736 | 0.1204 | 0.2500 | 0.1626 |
| React Native | 0.0508 | 0.1560 | 0.1034 | 0.3333 | 0.1578 |
| 仓库宏平均 | 0.0720 | 0.1714 | 0.1217 | 0.3854 | 0.1824 |

| 仓库 | 习语种类数 | 平均簇大小 | 平均唯一文件支持数 | AvgAST |
|---|---:|---:|---:|---:|
| Envoy | 100 | 44.36 | 11.40 | 113.99 |
| qBittorrent | 100 | 12.55 | 3.87 | 107.88 |
| React Native | 100 | 12.18 | 3.47 | 166.92 |
| 仓库宏平均 | 100.00 | 23.03 | 6.2467 | 129.60 |

必要的合并全局汇总为：`IC_macro=0.0816`（按函数加权）、`IC_micro=0.1784`（按节点加权）、`IC=0.1300`、`ISP=0.3891`（275 个符合条件且有训练支持的种类中复现 107 个），以及 `F1=0.1949`。冻结习语库包含 300 个种类和 6,909 个成员实例；按种类加权的平均簇大小为 23.03，平均唯一文件支持数为 6.2467，AvgAST 为 129.60。

结果文件为 `results/evaluation-mock/cpp/eval-mock-evidence.json`。独立完整性审计比较了 manifest、源簇和生成产物：300 个选中簇全部存在，预期的 6,909 个成员实例全部保留，缺失簇和大小不匹配均为 0，且没有输出 `rank` 字段。证据 oracle 评估覆盖 6,127 个函数中的 894,442 个 AST 节点，并标记其中 159,580 个为已覆盖。这些值有意既不为零也不接近一，说明修复后的分母和候选范围表现正常。由于聚类发生在文件划分之前，它们明确是模拟结果，不是研究结果。

更严格的模拟留一项目运行也保留为 `eval.json`。仓库宏平均为 `IC_macro=0.0027`、`IC_micro=0.0028`、最终 `IC=0.0027`、`ISP=0.1317` 和 `F1=0.0053`；较低的跨域覆盖是参数化模板/反统一阶段之前使用具体 DBSCAN 簇的已观察局限，不是评估器缺陷。

上述留一项目结果只保留为 2026-07-18 的历史实现证据。2026-07-24 明确的
“仓库隔离的专属习语挖掘”目标已取代其研究口径；不得把该数值用于正式实验或
恢复跨仓库泛化目标。

可复现命令：

```bash
.venv/bin/python -m src.evaluation.mock_idioms \
  --clusters outputs/cpp/clusters.pkl \
  --selection-manifest outputs/cpp/readables/clusters.top100.json \
  --output-dir results/evaluation-mock/cpp

.venv/bin/python -m src.evaluation.idiom_metrics \
  --idiom-dir results/evaluation-mock/cpp \
  --dataset outputs/cpp/dataset.pkl \
  --output results/evaluation-mock/cpp/eval-mock-evidence.json \
  --mode mock_cluster_file_split --test-fraction 0.2
```

变更后验证通过 `pip check`、`src/tests/scripts` 的 `compileall`、两个评估 CLI 帮助入口和全部 36 项离线测试。验证没有网络、模型下载或付费 API 请求。

#### 2026-07-18 三条 baseline 复现与共享指标合同

三条要求的 baseline 现已实现为独立 C++ 入口；方法细节和正式命令见 [baseline 复现指南](baselines.md)：

- `src.evaluation.haggis_cpp` 将 Haggis DP-pTSG 核心移植到当前 Tree-sitter C++ AST。固定参考是归档的 `mast-group/codemining-treelm` 提交 `8b241a195fe860713c8dbbee387710533b97258c`。实现使用 PCFG 先验、DP 后验预测、逐点 collapsed Gibbs 采样、burn-in 后收集，以及明确的后验/出现次数/文件数/节点数阈值。manifest 记录与 Java/JDT、blocked sampler、二值化、符号抽象，以及当前函数/块/语句 `ast_num >= 5` 输出投影的差异；文档没有把它描述成原 Java 工具直接支持 C++。
- `src.evaluation.llm_direct_baseline` 机械切分原始函数，并以 map/reduce 形式使用单一模型。发现阶段不接收 AST、嵌入、簇或 Agent 结论。全局预算估算统计 system prompt、追加 Schema 的 user prompt 和实际 JSON 输出。只有在发现结束后才映射 AST 证据，以满足公共评估合同。
- `src.evaluation.rules_embedding_baseline` 直接把符合条件的 DBSCAN 簇视为习语种类。当前合同依次应用最小簇大小、显式给定且小于 1 的比例，以及每项目种类上限。默认上限为 100；它是比例选择后的硬上限，不是固定 Top100 输出，也不适用于其他方法。
- `src.evaluation.baseline_validation` 拒绝 mock 或不完整产物，运行未修改的固定评估器，并要求项目级、仓库宏平均和全局层级都具备全部九项指标。公共列表为 `IC_macro`、`IC_micro`、`IC`、`ISP`、`F1`、`idiom_type_count`、`avg_cluster_size`、`avg_cross_file_support` 和 `AvgAST`。

确定性集成覆盖使用三个合成仓库。它运行全部三条 baseline，实现中为 LLM-Direct 注入理解 Schema 的假模型，以假共享客户端运行真实 CIMAS 判断 runtime（语义 Agent、语法 Agent 和判断 Agent），并通过同一个评估器验证四组产物。这在无需下载或付费请求的前提下证明方法级 Schema 和指标适用性。

早先一次完整当前簇运行使用 `min_cluster_size=3`、`selection_ratio=1.0` 和 `max_types=100`。三个项目都选择了 100 个种类并通过九指标合同：

| 仓库 | IC | ISP | F1 | 种类数 | 平均簇大小 | 平均文件支持数 | AvgAST |
|---|---:|---:|---:|---:|---:|---:|---:|
| Envoy | 0.0006 | 0.1550 | 0.0012 | 100 | 44.36 | 11.40 | 113.99 |
| qBittorrent | 0.0030 | 0.0400 | 0.0056 | 100 | 12.55 | 3.81 | 97.21 |
| React Native | 0.0046 | 0.2800 | 0.0091 | 100 | 12.18 | 3.47 | 157.60 |

这些值保留为适配器和指标在完整簇输入上运行过的历史证据，不是早先的 `mock_cluster_file_split` 证据 oracle 运行。作为规则 baseline 配置，它们已被取代，因为 `selection_ratio=1.0` 没有执行当前要求的比例截断。正式替代配置必须在运行前把小于 1 的比例冻结为统一固定值，或用只观察聚类内部支持度分布的预注册无监督规则确定；不得根据最终 IC、ISP、F1 或人工标签臆造参数。

修正后的三阶段选择器还在完整当前簇产物上进行配置冒烟测试，使用 `min_cluster_size=3`、`selection_ratio=0.5` 和 `max_types=100`。比例 0.5 只是连线验证值，不是根据测试结果选择的论文参数。Envoy 有 839 个大小合格簇，比例选择提出 420 个，上限保留 100 个；qBittorrent 有 219 个，提出 110 个并保留 100 个；React Native 有 175 个，提出并保留 88 个。因此最终种类数为 100/100/88，而不是强制每项目 Top100。九项指标全部通过；证据位于被忽略的 `results/baseline-smoke/rules-combined/cpp/`。

Haggis-CPP 有界冒烟测试读取真实当前 AST 数据集，但将每个项目限制为 20 个函数、每个函数最多 300 个节点，执行 6 次迭代并使用 50% burn-in，同时有意放宽选择阈值。它分别采样 1,997/1,009/2,922 个节点，为 Envoy/qBittorrent/React Native 输出 10/8/10 个习语种类。三个层级的九项指标均为有限值。跨项目 IC/ISP/F1 为零，因为宽松冒烟片段只有一个本地实例；这符合连线冒烟预期，不是质量结果。当前 Haggis 入口不再接受 `max_types`；所有通过方法原生阈值的片段都会写出。

最终 LLM-Direct-Budget 真实冒烟测试只使用两个手写 C++ 函数，没有披露仓库源码。`gpt-5.6-luna` 执行 1 次 map 和 1 次 reduce 请求，生成 1 个具有两个文件来源的习语；计入 system prompt 和 JSON Schema 后，估算输入加输出 token 为 1,493，低于 4,000 token 上限。manifest 记录 2 次逻辑调用和 2 次端点请求。实现期间同一合成用例成功运行三次：首次验证新 baseline，随后在修正 system/Schema 计数后运行，最后在修复请求也受预算约束后运行。因此该任务共有 6 次成功端点请求；首次被沙箱拒绝的尝试没有到达端点。单项目留一法 IC/ISP/F1 必然为零，但项目级、仓库宏平均和全局层级的九项数值均为有限值。中转服务未暴露精确账单，因此不声称费用。当前 manifest 明确记录 `max_output_tokens` 是单次响应 token 上限，且不应用最终习语数量上限。

被忽略的证据路径：

- 完整规则 baseline：`results/baselines/rules-embedding-clustering/cpp/`；
- 修正规则组合冒烟：`results/baseline-smoke/rules-combined/cpp/`；
- Haggis 冒烟：`results/baseline-smoke/haggis-cpp/cpp/`；
- 合成 LLM 输入：`outputs/baseline-smoke/synthetic/`；
- LLM-Direct 冒烟：`results/baseline-smoke/llm-direct-budget/cpp/`。

每个结果目录都包含 `baseline-manifest.json`、`eval.json` 和 `metric-validation.json`。这些运行证明可复现性与评估器兼容性；只有完整规则 baseline 处理了当前全部输入，任何冒烟数值都不应进入比较结果表。

输出选择修正也经过离线重新验证：在合成项目上，Haggis 输出未截断的 4/5/5 个种类，LLM-Direct 输出 2/2/2，规则 baseline 在 `min_cluster_size=2`、`selection_ratio=0.5`、`max_types=1` 下输出 1/1/1，无上限 CIMAS 判断输出 2/2/2。四种不同的输出基数都通过同一九指标合同。没有网络或付费请求。

#### 2026-07-18 CIM 5.4 baseline 文档发布

项目版本从既有 `CIM 5.3` 提交惯例推进到 `CIM 5.4`。`docs/guides/baselines.md` 现作为详细实现规范，记录每条 baseline 的研究作用、顺序算法、参数、C++ 适配或预算边界、输出选择合同、公共产物字段、公平性约束、命令、局限与验证证据。README 和固定评估规范使用相同版本标记。

发布验证通过 `pip check`、`src/tests/scripts` 的 `compileall`、全部 41 项确定性离线测试、四个 baseline/评估器的 `--help` 入口、`git diff --check`，以及 `scripts/check_shared_infrastructure.py --other ../WPF2React`（`shared_infrastructure_ok=True`，16 个文件）。没有源码发送到外部模型，也没有付费或联网 LLM 请求。

#### 2026-07-18 CIM 5.5 跨项目文档统一发布

项目版本升级到 `CIM 5.5`。本次发布与 WPF2React 统一项目自有文档的目录分层、文件命名和中文写作规则：开发文档归入 `docs/guides/`，研究资料归入 `docs/research/`，评估指标、baseline 与本地基线分别固定命名为 `evaluation-metrics.md`、`baselines.md` 和 `local-baseline.md`。原纯英文的本地基线记录已完整改为中文，命令、路径、标识符和历史证据数值保持不变。

发布前重新通过全部 41 项离线测试、16 文件跨仓库共享基础设施检查、文档中文比例与站内链接检查，以及 `git diff --check`。没有模型下载、网络调用或付费 API 请求。

## 日志与证据注意事项

跨项目基础设施统一前，源码以 `mode='w'` 将模块日志写入 `logs/<full.module.name>.log`，因此包导入可能截断较早证据。历史阶段快照仍保存在 `outputs/baselines/records/{parsers,embeddings,clusterings,evaluations}/` 和 `outputs/baselines/records/logs/`。当前代码改为通过 `src/common/logging.py` 将同一命令中的所有模块日志追加到 `logs/<run-name>.log`，因此早先的截断注意事项只适用于已经记录的基线运行。

## 现有实现与研究文档的差异

以下差异是背景记录，不是应自动修复的当前缺陷：

- 当前代码仅支持 C++，与研究语言边界一致，并以 Tree-sitter/C++ Adapter 实现零构建基础路径；2026-07-24 冻结后的拟议实证研究只把 Clang 作为安全编译信息可得子集上的可选增强。
- 当前提取在大小/子节点阈值约束下选择函数、块和语句 AST 节点。它没有实现拟议的固定三层加 L-CSDC 双轨、能力 mask、compile database 处理或依赖元数据。
- 当前嵌入仅为预训练模型输出的 mean pooling，没有 AST 结构向量或可选依赖摘要。
- 当前正式聚类统一使用 DBSCAN，并对每个新仓库执行同一套无监督自动调参规则；
  HDBSCAN 作为阶段2对照实现保留。两者都没有按来源/粒度分层，DBSCAN 的历史
  `--optimize` 入口仍保留。
- 当前阶段3已由 `src.idiom_judgment` 独立实现单簇合同/低价值规则、高频低语义差异的保守抽象提案、包含完整簇成员与规则初判的 LLM `abstract/keep` 决策、语义/复用价值与代码异味独立审查，以及固定门槛裁决。它不执行全面 AST 反统一；拒绝抽象时保留原代码，也尚未在26仓正式语料上运行付费 LLM 验证或人工质量核验。
- 当前阶段4已由 `src.idiom_synthesis` 独立实现阶段3正式输入、阶段2非执行合同适配、严格同代表区域分组、自动验证代表区域上下文、关系规划、代码组装、质量复审、共享异味审查、Tree-sitter语法和新增调用门禁。阶段2适配与严格阈值只接受离线逻辑测试，正式 CLI 和实验不执行直通；正式26仓合成与可选 Clang 模板验证尚未运行。
- `src.agents` 只保留当前阶段3/4实际使用的公共基类和注册函数；旧判断、合成
  Agent、流水线及 CLI 已删除，阶段4也不再接受旧习语列表输入。
- 当前评估实现一致的仓库内参考/测量分区 IC/ISP/F1、宏/微 AST 覆盖、候选级 AST 大小统计、精确计数、结构化词法匹配器、明确的 mock 验证模式，以及适用于所有已实现方法的共享九指标合同。留一项目入口仅为历史兼容。它仍未实现研究稿提出的 OY、IV、Cost、经人工验证的 V 指标和置信区间。
- Haggis-CPP、LLM-Direct-Budget 和 Rules-Embedding-Clustering 已实现并通过冒烟验证。正式全语料重复实验、人工标注、冻结语料 manifest、与完整 CIMAS 运行的成本匹配，以及更细论文消融仍处于延期状态。
- 融合研究方案定义与 WPF2React 共享的论文视角，不表示代码、数据或仓库合并。

## 2026-07-17 跨项目基础设施对齐

在不改变 C++ 解析/挖掘算法、提示词、评分阈值、pickle Schema、合成轮次或评估定义的前提下，可复用工程基础设施已与 WPF2React 对齐：

- `src/common/logging.py`、`src/llm/` 和 `src/agents/base.py` 现在在两个仓库中实现相同的日志、模型配置/客户端和 AutoGen 注册合同。
- C++ 判断/合成路径现在从 `src.llm.client` 获取底层 AutoGen 客户端；领域特定 JSON 解析、安全回退和独立 runtime 仍位于 `src/agents/`。
- Runtime 注册使用 `register_agent` / `default_agent_id`，保留既有 `register_factory` 和 `key="default"` 行为。
- `scripts/check_shared_infrastructure.py` 对有意共享的文件计算哈希，`tests/common/test_shared_infrastructure.py` 离线验证该合同。
- 共享规则纳入 `docs/guides/shared-development-conventions.md` 的版本控制；`repos/`、`outputs/`、`results/`、`logs/`、`tests/` 和 `docs/` 在两个仓库中具有相同语义职责。
- 变更后验证通过 `pip check`、`src/tests/scripts` 的 `compileall`、全部 25 项离线测试和 13 文件跨仓库哈希检查。没有模型下载或 LLM 请求。

## 2026-07-23 Parser v2 全量基线与优化

对相同三个项目和 4,804 个扫描文件，在修改前后分别完整运行 Parser 两次。
基线两次 SHA-256 均为
`05acec5d266812793c78f436a1c4fee0b50c1ed7c3241aed0d0ab8269336da14`；
v2 两次均为
`33cfb3224e295ba2564a3ca807da410bf9d71bfc04cf7188ae8e57a264ff9f30`。

全源文件审计得到 4,804/4,804 读取与解析成功、4,920,509 个 AST 节点、
11,376 个 `ERROR`、2,261 个 missing、44,765 个预处理节点和
98.0380% 的非空白字节可靠覆盖率。390,243 个未可靠覆盖字节及其
45,201 个连续区间均写入审计，不再因文件无函数而被排除。

Parser v2 的主要结果：

- 函数根由旧 28,495 个增加为 33,720 个；旧根只有 19,421 个是实际
  `function_definition`，v2 为 33,705 个真实定义和 15 个显式
  `recovered_function`；
- 189 个文件启用等长预处理影子，相关文件的 `ERROR + missing` 从
  1,922 降至 1,413，并保留 55 个改变的恢复函数范围；
- 3,686,548 个已保存 AST 节点都具有显式字节范围，原文逐字节匹配率为
  100%；函数根和所有实际候选都有稳定文件身份；
- quality-v2 选择 33,203 个函数、17,083 个基础区域、43,608 个真实语句
  和 3,668 个局部 Def-Use 语义区域；
- Def-Use 片段中位数为 13 行、569 字节，最大 80 行、3,962 字节，
  全部可精确回映射；
- 全量耗时由 23.16 秒增至 34.89 秒，峰值 RSS 由 3.185 GB 增至
  4.047 GB；元数据压缩后的 pickle 为 576,492,303 字节，比冻结基线小
  0.43%。

主数据集继续使用 `project`、`cppFile`、`func_ast`、`func_src` 四列；
`repo2data` 新增覆盖所有扫描文件的 `dataset.audit.json`。Parser 片段构建默认
使用 `quality-v2`，历史候选选择可显式使用 `legacy`。评价器已能将
`semantic_slice` 的字节范围映射回 AST 覆盖，旧数据仍保持原路径。

同日进一步完成 C++ Adapter 与模型输入治理：

- `src/parser/cpp_adapter.py` 集中 tree-sitter-cpp grammar、预处理影子、
  函数/区域/语句和 Def-Use 节点规则；AST 遍历、映射和排序逻辑保持通用，
  公共 CLI 仍然只支持 C++；
- UniXcoder 的 512-token 合同下，97,562 条原始候选中有 1,881 条超限；
- Parser 阶段生成 96,039 条 model-ready 片段：31,966 个函数、17,078 个
  基础区域、43,605 个语句和 3,390 个 Def-Use 区域，最大 512 tokens、
  超限 0、原文映射 100%；
- 1,310 条超长函数记录中 1,225 条有区域、Def-Use 或语句后备，85 条无后备；
  1,881 条去重超限候选全部写入 `fragment_rejections`；
- 两次 `fragments.pkl` SHA-256 均为
  `4e9bcc98f27d0c12f61719bd71cce80729ff34969af0920f9f12cc513e41e0b2`，
  单次构建耗时 23.56 秒，产物约 46 MB；
- embedding 只接受 Parser 片段产物，模型名、profile 或预算不一致即失败，
  tokenizer 使用 `truncation=False`，不再承担超长切分。

完整指标、命令、样本和风险分别见
[Parser 基线与优化对比](parser-quality-report.md)、
[C++ Adapter 与模型输入治理](cpp-adapter-and-model-input.md)、
[Parser 代表性产物审计](parser-artifact-audit.md)和
[Parser 风险与限制](parser-risks.md)。本次没有运行新的完整 UniXcoder、
DBSCAN 或真实 Agent；未发生模型下载、付费请求或外部源码披露。

最终验证通过 `pip check`、`src/tests` 的 `compileall`、全部 54 项离线测试、
七个公共包与 Parser v2 模块的组合导入，以及 Parser、片段构建、token 审计、嵌入和评价
CLI 的 `--help`。`pip` 仅提示用户缓存目录不可写并自动禁用缓存，
随后明确报告 `No broken requirements found`；没有测试失败。

## 2026-07-24 零构建解析原则冻结

项目将 Parser 的长期输入合同固定为：**免目标项目编译、免链接、免执行，源码
可得即可解析**，简称零构建解析（Zero-Build Parsing, ZBP）。这里的“开箱即用”
指安装 CodeIdiomMine 自身依赖后，不需要为输入仓库复现构建系统、下载项目依赖、
运行代码生成、编译、链接、测试或程序，即可执行 Tree-sitter AST、C++ Adapter、
逐文件异常审计、原文映射和片段生成。

当前 Parser v2 的全量证据已经满足该原则：三份仓库源码快照直接扫描，4,804 个
文件均进入统计；宏恢复使用等长静态影子；Def-Use 使用函数内名称级分析；单文件
失败不会中止全局；所有片段映射回原始字节范围。完整运行未执行输入项目的构建
脚本、链接器、测试或二进制。

该决策不否定后续可信环境中的静态验证。已有 `compile_commands.json`、Clang
符号/类型/CFG 和 `clang++ -fsyntax-only` 可作为显式能力增强或阶段3/4模板验证，
但不得成为 Parser 基础候选的全量门槛；失败时必须保留 Tree-sitter 结果、能力
缺失和诊断记录。研究稿据此把“方法无需逐仓库重建专用编译环境”纳入可复用性
论证。此节是文档与架构决策记录，不改变上述 2026-07-23 统计值。

## 2026-07-24 C++ 实验数据集冻结与 Parser 扫描治理

本轮在不执行目标仓库构建、安装、代码生成、测试或程序的前提下，检查 27 个公开
GitHub 候选：24 个新增候选和 Envoy、qBittorrent、React Native 三个原有种子。
每个候选均以独立本地 Git 仓库固定完整 commit，并保存公开元数据和根目录许可
文件证据。最终结论为 17 个保留、9 个条件保留、1 个淘汰，形成 26 项目正式
数据集。Microsoft GSL 被淘汰是因为其核心公开头文件使用无扩展名命名，排除
tests 后没有符合本轮标准扩展名合同的核心输入。

Parser 修改前对全部候选运行逐文件基线，得到 11,636 个扫描文件、1,894,674
有效代码行、139,012 个选中函数和 322,039 个候选；文件读取/Tree-sitter 建树
成功率为 100%，但有 5 个符号链接输入、4,238 个异常文件、60,005 个 ERROR 和
26,693 个 missing。证据位于忽略目录
`outputs/dataset-experiment/baseline/`。

基于基线证据实施以下通用修改：

- 扫描扩展名补齐 `.c`、`.hh`，并保持 `.cc`、`.cpp`、`.cxx`、`.c++`、
  `.h`、`.hpp`、`.hxx`；
- 用目录段和文件 token 规则取代 `test` 子串过滤，确定性排除构建、缓存、
  第三方、生成、测试、示例和基准输入；
- 不跟随符号链接，拒绝越界路径，并把排除原因与计数写入 Parser 审计；
- `cppFile` 与 AST `source_path` 统一为项目仓库相对 POSIX 路径；
- `repo2data` 增加可重复的 `--project` 精确项目选择，并拒绝路径穿越。

优化后正式语料包含 7,940 个核心源码文件、1,290,508 有效代码行、102,574
个函数和 237,845 个候选，文件级解析成功率仍为 100%。异常文件降至 2,492，
ERROR 降至 39,777，missing 降至 18,185，无函数输出文件由 3,063 降至
1,566；最终符号链接输入、越界路径和重复仓库相对路径均为 0。可靠 AST 字节
覆盖率由 82.13% 降至 78.52%，原因和低覆盖项目已明确记录，未通过静默删掉
宏密集核心文件美化指标。

26 个正式项目均通过标准 `repo2data` 入口生成独立四列 `dataset.pkl` 和
`dataset.audit.json`。机器可读正式清单
`docs/research/cpp-dataset-manifest.json` 保存完整 commit、许可证据、构建文件
证据、稀疏范围、复现命令、基线/最终统计和产物位置；统计由
`scripts/analyze_cpp_dataset.py` 从固定源码与实际产物重算。清单交叉校验重新
读取 27 个本地仓库和 26 组标准 Parser 产物，结果为 0 个错误。

Parser 源码指纹为
`48064d7996bba06da13cbb83672a528ad4c50b794caef75b6fd40ae47ba288f3`。
CLI11 和 qBittorrent 分别独立运行两次，确定性摘要逐字节一致：
`ab02ad38b1a1a54ee29c7d665c05ee876870f385b5ba72490798f5d0e93da7fd`
和
`f85bc022c2612941f7c08e289979b3299fbfc34d518be2ea97235dd2aa378965`。

最终验证通过：

- `.venv/bin/python -m pip check`；
- `.venv/bin/python -m compileall -q src scripts tests`；
- `.venv/bin/python -m unittest discover -s tests -t . -v`，共 57 项；
- `repo2data --help` 与数据集统计脚本入口；
- 正式 manifest 交叉校验；
- 全部纳入版本控制的 JSON 解析；
- `git diff --check`。

本轮只访问公开 GitHub 仓库与公开 API 元数据，没有下载新模型，没有调用 LLM，
没有披露本地非公开源码，也没有暂存、提交、推送或创建 PR。完整筛选结论、逐项目
排查和 Parser 回归分别见
`docs/research/cpp-dataset-status-report.md`、
`docs/research/cpp-dataset-project-audit.md` 和
`docs/guides/cpp-dataset-parser-regression.md`。

## 2026-07-24 仓库隔离研究目标纠正

项目最高优先级目标现固定为：针对每个给定 C++ 仓库，使用该仓库全部合格源码
独立挖掘仓库专属习语。不同仓库的候选、embedding 和 DBSCAN 输入不得混合；
发现前不做训练/开发/测试划分；最终评价分区只表示参考/测量位置，不重新运行
发现流程，也不表示未知仓库泛化。旧研究稿、指南和评价器默认中的留一仓库、
DBSCAN 前拆分及“全仓聚类是泄漏”等表述均由该目标取代。

本轮只执行了本地只读核查，没有运行 tokenizer、UniXcoder、DBSCAN 优化或真实
LLM：

- `outputs/dataset-experiment/final/` 下有 26 份 canonical `dataset.pkl` 和
  26 份 `dataset.audit.json`，没有逐仓 `fragments.pkl`；
- 26 个本地仓库 HEAD 均与各自 `analysis.json` 记录的固定 commit 一致；
- 26 份数据集的 `analysis.json` 共记录 237,845 次 `quality-v2` 候选出现，
  逐仓 `dataset.pkl` SHA-256 需要在阶段1 manifest 中单独保存；
- 产物记录的 Parser 源码指纹为
  `48064d7996bba06da13cbb83672a528ad4c50b794caef75b6fd40ae47ba288f3`，
  当前指纹为
  `bcb4596eb2a96a892b3743723ae43ac058558ea274d9b839e077cb1d653dd222`；
- 指纹差异来自 `file_scanner.py` 和 `repo2data.py` 的扫描诊断、路径安全、
  项目选择和进度改动，实际 AST、候选和语义切片模块未变；当前扫描器对 26 个
  固定仓库选出的逐文件清单与已有 26 份审计记录完全一致。

因此，指纹不同是必须记录的差异，但现有证据尚不足以要求无条件重跑全部 26 个
仓库。正式阶段1应先在小型、宏/模板密集和大型仓库上用当前 Parser 做分层重复
解析，对比文件清单、函数/候选统计、映射字段和确定性摘要；若差异只限新增审计
元数据，可继续复用 26 份 canonical AST 并补建片段；若 AST、候选、文件身份或
原文字节映射变化，则只对受影响仓库重建，不覆盖旧产物。

评价器正式默认已从 `leave_one_project_out` 改为
`within_project_file_split`。后者先接收完整仓库发现结果，再只按来源位置形成
参考/测量分区；保留的 `training_*`、`test_*` JSON 字段只是兼容名称。历史留一
模式仍可显式调用，但不得进入正式结果。

口径修正后的离线验证通过 `pip check`、`src/tests` 的 `compileall`、全部 58 项
确定性测试、相关 CLI 的 `--help` 入口、正式 manifest 交叉校验和
`git diff --check`。manifest 校验确认 26 个正式项目、1 个排除项目和 0 个错误。
本轮没有下载模型、运行 embedding/DBSCAN、调用 LLM，也没有暂存、提交或推送。

## 2026-07-25 阶段1正式实验

阶段1正式实验位于已忽略的
`outputs/experiments/repo-isolated-v1/`。本轮只加载本地缓存的 UniXcoder
tokenizer，没有加载模型权重、运行 embedding/DBSCAN 或调用 LLM。

先对 `concurrentqueue`、`tomlplusplus`、`qbittorrent` 和 `envoy` 执行当前
Parser 双跑，覆盖最小、模板密集、Qt/宏密集和大型仓库。四个仓库的当前
DataFrame 与 canonical `dataset.pkl` 精确一致，当前两次输出字节一致，
canonical 与当前审计核心也一致，因此正式决定复用 26 份 canonical AST。

随后对 26 个仓库分别执行首次 `fragments.pkl` 构建、重复构建和 token-length
audit，共 78 个逐仓任务。正式配置固定为 `quality-v2`、
`microsoft/unixcoder-base`、512 个总输入 token、禁止静默截断和仅使用本地缓存。
全部 26 份重复 pickle 在语义和字节层面一致。

阶段1汇总如下：

- 扫描 7,940 个文件，0 个解析失败，得到 102,574 个函数；
- `analysis.json` 按函数观察到 237,845 次候选；按稳定文件身份、extent、层级和
  来源去重后为 237,833 个唯一原始候选，差额是 4 个仓库中的 12 个跨嵌套函数
  重复 `semantic_def_use` 记录，不是候选丢失；
- 最终得到 233,912 个 model-ready 候选和 5,182 条超预算拒绝记录；
- model-ready 类型分布为函数 77,880、区域 41,566、Def-Use 8,413、语句
  106,053，超预算数为 0；
- 4,558 个超预算函数记录中，3,008 个具有至少一种合格后备候选，1,550 个没有
  合格后备；后者显式计数，没有截断或静默进入 embedding；
- 全量映射审计覆盖 12,967,439 个 canonical AST 节点，字节范围解析率、原文
  逐字匹配率和显式 byte range 比例均为 100%；102,574 个函数根全部具有稳定
  文件身份；
- 234 条确定性分层边界样本合同复核全部通过；另独立阅读四个代表仓库的 20 条
  样本，未发现半语句、半 token、跨文件或静默截断。该复核不冒充论文级人工金标；
- 78 个片段/重复/token 任务累计任务时间 410.32 秒。全量映射审计耗时
  94.05 秒、峰值约 9.55 GiB；逐仓任务的最大峰值约 3.11 GiB。

`experiment-manifest.json`、`stage1-summary.json`、
`stage1-acceptance-report.md`、`stage1-statistics.csv`、映射审计、Parser 复核、
分层样本及每仓 `stage1-manifest.json` 保存完整命令、SHA、计数、耗时、峰值内存
和验收结果。联合映射审计 pickle 在成功保存 SHA 后已删除；它从未进入
fragments、embedding 或 DBSCAN。全局 `stage2_ready=true`，阶段1正式出口为
`outputs/experiments/repo-isolated-v1/repos/<repo>/stage1/fragments.pkl`。
收尾验证通过 `pip check`、`src`、`tests` 与阶段1脚本的 `compileall`、全部
58 项确定性离线测试、26 仓正式 manifest 校验、正式产物 `SHA256SUMS` 和
`git diff --check`。

## 2026-07-25 阶段2 UniXcoder Embedding 正式实验

阶段2 Embedding 正式产物继续保存在已忽略的
`outputs/experiments/repo-isolated-v1/`，每仓独立读取
`repos/<repo>/stage1/fragments.pkl`，并写入
`repos/<repo>/stage2/embeddings.pkl`。正式配置固定为
`microsoft/unixcoder-base` 缓存 revision
`5604afdc964f6c53782a6813140ade5216b99006`、CPU、batch size 8、
`quality-v2`、512 个总输入 token 和 `min_project_size=1`。运行期间设置
`HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1` 与
`HF_DATASETS_OFFLINE=1`，没有下载模型、调用 LLM、产生 API 费用或向外部端点
披露源码。

26 个仓库全部完成正式生成和一次相同配置的完整重复生成。每次生成后均独立验证
项目身份、四列 embedding Schema、阶段1输入 SHA、候选数量与顺序、源码和元数据
逐项一致、每个 tensor 位于 CPU、dtype 为 `float32`、形状为 `(1, 768)` 且全部
为有限值。重复 pickle 在验证后立即删除，只保留正式文件、日志、资源指标和语义
摘要。

阶段2 Embedding 汇总如下：

- 26 份正式 `embeddings.pkl` 共包含 233,912 条向量，与阶段1 model-ready
  候选总数精确一致；不同仓库仍完全隔离；
- 正式产物总大小为 5,933,801,281 字节，约 5.53 GiB；
- 正式生成累计任务时间为 3,900.02 秒，重复生成累计任务时间为 4,007.98 秒；
- 正式生成最大峰值内存为 4,860,346,368 字节，约 4.53 GiB，来自 `envoy`；
- `envoy` 的 96,105 条向量耗时 1,642.60 秒，正式文件大小为
  2,440,207,584 字节，是本轮最慢且最大的单仓任务；
- 26/26 个仓库的源码、元数据和 float32 向量原始字节组合摘要在正式与重复运行
  间完全一致。PyTorch pickle 容器的文件级 SHA 不作为重复确定性门槛；正式文件
  自身的 SHA 已单独冻结并通过全量复核；
- 汇总向量摘要为
  `3c3155a65f84eb0985a77da7fd9250e54284519d469c74ecdeef642b44cba4f9`，
  覆盖项目名、源码、元数据和向量的汇总语义摘要为
  `1124e420f453de1f6c448332ab05e6c2e8b589968240bb35dd452f39e363660c`。

`stage2-embedding-experiment-manifest.json`、
`stage2-embedding-summary.json`、`stage2-embedding-acceptance-report.md`、
`STAGE2-EMBEDDINGS-SHA256SUMS`、逐仓
`stage2-embedding-manifest.json`、验证报告和资源日志保存配置、命令、SHA、
计数、耗时、峰值内存及重复证据。26 份正式文件的 SHA 清单已再次完整通过。
全局 `stage2_embedding_ready_for_clustering=true`；本轮没有运行 DBSCAN。
收尾验证通过 `pip check`、`src`、`tests` 与三个阶段2实验脚本的 `compileall`、
全部 58 项确定性离线测试、26 仓 manifest/验证报告交叉校验、重复临时文件清理
检查及 `git diff --check`。

## 2026-07-25 阶段2 DBSCAN 默认基线与逐仓快速优化

使用 26 份正式 `stage2/embeddings.pkl` 逐仓运行原
`src.mining.clustering` 入口。首先固定执行 `eps=0.5`、
`min_samples=2` 默认基线；随后执行参数优化。粗扫覆盖
`eps=0.15/0.20/0.25/0.30/0.35/0.40` 与
`min_samples=2/3/4`，仅对落在下边界的仓库补扫更小 `eps`。参数选择先要求
覆盖率为 50%～80%、最大簇占全部候选不超过 15%，再使用有效簇数、跨文件簇数、
Top100 跨文件簇数、覆盖率、最大簇占比和余弦内聚度形成固定的仓库内无监督分数。
没有根据 IC、ISP、F1 或人工标签反复调参。

默认参数在 233,912 个候选上只形成 337 个大小至少为 2 的有效簇，覆盖率
99.69%，全局平均簇大小 691.98；26 仓最大簇占比均为 95.3%～99.9%，确认发生
严重密度连锁合并。逐仓参数最终形成 31,965 个有效簇，覆盖 156,436 个候选，
微平均覆盖率 66.88%，全局平均/中位簇大小为 4.89/2，跨文件簇为 12,719 个，
26 仓最大簇占比均不超过 10.86%。簇级平均直接子节点数为 3.21，簇级平均完整
子树节点数为 64.52。

正式逐仓参数分布为：`0.01/3` 1 仓、`0.05/4` 1 仓、`0.15/2` 6 仓、
`0.15/3` 1 仓、`0.175/2` 1 仓、`0.20/2` 8 仓、`0.20/3` 2 仓和
`0.25/2` 6 仓。若必须使用单一公共参数，当前扫描证据建议
`eps=0.20`、`min_samples=2`；正式 DBSCAN 结果仍采用逐仓选择。

默认与最终 52 次完整聚类全部成功。最终 26 份 `clusters.pkl` 均通过项目身份、
七列 Schema、最小簇大小、成员计数、代表代码、位置标签、命令参数和扫描指标
一致性验证。默认/最终汇总、参数表、Top100 代表代码和中文分析报告位于
`outputs/experiments/repo-isolated-v1/dbscan-*.{json,csv,md}`，逐仓完整产物、
命令、日志及资源指标位于
`repos/<repo>/stage2/{dbscan-default,dbscan-scan,dbscan-final}/`。Top100 人工
抽查同时观察到并发循环、参数转发、状态机分派等可用模式，以及高频
`return`/`break` 简单语句；后者不能仅靠继续减小 `eps` 消除，仍需后续质量
筛选。该结果只完成 DBSCAN 分支，尚不能替代与 HDBSCAN 的同口径对照。

## 2026-07-25 阶段2 HDBSCAN 对照与单一 DBSCAN 最终方案

在同一批 26 份逐仓 `embeddings.pkl` 上新增 `hdbscan 0.8.44` 实现，并保持既有
七列簇 DataFrame 合同。正式 HDBSCAN 先对原始 768 维向量做 L2 归一化，再使用
`random_state=0` 的 randomized PCA 降至 32 维；聚类空间使用欧氏距离、
`boruvka_kdtree`、`leaf`、`cluster_selection_epsilon=0`、
`approx_min_span_tree=true` 和单个 core-distance worker。代表代码不在降维空间
选择，而是回到原始 768 维向量，用余弦距离选择最接近簇质心的实际成员。26 仓
PCA-32 平均解释方差为 54.18%。

先在 `concurrentqueue`、`cpp-httplib`、`catch2`、`simdjson` 和 `taskflow`
上比较 `eom/leaf` 与代表参数，再冻结不含人工标签的小网格：
`min_cluster_size={2,3,5,10,20,50}`、
`min_samples={1,2}`、`cluster_selection_method=leaf`。这里使用第三方
`hdbscan` 包，其 `min_samples` 包含点本身。参数选择复用 DBSCAN 的严格门槛：
覆盖率 50%～80%、最大簇占全部候选不超过 15%，随后按有效簇、跨文件簇、
Top100 跨文件簇、覆盖目标、反坍缩和原始空间余弦凝聚度评分。26 个仓库全部在
严格门槛内完成选择，没有使用扩展或兜底门槛，也没有使用 IC、ISP、F1 或
人工标签。

正式逐仓 HDBSCAN 参数分布：

- `min_cluster_size=2, min_samples=1`：7 仓；
- `min_cluster_size=2, min_samples=2`：9 仓；
- `min_cluster_size=3, min_samples=1`：3 仓；
- `min_cluster_size=3, min_samples=2`：3 仓；
- `min_cluster_size=5, min_samples=2`：2 仓；
- `min_cluster_size=10, min_samples=2`：`entt`；
- `min_cluster_size=20, min_samples=2`：`simdjson`。

HDBSCAN 最终得到 47,702 个有效簇、172,056 个聚类成员和 61,856 个噪声点；
微平均覆盖率为 73.56%，全局平均/中位簇大小为 3.61/2，跨文件簇为 23,646 个。
簇宏平均直接子节点数为 3.19，簇宏平均完整子树节点数为 61.85。26 次正式运行
累计 329.36 秒，最大峰值 RSS 为 6,561,906,688 字节，约 6.11 GiB。正式
`clusters.pkl` 的项目身份、七列 Schema、最小簇大小、成员计数、参数和扫描
标签全部一致。

算法比较同时使用每仓 Top100 与 `Top100 ∩ Top20%`。无标签“强习语代理”要求：
代表代码完整子树至少 10 个节点、去空白长度至少 20、簇内至少两个不同源码文本，
并至少跨两个文件；排名使用 `1/log2(rank+1)` 折扣。DBSCAN/HDBSCAN 的
Top100 强习语代理分别为 1,030/1,086 个，排名折扣强习语率为
39.92%/39.15%，非平凡代表为 2,216/1,961 个，纯重复代表为 328/519 个，
代表 AST 子树均值为 68.27/52.05。`Top100 ∩ Top20%` 的强习语代理分别为
948/923 个，排名折扣强习语率为 42.65%/39.33%。

HDBSCAN 的有效簇更多、覆盖率更高，但全局平均簇大小仅为 3.61，新增供给主要
集中在长尾小簇；DBSCAN 已有 31,965 个有效簇，候选供给充足，同时头部代表更
非平凡、纯重复更少、AST 结构更完整。HDBSCAN 还需 PCA-32，而该空间平均只保留
54.18% 方差；其 329.36 秒正式耗时是 DBSCAN 117.03 秒的 2.81 倍。综合头部质量、
候选数量和运行代价，正式流程统一选择 DBSCAN，HDBSCAN 仅保留为实验对照。

曾依据各仓聚类后质量差异形成过算法名单，但该方法无法在未知仓库聚类前确定
算法，不具备可扩展性，因此在最终冻结前撤销。正式方案不保存
`clustering-routing.json`，也不按仓库名路由。26 个统一出口全部重新物化为
DBSCAN：共 31,965 个有效簇、156,436 个聚类成员，微平均覆盖率 66.88%，平均/
中位簇大小为 4.89/2，跨文件簇 12,719 个，簇宏平均直接子节点数 3.21，簇宏
平均完整子树节点数 64.52。逐仓统一出口为
`repos/<repo>/stage2/clustering-final/clusters.pkl`，26 个文件的 SHA-256、
项目身份和算法标记均已通过。

为新仓库新增 `src.mining.dbscan_tuning`，并把参数策略冻结为仅改进领域目标
函数的标准贝叶斯优化。论文方法的代理模型固定为高斯过程（GP），采集函数固定
为期望改进（EI）；二者不作改动，warm-start 只复用已有观测。搜索空间为
`eps∈[0.0025,0.50]` 的对数实数区间和 `min_samples∈[2,4]` 的整数区间。
选择器先要求覆盖率 50%～80% 且最大簇占比不超过 15%，无解时按冻结层级放宽。
目标函数只保留三个核心指标：跨文件复现供给 `R`、Top100 头部复现 `H` 和
密度平衡 `B`；其中 `B` 是覆盖率接近65%与抗最大簇塌缩得分的等权平均，最终
最大化 `J=0.45R+0.15H+0.40B`，GP 最小化 `1-J`。可行性判断在目标评价阶段
完成，不改变 GP 或 EI。

当前完整聚类不重跑。已有每仓 18/33/45 组参数观测作为 warm-start，以简化目标
回放后 26 个仓库的最佳已观测可行参数与既有冻结参数全部一致，额外参数评估为
0。该 warm-start incumbent 被正式记为改进贝叶斯优化在当前观测集和预算下的
参数输出，因此无需重新运行 DBSCAN。若后续增加预算，EI 再继续提出参数并更新
GP；当前结论是贝叶斯优化得到的最佳已观测可行值，不声称是连续空间全局最优。
该规则只读取当前仓库的 embedding、簇和来源文件，对任意项目名执行相同逻辑，
不使用人工标签或最终评价指标。回放证据位于
`dbscan-improved-bayesian-replay.json`；`concurrentqueue` 与 `simdjson` 的
真实 embedding 冒烟分别复现已有 `0.15/2` 和 `0.01/3` 选择。

`clustering-final-selection.json` 保存单一算法决策与参数，
`clustering-final-manifest.json` 保存统一出口身份与校验和，
`clustering-algorithm-comparison.{json,csv}` 和
`clustering-analysis-report.md` 保存完整对照证据，
`clustering-representative-quality.json` 保存两种算法全部 Top100 代表代码的
逐条结构代理判定。源码新增 `src.mining.dbscan_tuning`、
`src.mining.hdbscan_clustering` 和共享簇结果构造器；没有算法路由模块。
HDBSCAN 依赖通过约 2.6 MB 的 macOS CPython 3.12 wheel 安装，没有下载新
embedding 模型，没有调用 LLM，也没有向外部端点发送仓库源码。

收尾验证通过 `pip check`、`src/tests/实验脚本` 的 `compileall`、全部 60 项
确定性离线测试、七个公共包组合导入、DBSCAN 自动调参与 HDBSCAN CLI 帮助
入口、26 仓正式数据集 manifest 交叉校验、26 份 DBSCAN 统一产物 SHA-256
复核和 `git diff --check`。

阶段2最终验收状态为 `accepted_with_repository_quality_warnings`，可以结束。
Embedding 的 233,912 条候选与向量完全对齐，全部满足 CPU `float32`、
`1×768`、有限且非零，26/26 仓重复生成语义一致。DBSCAN 的逐仓覆盖率为
60.16%～74.57%，最大簇占比不超过 10.85%，每仓至少有 6 个跨文件簇；Top100
非平凡代表率为 86.33%、纯重复率为 12.78%、强习语结构代理率为 40.12%，
代表 AST 子树均值为 68.27。`cli11`、`concurrentqueue`、`cpp-httplib`、
`entt`、`magic_enum`、`simdjson` 和 `uwebsockets` 保留头部质量警告，交由
下游优先过滤，不触发反向调参。验收口径见
`docs/guides/stage2-acceptance.md`，机器可读结论和报告见
`stage2-acceptance.json` 与 `stage2-acceptance-report.md`。验收参考线不属于
贝叶斯优化目标，也不用于重新选择算法或参数。

### 2026-07-26 Sol 5.8 阶段2正式验收发布

项目版本升级到 `Sol 5.8`。本次发布完成 26 个仓库的正式 UniXcoder Embedding、
DBSCAN 默认基线与逐仓无监督调参、HDBSCAN 同口径对照、单一 DBSCAN 最终方案
及阶段2验收。DBSCAN 参数方法固化为使用既有观测 warm-start、由领域目标函数
改进的标准 GP-EI 贝叶斯优化；正式产物继续按仓库隔离，未根据最终 IC、ISP、
F1 或人工标签反向选择算法和参数。

发布同时补充 DBSCAN/HDBSCAN 共享簇结果构造、HDBSCAN 实现、DBSCAN 自动调参
与离线测试，项目入口版本、baseline 规范和评价指标规范统一标记为 `Sol 5.8`。
阶段2验收结论为“通过，但保留逐仓质量警告”，其结构代理只证明聚类结果适合作为
后续 LLM 的高质量候选集合，不直接把全部簇认定为最终代码习语。

### 2026-07-26 习语判断与习语合成架构实现

根据阶段职责重新建立两个语义包：`src.idiom_judgment` 负责单个聚类簇能否
成为习语，`src.idiom_synthesis` 负责同一区域内多个候选习语能否合成为质量
更高的习语；未建立 `stage3`、`stage4` 数字包。阶段编号只保留在研究叙事和
artifact 元数据中。

习语判断现包含单仓/单簇输入合同、支持度与低价值硬门禁、保守差异对齐、语义/
复用价值 Agent、共享代码异味 Agent、业务评分和独立异味门禁。抽象只对至少三个实例中高频、
位置稳定且低语义的局部变量或保守字面量生成提案，调用目标、类型、控制结构、
返回语义、哨兵值和格式字符串默认不抽象；语义/抽象 Agent 接收同簇全部代码、
规则初判和全部提案，显式返回 `abstract` 或 `keep`，且只能批准规则生成的提案。
确定性代码只应用批准集合与规则提案的交集；有效响应中的 `keep` 或无提案均保留
代表代码，不会单独拒绝习语。整份语义/抽象响应在修复和有界重试后仍失败时，
仍保留原代码作为审计证据，但语义与复用分安全降为0并拒绝。离线 `--rule-only` 输出
`pending_llm`，不会伪装成已接受习语。

习语合成正式读取习语判断 artifact 的 `accepted` 记录，按同一函数/区域分组。
阶段2 `clusters.pkl` 仍可由内部适配器归一化并接受严格阈值逻辑测试；程序化
传入只生成 `contract_only_not_executed` 空 artifact，不创建 Agent 或调用 LLM。
正式 CLI 不暴露该输入，实际实验也不执行阶段2直通。编排层在 LLM 调用前自动读取经范围和
内容哈希验证的同函数片段，失败时零调用拒绝；关系规划、代码组装和质量复审使用
独立路由 Agent，异味审查复用阶段3的同一 Agent 类型、分类和输入输出合同，但
针对当前合成结果重新执行。合成代码新增调用必须来自输入习语或该上下文。阶段2
合同分支保留业务质量门槛80的离线断言，正式阶段3输入门槛为70。评价器与可读产物导出器新增
`judgment`、`synthesis` 语义阶段；同名阶段继续兼容旧列表产物。

阶段3、阶段4的正式结果均只保留 `accepted` 与 `rejected`。阶段3总分按
规则20%、语义45%、复用35%计算；阶段4业务分直接使用质量复审分。异味不参与
两个阶段的业务评分，统一 Agent 只返回17类固定分类中的结构化发现，风险分由
严重度、置信度和多异味累积项确定性计算；`risk_score >= 60` 或异味分析失败
由独立 `smell_gate` 直接拒绝，不再输出 `manual_review`。每条已审查记录保存
完整审查输入、分类发现和门禁证据。

新增确定性事后审计入口，从阶段3和阶段4 artifact 分层抽取被异味过滤、未过滤和
分析失败样本，生成盲审标签模板；评价时报告总体/分阶段过滤准确性、Precision、
Recall、F1、误过滤率和漏报率，并按异味类别报告 TP、FP、FN、支持数和
P/R/F1。分析失败单独统计，不伪装成异味类别，也不进入检测准确性。

阶段3/4的 `JsonLLMAgent` 现固定为每条消息最多2次逻辑尝试；每次尝试仍复用共享
`src.llm` 的严格 JSON 解析、Schema 校验和1次修复，因此单 Agent 最多4次端点
请求。阶段3的两个并行分支和阶段4的两个复审分支使用异常隔离：一方失败不会取消
另一方。规划失败跳过组装与复审，组装/语法/新增调用门禁失败跳过两个复审；
命令级未预料异常只记录并跳过当前簇或组。判断 Schema 升至v5，合成 Schema
升至v4，新增 `agent_trace` 和汇总 `technical_failure_count`。

命名、抽象决策、Agent 失败恢复与异味门禁收口后，`pip check`、`src/tests` 的
`compileall`、全部86项
确定性离线测试、
判断/合成/评价/导出 CLI 帮助入口、跨项目17个共享基础设施文件检查和
`git diff --check` 均通过。另以 `cli11` 正式阶段2产物的前20个簇运行
`--rule-only`，20个结果均按合同标记为 `pending_llm`。

随后使用 `gpt-5.6-luna` 对完全手写的合成 C++ 片段执行三轮真实 smoke，没有
发送 `repos/` 或26仓正式源码。第一轮阶段3处理5个簇，10个 Agent 结构化调用
均一次成功，接受4簇、拒绝1簇：高频局部变量换名的两个簇得到抽象，锁守卫和
资源释放保持原样，固定小缓冲区配合 `strcpy` 的候选由独立异味门禁以
`memory_lifetime`、`unsafe_api` 和风险79.25过滤。阶段4随后对同函数中的资源
获取/检查与消费/释放两个阶段3习语执行4个 Agent 调用，自动读取并通过
SHA-256验证8行函数上下文，将占位符绑定为 `handle`，合成结果通过
Tree-sitter、禁止新增调用和质量复审；共享异味 Agent 报告异常路径手工释放的
中等 `resource_lifetime` 风险37.8，未达到60的独立过滤阈值。

第二轮阶段3边界 smoke 处理4个簇，8个 Agent 调用均一次成功。规则对
`configure_retries(2/4/8)` 提出字面量抽象候选，但语义 Agent 返回 `keep`，
验证数值语义不会仅因高频变化被抽象；命令拼接后调用 `std::system` 的候选以
`unsafe_api`、`error_handling` 和风险100过滤，分离线程引用捕获候选以
`memory_lifetime` 和风险66过滤。指标名簇保持原样并通过。另以不存在的源码根
运行阶段4上下文门禁，规划、组装、质量和异味4个 Agent 均记录
`not_run`、逻辑调用数0，候选组安全拒绝。

三次成功的真实运行合计得到22个有效结构化响应，没有触发 JSON 修复、逻辑重试
或技术失败。第一次在受限网络环境内尝试时，5个簇全部在连接层失败；有界重试、
逐簇继续和 `technical_failure_count=5` 按设计生效，随后在获准网络环境中重新
运行成功。真实运行还暴露并修复了判断/合成 CLI 在加载根 `.env` 之前检查
`OPENAI_API_KEY` 的启动顺序错误，并增加回归测试。端点把模型别名
`gpt-5.6-luna` 解析为带日期的快照，AutoGen 因别名与响应模型名不同打印成本
估算提示；实际 JSON 模式和调用结果不受影响，当前不据此改写冻结模型档位。

可复现输入、规则预检和真实产物分别位于已忽略的
`outputs/llm-smoke/stage34-20260726*/` 与
`results/llm-smoke/stage34-20260726*/`。从阶段3/4产物提取的10个合成样本又
执行了一次已知用例意图 oracle 审计，过滤 Precision、Recall、F1 和 Accuracy
均为1.0，五个出现类别的宏 F1 为1.0。该 oracle 只验证审计连线与已设计用例，
不是正式双人盲审、模型质量结论或论文结果。正式26仓习语判断、合成、人工审计
和指标实验仍需冻结逐仓调用预算与非公开源码披露范围。

### 2026-07-26 Sol 5.9 阶段3/4发布

阶段4分组进一步收紧为代表 `project + source_path + source_extent` 完全一致；
历史 `loc_label` 只用于展示，缺少可验证代表范围的候选使用独立键，不会因标签
相同而误合成。阶段4 artifact 固定为 `synthesis_delta`，显式记录
`passthrough_included=false`，只保存合成尝试和成功增量；单例、未选择和未成功
合成的习语继续由阶段3 `accepted` 持有。判断与合成 Schema 当前均为v6。

阶段3和阶段4复用同一代表范围加载器，验证项目、相对路径、范围和整文件
SHA-256。阶段4只保留三个核心确定性检查：上下文合同、Tree-sitter 语法和新增
调用目标；此前追加的敏感操作类别与调用顺序门禁及其重复结果字段已移除。长时
运行的 SQLite checkpoint 把 Schema 版本纳入配置一致性合同。

`src.agents` 中旧语义、语法、综合判断、旧判断流水线、旧规划、旧组装和旧合成
等8个业务模块已删除；旧习语列表到阶段4的输入适配也已删除。该包现在只保留
`base.py`、`_base.py`、最小导出和 README。旧三 Agent 专用的4项测试随死代码
删除；评价合同测试改为直接读取当前 `idiom_judgment` artifact。最终依赖检查、
`compileall` 和89项确定性离线测试全部通过。

本轮真实 smoke 仍只使用手写合成 C++，模型为 `gpt-5.6-luna`。受限网络中的
首次阶段3运行验证了连接失败、两次有界重试和逐簇拒绝；获准网络后，严格上下文
阶段3接受2/2个簇，其中1个抽象、1个保持原样，两个上下文均验证成功，使用
7,521个输入 token 与1,985个输出 token。阶段4在三次逐步收口运行中均接受同一
严格区域的1个合成增量；最终 Schema v6 运行使用5,372个输入 token 与1,174个
输出 token，`passthrough_candidate_count=0`，核心三个确定性检查均通过，未发生
技术失败。中间运行用于确认提示词命名和精简前后行为，不作为额外研究样本。

## 当前阻碍与延期工作

1. 中转端点、凭据加载、Luna JSON 模式以及当前二态评分、自动上下文、共享异味
   和失败回退合同已通过22个初始纯合成真实响应、本轮16个收口响应与离线故障
   注入。完整语料的付费
   Agent 评估仍有意延期，因为逐仓预算、非公开源码披露范围和研究有效性需要
   单独冻结；合成 smoke 的成功率不能外推为26仓质量。
2. 新冻结的 26 项目已完成正式阶段1、全量 tokenizer 长度治理、逐仓
   UniXcoder embedding、DBSCAN 默认基线、HDBSCAN 对照和单一 DBSCAN 最终
   聚类。历史
   三个快照上的 96,039 个片段仍只作旧语料证据，不得与新正式产物混用。
3. Baseline 实现和有界验证已获授权并完成，固定源码 commit 与总语料 manifest
   也已形成。完整 CIMAS token 测量及源码披露/成本决策属于后续付费 Agent
   运行门槛；后续应先由习语判断逐仓消费 `clustering-final/clusters.pkl`，
   习语合成再消费其 `accepted` 产物；阶段2到阶段4只保留不启动 Agent 的合同
   适配，不执行后备或消融合成。不得根据最终 IC、ISP 或 F1 反向调整本轮算法
   与参数。
4. `requirements-local.lock` 提高了可复现性；正式 `requirements.txt` 对科学计算包仍使用宽泛版本范围，但现已包含 Agent 技术栈。过时的非 C++ grammar 依赖已移除。
5. 包预先导入导致的 CLI `runpy` 警告仍不影响运行。跨项目基础设施对齐期间，追加式运行日志器已消除早先的预先导入日志截断问题。

## 建议的下一项决策

下一项实验级决策是先运行习语判断的离线规则预检，统计硬拒绝、
`pending_llm`、抽象提案和预计逻辑调用量，再估算 token、费用和源码披露量。
随后才能决定是否执行正式单簇 LLM 判断及多习语合成。可以先使用少量公开仓库
代表簇验证接受率和 Schema，但冒烟结果不得作为正式习语质量结论，也不得用于
反向重调阶段2聚类参数。
