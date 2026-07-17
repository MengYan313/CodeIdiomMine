"""
消息构建模块

提供用于构建和管理 LLM 交互消息的工具。
"""

from enum import Enum
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass


class MessageRole(str, Enum):
    """消息角色类型"""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    FUNCTION = "function"
    TOOL = "tool"


@dataclass
class Message:
    """
    表示对话中的单条消息

    属性:
        role: 消息角色（system, user, assistant 等）
        content: 消息内容
        name: 可选的消息发送者名称
        function_call: 可选的函数调用信息
        tool_calls: 可选的工具调用信息
    """

    role: MessageRole
    content: str
    name: Optional[str] = None
    function_call: Optional[Dict[str, Any]] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> Dict[str, Any]:
        """将消息转换为字典格式"""
        msg_dict = {
            'role': self.role.value,
            'content': self.content,
        }

        if self.name:
            msg_dict['name'] = self.name

        if self.function_call:
            msg_dict['function_call'] = self.function_call

        if self.tool_calls:
            msg_dict['tool_calls'] = self.tool_calls

        return msg_dict

    @classmethod
    def from_dict(cls, msg_dict: Dict[str, Any]) -> 'Message':
        """从字典创建消息"""
        return cls(
            role=MessageRole(msg_dict['role']),
            content=msg_dict['content'],
            name=msg_dict.get('name'),
            function_call=msg_dict.get('function_call'),
            tool_calls=msg_dict.get('tool_calls'),
        )


class MessageBuilder:
    """
    用于构建对话消息的构建器类

    示例:
        >>> builder = MessageBuilder()
        >>> builder.add_system_message("你是一个有帮助的助手。")
        >>> builder.add_user_message("你好！")
        >>> messages = builder.build()
    """

    def __init__(self):
        self.messages: List[Message] = []

    def add_system_message(self, content: str, name: Optional[str] = None) -> 'MessageBuilder':
        """添加系统消息"""
        self.messages.append(Message(
            role=MessageRole.SYSTEM,
            content=content,
            name=name
        ))
        return self

    def add_user_message(self, content: str, name: Optional[str] = None) -> 'MessageBuilder':
        """添加用户消息"""
        self.messages.append(Message(
            role=MessageRole.USER,
            content=content,
            name=name
        ))
        return self

    def add_assistant_message(self, content: str, name: Optional[str] = None) -> 'MessageBuilder':
        """添加助手消息"""
        self.messages.append(Message(
            role=MessageRole.ASSISTANT,
            content=content,
            name=name
        ))
        return self

    def add_function_message(
        self,
        content: str,
        name: str,
        function_call: Optional[Dict[str, Any]] = None
    ) -> 'MessageBuilder':
        """添加函数消息"""
        self.messages.append(Message(
            role=MessageRole.FUNCTION,
            content=content,
            name=name,
            function_call=function_call
        ))
        return self

    def add_message(self, message: Message) -> 'MessageBuilder':
        """添加预构建的消息"""
        self.messages.append(message)
        return self

    def add_messages(self, messages: List[Message]) -> 'MessageBuilder':
        """添加多条消息"""
        self.messages.extend(messages)
        return self

    def clear(self) -> 'MessageBuilder':
        """清空所有消息"""
        self.messages.clear()
        return self

    def build(self) -> List[Dict[str, Any]]:
        """构建并返回字典格式的消息列表"""
        return [msg.to_dict() for msg in self.messages]

    def build_messages(self) -> List[Message]:
        """构建并返回 Message 对象列表"""
        return self.messages.copy()

    def get_last_message(self) -> Optional[Message]:
        """获取最后一条消息"""
        return self.messages[-1] if self.messages else None

    def get_messages_by_role(self, role: MessageRole) -> List[Message]:
        """获取指定角色的所有消息"""
        return [msg for msg in self.messages if msg.role == role]

    def count(self) -> int:
        """获取消息数量"""
        return len(self.messages)

    def __len__(self) -> int:
        """获取消息数量"""
        return len(self.messages)

    def __repr__(self) -> str:
        """字符串表示"""
        return f"MessageBuilder(messages={len(self.messages)})"


