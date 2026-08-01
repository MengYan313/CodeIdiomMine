"""
代码嵌入模块
支持多种代码嵌入模型：
- CodeLLaMA 7B: 大型代码语言模型，性能优异
- UniXcoder: 轻量级代码预训练模型，速度快
"""

import os
import re
from typing import Any, List, Dict, Mapping, Optional, Tuple

import torch
import pandas as pd
from transformers import AutoTokenizer, AutoModel

from ..common.logging import get_logger
from ..common.progress import progress
from ..parser.fragment_builder import MODEL_INPUT_CONFIGS
from ..parser.token_budget import TokenBudget, resolve_max_input_tokens

# 创建日志记录器
logger = get_logger(__name__)


class CodeEmbedder:
    """
    代码嵌入器
    
    支持的模型：
    - codellama/CodeLlama-7b-hf: CodeLLaMA 7B 大型模型
    - microsoft/unixcoder-base: UniXcoder 轻量级模型（推荐测试使用）
    - microsoft/codebert-base: CodeBERT 基础模型（备选）
    """
    
    # 预定义模型配置
    MODEL_CONFIGS = MODEL_INPUT_CONFIGS
    
    def __init__(
        self,
        model_name: str = "unixcoder",
        device: Optional[str] = None,
        max_input_tokens: Optional[int] = None,
    ):
        """
        初始化代码嵌入器
        
        Args:
            model_name: 模型名称，可以是：
                - 简称："codellama", "unixcoder", "codebert"
                - 完整 HuggingFace 模型名
            device: 设备（cuda/cpu），None 表示自动选择
            max_input_tokens: 可选的更严格输入上限，不得超过模型配置值
        """
        # 解析模型名称
        if model_name in self.MODEL_CONFIGS:
            config = self.MODEL_CONFIGS[model_name]
            self.model_name = config["name"]
            self.configured_max_length = int(config["max_length"])
            logger.info(f"使用预定义模型: {config['description']}")
        else:
            self.model_name = model_name
            self.configured_max_length = 512
            logger.info(f"使用自定义模型: {model_name}")
        self._requested_max_input_tokens = max_input_tokens
        self.max_input_tokens = resolve_max_input_tokens(
            self.configured_max_length,
            max_input_tokens,
        )
        # 保留历史属性名；它现在明确表示实际允许送入模型的总 token 数。
        self.max_length = self.max_input_tokens
        
        # 自动选择设备
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = device
        logger.info(f"设备: {self.device}")
        
        # 加载模型和分词器
        self._load_model()
    
    def _load_model(self):
        """加载模型和分词器"""
        try:
            logger.info(f"正在加载模型: {self.model_name}")
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name, trust_remote_code=True)
            
            # 设置 pad_token（如果不存在）
            if self.tokenizer.pad_token is None:
                if self.tokenizer.eos_token is not None:
                    self.tokenizer.pad_token = self.tokenizer.eos_token
                else:
                    self.tokenizer.add_special_tokens({'pad_token': '[PAD]'})
            
            # 加载模型
            if torch.cuda.is_available() and self.device == "cuda":
                try:
                    # 尝试使用半精度加载到 GPU
                    self.model = AutoModel.from_pretrained(
                        self.model_name,
                        trust_remote_code=True,
                        dtype=torch.float16
                    )
                    self.model.to(self.device)
                    logger.info("模型已加载到 GPU（半精度）")
                except Exception as e:
                    logger.warning(f"GPU 加载失败，尝试 CPU: {e}")
                    self.model = AutoModel.from_pretrained(self.model_name, trust_remote_code=True)
                    self.model.to("cpu")
                    self.device = "cpu"
                    logger.info("模型已加载到 CPU")
            else:
                self.model = AutoModel.from_pretrained(self.model_name, trust_remote_code=True)
                self.model.to(self.device)
                logger.info(f"模型已加载到 {self.device}")
            
            self.model.eval()
            self.token_budget = TokenBudget(
                tokenizer=self.tokenizer,
                model_name=self.model_name,
                max_input_tokens=self.max_input_tokens,
            )
            logger.info("模型加载成功")
            
        except Exception as e:
            logger.error(f"加载模型 {self.model_name} 失败: {e}")
            logger.info("尝试使用 CodeBERT 作为备选...")
            
            # 回退到 CodeBERT
            self.model_name = "microsoft/codebert-base"
            self.configured_max_length = 512
            self.max_input_tokens = min(
                self._requested_max_input_tokens or 512,
                self.configured_max_length,
            )
            self.max_length = self.max_input_tokens
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModel.from_pretrained(self.model_name)
            self.model.to(self.device)
            self.model.eval()
            self.token_budget = TokenBudget(
                tokenizer=self.tokenizer,
                model_name=self.model_name,
                max_input_tokens=self.max_input_tokens,
            )
            logger.info("备选模型 CodeBERT 加载成功")

    def get_token_count(self, code_snippet: str) -> int:
        """返回实际 tokenizer 生成的总输入长度（含特殊 token）。"""
        return self.token_budget.count(code_snippet)

    def fits_token_budget(
        self,
        snippet_or_node: str | Mapping[str, Any],
    ) -> bool:
        """判断片段能否在不截断的情况下送入当前模型。"""
        return self.token_budget.fits(snippet_or_node)
    
    def get_embedding(self, code_snippet: str) -> torch.Tensor:
        """
        获取代码片段的嵌入向量
        
        Args:
            code_snippet: 代码片段字符串
            
        Returns:
            嵌入向量张量 (1, hidden_size)
        """
        return self.get_embeddings([code_snippet], batch_size=1)[0]

    def get_embeddings(
        self,
        code_snippets: List[str],
        batch_size: int = 8
    ) -> List[torch.Tensor]:
        """批量生成嵌入，并保持输入顺序及单段 ``(1, hidden_size)`` 形状。"""
        if batch_size < 1:
            raise ValueError("batch_size 必须大于等于 1")
        if not code_snippets:
            return []

        hidden_size = self.model.config.hidden_size
        embeddings: List[Optional[torch.Tensor]] = [None] * len(code_snippets)
        nonempty_indices = [
            index for index, snippet in enumerate(code_snippets)
            if snippet and snippet.strip()
        ]
        self.token_budget.validate(
            [code_snippets[index] for index in nonempty_indices]
        )

        for index, snippet in enumerate(code_snippets):
            if not snippet or not snippet.strip():
                embeddings[index] = torch.zeros(1, hidden_size)

        # 相近长度的片段放入同一批次，减少 padding；结果写回原下标，因此
        # 不改变下游代码段、位置信息和嵌入之间的顺序契约。
        nonempty_indices.sort(key=lambda index: len(code_snippets[index]))
        device = next(self.model.parameters()).device

        batch_starts = range(0, len(nonempty_indices), batch_size)
        for start in progress(batch_starts, desc="生成嵌入", unit="批", leave=False):
            batch_indices = nonempty_indices[start:start + batch_size]
            batch_snippets = [code_snippets[index] for index in batch_indices]
            inputs = self.tokenizer(
                batch_snippets,
                return_tensors="pt",
                truncation=False,
                padding=True,
            )
            inputs = {key: value.to(device) for key, value in inputs.items()}

            with torch.no_grad():
                hidden_states = self.model(**inputs).last_hidden_state
                attention_mask = inputs['attention_mask']
                mask_expanded = attention_mask.unsqueeze(-1).expand(hidden_states.size()).float()
                sum_embeddings = torch.sum(hidden_states * mask_expanded, dim=1)
                sum_mask = torch.clamp(mask_expanded.sum(dim=1), min=1e-9)
                batch_embeddings = (sum_embeddings / sum_mask).cpu()

            for index, embedding in zip(batch_indices, batch_embeddings):
                embeddings[index] = embedding.unsqueeze(0)

        if any(embedding is None for embedding in embeddings):
            raise RuntimeError("存在未生成的代码嵌入")
        return [embedding for embedding in embeddings if embedding is not None]


