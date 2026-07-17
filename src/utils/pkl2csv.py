"""
PKL 转 CSV 工具

将 pickle 文件转换为 CSV 格式：
- 单个文件转换（生成在同目录）
- 目录批量转换（每个文件生成在原位置）
"""

import argparse
from pathlib import Path
import pandas as pd


class Pkl2CsvConverter:
    """PKL 到 CSV 转换器"""
    
    def convert_file(self, pkl_file: str) -> bool:
        """
        转换单个 PKL 文件到 CSV（同目录下）
        
        Args:
            pkl_file: PKL 文件路径
            
        Returns:
            转换是否成功
        """
        pkl_path = Path(pkl_file)
        
        if not pkl_path.exists():
            print(f"❌ 文件不存在: {pkl_file}")
            return False
        
        if pkl_path.suffix != '.pkl':
            print(f"⚠️  跳过非 PKL 文件: {pkl_file}")
            return False
        
        try:
            print(f"🔄 转换: {pkl_file}")
            
            # 读取 PKL 文件
            data = pd.read_pickle(pkl_file)
            
            # 输出文件：同目录，同名，.csv 扩展名
            csv_file = pkl_path.with_suffix('.csv')
            
            # 原生态转换：直接保存，不做任何处理
            if isinstance(data, pd.DataFrame):
                data.to_csv(csv_file, index=False, encoding='utf-8-sig')
            elif isinstance(data, dict):
                pd.DataFrame([data]).to_csv(csv_file, index=False, encoding='utf-8-sig')
            elif isinstance(data, list):
                pd.DataFrame(data).to_csv(csv_file, index=False, encoding='utf-8-sig')
            else:
                pd.DataFrame({'data': [data]}).to_csv(csv_file, index=False, encoding='utf-8-sig')
            
            print(f"✅ 已保存: {csv_file}")
            return True
            
        except Exception as e:
            print(f"❌ 转换失败: {pkl_file}")
            print(f"   错误: {str(e)}")
            return False
    
    def convert_directory(self, directory: str, recursive: bool = False) -> int:
        """
        转换目录中的所有 PKL 文件
        
        Args:
            directory: 目录路径
            recursive: 是否递归处理子目录
            
        Returns:
            成功转换的文件数量
        """
        dir_path = Path(directory)
        
        if not dir_path.exists():
            print(f"❌ 目录不存在: {directory}")
            return 0
        
        if not dir_path.is_dir():
            print(f"❌ 不是目录: {directory}")
            return 0
        
        # 查找所有 PKL 文件
        pkl_files = list(dir_path.rglob('*.pkl') if recursive else dir_path.glob('*.pkl'))
        
        if not pkl_files:
            print(f"⚠️  目录中没有 PKL 文件: {directory}")
            return 0
        
        print(f"📁 找到 {len(pkl_files)} 个 PKL 文件\n")
        
        # 转换所有文件
        success_count = 0
        for i, pkl_file in enumerate(pkl_files, 1):
            print(f"[{i}/{len(pkl_files)}] ", end="")
            if self.convert_file(str(pkl_file)):
                success_count += 1
            print()
        
        print(f"✨ 完成: {success_count}/{len(pkl_files)} 个文件转换成功")
        return success_count


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description='将 PKL 文件转换为 CSV 格式（生成在原文件位置）'
    )
    parser.add_argument(
        'input',
        help='输入 PKL 文件路径或目录路径'
    )
    parser.add_argument(
        '--recursive', '-r',
        action='store_true',
        help='递归处理子目录'
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("PKL 转 CSV 工具")
    print("=" * 60)
    
    input_path = Path(args.input)
    converter = Pkl2CsvConverter()
    
    if input_path.is_file():
        # 单文件转换
        success = converter.convert_file(args.input)
        exit(0 if success else 1)
    
    elif input_path.is_dir():
        # 目录批量转换
        print(f"📂 输入目录: {args.input}")
        print(f"🔁 递归模式: {'是' if args.recursive else '否'}\n")
        
        success_count = converter.convert_directory(args.input, args.recursive)
        exit(0 if success_count > 0 else 1)
    
    else:
        print(f"❌ 路径不存在: {args.input}")
        exit(1)


# 使用示例（从项目根目录运行）：
# 
# 单文件转换:
#   运行：python -m src.utils.pkl2csv outputs/cpp/clusters.pkl
#   生成: outputs/cpp/clusters.csv
# 
# 目录转换:
#   运行：python -m src.utils.pkl2csv outputs/cpp
#   生成: outputs/cpp/*.csv
# 
# 递归目录转换:
#   运行：python -m src.utils.pkl2csv outputs --recursive
#   生成: outputs/**/*.csv

if __name__ == "__main__":
    main()
