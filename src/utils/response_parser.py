"""
LLM 响应解析工具

提供统一的解析函数，用于从 LLM 响应中提取结构化数据。
"""

import json
import re
import logging
from typing import Any, Dict, List, Optional

from ..common.logging import get_logger

# 获取模块级别的 logger
logger = get_logger(__name__)


def extract_tag_content(response: str, tag_name: str, default: str = "", logger_instance: logging.Logger = None) -> str:
    """
    从 LLM 响应中提取指定标记的内容
    
    使用标准标记格式：[Tag Name] ... [/Tag Name]
    
    Args:
        response: LLM 响应文本
        tag_name: 标记名称（例如 "Code Idiom", "Reason", "Description"）
        default: 如果标记不存在或解析失败时返回的默认值。如果为空字符串，则返回原始响应
        logger_instance: 日志记录器实例。如果为 None，使用模块级别的 logger
    
    Returns:
        提取的标记内容（已去除标记），如果标记不存在或解析失败则返回 default 或原始响应
    """
    if logger_instance is None:
        logger_instance = logger
    
    cleaned_response = response.strip()
    
    # 使用标准标记格式进行解析：[Tag Name] ... [/Tag Name]
    pattern = rf'\[{re.escape(tag_name)}\]\s*\n?(.*?)\n?\[/{re.escape(tag_name)}\]'
    match = re.search(pattern, cleaned_response, re.DOTALL | re.IGNORECASE)
    
    if match:
        return match.group(1).strip()
    
    # 解析失败，根据 default 记录错误并返回默认值或原始响应
    if default:
        logger_instance.warning(f"无法从 LLM 响应中提取 [{tag_name}] 标记，使用默认值。完整响应:\n{response[:300]}")
        return default
    else:
        logger_instance.warning(f"无法从 LLM 响应中提取 [{tag_name}] 标记，返回原始响应。完整响应:\n{response[:300]}")
        return cleaned_response


def extract_json(text: str) -> Dict[str, Any]:
    """
    从文本中提取 JSON
    
    Args:
        text: 包含 JSON 的文本
        
    Returns:
        解析后的字典
        
    Raises:
        ValueError: 如果无法提取 JSON
    """
    # 尝试直接解析
    try:
        return json.loads(text)
    except Exception:
        pass
    
    # 尝试提取 ```json 代码块中的 JSON
    json_match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except Exception:
            pass
    
    # 尝试提取任意代码块中的 JSON
    json_match = re.search(r'```\s*(\{.*?\})\s*```', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except Exception:
            pass
    
    # 尝试提取大括号内的内容（不在代码块中）
    json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except Exception:
            pass
    
    raise ValueError(f"Cannot extract JSON from text: {text[:200]}...")


def parse_json_response(
    text: str,
    required_fields: Optional[List[str]] = None,
    default_values: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    解析 JSON 响应，并验证必需字段
    
    Args:
        text: 包含 JSON 的文本
        required_fields: 必需的字段列表
        default_values: 缺失字段的默认值
        
    Returns:
        解析并验证后的字典
        
    Raises:
        ValueError: 如果缺少必需字段且没有默认值
    """
    result = extract_json(text)
    
    if required_fields:
        for field in required_fields:
            if field not in result:
                if default_values and field in default_values:
                    result[field] = default_values[field]
                else:
                    raise ValueError(f"Missing required field: {field}")
    
    return result


# 模块运行命令（从项目根目录运行）：
# python -m src.utils.response_parser

if __name__ == "__main__":
    # 测试解析函数
    print("=" * 60)
    print("测试响应解析工具")
    print("=" * 60)
    
    # 测试 1: 提取标记内容
    print("\n测试 1: 提取 [Code Idiom] 标记")
    text1 = """
    Here is the code idiom:
    [Code Idiom]
    def calculate_average(numbers):
        return sum(numbers) / len(numbers)
    [/Code Idiom]
    
    This is a common pattern.
    """
    result1 = extract_tag_content(text1, "Code Idiom")
    print(f"提取的代码:\n{result1}")
    
    # 测试 2: 提取 JSON
    print("\n测试 2: 提取 JSON")
    text2 = """
    Here is the result:
    ```json
    {
        "is_clear": true,
        "score": 85,
        "reason": "Good naming"
    }
    ```
    """
    result2 = extract_json(text2)
    print(f"提取的 JSON: {result2}")
    
    # 测试 3: 提取多个标记
    print("\n测试 3: 提取多个标记")
    text3 = """
    [Reason]
    The code is clear and concise.
    [/Reason]
    
    [Confidence]
    High confidence: 95%
    [/Confidence]
    """
    reason = extract_tag_content(text3, "Reason")
    confidence = extract_tag_content(text3, "Confidence")
    print(f"Reason: {reason}")
    print(f"Confidence: {confidence}")
    
    # 测试 4: 标记不存在的情况
    print("\n测试 4: 标记不存在")
    text4 = "This is just plain text without any tags."
    result4 = extract_tag_content(text4, "NonExistent", default="默认值")
    print(f"结果: {result4}")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
