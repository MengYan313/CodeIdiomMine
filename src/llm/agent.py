"""
Agent 模块

提供基于 AutoGen 的 Agent 封装，用于构建多 Agent 系统。
"""

from typing import List, Dict, Any, Optional, Callable
from abc import ABC, abstractmethod

from .config import AgentConfig, LLMConfig
from .client import LLMClient
from .message import ConversationHistory, MessageBuilder, MessageRole


class BaseAgent(ABC):
    """
    Agent 基类

    提供 Agent 的基本功能和接口，子类需要实现具体的处理逻辑。
    """

    def __init__(self, config: AgentConfig):
        """
        初始化 Agent

        Args:
            config: Agent 配置
        """
        self.config = config
        self.name = config.name
        self.system_message = config.system_message

        # 创建 LLM 客户端
        if config.llm_config:
            self.llm_client = LLMClient(config.llm_config)
        else:
            self.llm_client = None

        # 对话历史
        self.conversation_history = ConversationHistory(
            max_messages=10,
            system_message=config.system_message
        )

    @abstractmethod
    async def process(self, message: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        处理输入消息（需要子类实现，异步）

        Args:
            message: 输入消息
            context: 可选的上下文信息

        Returns:
            处理后的响应
        """
        pass

    async def chat(self, message: str, **kwargs) -> str:
        """
        与 Agent 对话（异步）

        Args:
            message: 用户消息
            **kwargs: 其他参数

        Returns:
            Agent 响应
        """
        # 添加用户消息到历史
        self.conversation_history.add_user_message(message)

        # 处理消息
        response = await self.process(message, context=kwargs)

        # 添加助手响应到历史
        self.conversation_history.add_assistant_message(response)

        return response

    def reset(self):
        """重置 Agent 状态"""
        self.conversation_history.clear(keep_system=True)

    def get_history(self) -> List[Dict[str, Any]]:
        """获取对话历史"""
        return self.conversation_history.get_messages()

    def get_name(self) -> str:
        """获取 Agent 名称"""
        return self.name


class SimpleAgent(BaseAgent):
    """
    简单 Agent 实现（纯异步）

    直接使用 LLM 处理消息，适用于简单的对话场景。
    """

    async def process(self, message: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        处理输入消息（异步）

        Args:
            message: 输入消息
            context: 可选的上下文信息

        Returns:
            LLM 响应
        """
        if not self.llm_client:
            raise ValueError("LLM 客户端未配置")

        # 获取对话历史
        messages = self.conversation_history.get_messages()

        # 调用 LLM（异步）
        response = await self.llm_client.chat_with_history(messages)

        return response




class AgentTeam:
    """
    Agent 团队

    管理多个 Agent 协作工作。
    """

    def __init__(self, name: str = "AgentTeam"):
        """
        初始化 Agent 团队

        Args:
            name: 团队名称
        """
        self.name = name
        self.agents: Dict[str, BaseAgent] = {}
        self.workflow: List[str] = []

    def add_agent(self, agent: BaseAgent):
        """
        添加 Agent 到团队

        Args:
            agent: Agent 实例
        """
        self.agents[agent.get_name()] = agent

    def remove_agent(self, name: str):
        """
        从团队移除 Agent

        Args:
            name: Agent 名称
        """
        if name in self.agents:
            del self.agents[name]

    def get_agent(self, name: str) -> Optional[BaseAgent]:
        """
        获取 Agent

        Args:
            name: Agent 名称

        Returns:
            Agent 实例或 None
        """
        return self.agents.get(name)

    def set_workflow(self, workflow: List[str]):
        """
        设置工作流程（Agent 执行顺序）

        Args:
            workflow: Agent 名称列表
        """
        # 验证所有 Agent 是否存在
        for agent_name in workflow:
            if agent_name not in self.agents:
                raise ValueError(f"Agent '{agent_name}' 不存在于团队中")

        self.workflow = workflow

    async def execute(self, message: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        """
        按工作流执行所有 Agent（异步）

        Args:
            message: 输入消息
            context: 可选的上下文信息

        Returns:
            每个 Agent 的响应字典
        """
        if not self.workflow:
            raise ValueError("工作流未设置")

        results = {}
        current_message = message
        ctx = context or {}

        for agent_name in self.workflow:
            agent = self.agents[agent_name]
            response = await agent.chat(current_message, **ctx)
            results[agent_name] = response
            current_message = response  # 将当前响应作为下一个 Agent 的输入

        return results

    async def parallel_execute(
        self,
        message: str,
        agent_names: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        """
        并行执行多个 Agent（真正的异步并发）

        Args:
            message: 输入消息
            agent_names: 要执行的 Agent 名称列表（None 表示所有 Agent）
            context: 可选的上下文信息

        Returns:
            每个 Agent 的响应字典
        """
        import asyncio

        if agent_names is None:
            agent_names = list(self.agents.keys())

        ctx = context or {}

        # 验证所有 Agent 存在
        for agent_name in agent_names:
            if agent_name not in self.agents:
                raise ValueError(f"Agent '{agent_name}' 不存在于团队中")

        # 并发执行所有 Agent
        tasks = {
            agent_name: self.agents[agent_name].chat(message, **ctx)
            for agent_name in agent_names
        }

        # 等待所有任务完成
        responses = await asyncio.gather(*[tasks[name] for name in agent_names])

        # 构建结果字典
        results = {name: response for name, response in zip(agent_names, responses)}

        return results

    def reset_all(self):
        """重置所有 Agent"""
        for agent in self.agents.values():
            agent.reset()

    def list_agents(self) -> List[str]:
        """列出所有 Agent 名称"""
        return list(self.agents.keys())
