"""阶段3/4共享的 C++ 代码异味分类、风险计算与独立门禁。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, Mapping, Sequence


SMELL_REJECTION_THRESHOLD = 60.0

SEVERITY_BASE_RISK = {
    "low": 20.0,
    "medium": 45.0,
    "high": 75.0,
    "critical": 100.0,
}


@dataclass(frozen=True)
class SmellCategory:
    """一个稳定、可审计的代码异味类别。"""

    category: str
    family: str
    name: str
    applicable_scope: str
    description: str
    evidence_rule: str


@dataclass(frozen=True)
class SmellFinding:
    """异味 Agent 的单条可定位发现。"""

    category: str
    severity: str
    confidence: float
    evidence: str
    impact: str
    remediation: str


SMELL_CATEGORIES: tuple[SmellCategory, ...] = (
    SmellCategory(
        category="resource_lifetime",
        family="correctness",
        name="资源生命周期失配",
        applicable_scope="片段/函数",
        description=(
            "获取与释放、加锁与解锁、打开与关闭不配对，或手工资源管理在提前返回、"
            "异常路径中泄漏、重复释放；能够使用 RAII 却传播脆弱的裸生命周期。"
        ),
        evidence_rule="必须定位资源实体及缺失、重复或顺序错误的生命周期操作。",
    ),
    SmellCategory(
        category="memory_lifetime",
        family="correctness",
        name="内存与对象生命周期风险",
        applicable_scope="片段/函数",
        description=(
            "越界访问、悬空引用、释放后使用、移动后使用、未初始化读取、双重释放，"
            "或对象生命周期结束后仍访问其存储。"
        ),
        evidence_rule="必须指出具体对象以及可见的失效、越界或未初始化路径。",
    ),
    SmellCategory(
        category="null_optional_access",
        family="correctness",
        name="空值或可选值未检查访问",
        applicable_scope="片段/函数",
        description=(
            "在没有支配性非空、has_value 或等价保证时解引用指针、迭代器、optional"
            " 或可能为空的句柄。"
        ),
        evidence_rule="必须定位访问点，并说明输入中为什么不存在有效保护条件。",
    ),
    SmellCategory(
        category="error_handling",
        family="correctness",
        name="错误处理缺失或吞没",
        applicable_scope="片段/函数",
        description=(
            "忽略失败返回值、空 catch、吞掉异常、错误后继续使用无效结果，或失败路径"
            "没有恢复、传播和清理。"
        ),
        evidence_rule="必须定位被忽略的错误信号或可见的空/不完整失败路径。",
    ),
    SmellCategory(
        category="exception_safety",
        family="correctness",
        name="异常安全破坏",
        applicable_scope="片段/函数",
        description=(
            "抛出时留下部分更新状态、资源泄漏或不变量破坏；析构/清理路径可能抛出，"
            "或 catch/rethrow 改变异常语义。"
        ),
        evidence_rule="必须指出可能抛出的操作及其前后可见状态或清理缺口。",
    ),
    SmellCategory(
        category="concurrency",
        family="correctness",
        name="并发与同步风险",
        applicable_scope="片段/函数",
        description=(
            "数据竞争、锁不配对、锁顺序冲突、持锁阻塞/挂起、条件变量误用，或共享"
            "可变状态缺少可见同步。"
        ),
        evidence_rule="必须定位共享状态、同步原语和可见的竞态或活性风险。",
    ),
    SmellCategory(
        category="undefined_behavior",
        family="correctness",
        name="未定义或实现相关行为",
        applicable_scope="片段/函数",
        description=(
            "有符号溢出、非法移位、严格别名/对齐违例、失效迭代器、求值顺序依赖，"
            "或其他由可见代码触发的 C++ 未定义行为。"
        ),
        evidence_rule="必须指出具体表达式和触发条件，不得只因使用底层语法而报告。",
    ),
    SmellCategory(
        category="unsafe_api",
        family="correctness",
        name="危险 API 或接口误用",
        applicable_scope="片段/函数",
        description=(
            "使用已知无边界接口、错误的长度/所有权约定、裸内存操作作用于非平凡"
            "对象，或以不受支持的参数组合调用 API。"
        ),
        evidence_rule="必须定位 API、参数和输入中可见的危险契约证据。",
    ),
    SmellCategory(
        category="control_flow_complexity",
        family="maintainability",
        name="复杂或脆弱控制流",
        applicable_scope="区域/函数",
        description=(
            "深层嵌套、过多分支、不可达路径、脆弱 goto、遗漏必要 default，或条件"
            "组合使行为和清理职责难以验证。"
        ),
        evidence_rule="只有可见范围足以证明复杂性或遗漏时才报告。",
    ),
    SmellCategory(
        category="oversized_responsibility",
        family="maintainability",
        name="过长单元或职责膨胀",
        applicable_scope="完整函数/类",
        description=(
            "Long Function、Large/God Class 或一个单元承担多个不相干职责。"
        ),
        evidence_rule="仅在输入提供完整函数或类时报告，片段截断不能作为证据。",
    ),
    SmellCategory(
        category="global_mutable_state",
        family="coupling",
        name="全局可变状态与隐藏副作用",
        applicable_scope="片段/函数/类",
        description=(
            "读写全局、静态或隐式共享状态，造成顺序依赖、不可重入、难测试或并发"
            "耦合。"
        ),
        evidence_rule="必须定位状态对象和可见读写；只读常量不属于该类。",
    ),
    SmellCategory(
        category="magic_literal",
        family="maintainability",
        name="魔法值与协议常量散落",
        applicable_scope="片段/函数",
        description=(
            "缺少语义名称的数字、字符串、位掩码或协议值直接控制重要行为。"
        ),
        evidence_rule=(
            "0/1/-1、nullptr、布尔量、格式字符串及项目约定明显可见时不得机械报告。"
        ),
    ),
    SmellCategory(
        category="type_conversion",
        family="correctness",
        name="危险类型转换与类型滥用",
        applicable_scope="片段/函数",
        description=(
            "可能丢失信息的窄化、无依据的 reinterpret/C 风格转换、符号性混用，"
            "或用原始类型承载需要受约束领域类型的关键值。"
        ),
        evidence_rule="必须定位转换和值域风险；显式且有可见检查的转换不报告。",
    ),
    SmellCategory(
        category="macro_side_effect",
        family="correctness",
        name="宏展开与重复求值风险",
        applicable_scope="片段/函数",
        description=(
            "多语句宏缺少安全包裹、参数重复求值、优先级未加括号，或宏隐藏控制流"
            "和资源操作。"
        ),
        evidence_rule="必须看到宏定义或足以证明展开风险的完整证据。",
    ),
    SmellCategory(
        category="dead_redundant_code",
        family="maintainability",
        name="死代码与冗余逻辑",
        applicable_scope="片段/函数",
        description=(
            "不可达语句、永真/永假分支、无效赋值、重复检查或候选内部没有作用的"
            "操作。"
        ),
        evidence_rule="必须由可见控制流、数据流或重复操作直接支持。",
    ),
    SmellCategory(
        category="interface_coupling",
        family="coupling",
        name="接口与数据耦合",
        applicable_scope="完整函数/类",
        description=(
            "Long Parameter List、Data Clumps、Feature Envy、Message Chain，或对"
            "外部对象内部结构的过度依赖。"
        ),
        evidence_rule="只有完整签名、调用链或类上下文可见时才报告。",
    ),
    SmellCategory(
        category="duplicated_logic",
        family="maintainability",
        name="候选内部重复逻辑",
        applicable_scope="区域/函数",
        description=(
            "单个候选内部重复实现同一职责，导致修复需同步修改多处。聚类成员之间"
            "重复是习语发现信号，本身不属于该异味。"
        ),
        evidence_rule="必须定位同一候选内部的重复块，不得把簇支持度当作异味。",
    ),
)

SMELL_CATEGORY_BY_ID = {
    category.category: category for category in SMELL_CATEGORIES
}
SMELL_CATEGORY_IDS = tuple(SMELL_CATEGORY_BY_ID)

SMELL_TAXONOMY_SOURCES = (
    {
        "name": "[E108] Martin Fowler: Code Smell",
        "url": "https://martinfowler.com/bliki/CodeSmell.html",
        "role": "官方网页；异味是风险信号而不是缺陷真值。",
    },
    {
        "name": "[E028] CLEAN++: Code Smells Extraction for C++",
        "url": "https://doi.org/10.1109/MSR59073.2023.00066",
        "role": "正式会议论文；C++ AST 规则异味、分类与阈值检测对照。",
    },
    {
        "name": "[E109] LLVM Clang-Tidy Checks",
        "url": "https://clang.llvm.org/extra/clang-tidy/checks/list.html",
        "role": "动态维护的官方网页；C++ bugprone、CERT、concurrency、readability 等检查族。",
    },
    {
        "name": "[E110] SEI CERT C++ Coding Standard",
        "url": (
            "https://cmu-sei.github.io/secure-coding-standards/"
            "sei-cert-cpp-coding-standard/"
        ),
        "role": "持续维护的在线技术标准；内存、错误处理、对象、并发与安全风险边界。",
    },
    {
        "name": (
            "[E027] iSMELL: Assembling LLMs with Expert Toolsets for "
            "Code Smell Detection and Refactoring"
        ),
        "url": "https://doi.org/10.1145/3691620.3695508",
        "role": "正式会议论文；LLM 与专家工具结合及按类别评价的实验依据。",
    },
)


def render_taxonomy_for_prompt() -> str:
    """生成稳定、紧凑的中文提示词分类表。"""

    return "\n".join(
        (
            f"- `{item.category}`（{item.name}；{item.applicable_scope}）："
            f"{item.description} 证据要求：{item.evidence_rule}"
        )
        for item in SMELL_CATEGORIES
    )


def calculate_smell_risk_score(
    findings: Iterable[SmellFinding | Mapping[str, Any]],
) -> float:
    """由严重度和置信度确定性计算独立异味风险分。"""

    effective_scores = []
    for finding in findings:
        data = asdict(finding) if isinstance(finding, SmellFinding) else finding
        severity = str(data.get("severity") or "")
        if severity not in SEVERITY_BASE_RISK:
            continue
        try:
            confidence = float(data.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(100.0, confidence))
        effective_scores.append(
            SEVERITY_BASE_RISK[severity] * confidence / 100.0
        )
    if not effective_scores:
        return 0.0
    effective_scores.sort(reverse=True)
    additional_material_findings = sum(
        score >= 30.0 for score in effective_scores[1:]
    )
    accumulation = min(15.0, 5.0 * additional_material_findings)
    return round(min(100.0, effective_scores[0] + accumulation), 4)


def build_smell_gate(
    *,
    analysis_status: str,
    risk_score: float,
    max_severity: str,
    categories: Sequence[str],
    finding_count: int,
    threshold: float = SMELL_REJECTION_THRESHOLD,
) -> Dict[str, Any]:
    """构造与业务质量分完全分离的异味门禁证据。"""

    analysis_failed = analysis_status != "completed"
    threshold_exceeded = risk_score >= threshold
    rejected = analysis_failed or threshold_exceeded
    if analysis_failed:
        trigger_kind = "analysis_failure"
    elif threshold_exceeded:
        trigger_kind = "risk_threshold"
    else:
        trigger_kind = "none"
    return {
        "threshold": float(threshold),
        "analysis_status": analysis_status,
        "risk_score": round(float(risk_score), 4),
        "max_severity": max_severity,
        "categories": sorted(set(categories)),
        "finding_count": int(finding_count),
        "threshold_exceeded": threshold_exceeded,
        "rejected": rejected,
        "trigger_kind": trigger_kind,
    }
