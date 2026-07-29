# C++ 习语类型目录与开放分类合同

阶段3和阶段4采用“受控目录分类 + 仓库内开放发现”的混合合同。目录分类用于识别
已有 C++ 文献和工程资料已经命名的通用习语；开放发现用于保留无法可靠对应已有
类型、但在当前仓库内重复出现且通过全部有效性门禁的专属习语。类型判定不参与
聚类、业务评分或异味风险分，不能为了提高已知类型占比而强行匹配。

## 一、最终习语库的知识组织定位

CodeIdiomMine 在发现层坚持仓库隔离，在知识组织层采用双层分类，并提供全量联合
视图。三个概念的边界固定如下：

| 知识视图 | 运行时条件 | 标识作用域 | 主要用途 |
| --- | --- | --- | --- |
| 目录化通用习语（cataloged common idiom） | `kind=cataloged`，且类型编号属于当前受控目录 | `taxonomy_version + catalog_id` | 按已知类型跨仓库汇总、比较，并在满足适用前提时复用 |
| 仓库专属习语（repository-specific idiom） | `kind=repository_specific` | 项目和阶段内记录身份 | 分析当前仓库特有或尚未被目录收录的稳定实践 |
| 全量联合视图（combined idiom view） | 前两类已接受习语的并集 | 保留原始类别及各自标识作用域 | 分析项目产生的全部习语，不抹平通用/专属边界 |

“目录化通用”表示该习语能够与当前版本的已有类型目录精确对应，因此允许在所有
仓库分别完成挖掘后，按稳定类型编号进行跨仓库知识聚合，也可作为跨仓库复用候选。
复用仍须保留来源、适用前提和代码上下文，不等于把某个仓库的原始片段直接移植到
另一仓库。

“仓库专属”是相对于**当前目录版本**作出的操作性分类，而不是对习语本体性质的
永久断言。它既包括真正依赖项目约定的专属习语，也包括可能具有一般意义、但尚未
被现有目录命名或证据不足以可靠归类的不常见通用习语。后一类在目录正式扩充并
完成版本迁移前仍按仓库专属习语管理，不得凭相似印象跨仓库合并。

这套知识组织不改变仓库隔离挖掘原则：候选、embedding、聚类、阶段3判断和阶段4
合成都只使用当前仓库证据；跨仓库的通用类型聚合只能发生在各仓库独立完成流水线
之后。阶段4还必须针对当前合成结果重新判定类型，不能直接继承来源习语的类别。

## 二、研究依据

当前目录版本为 `cpp-common-idioms-v1`，其类型边界依据由同级 thesis 的
[英文文献库](../../../thesis/references/英文文献库.md)统一维护：

- thesis 全局文献编号 `[E003]`：Sutton、Holeman 与 Maletic 的
  *Identification of Idiom Usage in C++ Generic Libraries*，为 `traits`、
  `tag-dispatch`、`sfinae`、`crtp` 等泛型库习语提供研究依据；
- thesis 全局文献编号 `[E025]`：*More C++ Idioms*，
  提供覆盖资源管理、对象语义、泛型编程和接口设计的候选目录；
- thesis 全局文献编号 `[E111]`：James O. Coplien 的
  *Advanced C++ Programming Styles and Idioms*，
  用于确认“习语”是反复出现、依赖语言机制并解决设计问题的程序结构，而不只是
  任意相似代码；
- thesis 全局文献编号 `[E112]`：*C++ Core Guidelines*；
- thesis 全局文献编号 `[E113]`：cppreference 的 RAII 说明；
- thesis 全局文献编号 `[E114]`：cppreference 的三/五/零法则说明；
- thesis 全局文献编号 `[E115]`：Boost.Scope 的 Scope Guards 文档。

上述资料用于收紧资源生命周期、特殊成员和作用域清理类习语的识别边界。完整
著录、官方 URL 和全局稳定编号只由 thesis 文献库维护，本仓库不复制书目。
`src.idiom_judgment.idiom_taxonomy` 只保存运行所需的稳定类型编号、名称、简短
识别提示和来源编号。

## 三、受控目录

目录有意保持紧凑，只纳入能够从局部代码、完整簇和已验证代表区域中形成相对明确
证据的类型。它不是 C++ 习语的穷尽清单。

