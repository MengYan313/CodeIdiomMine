# Parser 模块

本模块以零构建方式扫描 C/C++ 源码，生成 AST、逐文件审计侧车和满足目标 tokenizer 长度约束的候选片段。目标仓库无需编译、链接或执行；单文件失败不会中止其他文件。

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

详细设计见 [Parser v2](../../docs/guides/parser-design.md)，复杂语法与长度策略见 [C++ Adapter 与模型输入治理](../../docs/guides/cpp-adapter-and-model-input.md)。
