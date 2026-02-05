# CodeIdiomMine

代码习语挖掘项目 - 从源代码仓库中挖掘常见的代码模式和习语。

## 项目结构

```
CodeIdiomMine/
├── common/              # 公共模块（共享定义和工具）
│   ├── __init__.py
│   └── node_kinds.py   # AST 节点类型定义
├── parser/              # 代码解析模块
│   ├── ast_parser.py   # AST 解析器（基于 tree-sitter）
│   ├── file_scanner.py # 文件扫描器
│   └── repo2data.py    # 主入口文件
├── mining/              # 代码习语挖掘模块
│   ├── code_embedding.py  # 代码嵌入（使用 CodeLLaMA 7B）
│   └── clustering.py      # 聚类分析（DBSCAN）
├── repo/                # 源代码仓库（输入）
│   └── cpp/            # C++ 项目
├── output/              # 输出结果
│   └── cpp/            # C++ 解析结果
├── requirements.txt     # 统一依赖包
├── .gitignore          # Git 忽略文件
└── README.md           # 项目说明
```

## 安装

### 1. 创建 conda 环境

```bash
conda create -n cim python=3.14 -y
conda activate cim
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

## 使用方法

### 步骤 1: 解析代码仓库

```bash
cd parser
python repo2data.py \
    --input ../repo/cpp \
    --output ../output/cpp/dataset.pkl \
    --language cpp
```

**参数说明**:
- `--input, -i`: 输入项目路径
- `--output, -o`: 输出数据文件路径
- `--language, -l`: 编程语言类型（`cpp`, `python`, `java`, `javascript`）

**输出格式**: pickle 格式的 DataFrame，包含：
- `project`: 项目名称列表
- `cppFile`: 文件路径列表（2D: 项目-文件）
- `func_ast`: 函数 AST 节点信息列表（3D: 项目-文件-函数）
- `func_src`: 函数源代码列表（3D: 项目-文件-函数）

### 步骤 2: 生成代码嵌入

```bash
cd mining
python code_embedding.py \
    --input ../output/cpp/dataset.pkl \
    --output ../output/cpp/embeddings.pkl \
    --model codellama/CodeLlama-7b-hf \
    --language cpp
```

**参数说明**:
- `--input, -i`: 输入的 AST 数据文件路径
- `--output, -o`: 输出的嵌入数据文件路径
- `--model, -m`: 模型名称（默认: `codellama/CodeLlama-7b-hf`）
- `--language, -l`: 编程语言类型
- `--device, -d`: 设备（`cuda`/`cpu`，默认自动选择）

**输出格式**: pickle 格式的 DataFrame，包含：
- `pros_name`: 项目名称列表
- `pros_src`: 代码片段列表（2D）
- `pros_emb`: 嵌入向量列表（2D，torch.Tensor）
- `pros_info`: 信息列表（2D）

### 步骤 3: 执行聚类

```bash
cd mining
python clustering.py \
    --input ../output/cpp/embeddings.pkl \
    --output ../output/cpp/clusters.pkl \
    --eps 0.5 \
    --min-samples 2
```

**参数说明**:
- `--input, -i`: 输入的嵌入数据文件路径
- `--output, -o`: 输出的聚类结果文件路径
- `--eps, -e`: DBSCAN eps 参数（默认: 0.5）
- `--min-samples, -m`: DBSCAN min_samples 参数（默认: 2）
- `--optimize`: 是否优化聚类参数（使用贝叶斯优化）

**输出格式**: pickle 格式的列表，每个元素包含：
- `pros_name`: 项目名称
- `clusters`: DataFrame，包含簇标签、中心点代码片段、簇大小等信息

## 模块说明

### Parser 模块

- **功能**: 将源代码解析为 AST，提取函数节点和代码片段
- **技术**: tree-sitter（支持多语言）
- **支持语言**: C++、Python、Java、JavaScript
- **特性**: 
  - 自动识别不同语言的源代码文件扩展名
  - 自动过滤测试文件和隐藏目录
  - 提取函数级别的代码片段和 AST 节点信息

### Mining 模块

- **代码嵌入**: 使用 CodeLLaMA 7B 生成代码嵌入向量
  - 支持更长的代码序列（最大 2048 tokens）
  - 4096 维输出（更高的表达能力）
  - 自动 GPU 分配和多 GPU 支持
  - 使用 float16 半精度以节省显存
- **聚类分析**: 使用 DBSCAN 算法进行基于密度的聚类
  - 支持贝叶斯优化自动选择最佳参数
  - 自动识别频繁代码习语

### Common 模块

- **节点类型定义**: 统一的 AST 节点类型定义
- **支持语言**: C++、Python、Java、JavaScript
- **导入方式**: `from common.node_kinds import get_node_kinds, get_func_kinds`

## 配置

### 环境变量（可选）

复制 `env.example` 为 `.env` 并修改配置：

```bash
cp env.example .env
```

主要配置项：
- `EMBEDDING_MODEL`: 嵌入模型名称
- `DEVICE`: 设备（`auto`, `cuda`, `cpu`）
- `REPO_PATH`: 源代码仓库路径
- `OUTPUT_PATH`: 输出结果路径

## 注意事项

### 模型要求

- **模型大小**: CodeLLaMA 7B 约 13GB，确保有足够的磁盘空间
- **GPU 推荐**: 强烈建议使用 GPU（至少 16GB 显存），CPU 模式会非常慢
- **首次运行**: 会自动下载模型（使用 HuggingFace 缓存），下载可能需要较长时间

### 使用建议

- 确保已安装对应语言的 tree-sitter 语言库
- 输出目录会自动创建
- 测试文件和隐藏目录会被自动跳过
- 解析失败的文件会被跳过，不会中断整个流程
- 聚类参数优化可能需要较长时间，建议先在小数据集上测试

## 开发

### 安装为开发包

```bash
pip install -e .
```

### 导入方式

所有模块统一从 `common.node_kinds` 导入节点类型：

```python
from common.node_kinds import get_node_kinds, get_func_kinds, get_block_kinds, get_stmt_kinds
```

## 许可证

[添加许可证信息]

## 贡献

[添加贡献指南]
