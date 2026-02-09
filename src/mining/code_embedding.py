"""
代码嵌入模块
支持多种代码嵌入模型：
- CodeLLaMA 7B: 大型代码语言模型，性能优异
- UniXcoder: 轻量级代码预训练模型，速度快
"""

import os
import re
from typing import List, Dict, Optional, Tuple

import torch
import numpy as np
import pandas as pd
from transformers import AutoTokenizer, AutoModel

from ..common.node_kinds import get_func_kinds, get_block_kinds, get_stmt_kinds
from ..logger import get_logger

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
    MODEL_CONFIGS = {
        "codellama": {
            "name": "codellama/CodeLlama-7b-hf",
            "max_length": 2048,
            "description": "CodeLLaMA 7B - 大型代码语言模型"
        },
        "unixcoder": {
            "name": "microsoft/unixcoder-base",
            "max_length": 512,
            "description": "UniXcoder - 轻量级代码预训练模型"
        },
        "codebert": {
            "name": "microsoft/codebert-base",
            "max_length": 512,
            "description": "CodeBERT - 基础代码预训练模型"
        }
    }
    
    def __init__(self, model_name: str = "unixcoder", device: Optional[str] = None):
        """
        初始化代码嵌入器
        
        Args:
            model_name: 模型名称，可以是：
                - 简称："codellama", "unixcoder", "codebert"
                - 完整 HuggingFace 模型名
            device: 设备（cuda/cpu），None 表示自动选择
        """
        # 解析模型名称
        if model_name in self.MODEL_CONFIGS:
            config = self.MODEL_CONFIGS[model_name]
            self.model_name = config["name"]
            self.max_length = config["max_length"]
            logger.info(f"使用预定义模型: {config['description']}")
        else:
            self.model_name = model_name
            self.max_length = 512  # 默认长度
            logger.info(f"使用自定义模型: {model_name}")
        
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
                        torch_dtype=torch.float16
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
            logger.info("模型加载成功")
            
        except Exception as e:
            logger.error(f"加载模型 {self.model_name} 失败: {e}")
            logger.info("尝试使用 CodeBERT 作为备选...")
            
            # 回退到 CodeBERT
            self.model_name = "microsoft/codebert-base"
            self.max_length = 512
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModel.from_pretrained(self.model_name)
            self.model.to(self.device)
            self.model.eval()
            logger.info("备选模型 CodeBERT 加载成功")
    
    def get_embedding(self, code_snippet: str) -> torch.Tensor:
        """
        获取代码片段的嵌入向量
        
        Args:
            code_snippet: 代码片段字符串
            
        Returns:
            嵌入向量张量 (1, hidden_size)
        """
        if not code_snippet or code_snippet.strip() == "":
            # 返回零向量
            hidden_size = self.model.config.hidden_size
            logger.debug("空代码片段，返回零向量")
            return torch.zeros(1, hidden_size)
        
        # 使用配置的最大长度
        inputs = self.tokenizer(
            code_snippet,
            return_tensors="pt",
            truncation=True,
            padding=True,
            max_length=self.max_length
        )
        
        # 将输入移动到模型所在的设备
        device = next(self.model.parameters()).device
        inputs = {k: v.to(device) for k, v in inputs.items()}
        
        with torch.no_grad():
            outputs = self.model(**inputs)
            # 使用 mean pooling 所有 token 的嵌入
            hidden_states = outputs.last_hidden_state
            # 计算平均池化（排除 padding tokens）
            attention_mask = inputs['attention_mask']
            # 扩展 attention_mask 以匹配 hidden_states 的维度
            mask_expanded = attention_mask.unsqueeze(-1).expand(hidden_states.size()).float()
            # 计算加权平均
            sum_embeddings = torch.sum(hidden_states * mask_expanded, dim=1)
            sum_mask = torch.clamp(mask_expanded.sum(dim=1), min=1e-9)
            embedding = sum_embeddings / sum_mask
        
        return embedding.cpu()  # 返回 CPU 张量以便后续处理


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


