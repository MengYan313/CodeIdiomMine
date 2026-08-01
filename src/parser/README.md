# Parser

Parser 扫描当前 C/C++ 仓库，用 Tree-sitter 提取函数 AST、源码范围、解析诊断和多粒度候选。文件身份是仓库相对 POSIX 路径。

```bash
.venv/bin/python -m src.parser.repo2data \
  --input repos --project cli11 \
  --output outputs/cpp/cli11/dataset.pkl \
  --audit-output outputs/cpp/cli11/dataset.audit.json \
  --fragment-output outputs/cpp/cli11/fragments.pkl \
  --embedding-model unixcoder --local-files-only
```

当前只存在一套候选规则和一套数据格式。`fragments.pkl` 是嵌入阶段的唯一输入，包含原始片段、候选信息、拒绝记录和统计。

解析器允许 Tree-sitter 对不完整 C++ 产生诊断与有限恢复，但不会为旧 AST、旧字段或旧候选策略提供兼容路径。
