# C++ 阶段2簇归并验证报告

## 结论

2026-07-29 使用正式23仓已冻结的 `clustering-final/clusters.pkl` 与
`embeddings.pkl`，在不重新运行 Parser、Embedding、DBSCAN 或真实 LLM 的前提下，
完成阶段2到阶段3之间的仓库内保守簇归并。原冻结产物未被覆盖；派生结果分别写入
各仓 `stage2/clustering-merged/`。

23仓合计簇数从29,404降为29,401，归并3组、减少3簇；簇内成员总数始终为
133,220。归并幅度很小是有意结果：模糊归并只允许已声明局部变量的一致换名，
调用名、类型、运算符、字面量、控制条件、返回值及其他非局部标识必须逐 token
一致。

## 归并合同

- C++ 词法等价忽略排版空白和注释，但保留字符串、字符、调用名、类型、运算符、
  控制条件、返回值与其他实际 token；
- 中心代码词法等价时直接归并；
- 模糊归并要求 Tree-sitter AST 节点序列和 token 数完全相同、token 相似度至少
  0.92，并且所有差异只能形成已声明局部变量之间的一一对应换名；
- 每次只读取一个仓库，禁止跨仓归并；
- 归并后用全部成员原始 embedding 的算术均值重新计算质心，再按余弦距离选择最近
  的真实成员作为代表；
- 七列簇表 Schema 不变，完整 `infos`、成员代码和成员总数不丢失；来源 label 与
  归并理由保存在顶层 `clustering_metadata.postprocessing.clusters`。

## 23仓结果

实际发生归并的项目如下：

| 项目 | 归并前簇数 | 归并后簇数 | 归并组数 | 理由 |
|---|---:|---:|---:|---|
| `drogon` | 1,134 | 1,133 | 1 | AST同构、高词法相似且仅局部变量换名 |
| `envoy` | 13,978 | 13,976 | 2 | 中心代码词法等价 |

其余21仓簇数不变。`cpp-httplib`、`entt` 和 `simdjson` 未生成派生归并目录，
不会进入阶段3。

语义复核确认：

- `drogon` 合并的是同一 `std::regex_replace(...)` 声明，差异仅为新声明局部变量
  `ctlName`/`fileName`；
- `envoy` 两组分别是带说明注释和紧凑写法的同一 `return false` 覆盖函数，以及
  带 `TODO` 注释和空函数体写法的同一覆盖函数；
- `setTag` 的标签参数差异、事件常量差异、回调目标差异、成员字段差异和函数名
  差异均保持分离。

## 归并前后指标

以下“纯重复”和“强结构代理”均按新的 C++ 词法等价口径重算，因此与早期按空白
正则归一化的筛选报告不是同一口径。强结构代理要求代表 AST 子树至少10个节点、
代表有效词法文本至少20字符、至少两个词法变体并且至少跨两个文件。

| 指标 | 归并前 | 归并后 | 变化 |
|---|---:|---:|---:|
| 有效簇数 | 29,404 | 29,401 | -3（-0.0102%） |
| 簇内成员数 | 133,220 | 133,220 | 0 |
| 词法纯重复簇数 | 4,177 | 4,173 | -4 |
| 词法纯重复率 | 14.2056% | 14.1934% | -0.0122 个百分点 |
| 强结构代理簇数 | 7,687 | 7,689 | +2 |
| 强结构代理率 | 26.1427% | 26.1522% | +0.0095 个百分点 |

归并不会直接消除簇内的所有真实重复实例：完整成员仍用于支持度、评价和实例归类。
因此指标改善有限且不应解释为重新优化 DBSCAN；本步骤只去除阶段3会重复判断的
确定性同义簇。

## 复现命令

每个正式仓库分别执行：

```bash
.venv/bin/python -m src.mining.cluster_merge \
  --clusters outputs/experiments/repo-isolated-v1/repos/<project>/stage2/clustering-final/clusters.pkl \
  --embeddings outputs/experiments/repo-isolated-v1/repos/<project>/stage2/embeddings.pkl \
  --output outputs/experiments/repo-isolated-v1/repos/<project>/stage2/clustering-merged/clusters.pkl \
  --report outputs/experiments/repo-isolated-v1/repos/<project>/stage2/clustering-merged/report.json
```

每份报告记录两个输入文件的 SHA-256、参数、归并前后指标和逐簇来源信息。派生
目录仍被 Git 忽略，可由冻结输入确定性重建。
