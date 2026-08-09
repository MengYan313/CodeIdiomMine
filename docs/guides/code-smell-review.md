# C++代码异味审查与事后审计

本文定义阶段3和阶段4共享、但对每个候选独立执行的代码异味机制。异味审查是
习语价值与合成质量之外的独立过滤关卡，不参与二者的加权评分，也不能被高语义分、
高复用分或高合成质量分抵消。

## 一、设计依据与边界

文献编号与完整著录由同级 thesis 仓库的
[英文文献库](../../../thesis/references/英文文献库.md)统一维护；本仓库不建立
文献库副本。运行时审计只保存 thesis 稳定编号、名称和官方 URL，不复制可漂移的
书目信息。

代码异味是提示更深层问题的风险信号，不等同于已经证明的缺陷。Martin Fowler
明确指出异味有时并不对应真实问题，因此本项目要求每条发现同时保留可定位证据、
影响、置信度和修复方向，而不是只返回一个标签。

C++分类表综合以下资料，并针对“细粒度习语候选”缩小到输入范围能够审查的类别：

- [E108：Martin Fowler “Code Smell”](../../../thesis/references/英文文献库.md#e108)
  （[作者官网](https://martinfowler.com/bliki/CodeSmell.html)，官方网页）：
  异味的风险信号边界和经典可维护性异味；
- [E028：CLEAN++](../../../thesis/references/英文文献库.md#e028)
  （[DOI](https://doi.org/10.1109/MSR59073.2023.00066)，正式会议论文）：
  基于 Clang AST 和阈值规则的35类 C++异味实现及工具评价；
- [E109：LLVM Clang-Tidy Checks](../../../thesis/references/英文文献库.md#e109)
  （[LLVM 官方文档](https://clang.llvm.org/extra/clang-tidy/checks/list.html)，
  动态维护的官方网页）：
  `bugprone`、`cert`、`concurrency`、`cppcoreguidelines` 和 `readability`
  等 C++检查族；
- [E110：SEI CERT C++ Coding Standard](../../../thesis/references/英文文献库.md#e110)
  （[SEI/CMU 官方页面](https://cmu-sei.github.io/secure-coding-standards/sei-cert-cpp-coding-standard/)，
  持续维护的在线技术标准）：
  内存、错误处理、对象、并发与安全风险；
- [E027：iSMELL](../../../thesis/references/英文文献库.md#e027)
  （[DOI](https://doi.org/10.1145/3691620.3695508)，正式会议论文）：
  LLM与专家工具组合及按异味类别评价的实验依据。

当前实现不把 CLEAN++ 或 clang-tidy 设为前置条件。它们通常需要编译数据库或更完整
的构建语义，不能破坏零构建解析主链路；正式实验中可以作为分层对照或可选增强。
Clang-Tidy 与 SEI CERT C++ 均会持续更新，正式实验记录启用检查、规则标识和访问日期。

## 二、固定分类表

规范分类由 `src.idiom_judgment.smell_taxonomy` 单点维护，prompt、阶段产物和审计器
直接复用当前分类。不得在阶段4复制另一套名称或阈值。

| 类别 | 家族 | 典型问题 | 可审查范围 |
|---|---|---|---|
| `resource_lifetime` | correctness | 获取/释放、加锁/解锁、打开/关闭失配，异常或提前返回泄漏，脆弱裸生命周期 | 片段/函数 |
| `memory_lifetime` | correctness | 越界、悬空、释放后/移动后使用、未初始化读取、双重释放 | 片段/函数 |
| `null_optional_access` | correctness | 未经支配性检查解引用空指针、optional、迭代器或句柄 | 片段/函数 |
| `error_handling` | correctness | 忽略错误返回、空catch、吞异常、失败后继续运行 | 片段/函数 |
| `exception_safety` | correctness | 抛出后部分状态、资源泄漏、不变量破坏或危险清理 | 片段/函数 |
| `concurrency` | correctness | 数据竞争、锁失配/顺序、持锁挂起、条件变量误用 | 片段/函数 |
| `undefined_behavior` | correctness | 非法移位、溢出、别名/对齐、失效迭代器和生命周期违例 | 片段/函数 |
| `unsafe_api` | correctness | 无边界接口、长度/所有权误用、危险裸内存操作 | 片段/函数 |
| `control_flow_complexity` | maintainability | 深层嵌套、过多分支、不可达路径、脆弱goto、必要default缺失 | 区域/函数 |
| `oversized_responsibility` | maintainability | Long Function、Large/God Class、多职责单元 | 完整函数/类 |
| `global_mutable_state` | coupling | 全局/静态可变状态、隐藏副作用、顺序和并发耦合 | 片段/函数/类 |
| `magic_literal` | maintainability | 缺少语义名称的协议值、位掩码、数字或字符串 | 片段/函数 |
| `type_conversion` | correctness | 窄化、无依据强制转换、符号性混用和关键原始类型滥用 | 片段/函数 |
| `macro_side_effect` | correctness | 宏参数重复求值、多语句宏、优先级或隐藏控制流风险 | 片段/函数 |
| `dead_redundant_code` | maintainability | 不可达代码、永真/永假分支、无效赋值和重复检查 | 片段/函数 |
| `interface_coupling` | coupling | Long Parameter List、Data Clumps、Feature Envy、Message Chain | 完整函数/类 |
| `duplicated_logic` | maintainability | 单个候选内部重复实现同一职责 | 区域/函数 |

簇成员之间重复是阶段2发现习语的输入信号，不属于 `duplicated_logic`。只提供局部
片段时，不得报告需要完整函数或类才能确认的异味。命名、格式、非主流写法及缺少
未展示上下文不能单独形成 finding。

## 三、Agent输入输出

阶段3和阶段4使用同一个 `SmellReviewAgent`、`SmellReviewRequest`、
`SmellReviewResult` 和 JSON Schema，但分别对当前单簇代表或当前合成结果发起
独立请求。

请求统一包含：

- `project`、`candidate_id` 和 `candidate_code`；
- `related_examples`：阶段3传入簇内代表性变体，阶段4传入已验证函数上下文和
  来源习语；
- `deterministic_evidence`：规则、语法、来源和新增调用等可复查证据。

模型只返回 `findings` 和总体说明。每条 finding 必须包含固定 `category`、
`severity`、`confidence`、`evidence`、`impact` 和 `remediation`。模型不输出
接受/拒绝状态，也不直接决定风险总分。响应经单次 JSON 修复和一次有界逻辑
重试后仍失败，记录为 `analysis_status=failed`，由独立门禁安全拒绝，但不
伪装成某一种代码异味。
未知类别、越界置信度或缺少证据/影响/修复方向的 finding 也按分析失败处理，
不能因丢弃畸形 finding 而把候选误判为“无异味”。

## 四、确定性风险分与独立过滤

严重度基础风险固定为：

| `severity` | 基础风险 |
|---|---:|
| `low` | 20 |
| `medium` | 45 |
| `high` | 75 |
| `critical` | 100 |

单条 finding 的有效风险为：

\[
e_i=base(severity_i)\times confidence_i/100
\]

整体异味风险为最高有效风险加多异味累积项：

\[
SmellRisk=\min(100,\max_i e_i+\min(15,5N_{extra}))
\]

其中 \(N_{extra}\) 是除最高项外有效风险不低于30的 finding 数。当前冻结过滤阈值
为 `SmellRisk >= 60`。这意味着高严重度且置信度至少80、critical且置信度至少60，
或多个高置信中等异味可以触发过滤。风险计算、阈值和触发原因保存在独立
`smell_gate`，不得写入业务 `scorecard`。

阶段3业务总分只包含规则20%、语义45%和复用35%；阶段4直接使用质量复审分。
正式阶段3输入门槛为60，不再对语义分、复用分或动作数量叠加重复硬门禁。阶段2
非执行合同分支保留门槛80的离线测试。任一业务门禁失败会拒绝候选；
业务门禁通过后，异味门禁仍可独立覆盖为 `rejected`。反过来，异味未过阈值也
不能挽救业务质量失败。

## 五、事后审计

每条执行过异味审查的记录保存 `smell_review_input`、结构化 `smell` 和独立
`smell_gate`。审计器从阶段3/4 artifact 生成确定性分层样本，先平衡三类触发
结果，再在过滤与未过滤桶内优先覆盖更多预测类别：

- `risk_threshold`：因异味阈值被过滤；
- `none`：异味审查完成但未触发过滤，用于发现漏报；
- `analysis_failure`：技术失败，单独统计且不混入检测准确性。

人工标签至少包含：

- `blocking_smell`：该候选是否确实含应阻止复用的异味；
- `categories`：所有人工确认类别，必须来自固定分类表；
- `notes`：证据、项目约定或分歧说明。

审计 payload 中的 `review_items` 只含候选、上下文与确定性证据，不含预测分数、
过滤结论或最终状态；标注者应只使用该视图和固定分类表。保留预测信息的 `samples`
仅供评价程序按 `audit_id` 匹配。推荐两名具备 C++经验的标注者独立标注，分歧由
第三人裁决。报告总体、阶段3、阶段4三个层级的过滤 Precision、Recall、F1、Accuracy、
误过滤率与漏报率，并对每个异味类别报告 TP、FP、FN、支持数和 P/R/F1。
`analysis_failure` 只报告数量，不当作异味真阳性或假阳性。
其中误过滤率为 `FP/(TP+FP)`，表示被系统过滤的样本中实际不应过滤的比例；漏报率
为 `FN/(TP+FN)`，表示人工确认应阻断的异味中未被门禁捕获的比例。

样本准备和评价入口见
[习语判断模块 README](../../src/idiom_judgment/README.md)。阈值只能根据独立
pilot审计冻结；不得使用最终 IC、ISP、F1 或完整实验人工标签反复调整。
