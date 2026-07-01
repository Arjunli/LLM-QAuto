"""
插件系统 - 支持动态加载各种扩展
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Type, Optional
from dataclasses import dataclass


@dataclass
class JudgeContext:
    """评判上下文"""
    test_input: Any
    test_output: Any = None
    previous_results: List[Any] = None
    global_config: Dict[str, Any] = None
    artifacts_dir: Optional[str] = None

    def __post_init__(self):
        if self.previous_results is None:
            self.previous_results = []
        if self.global_config is None:
            self.global_config = {}


class PluginRegistry:
    """插件注册表 - 单例模式"""
    _instance = None
    _plugins: Dict[str, Dict[str, Type]] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._plugins = {
                "connector": {},
                "generator": {},
                "evaluator": {},
                "reporter": {},
            }
        return cls._instance
    
    def register(self, plugin_type: str, name: str, plugin_class: Type):
        """注册插件"""
        if plugin_type not in self._plugins:
            self._plugins[plugin_type] = {}
        self._plugins[plugin_type][name] = plugin_class
    
    def get(self, plugin_type: str, name: str) -> Optional[Type]:
        """获取插件类"""
        return self._plugins.get(plugin_type, {}).get(name)
    
    def list_plugins(self, plugin_type: Optional[str] = None) -> Dict:
        """列出已注册插件"""
        if plugin_type:
            return {plugin_type: list(self._plugins.get(plugin_type, {}).keys())}
        return {k: list(v.keys()) for k, v in self._plugins.items()}


def register_plugin(plugin_type: str, name: str):
    """插件注册装饰器
    
    用法:
        @register_plugin("evaluator", "my_judge")
        class MyEvaluator(BaseEvaluator):
            ...
    """
    def decorator(cls):
        registry = PluginRegistry()
        registry.register(plugin_type, name, cls)
        return cls
    return decorator


def load_plugin(plugin_type: str, name: str) -> Any:
    """加载插件实例
    
    Args:
        plugin_type: 插件类型 (connector/generator/evaluator/reporter)
        name: 插件名称
    
    Returns:
        插件实例
    
    Raises:
        ValueError: 插件不存在
    """
    registry = PluginRegistry()
    plugin_class = registry.get(plugin_type, name)
    if not plugin_class:
        raise ValueError(
            f"未知插件: {plugin_type}/{name}\n"
            f"可用插件: {registry.list_plugins(plugin_type)}"
        )
    return plugin_class()


class Plugin(ABC):
    """插件基类"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """插件名称"""
        pass
    
    @abstractmethod
    async def initialize(self, config: Dict[str, Any]):
        """初始化插件
        
        Args:
            config: 插件配置
        """
        pass
    
    @abstractmethod
    async def cleanup(self):
        """清理资源"""
        pass


# 导入所有内置插件，确保它们被注册
from . import connectors, generators, evaluators

__all__ = [
    "PluginRegistry",
    "register_plugin",
    "load_plugin",
    "Plugin",
    "JudgeContext",
]
