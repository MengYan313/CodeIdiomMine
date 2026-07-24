# Parser 模块

本模块以零构建方式扫描 C/C++ 源码，生成 AST、逐文件审计侧车和满足目标 tokenizer 长度约束的候选片段。目标仓库无需编译、链接或执行；单文件失败不会中止其他文件。

每个仓库是独立的 Parser 和后续挖掘单元。多个仓库必须分别生成各自的
`dataset.pkl`、`dataset.audit.json` 和 `fragments.pkl`；不要合并不同仓库的
片段。已有 canonical `dataset.pkl` 通过固定 commit、Parser 指纹、审计侧车和
SHA 核对后，可以直接用 `src.parser.fragment_builder` 补建片段，无需重复 AST
解析。

## 启动命令

```bash
.venv/bin/python -m src.parser.repo2data \
  --input repos --project cli11 \
  --output outputs/cpp/cli11/dataset.pkl \
  --fragment-output outputs/cpp/cli11/fragments.pkl \
  --embedding-model unixcoder --local-files-only

.venv/bin/python -m src.parser.audit \
  --source-root repos \
  --dataset outputs/cpp/cli11/dataset.pkl \
  --output outputs/cpp/cli11/parser-audit.json
```

从已经审计的 AST 产物单独补建模型输入：

```bash
.venv/bin/python -m src.parser.fragment_builder \
  --input outputs/cpp/cli11/dataset.pkl \
  --output outputs/cpp/cli11/fragments.pkl \
  --model unixcoder --candidate-profile quality-v2 --local-files-only

.venv/bin/python -m src.parser.token_length_audit \
  --dataset outputs/cpp/cli11/dataset.pkl \
  --output outputs/cpp/cli11/token-length-audit.json \
  --model unixcoder --candidate-profile quality-v2 --local-files-only
```

详细设计见 [Parser v2](../../docs/guides/parser-design.md)，复杂语法与长度策略见 [C++ Adapter 与模型输入治理](../../docs/guides/cpp-adapter-and-model-input.md)。