def parse_extent(extent: str) -> Tuple[int, int, int, int]:
    """解析 extent 字符串为四个整数"""
    match = re.match(r"(\d+)-(\d+)-(\d+)-(\d+)", extent)
    if match:
        start_line, start_column, end_line, end_column = map(int, match.groups())
        return start_line, start_column, end_line, end_column
    else:
        logger.error(f"无效的 extent 格式: {extent}")
        raise ValueError(f"Invalid extent format: {extent}")


def is_within_extent(extent_pre: str, extent_cur: str) -> bool:
    """判断 extent_cur 是否在 extent_pre 的范围内"""
    try:
        pre_start_line, pre_start_column, pre_end_line, pre_end_column = parse_extent(extent_pre)
        cur_start_line, cur_start_column, cur_end_line, cur_end_column = parse_extent(extent_cur)
        
        if (pre_start_line < cur_start_line or 
            (pre_start_line == cur_start_line and pre_start_column <= cur_start_column)) and \
           (pre_end_line > cur_end_line or 
            (pre_end_line == cur_end_line and pre_end_column >= cur_end_column)):
            return True
        return False
    except Exception as e:
        logger.debug(f"检查 extent 范围时出错: {e}")
        return False


def get_fragment_src_and_embedding(
    fragments: pd.DataFrame,
    embedder: CodeEmbedder,
    *,
    min_project_size: int = 1000,
    batch_size: int = 8,
) -> Tuple[List[str], List[List[str]], List[List[torch.Tensor]], List[List[List]]]:
    """只嵌入 Parser 已完成降级的 model-ready 片段。"""
    required = {
        "project",
        "model_name",
        "max_input_tokens",
        "fragment_src",
        "fragment_info",
    }
    missing = sorted(required - set(fragments.columns))
    if missing:
        raise ValueError(
            "输入不是 Parser model-ready 片段产物，缺少列: "
            + ", ".join(missing)
        )

    pros_name: List[str] = []
    pros_src: List[List[str]] = []
    pros_emb: List[List[torch.Tensor]] = []
    pros_info: List[List[List]] = []
    for row_index in progress(
        range(len(fragments)), desc="嵌入项目", unit="项目"
    ):
        row = fragments.iloc[row_index]
        artifact_model = str(row["model_name"])
        artifact_budget = int(row["max_input_tokens"])
        if artifact_model != embedder.model_name:
            raise ValueError(
                "Parser 片段 tokenizer 与 embedding 模型不一致："
                f"{artifact_model} != {embedder.model_name}"
            )
        if artifact_budget != embedder.max_input_tokens:
            raise ValueError(
                "Parser 片段 token 预算与 embedding 配置不一致："
                f"{artifact_budget} != {embedder.max_input_tokens}"
            )
        sources = list(row["fragment_src"])
        infos = list(row["fragment_info"])
        if len(sources) != len(infos):
            raise ValueError("fragment_src 与 fragment_info 长度不一致")
        embedder.token_budget.validate(sources)
        project = str(row["project"])
        if len(sources) < min_project_size:
            logger.warning(
                "项目 %s 跳过（model-ready 片段数 %s < %s）",
                project,
                len(sources),
                min_project_size,
            )
            continue
        embeddings = embedder.get_embeddings(sources, batch_size=batch_size)
        pros_name.append(project)
        pros_src.append(sources)
        pros_emb.append(embeddings)
        pros_info.append(infos)
    return pros_name, pros_src, pros_emb, pros_info


