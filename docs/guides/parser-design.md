# Parser 设计

Parser 使用 Tree-sitter C++ 在不构建项目的情况下扫描 `.c/.cc/.cpp/.cxx/.c++/.h/.hh/.hpp/.hxx` 文件。

## 数据流

1. `FileScanner` 排除构建目录、依赖副本、示例、测试和生成文件。
2. `ASTParser` 记录函数 AST、源码范围、实体与解析诊断。
3. 候选选择器生成函数、区域、语句和 Def-Use 语义片段。
4. `fragment_builder` 按目标模型 token 预算生成 `fragments.pkl`。

`source_file_id` 就是仓库相对 POSIX 路径；范围使用原文件字节偏移和行列位置。函数根保存文件身份，候选直接继承它。

Tree-sitter 的容错树可能包含 `ERROR` 节点。预处理器影子仅帮助恢复周围语法边界，恢复结果会带诊断，不会伪装成干净函数。候选过长时按模型预算裁剪或拒绝，不维护第二套候选策略。

当前 Parser 产物是唯一受支持输入。改变字段时同步修改消费者和测试，不增加旧格式分支。
