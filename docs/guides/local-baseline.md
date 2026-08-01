# 本地运行基线

当前本地工作区使用项目根目录 `.venv`。依赖安装入口为 `requirements.txt`；`requirements-local.lock` 仅保留在本机并由 Git 忽略。

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -t . -v
```

数据集清单只包含 [`cpp-dataset-selection.json`](../research/cpp-dataset-selection.json) 中的 23 个正式项目。当前统计见 [`cpp-dataset-statistics.json`](../research/cpp-dataset-statistics.json)，当前分析清单见 [`cpp-dataset-manifest.json`](../research/cpp-dataset-manifest.json)。

离线测试是代码变更的必要基线。真实 Parser、embedding、聚类和 LLM 实验按根 `README.md` 的当前命令运行；中间产物写入 `outputs/`，最终产物写入 `results/`。

本文不维护历史提交、旧产物对照或发布记录。新的可重复事实应由当前脚本和测试直接生成。
