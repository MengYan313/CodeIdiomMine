# Mining & Parser 模块测试指南

## ✅ 改动总结

### 1. 所有模块统一使用相对导入
- ✅ 移除了所有 `sys.path.insert()` 代码
- ✅ 使用相对导入（`from ..common import xxx`）
- ✅ 所有模块都支持 `python -m` 方式运行

### 2. 全面集成 Logger 系统
- ✅ `src/mining/code_embedding.py` → `log/code_embedding.log`
- ✅ `src/mining/clustering.py` → `log/clustering.log`
- ✅ `src/parser/repo2data.py` → `log/repo2data.log`
- ✅ `src/parser/ast_parser.py` → `log/ast_parser.log`
- ✅ `src/parser/file_scanner.py` → `log/file_scanner.log`

### 3. 日志特性
- 控制台：简化输出（INFO 级别）
- 文件：详细日志（DEBUG 级别）
- 每个脚本对应一个 `.log` 文件

### 4. 默认路径修改
- ✅ 所有默认路径改为从项目根目录开始
- ✅ 例如：`output/cpp/dataset.pkl` 而不是 `../../output/cpp/dataset.pkl`

### 5. 添加运行命令注释
- ✅ 每个模块文件末尾都有模块运行命令示例
- ✅ 包含前台和后台（nohup）两种运行方式

---

## 🧪 完整测试流程

### 前置条件

```bash
# 1. 激活虚拟环境
conda activate cim

# 2. 确保在项目根目录
cd /home/wenxinyao/zju-pro/CodeIdiomMine

# 3. 检查数据文件
ls -lh output/cpp/dataset.pkl
```

---

## 测试步骤

### 步骤 0: （可选）测试 Parser 模块

如果需要重新解析代码仓库：

```bash
python -m src.parser.repo2data \
    --input repo/cpp \
    --output output/cpp/dataset_new.pkl \
    --language cpp
```

**预期结果：**
- ✅ 控制台输出简化日志（INFO 级别）
- ✅ 生成 `log/repo2data.log` 文件（详细日志）
- ✅ 生成 `output/cpp/dataset_new.pkl` 文件

**查看日志：**
```bash
cat log/repo2data.log
# 或实时查看
tail -f log/repo2data.log
```

---

```bash
# 测试命令
python -m src.mining.code_embedding \
    --input output/cpp/dataset.pkl \
    --output output/cpp/embeddings_test.pkl \
    --model unixcoder \
    --min-project-size 10
```

**预期结果：**
- ✅ 控制台输出简化日志（INFO 级别）
- ✅ 生成 `log/code_embedding.log` 文件（详细日志）
- ✅ 生成 `output/cpp/embeddings_test.pkl` 文件

**查看日志：**
```bash
cat log/code_embedding.log
```

**如果需要后台运行：**
```bash
nohup python -m src.mining.code_embedding \
    --input output/cpp/dataset.pkl \
    --output output/cpp/embeddings_test.pkl \
    --model unixcoder \
    --min-project-size 10 > log/embedding_run.log 2>&1 &

# 查看实时日志
tail -f log/code_embedding.log
```

---

### 步骤 2: 测试聚类

```bash
# 测试命令（依赖步骤1生成的 embeddings_test.pkl）
python -m src.mining.clustering \
    --input output/cpp/embeddings_test.pkl \
    --output output/cpp/clusters_test.pkl \
    --eps 0.5 \
    --min-samples 2
```

**预期结果：**
- ✅ 控制台输出简化日志（INFO 级别）
- ✅ 生成 `log/clustering.log` 文件（详细日志）
- ✅ 生成 `output/cpp/clusters_test.pkl` 文件

**查看日志：**
```bash
cat log/clustering.log
```

**如果需要后台运行：**
```bash
nohup python -m src.mining.clustering \
    --input output/cpp/embeddings_test.pkl \
    --output output/cpp/clusters_test.pkl \
    --eps 0.5 \
    --min-samples 2 > log/clustering_run.log 2>&1 &

# 查看实时日志
tail -f log/clustering.log
```

---