| 领域 | 稳定类型编号 | 中文名称 |
| --- | --- | --- |
| 资源与所有权 | `raii`、`scope-guard`、`smart-pointer-ownership` | 资源获取即初始化、作用域守卫、智能指针所有权 |
| 特殊成员与值语义 | `rule-of-zero`、`rule-of-three-five`、`copy-and-swap`、`copy-on-write`、`intrusive-reference-counting` | 零法则、三/五法则、复制并交换、写时复制、侵入式引用计数 |
| 构造与封装 | `construct-on-first-use`、`pimpl`、`non-copyable`、`named-constructor` | 首次使用时构造、编译防火墙、不可复制类型、命名构造函数 |
| 接口与多态 | `crtp`、`non-virtual-interface`、`type-erasure`、`thread-safe-interface` | 奇异递归模板模式、非虚接口、类型擦除、线程安全接口 |
| 泛型与编译期分派 | `traits`、`tag-dispatch`、`sfinae`、`policy-based-design`、`expression-template`、`empty-base-optimization` | 特征类、标签分派、替换失败非错误、策略式设计、表达式模板、空基类优化 |
| STL 与可调用结构 | `erase-remove`、`iterator-pair`、`function-object` | 擦除-移除、迭代器对、函数对象 |
| 类型约束 | `type-safe-enum` | 类型安全枚举 |

类型目录的变化会改变提示词哈希和实验解释。增加、删除、拆分或合并类型时必须：

1. 升级 `IDIOM_TAXONOMY_VERSION`；
2. 更新阶段3、阶段4提示词版本和离线测试；
3. 记录研究依据与兼容影响；
4. 不用正式 IC、ISP、F1 或人工标签反复挑选目录。

## 四、三态分类合同

最终有效性 Agent 输出 `is_idiom`，并同时返回 `idiom_classification`：

```json
{
  "kind": "cataloged",
  "catalog_ids": ["raii"],
  "confidence": 92,
  "reason": "资源获取和释放由同一局部对象的构造与析构边界管理。"
}
```

确定性代码把它标准化为含目录版本、中文/英文名称和标签的产物字段。三种
`kind` 的含义固定如下：

| `kind` | 使用条件 | `catalog_ids` | 最终标签 |
| --- | --- | --- | --- |
| `cataloged` | 候选是习语，且有充分证据与目录类型精确对应 | 1～3 个受控编号 | 对应的具体类型名称；知识层归入目录化通用习语 |
| `repository_specific` | 候选是习语，但无法与目录可靠对应 | 空数组 | `仓库特有习语`；知识层归入仓库专属习语 |
| `not_applicable` | 候选不是习语，或技术失败后安全拒绝 | 空数组 | `非习语` |

`repository_specific` 不是“低质量”“未知错误”或兜底接受标签。它仍必须先满足
仓库内重复、稳定意图、复用价值、上下文合同、业务质量和独立异味门禁。它表达的
只是：当前证据支持这是该仓库内部可成立的习语，但不足以认定为当前目录中的已有
通用类型。即使该模式实际上可能是不常见的通用习语，在当前目录版本下仍按
`repository_specific` 处理。

以下情况视为无效领域载荷并安全拒绝：

- `is_idiom=false` 却选择已知或仓库特有类型；
- `cataloged` 没有合法目录编号，或选择超过3个编号；
- `repository_specific` 携带目录编号；
- 类型编号不在当前版本目录；
- `confidence` 不是 0～100 的有限数；
- 判断理由或分类理由为空。

## 五、理由链与人工审计

所有承担选择、生成或有效性判断的 Agent 都必须输出非空中文 `reason`：

- 阶段3：语义/抽象/类型 Agent、共享异味审查 Agent；
- 阶段4：合成规划 Agent、代码组装 Agent、质量/有效性/类型复审 Agent、
  共享异味审查 Agent。

阶段3 Schema v8 在每条记录保存 `decision_reason`、`idiom_classification` 和
`agent_reasons`；阶段4 Schema v7 继续携带来源阶段3的判断理由和类型，并对当前
合成结果重新分类，以顶层 `source_judgments` 保存来源证据，并保存规划、组装、
质量、类型与异味理由。最终确定性裁决会把
业务有效性依据和异味依据汇入 `decision_reason`，供后续抽样和人工审计使用。

阶段3理由只能引用代表代码、词法去重变体、四项簇统计和规则证据；阶段4理由
可以引用已验证源码上下文、来源习语、合成代码和结构化检查结果。不得编造未提供
的业务背景；证据不足时应降分、归为
`repository_specific`，或判定为非习语，而不是用相近目录名称填补信息缺口。
