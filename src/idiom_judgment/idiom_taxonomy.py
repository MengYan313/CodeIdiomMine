"""C++ 常见习语目录与开放式“仓库特有习语”分类合同。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, List, Mapping, Sequence


IDIOM_TAXONOMY_VERSION = "cpp-common-idioms-v1"
CATALOGED_IDIOM_KIND = "cataloged"
REPOSITORY_SPECIFIC_IDIOM_KIND = "repository_specific"
NOT_APPLICABLE_IDIOM_KIND = "not_applicable"
REPOSITORY_SPECIFIC_IDIOM_LABEL = "仓库特有习语"
NOT_APPLICABLE_IDIOM_LABEL = "非习语"


@dataclass(frozen=True)
class KnownIdiomType:
    """一个可由 LLM 选择、由确定性代码校验的已知 C++ 习语类型。"""

    type_id: str
    name_zh: str
    name_en: str
    recognition_hint: str
    source_refs: Sequence[str]


KNOWN_IDIOM_TYPES: tuple[KnownIdiomType, ...] = (
    KnownIdiomType(
        "raii",
        "资源获取即初始化",
        "RAII",
        "资源的获取与释放绑定到对象构造、析构或词法作用域。",
        ("E025", "E112", "E113"),
    ),
    KnownIdiomType(
        "scope-guard",
        "作用域守卫",
        "Scope Guard",
        "离开作用域时可靠执行清理、回滚、成功或失败动作。",
        ("E025", "E115"),
    ),
    KnownIdiomType(
        "smart-pointer-ownership",
        "智能指针所有权",
        "Smart Pointer Ownership",
        "使用 unique_ptr、shared_ptr 或等价句柄表达和转移对象所有权。",
        ("E025", "E112"),
    ),
    KnownIdiomType(
        "rule-of-zero",
        "零法则",
        "Rule of Zero",
        "由成员自动管理资源，业务类不自定义析构、复制或移动操作。",
        ("E025", "E112", "E114"),
    ),
    KnownIdiomType(
        "rule-of-three-five",
        "三法则/五法则",
        "Rule of Three/Five",
        "拥有资源的类型成套定义析构、复制及必要的移动特殊成员。",
        ("E025", "E112", "E114"),
    ),
    KnownIdiomType(
        "copy-and-swap",
        "复制并交换",
        "Copy-and-Swap",
        "赋值时先复制临时对象，再通过 swap 提交状态以获得异常安全。",
        ("E025", "E114"),
    ),
    KnownIdiomType(
        "construct-on-first-use",
        "首次使用时构造",
        "Construct on First Use",
        "把静态对象构造延迟到首次调用，以规避静态初始化顺序问题。",
        ("E025", "E111"),
    ),
    KnownIdiomType(
        "pimpl",
        "编译防火墙",
        "Pimpl",
        "公共类只持有指向隐藏实现的句柄，以隔离实现和编译依赖。",
        ("E025", "E111"),
    ),
    KnownIdiomType(
        "crtp",
        "奇异递归模板模式",
        "CRTP",
        "派生类把自身类型作为基类模板参数，实现静态多态或 mixin。",
        ("E003", "E025"),
    ),
    KnownIdiomType(
        "non-virtual-interface",
        "非虚接口",
        "Non-Virtual Interface",
        "公有非虚函数固定契约，并调用受保护虚函数完成可定制步骤。",
        ("E025",),
    ),
    KnownIdiomType(
        "non-copyable",
        "不可复制类型",
        "Non-Copyable",
        "显式删除或隐藏复制操作，以表达唯一资源或对象身份。",
        ("E025",),
    ),
    KnownIdiomType(
        "named-constructor",
        "命名构造函数",
        "Named Constructor",
        "用命名静态工厂表达不同构造意图或校验路径。",
        ("E025",),
    ),
    KnownIdiomType(
        "erase-remove",
        "擦除-移除",
        "Erase-Remove",
        "先用 remove/remove_if 重排范围，再调用容器 erase 真正删除。",
        ("E025",),
    ),
    KnownIdiomType(
        "iterator-pair",
        "迭代器对",
        "Iterator Pair",
        "用半开区间的 begin/end 迭代器对表达泛型范围。",
        ("E003", "E025"),
    ),
    KnownIdiomType(
        "function-object",
        "函数对象",
        "Function Object",
        "以定义 operator() 的对象封装可调用行为及其状态。",
        ("E025",),
    ),
    KnownIdiomType(
        "traits",
        "特征类",
        "Traits",
        "用模板类型或特化集中暴露类型属性和相关操作。",
        ("E003", "E025"),
    ),
    KnownIdiomType(
        "tag-dispatch",
        "标签分派",
        "Tag Dispatch",
        "以空标签类型和重载在编译期选择实现路径。",
        ("E003", "E025"),
    ),
    KnownIdiomType(
        "sfinae",
        "替换失败非错误",
        "SFINAE/enable_if",
        "利用模板替换失败、enable_if 或等价约束选择合法重载。",
        ("E003", "E025"),
    ),
    KnownIdiomType(
        "policy-based-design",
        "策略式设计",
        "Policy-Based Design",
        "通过策略模板参数组合可替换行为，而不是运行时条件分派。",
        ("E003", "E025"),
    ),
    KnownIdiomType(
        "type-erasure",
        "类型擦除",
        "Type Erasure",
        "隐藏具体类型，同时通过统一值语义或接口保留所需操作。",
        ("E025",),
    ),
    KnownIdiomType(
        "expression-template",
        "表达式模板",
        "Expression Template",
        "用惰性模板表达式树融合运算并避免不必要临时对象。",
        ("E025",),
    ),
    KnownIdiomType(
        "empty-base-optimization",
        "空基类优化",
        "Empty Base Optimization",
        "把无状态策略存为基类以避免其作为成员占用额外空间。",
        ("E025",),
    ),
    KnownIdiomType(
        "copy-on-write",
        "写时复制",
        "Copy-on-Write",
        "多个值共享表示，只在写入前分离副本。",
        ("E025",),
    ),
    KnownIdiomType(
        "intrusive-reference-counting",
        "侵入式引用计数",
        "Intrusive Reference Counting",
        "引用计数存放在被管理对象内部，由句柄增减计数。",
        ("E025",),
    ),
    KnownIdiomType(
        "type-safe-enum",
        "类型安全枚举",
        "Type-Safe Enum",
        "用 enum class 或封装类型限制枚举值的隐式转换和作用域。",
        ("E025",),
    ),
    KnownIdiomType(
        "thread-safe-interface",
        "线程安全接口",
        "Thread-Safe Interface",
        "公共入口统一持锁或建立同步不变量，再调用内部未加锁实现。",
        ("E025",),
    ),
)

KNOWN_IDIOM_TYPE_BY_ID = {
    idiom_type.type_id: idiom_type for idiom_type in KNOWN_IDIOM_TYPES
}
KNOWN_IDIOM_TYPE_IDS = tuple(KNOWN_IDIOM_TYPE_BY_ID)


IDIOM_CLASSIFICATION_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "enum": [
                CATALOGED_IDIOM_KIND,
                REPOSITORY_SPECIFIC_IDIOM_KIND,
                NOT_APPLICABLE_IDIOM_KIND,
            ],
        },
        "catalog_ids": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": list(KNOWN_IDIOM_TYPE_IDS),
            },
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 100,
        },
        "reason": {"type": "string"},
    },
    "required": ["kind", "catalog_ids", "confidence", "reason"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class IdiomClassification:
    """写入最终产物的标准化分类结果。"""

    taxonomy_version: str
    kind: str
    label: str
    catalog_ids: List[str]
    catalog_names: List[str]
    confidence: float
    reason: str


def render_idiom_catalog_for_prompt() -> str:
    """渲染紧凑目录，供阶段3和阶段4最终有效性 Agent 使用。"""

    return "\n".join(
        (
            f"- {item.type_id}: {item.name_zh}（{item.name_en}）——"
            f"{item.recognition_hint}"
        )
        for item in KNOWN_IDIOM_TYPES
    )


def empty_idiom_classification(reason: str = "") -> IdiomClassification:
    return IdiomClassification(
        taxonomy_version=IDIOM_TAXONOMY_VERSION,
        kind=NOT_APPLICABLE_IDIOM_KIND,
        label=NOT_APPLICABLE_IDIOM_LABEL,
        catalog_ids=[],
        catalog_names=[],
        confidence=0.0,
        reason=reason,
    )


def normalize_idiom_classification(
    value: object,
    *,
    is_idiom: bool,
) -> tuple[IdiomClassification, bool]:
    """
    标准化 LLM 分类并报告领域载荷是否无效。

    已知类型最多保留三个目录编号；不能与目录可靠对应时必须显式归为
    ``repository_specific``，不得用近似名称强行匹配。
    """

    if not isinstance(value, Mapping):
        return empty_idiom_classification("分类字段不是对象。"), True

    kind = str(value.get("kind") or "").strip()
    reason = str(value.get("reason") or "").strip()
    raw_ids = value.get("catalog_ids")
    if not isinstance(raw_ids, list):
        return empty_idiom_classification(reason), True
    catalog_ids: List[str] = []
    invalid = False
    for raw_id in raw_ids:
        type_id = str(raw_id or "").strip()
        if type_id not in KNOWN_IDIOM_TYPE_BY_ID:
            invalid = True
            continue
        if type_id not in catalog_ids:
            catalog_ids.append(type_id)
    if len(catalog_ids) > 3:
        invalid = True
        catalog_ids = catalog_ids[:3]
    try:
        if isinstance(value.get("confidence"), bool):
            raise ValueError
        confidence = float(value.get("confidence"))
    except (TypeError, ValueError):
        confidence = -1.0
    if not math.isfinite(confidence) or confidence < 0 or confidence > 100:
        invalid = True
        confidence = (
            max(0.0, min(100.0, confidence))
            if math.isfinite(confidence)
            else 0.0
        )
    if not reason:
        invalid = True

    if not is_idiom:
        if kind != NOT_APPLICABLE_IDIOM_KIND or catalog_ids:
            invalid = True
        return (
            IdiomClassification(
                taxonomy_version=IDIOM_TAXONOMY_VERSION,
                kind=NOT_APPLICABLE_IDIOM_KIND,
                label=NOT_APPLICABLE_IDIOM_LABEL,
                catalog_ids=[],
                catalog_names=[],
                confidence=confidence,
                reason=reason,
            ),
            invalid,
        )

    if kind == CATALOGED_IDIOM_KIND and catalog_ids:
        catalog_names = [
            (
                f"{KNOWN_IDIOM_TYPE_BY_ID[type_id].name_zh}"
                f"（{KNOWN_IDIOM_TYPE_BY_ID[type_id].name_en}）"
            )
            for type_id in catalog_ids
        ]
        return (
            IdiomClassification(
                taxonomy_version=IDIOM_TAXONOMY_VERSION,
                kind=CATALOGED_IDIOM_KIND,
                label="、".join(catalog_names),
                catalog_ids=catalog_ids,
                catalog_names=catalog_names,
                confidence=confidence,
                reason=reason,
            ),
            invalid,
        )

    if kind == REPOSITORY_SPECIFIC_IDIOM_KIND and not catalog_ids:
        return (
            IdiomClassification(
                taxonomy_version=IDIOM_TAXONOMY_VERSION,
                kind=REPOSITORY_SPECIFIC_IDIOM_KIND,
                label=REPOSITORY_SPECIFIC_IDIOM_LABEL,
                catalog_ids=[],
                catalog_names=[],
                confidence=confidence,
                reason=reason,
            ),
            invalid,
        )

    return empty_idiom_classification(reason), True
