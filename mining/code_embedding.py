"""
代码嵌入模块
使用 CodeLLaMA 7B 模型进行代码嵌入
CodeLLaMA 是专门为代码任务训练的大语言模型，性能优异
"""

import os
import torch
import numpy as np
import pandas as pd
import sys
import re
from typing import List, Dict, Optional, Tuple
from transformers import AutoTokenizer, AutoModel
from common.node_kinds import get_func_kinds, get_block_kinds, get_stmt_kinds


class CodeEmbedder:
    """代码嵌入器，使用 CodeLLaMA 7B 模型"""
    
    def __init__(self, model_name: str = "codellama/CodeLlama-7b-hf", device: Optional[str] = None):
        """
        初始化代码嵌入器
        
        Args:
            model_name: HuggingFace 模型名称，默认使用 CodeLLaMA 7B
            device: 设备（cuda/cpu），None 表示自动选择
        """
        self.model_name = model_name
        print(f"加载模型: {model_name}")
        
        # 自动选择设备
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = device
        
        # 加载模型和分词器
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            # CodeLLaMA 可能需要设置 pad_token
            if self.tokenizer.pad_token is None:
                self.tokenizer.pad_token = self.tokenizer.eos_token
            
            # 使用 device_map="auto" 自动分配 GPU（如果有多个 GPU）
            if torch.cuda.is_available():
                self.model = AutoModel.from_pretrained(
                    model_name,
                    device_map="auto",
                    torch_dtype=torch.float16  # 使用半精度以节省显存
                )
                print("模型已自动分配到 GPU")
            else:
                self.model = AutoModel.from_pretrained(model_name)
                self.model.to(self.device)
                print(f"模型已加载到设备: {self.device}")
            
            self.model.eval()
        except Exception as e:
            print(f"加载模型失败: {e}")
            print("尝试使用 CodeBERT 作为备选...")
            # 如果 CodeLLaMA 加载失败，回退到 CodeBERT
            self.model_name = "microsoft/codebert-base"
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self.model = AutoModel.from_pretrained(self.model_name)
            self.model.to(self.device)
            self.model.eval()
    
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
            return torch.zeros(1, hidden_size)
        
        # CodeLLaMA 支持更长的序列，但为了效率限制在 2048
        inputs = self.tokenizer(
            code_snippet,
            return_tensors="pt",
            truncation=True,
            padding=True,
            max_length=2048  # CodeLLaMA 支持更长的序列
        )
        
        # 将输入移动到模型所在的设备
        if hasattr(self.model, 'device'):
            device = next(self.model.parameters()).device
        else:
            device = self.device
        inputs = {k: v.to(device) for k, v in inputs.items()}
        
        with torch.no_grad():
            outputs = self.model(**inputs)
            # CodeLLaMA 使用 mean pooling 或最后一个 token
            # 这里使用 mean pooling 所有 token 的嵌入
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
        raise ValueError(f"Invalid extent format: {extent}")


def is_within_extent(extent_pre: str, extent_cur: str) -> bool:
    """判断 extent_cur 是否在 extent_pre 的范围内"""
    pre_start_line, pre_start_column, pre_end_line, pre_end_column = parse_extent(extent_pre)
    cur_start_line, cur_start_column, cur_end_line, cur_end_column = parse_extent(extent_cur)
    
    if (pre_start_line < cur_start_line or 
        (pre_start_line == cur_start_line and pre_start_column <= cur_start_column)) and \
       (pre_end_line > cur_end_line or 
        (pre_end_line == cur_end_line and pre_end_column >= cur_end_column)):
        return True
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
        print(f"处理项目 [{i+1}/{len(asts)}]: {pro_name}")
        sys.stdout.flush()
        
        pro_src, pro_emb, pro_info = [], [], []
        
        for j, file_data in enumerate(project_data):
            file_name = files[i][j]
            print(f"  处理文件 [{j+1}/{len(project_data)}]: {os.path.basename(file_name)}")
            sys.stdout.flush()
            
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
        
        print(f"  项目 {pro_name}: {len(pro_src)} 个代码片段")
        sys.stdout.flush()
        
        # 只有当项目代码片段数量达到阈值时才添加
        if len(pro_src) >= min_project_size:
            pros_name.append(pro_name)
            pros_src.append(pro_src)
            pros_emb.append(pro_emb)
            pros_info.append(pro_info)
    
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
    import os
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    print(f"\n数据统计:")
    print(f"  项目数: {len(pros_name)}")
    print(f"  总代码片段数: {sum(len(srcs) for srcs in pros_src)}")
    
    data = pd.DataFrame({
        'pros_name': pros_name,
        'pros_src': pros_src,
        'pros_emb': pros_emb,
        'pros_info': pros_info
    })
    
    print(f"数据列: {data.columns.tolist()}")
    print(f"数据形状: {data.shape}")
    
    pd.to_pickle(data, output_path)
    print(f"\n嵌入数据已保存到: {output_path}")


def generate_embeddings(
    input_file: str,
    output_file: str,
    model_name: str = "codellama/CodeLlama-7b-hf",
    language: str = "cpp",
    device: Optional[str] = None
):
    """
    生成代码嵌入的主函数
    
    Args:
        input_file: 输入的 AST 数据文件路径
        output_file: 输出的嵌入数据文件路径
        model_name: 模型名称
        language: 编程语言类型
        device: 设备（cuda/cpu）
    """
    print("=" * 60)
    print("代码嵌入生成")
    print("=" * 60)
    
    # 加载数据
    print(f"加载数据: {input_file}")
    data = pd.read_pickle(input_file)
    print(f"数据形状: {data.shape}")
    
    # 初始化嵌入器
    embedder = CodeEmbedder(model_name=model_name, device=device)
    
    # 生成嵌入
    print("\n开始生成嵌入...")
    pros_name, pros_src, pros_emb, pros_info = get_pros_src_and_embedding(
        data, embedder, language=language
    )
    
    # 保存结果
    write_embedding_data(pros_name, pros_src, pros_emb, pros_info, output_file)


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='生成代码嵌入')
    parser.add_argument(
        '--input', '-i',
        default='../output/cpp/dataset.pkl',
        help='输入的 AST 数据文件路径'
    )
    parser.add_argument(
        '--output', '-o',
        default='../output/cpp/embeddings.pkl',
        help='输出的嵌入数据文件路径'
    )
    parser.add_argument(
        '--model', '-m',
        default='codellama/CodeLlama-7b-hf',
        help='模型名称（HuggingFace），默认使用 CodeLLaMA 7B'
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
    
    args = parser.parse_args()
    
    generate_embeddings(
        input_file=args.input,
        output_file=args.output,
        model_name=args.model,
        language=args.language,
        device=args.device
    )


if __name__ == "__main__":
    import os
    main()