def write_embedding_data(
    pros_name: List[str],
    pros_src: List[List[str]],
    pros_emb: List[List[torch.Tensor]],
    pros_info: List[List[List]],
    output_path: str
):
    """
    保存嵌入数据到 pickle 文件
    
    Args:
        pros_name: 项目名称列表
        pros_src: 代码片段列表（2D）
        pros_emb: 嵌入向量列表（2D）
        pros_info: 信息列表（2D）
        output_path: 输出文件路径
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    total_snippets = sum(len(srcs) for srcs in pros_src)
    logger.info(f"数据统计:")
    logger.info(f"  项目数: {len(pros_name)}")
    logger.info(f"  总代码片段数: {total_snippets}")
    
    data = pd.DataFrame({
        'pros_name': pros_name,
        'pros_src': pros_src,
        'pros_emb': pros_emb,
        'pros_info': pros_info
    })
    
    logger.info(f"数据列: {data.columns.tolist()}")
    logger.info(f"数据形状: {data.shape}")
    
    pd.to_pickle(data, output_path)
    logger.info(f"嵌入数据已保存到: {output_path}")


def generate_embeddings(
    input_file: str,
    output_file: str,
    model_name: str = "unixcoder",
    device: Optional[str] = None,
    min_project_size: int = 100,  # 降低测试阈值
    batch_size: int = 8,
    max_input_tokens: Optional[int] = None,
):
    """
    生成代码嵌入的主函数
    
    Args:
        input_file: Parser 生成的 model-ready fragments.pkl
        output_file: 输出的嵌入数据文件路径
        model_name: 模型名称（"codellama", "unixcoder", "codebert" 或完整模型名）
        device: 设备（cuda/cpu）
        min_project_size: 项目最小代码片段数量（测试时可以设置较小值）
        batch_size: 模型批量推理大小
        max_input_tokens: 可选的更严格模型输入 token 上限
    """
    logger.info("=" * 60)
    logger.info("代码嵌入生成")
    logger.info("=" * 60)
    
    # 加载数据
    logger.info(f"加载数据: {input_file}")
    data = pd.read_pickle(input_file)
    logger.info(f"数据形状: {data.shape}")
    logger.info(f"数据列: {data.columns.tolist()}")
    
    # 初始化嵌入器
    embedder = CodeEmbedder(
        model_name=model_name,
        device=device,
        max_input_tokens=max_input_tokens,
    )
    
    # 只消费 Parser 已完成长度降级的片段，不再从 AST 临时选取或截断。
    logger.info("开始生成嵌入...")
    pros_name, pros_src, pros_emb, pros_info = get_fragment_src_and_embedding(
        data,
        embedder,
        min_project_size=min_project_size,
        batch_size=batch_size,
    )
    
    # 保存结果
    write_embedding_data(pros_name, pros_src, pros_emb, pros_info, output_file)
    logger.info("代码嵌入生成完成！")


def main():
    """测试代码嵌入功能"""
    import argparse
    
    parser = argparse.ArgumentParser(description='生成代码嵌入')
    parser.add_argument(
        '--input', '-i',
        default='outputs/cpp/fragments.pkl',
        help='Parser 生成的 model-ready 片段文件'
    )
    parser.add_argument(
        '--output', '-o',
        default='outputs/cpp/embeddings.pkl',
        help='输出的嵌入数据文件路径'
    )
    parser.add_argument(
        '--model', '-m',
        default='unixcoder',
        help='模型名称：codellama, unixcoder, codebert 或完整 HuggingFace 模型名（默认: unixcoder）'
    )
    parser.add_argument(
        '--device', '-d',
        default=None,
        help='设备（cuda/cpu），None 表示自动选择'
    )
    parser.add_argument(
        '--min-project-size',
        type=int,
        default=100,
        help='项目最小代码片段数量阈值（默认: 100，测试时可设为更小值）'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=8,
        help='模型批量推理大小（默认: 8）'
    )
    parser.add_argument(
        '--max-input-tokens',
        type=int,
        default=None,
        help='可选的更严格总 token 上限；只能小于等于模型配置值',
    )
    
    args = parser.parse_args()
    
    generate_embeddings(
        input_file=args.input,
        output_file=args.output,
        model_name=args.model,
        device=args.device,
        min_project_size=args.min_project_size,
        batch_size=args.batch_size,
        max_input_tokens=args.max_input_tokens,
    )


if __name__ == "__main__":
    main()
