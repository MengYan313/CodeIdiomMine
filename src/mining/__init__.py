"""
CodeIdiomMine Mining Module
代码习语挖掘模块：代码嵌入和聚类
"""

from importlib import import_module

__all__ = [
    'CodeEmbedder',
    'generate_embeddings',
    'ClusteringProcessor',
    'DBSCANAutoTuner',
    'HDBSCANClusteringProcessor',
]

_EXPORTS = {
    "CodeEmbedder": (".code_embedding", "CodeEmbedder"),
    "generate_embeddings": (".code_embedding", "generate_embeddings"),
    "ClusteringProcessor": (".clustering", "ClusteringProcessor"),
    "DBSCANAutoTuner": (".dbscan_tuning", "DBSCANAutoTuner"),
    "HDBSCANClusteringProcessor": (
        ".hdbscan_clustering",
        "HDBSCANClusteringProcessor",
    ),
}


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attribute = _EXPORTS[name]
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
