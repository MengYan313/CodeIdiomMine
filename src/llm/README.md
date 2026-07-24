# LLM 基础设施

本模块集中管理根目录 `.env`、模型分档、AutoGen 客户端、JSON mode、Schema 校验、单次响应修复和客户端关闭。领域提示词与阈值不放在这里。

该模块是库，不提供独立实验入口。离线验证命令：

```bash
.venv/bin/python -m unittest discover -s tests/llm -t . -v
```

调用规范见[两项目共享开发约定](../../docs/guides/shared-development-conventions.md)，提示词规则见[提示词工程指南](../../docs/guides/prompt-engineering-guide.md)。