### 步骤 3: （可选）测试 Parser 模块

```bash
# 重新解析代码仓库生成 dataset.pkl
python -m src.parser.repo2data \
    --input repo/cpp \
    --output output/cpp/dataset_new.pkl \
    --language cpp
```

---

## 📊 验证测试结果

```bash
# 检查生成的文件
ls -lh output/cpp/embeddings_test.pkl
ls -lh output/cpp/clusters_test.pkl

# 查看所有日志文件
ls -lh log/

# 检查日志内容（前20行）
head -n 20 log/code_embedding.log
head -n 20 log/clustering.log
```

---

## 🎯 测试不同模型（可选）

### UniXcoder（推荐，轻量级）
```bash
python -m src.mining.code_embedding \
    --input output/cpp/dataset.pkl \
    --output output/cpp/embeddings_unixcoder.pkl \
    --model unixcoder \
    --min-project-size 10
```

### CodeBERT（中等）
```bash
python -m src.mining.code_embedding \
    --input output/cpp/dataset.pkl \
    --output output/cpp/embeddings_codebert.pkl \
    --model codebert \
    --min-project-size 10
```

### CodeLLaMA（大模型，需要 GPU）
```bash
python -m src.mining.code_embedding \
    --input output/cpp/dataset.pkl \
    --output output/cpp/embeddings_codellama.pkl \
    --model codellama \
    --min-project-size 10
```

---

## 📝 查看帮助文档

```bash
# 代码嵌入帮助
python -m src.mining.code_embedding --help

# 聚类帮助
python -m src.mining.clustering --help

# Parser 帮助
python -m src.parser.repo2data --help
```

---

## ⚠️ 可能遇到的问题

### 问题 1: ModuleNotFoundError
**现象：** `ModuleNotFoundError: No module named 'src'`

**解决：** 确保从项目根目录运行命令
```bash
cd /home/wenxinyao/zju-pro/CodeIdiomMine
pwd  # 应该显示 /home/wenxinyao/zju-pro/CodeIdiomMine
```

### 问题 2: 相对导入错误
**现象：** `ImportError: attempted relative import with no known parent package`

**解决：** 必须使用 `python -m` 方式运行，不能直接运行脚本
```bash
# ✅ 正确
python -m src.mining.code_embedding ...

# ❌ 错误
python src/mining/code_embedding.py ...
```

### 问题 3: 模型下载缓慢
**现象：** 模型下载时间过长

**解决：**
- UniXcoder 约 500MB，首次使用需下载
- 检查网络连接
- 可以预先下载模型到 `~/.cache/huggingface/`

### 问题 4: 内存不足
**现象：** `RuntimeError: CUDA out of memory` 或系统卡顿

**解决：**
```bash
# 降低项目大小阈值
--min-project-size 10

# 或者只处理部分数据
# 可以手动修改 dataset.pkl，只保留少量项目
```

---

## ✅ 测试清单

完成测试后，请检查以下项目：

- [ ] 代码嵌入命令成功运行
- [ ] 生成了 `output/cpp/embeddings_test.pkl` 文件
- [ ] 生成了 `log/code_embedding.log` 日志文件
- [ ] 聚类命令成功运行
- [ ] 生成了 `output/cpp/clusters_test.pkl` 文件
- [ ] 生成了 `log/clustering.log` 日志文件
- [ ] 控制台输出简化日志（只有 INFO 级别）
- [ ] 日志文件包含详细信息（包括 DEBUG 级别）

---

## 📤 反馈测试结果

测试完成后，请提供以下信息：

1. **运行结果：** ✅/❌
2. **生成的文件：** 列出 `output/cpp/` 和 `log/` 目录内容
3. **错误信息：** 如有错误，提供完整错误堆栈或日志内容
4. **日志片段：** 提供 `log/code_embedding.log` 和 `log/clustering.log` 的前30行

示例反馈：
```bash
# 查看生成的文件
ls -lh output/cpp/*.pkl
ls -lh log/*.log

# 查看日志前30行
head -n 30 log/code_embedding.log
head -n 30 log/clustering.log
```