def get_pros_src_and_embedding(
    data: pd.DataFrame,
    embedder: CodeEmbedder,
    language: str = "cpp",
    min_nodes: int = 10,
    min_ast_num: int = 5,
    min_project_size: int = 1000
) -> Tuple[List[str], List[List[str]], List[List[torch.Tensor]], List[List[List]]]:
    """
    从 AST 数据中提取代码片段并生成嵌入
    
    Args:
        data: 包含 AST 数据的 DataFrame
        embedder: 代码嵌入器实例
        language: 编程语言类型
        min_nodes: 函数的最小节点数阈值
        min_ast_num: 节点的最小 AST 数量阈值
        min_project_size: 项目的最小代码片段数量阈值
        
    Returns:
        (pros_name, pros_src, pros_emb, pros_info) 元组
    """
    logger.info(f"开始提取代码片段并生成嵌入（语言: {language}）")
    logger.info(f"过滤条件: min_nodes={min_nodes}, min_ast_num={min_ast_num}, min_project_size={min_project_size}")
    
    # 获取节点类型
    func_kind = get_func_kinds(language)
    block_kind = get_block_kinds(language)
    stmt_kind = get_stmt_kinds(language)
    
    projects = data['project']
    files = data['cppFile']
    asts = data['func_ast']
    srcs = data['func_src']
    
    pros_name, pros_src, pros_emb, pros_info = [], [], [], []
    
    for i, project_data in enumerate(asts):
        pro_name = projects[i]
        logger.info(f"处理项目 [{i+1}/{len(asts)}]: {pro_name}")
        
        pro_src, pro_emb, pro_info = [], [], []
        
        for j, file_data in enumerate(project_data):
            file_name = files[i][j]
            logger.info(f"  处理文件 [{j+1}/{len(project_data)}]: {os.path.basename(file_name)}")
            
            for k, func_data in enumerate(file_data):
                if len(func_data) < min_nodes:
                    continue
                
                extent_valid = "0-0-0-0"
                extent_root = ""
                
                for l, node_info in enumerate(func_data):
                    code_snippet = node_info.get("code_snippet", "")
                    kind = node_info.get("kind", "")
                    extent = node_info.get("extent", "")
                    ast_num = node_info.get("ast_num", 0)
                    
                    if l == 0:
                        extent_root = extent
                    
                    if not code_snippet or code_snippet == "" or ast_num < min_ast_num:
                        continue
                    
                    # 处理函数和块级别的节点
                    if kind in func_kind or kind in block_kind:
                        pro_src.append(code_snippet)
                        embedding = embedder.get_embedding(code_snippet)
                        pro_emb.append(embedding)
                        pro_info.append([pro_name, file_name, extent_root, node_info])
                    
                    # 处理语句级别的节点（需要检查是否嵌套）
                    elif kind in stmt_kind:
                        if not is_within_extent(extent_valid, extent):
                            extent_valid = extent
                            pro_src.append(code_snippet)
                            embedding = embedder.get_embedding(code_snippet)
                            pro_emb.append(embedding)
                            pro_info.append([pro_name, file_name, extent_root, node_info])
        
        logger.info(f"  项目 {pro_name}: {len(pro_src)} 个代码片段")
        
        # 只有当项目代码片段数量达到阈值时才添加
        if len(pro_src) >= min_project_size:
            pros_name.append(pro_name)
            pros_src.append(pro_src)
            pros_emb.append(pro_emb)
            pros_info.append(pro_info)
            logger.info(f"  项目 {pro_name} 已添加（符合最小项目大小阈值）")
        else:
            logger.warning(f"  项目 {pro_name} 跳过（代码片段数 {len(pro_src)} < {min_project_size}）")
    
    logger.info(f"完成处理，共 {len(pros_name)} 个项目符合条件")
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
    language: str = "cpp",
    device: Optional[str] = None,
    min_project_size: int = 100  # 降低测试阈值
):
    """
    生成代码嵌入的主函数
    
    Args:
        input_file: 输入的 AST 数据文件路径
        output_file: 输出的嵌入数据文件路径
        model_name: 模型名称（"codellama", "unixcoder", "codebert" 或完整模型名）
        language: 编程语言类型
        device: 设备（cuda/cpu）
        min_project_size: 项目最小代码片段数量（测试时可以设置较小值）
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
    embedder = CodeEmbedder(model_name=model_name, device=device)
    
    # 生成嵌入
    logger.info("开始生成嵌入...")
    pros_name, pros_src, pros_emb, pros_info = get_pros_src_and_embedding(
        data, embedder, language=language, min_project_size=min_project_size
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
        default='output/cpp/dataset.pkl',
        help='输入的 AST 数据文件路径'
    )
    parser.add_argument(
        '--output', '-o',
        default='output/cpp/embeddings.pkl',
        help='输出的嵌入数据文件路径'
    )
    parser.add_argument(
        '--model', '-m',
        default='unixcoder',
        help='模型名称：codellama, unixcoder, codebert 或完整 HuggingFace 模型名（默认: unixcoder）'
    )
    parser.add_argument(
        '--language', '-l',
        default='cpp',
        choices=['cpp', 'python', 'java', 'javascript'],
        help='编程语言类型'
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
    
    args = parser.parse_args()
    
    generate_embeddings(
        input_file=args.input,
        output_file=args.output,
        model_name=args.model,
        language=args.language,
        device=args.device,
        min_project_size=args.min_project_size
    )


# 模块运行命令（从项目根目录运行）：
# python -m src.mining.code_embedding --input output/cpp/dataset.pkl --output output/cpp/embeddings.pkl --model unixcoder
# nohup python -m src.mining.code_embedding --input output/cpp/dataset.pkl --output output/cpp/embeddings.pkl --model unixcoder > logs/code_embedding.log 2>&1 &

if __name__ == "__main__":
    main()

