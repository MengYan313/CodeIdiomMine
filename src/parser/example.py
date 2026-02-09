"""
使用示例
演示如何使用 parser 模块解析代码仓库
"""

from repo2data import parse_repository, read_data

# 示例 1: 解析 C++ 项目
if __name__ == "__main__":
    # 解析仓库
    input_path = "../repo/cpp"
    output_path = "../output/cpp/dataset.pkl"
    
    print("开始解析 C++ 项目...")
    parse_repository(input_path, output_path, language="cpp")
    
    # 读取解析结果
    print("\n读取解析结果...")
    data = read_data(output_path)
    print(f"项目数量: {len(data)}")
    print(f"数据列: {data.columns.tolist()}")
    
    # 查看第一个项目的信息
    if len(data) > 0:
        first_project = data.iloc[0]
        print(f"\n第一个项目: {first_project['project']}")
        print(f"文件数量: {len(first_project['cppFile'])}")
        if len(first_project['cppFile']) > 0:
            print(f"第一个文件: {first_project['cppFile'][0]}")
            if len(first_project['func_ast']) > 0:
                print(f"第一个文件的函数数量: {len(first_project['func_ast'][0])}")