class ConversationHistory:
    """
    管理具有 token 限制意识的对话历史

    示例:
        >>> history = ConversationHistory(max_messages=10)
        >>> history.add_user_message("你好")
        >>> history.add_assistant_message("你好！很高兴见到你！")
        >>> messages = history.get_messages()
    """

    def __init__(self, max_messages: Optional[int] = None, system_message: Optional[str] = None):
        """
        初始化对话历史

        Args:
            max_messages: 保留的最大消息数量（None 表示无限制）
            system_message: 可选的系统消息，始终包含在内
        """
        self.max_messages = max_messages
        self.system_message = system_message
        self.messages: List[Message] = []

        if system_message:
            self.messages.append(Message(
                role=MessageRole.SYSTEM,
                content=system_message
            ))

    def add_message(self, role: MessageRole, content: str, name: Optional[str] = None):
        """向历史记录添加消息"""
        message = Message(role=role, content=content, name=name)
        self.messages.append(message)
        self._trim_history()

    def add_user_message(self, content: str, name: Optional[str] = None):
        """添加用户消息"""
        self.add_message(MessageRole.USER, content, name)

    def add_assistant_message(self, content: str, name: Optional[str] = None):
        """添加助手消息"""
        self.add_message(MessageRole.ASSISTANT, content, name)

    def _trim_history(self):
        """修剪历史记录至 max_messages，保留系统消息"""
        if self.max_messages is None:
            return

        # 单独保留系统消息
        system_msgs = [msg for msg in self.messages if msg.role == MessageRole.SYSTEM]
        other_msgs = [msg for msg in self.messages if msg.role != MessageRole.SYSTEM]

        # 修剪其他消息
        if len(other_msgs) > self.max_messages:
            other_msgs = other_msgs[-self.max_messages:]

        # 重建消息列表
        self.messages = system_msgs + other_msgs

    def get_messages(self) -> List[Dict[str, Any]]:
        """获取所有消息的字典格式"""
        return [msg.to_dict() for msg in self.messages]

    def get_message_objects(self) -> List[Message]:
        """获取所有消息的 Message 对象"""
        return self.messages.copy()

    def clear(self, keep_system: bool = True):
        """
        清空对话历史

        Args:
            keep_system: 是否保留系统消息
        """
        if keep_system and self.system_message:
            self.messages = [msg for msg in self.messages if msg.role == MessageRole.SYSTEM]
        else:
            self.messages.clear()

    def count(self) -> int:
        """获取消息数量"""
        return len(self.messages)

    def __len__(self) -> int:
        """获取消息数量"""
        return len(self.messages)


def create_prompt_template(
    template: str,
    variables: Dict[str, Any],
    escape: bool = False
) -> str:
    """
    从带变量的模板创建提示词

    Args:
        template: 包含 {variable} 占位符的模板字符串
        variables: 变量值字典
        escape: 是否转义特殊字符

    Returns:
        格式化的提示词字符串

    示例:
        >>> template = "将 {text} 翻译成 {language}"
        >>> prompt = create_prompt_template(template, {"text": "hello", "language": "法语"})
        >>> print(prompt)  # "将 hello 翻译成法语"
    """
    try:
        if escape:
            # 格式化前转义替换值中的花括号；若在 ``format`` 后转义，
            # 会破坏最终提示词中原本正确的花括号。
            variables = {
                key: (
                    value.replace('{', '{{').replace('}', '}}')
                    if isinstance(value, str)
                    else value
                )
                for key, value in variables.items()
            }

        return template.format(**variables)
    except KeyError as e:
        raise ValueError(f"模板中缺少变量: {e}")


def format_code_block(code: str, language: str = "") -> str:
    """
    在 markdown 代码块中格式化代码

    Args:
        code: 代码内容
        language: 语法高亮的编程语言

    Returns:
        格式化的代码块
    """
    return f"```{language}\n{code}\n```"


def format_json_block(data: Union[Dict, List]) -> str:
    """
    在 markdown 代码块中格式化 JSON 数据

    Args:
        data: 要格式化为 JSON 的字典或列表

    Returns:
        格式化的 JSON 代码块
    """
    import json
    json_str = json.dumps(data, indent=2, ensure_ascii=False)
    return format_code_block(json_str, "json")
