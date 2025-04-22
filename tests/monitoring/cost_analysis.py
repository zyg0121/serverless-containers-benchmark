import boto3
import datetime
import pandas as pd
import matplotlib.pyplot as plt
import argparse
from tabulate import tabulate

def get_cost_and_usage(region, start_date, end_date, granularity, filter_type, filter_value):
    """
    获取AWS成本和使用数据
    
    参数:
    - region: AWS区域
    - start_date: 开始日期 (YYYY-MM-DD)
    - end_date: 结束日期 (YYYY-MM-DD)
    - granularity: 粒度 ('DAILY'|'MONTHLY')
    - filter_type: 过滤类型 ('lambda'|'fargate'|'ec2')
    - filter_value: 资源标签值或资源ID
    
    返回:
    - 成本数据 DataFrame
    """
    client = boto3.client('ce', region_name=region)
    
    # 根据过滤类型设置筛选条件
    if filter_type == 'lambda':
        filter_expr = {
            'Dimensions': {
                'Key': 'SERVICE',
                'Values': ['AWS Lambda']
            }
        }
    elif filter_type == 'fargate':
        filter_expr = {
            'Dimensions': {
                'Key': 'SERVICE',
                'Values': ['Amazon Elastic Container Service']
            }
        }
    elif filter_type == 'ec2':
        filter_expr = {
            'Dimensions': {
                'Key': 'SERVICE',
                'Values': ['Amazon Elastic Compute Cloud - Compute']
            }
        }
    else:
        filter_expr = {}
    
    # 添加标签过滤器（如果提供）
    tag_filters = {}
    if filter_value:
        tag_filters = {
            'Tags': {
                'Key': 'Project',
                'Values': [filter_value]
            }
        }
    
    # 合并过滤器
    filters = {}
    if filter_expr and tag_filters:
        filters = {
            'And': [filter_expr, tag_filters]
        }
    elif filter_expr:
        filters = filter_expr
    elif tag_filters:
        filters = tag_filters
    
    try:
        response = client.get_cost_and_usage(
            TimePeriod={
                'Start': start_date,
                'End': end_date
            },
            Granularity=granularity,
            Metrics=['BlendedCost', 'UsageQuantity'],
            GroupBy=[
                {
                    'Type': 'DIMENSION',
                    'Key': 'SERVICE'
                }
            ],
            Filter=filters if filters else None
        )
        
        # 解析响应
        cost_data = []
        for result in response.get('ResultsByTime', []):
            for group in result.get('Groups', []):
                service = group.get('Keys', ['Unknown'])[0]
                metrics = group.get('Metrics', {})
                cost = float(metrics.get('BlendedCost', {}).get('Amount', 0))
                usage = float(metrics.get('UsageQuantity', {}).get('Amount', 0))
                
                cost_data.append({
                    'Date': result.get('TimePeriod', {}).get('Start'),
                    'Service': service,
                    'Cost': cost,
                    'Usage': usage
                })
        
        return pd.DataFrame(cost_data)
    
    except Exception as e:
        print(f"获取成本数据时出错: {str(e)}")
        return pd.DataFrame()

def plot_cost_comparison(lambda_costs, fargate_costs, ec2_costs, output_file):
    """
    绘制成本比较图表
    
    参数:
    - lambda_costs: Lambda成本DataFrame
    - fargate_costs: Fargate成本DataFrame
    - ec2_costs: EC2成本DataFrame
    - output_file: 输出文件
    """
    plt.figure(figsize=(10, 6))
    
    if not lambda_costs.empty:
        lambda_costs_sum = lambda_costs.groupby('Date')['Cost'].sum()
        plt.plot(lambda_costs_sum.index, lambda_costs_sum.values, marker='o', label='Lambda')
    
    if not fargate_costs.empty:
        fargate_costs_sum = fargate_costs.groupby('Date')['Cost'].sum()
        plt.plot(fargate_costs_sum.index, fargate_costs_sum.values, marker='s', label='Fargate')
    
    if not ec2_costs.empty:
        ec2_costs_sum = ec2_costs.groupby('Date')['Cost'].sum()
        plt.plot(ec2_costs_sum.index, ec2_costs_sum.values, marker='^', label='EC2')
    
    plt.title('AWS service cost compare')
    plt.xlabel('date')
    plt.ylabel('cost (USD)')
    plt.grid(True)
    plt.legend()
    plt.xticks(rotation=45)
    plt.tight_layout()
    
    plt.savefig(output_file)
    plt.close()

def generate_cost_report(lambda_costs, fargate_costs, ec2_costs, output_file):
    """
    生成成本报告
    
    参数:
    - lambda_costs: Lambda成本DataFrame
    - fargate_costs: Fargate成本DataFrame
    - ec2_costs: EC2成本DataFrame
    - output_file: 输出文件路径
    """
    # 计算总成本和平均每日成本
    lambda_total = lambda_costs['Cost'].sum() if not lambda_costs.empty else 0
    fargate_total = fargate_costs['Cost'].sum() if not fargate_costs.empty else 0
    ec2_total = ec2_costs['Cost'].sum() if not ec2_costs.empty else 0
    
    lambda_daily_avg = lambda_costs.groupby('Date')['Cost'].sum().mean() if not lambda_costs.empty else 0
    fargate_daily_avg = fargate_costs.groupby('Date')['Cost'].sum().mean() if not fargate_costs.empty else 0
    ec2_daily_avg = ec2_costs.groupby('Date')['Cost'].sum().mean() if not ec2_costs.empty else 0
    
    # 创建比较表格
    cost_table = [
        ["指标", "AWS Lambda", "AWS Fargate", "EC2"],
        ["总成本 (USD)", f"{lambda_total:.2f}", f"{fargate_total:.2f}", f"{ec2_total:.2f}"],
        ["平均每日成本 (USD)", f"{lambda_daily_avg:.2f}", f"{fargate_daily_avg:.2f}", f"{ec2_daily_avg:.2f}"]
    ]
    
    # 写入报告
    with open(output_file, 'w') as f:
        f.write("# AWS无服务器容器成本分析\n\n")
        f.write("## 成本摘要\n\n")
        f.write(tabulate(cost_table, headers="firstrow", tablefmt="pipe"))
        f.write("\n\n")
        
        # 各服务详细成本分析
        f.write("## Lambda成本分析\n\n")
        if not lambda_costs.empty:
            lambda_by_service = lambda_costs.groupby('Service').agg({'Cost': 'sum'}).sort_values('Cost', ascending=False)
            f.write(tabulate([["服务", "成本 (USD)"]] + [[service, f"{cost:.2f}"] for service, cost in zip(lambda_by_service.index, lambda_by_service['Cost'])], headers="firstrow", tablefmt="pipe"))
        else:
            f.write("没有可用的Lambda成本数据\n")
        
        f.write("\n\n## Fargate成本分析\n\n")
        if not fargate_costs.empty:
            fargate_by_service = fargate_costs.groupby('Service').agg({'Cost': 'sum'}).sort_values('Cost', ascending=False)
            f.write(tabulate([["服务", "成本 (USD)"]] + [[service, f"{cost:.2f}"] for service, cost in zip(fargate_by_service.index, fargate_by_service['Cost'])], headers="firstrow", tablefmt="pipe"))
        else:
            f.write("没有可用的Fargate成本数据\n")
        
        f.write("\n\n## EC2成本分析\n\n")
        if not ec2_costs.empty:
            ec2_by_service = ec2_costs.groupby('Service').agg({'Cost': 'sum'}).sort_values('Cost', ascending=False)
            f.write(tabulate([["服务", "成本 (USD)"]] + [[service, f"{cost:.2f}"] for service, cost in zip(ec2_by_service.index, ec2_by_service['Cost'])], headers="firstrow", tablefmt="pipe"))
        else:
            f.write("没有可用的EC2成本数据\n")
        
        # 添加成本优化建议
        f.write("\n\n## 成本优化建议\n\n")
        
        if lambda_daily_avg < fargate_daily_avg and lambda_daily_avg < ec2_daily_avg:
            f.write("1. **AWS Lambda**展现出最低的平均每日成本，适合以下场景：\n")
            f.write("   - 事件驱动型工作负载\n")
            f.write("   - 执行时间短的任务（<15分钟）\n")
            f.write("   - 流量模式不可预测或高度可变的应用\n")
        elif fargate_daily_avg < lambda_daily_avg and fargate_daily_avg < ec2_daily_avg:
            f.write("1. **AWS Fargate**展现出最低的平均每日成本，适合以下场景：\n")
            f.write("   - 中长期运行的服务（>15分钟）\n")
            f.write("   - 需要可预测性能的微服务\n")
            f.write("   - 不需要服务器管理但需要容器级控制的应用\n")
        else:
            f.write("1. **EC2**展现出最低的平均每日成本，适合以下场景：\n")
            f.write("   - 持续运行的工作负载\n")
            f.write("   - 需要专用硬件或特定实例类型的应用\n")
            f.write("   - 高性能计算或内存密集型工作负载\n")
        
        f.write("\n2. 成本优化策略：\n")
        f.write("   - Lambda: 优化内存配置以减少执行时间，为不常用的功能配置缩短超时时间\n")
        f.write("   - Fargate: 优化任务定义中的CPU和内存配置，使用自动扩展策略根据实际需求调整任务数量\n")
        f.write("   - EC2: 考虑使用预留实例或竞价实例降低成本，实现自动扩展以在低使用率时关闭未使用的实例\n")
        
        f.write("\n3. 综合建议：\n")
        if lambda_total < fargate_total and lambda_total < ec2_total:
            f.write("   - 对于本项目的工作负载特性，AWS Lambda提供了最具成本效益的解决方案\n")
        elif fargate_total < lambda_total and fargate_total < ec2_total:
            f.write("   - 对于本项目的工作负载特性，AWS Fargate提供了最具成本效益的解决方案\n")
        else:
            f.write("   - 对于本项目的工作负载特性，EC2提供了最具成本效益的解决方案\n")
        
        f.write("   - 考虑采用混合方法：将事件驱动的组件部署在Lambda上，将长时间运行的服务部署在Fargate上\n")
        f.write("   - 定期监控和审核成本，根据使用模式调整部署策略\n")

def main():
    parser = argparse.ArgumentParser(description='AWS无服务器容器成本分析')
    parser.add_argument('--region', type=str, default='us-east-1', help='AWS区域')
    parser.add_argument('--start-date', type=str, required=True, help='开始日期 (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, required=True, help='结束日期 (YYYY-MM-DD)')
    parser.add_argument('--granularity', type=str, default='DAILY', choices=['DAILY', 'MONTHLY'], help='数据粒度')
    parser.add_argument('--project-tag', type=str, help='项目标签值')
    parser.add_argument('--output-dir', type=str, default='./results', help='输出目录')
    
    args = parser.parse_args()
    
    # 确保输出目录存在
    import os
    os.makedirs(args.output_dir, exist_ok=True)
    
    # 获取成本数据
    print(f"获取Lambda成本数据...")
    lambda_costs = get_cost_and_usage(args.region, args.start_date, args.end_date, args.granularity, 'lambda', args.project_tag)
    
    print(f"获取Fargate成本数据...")
    fargate_costs = get_cost_and_usage(args.region, args.start_date, args.end_date, args.granularity, 'fargate', args.project_tag)
    
    print(f"获取EC2成本数据...")
    ec2_costs = get_cost_and_usage(args.region, args.start_date, args.end_date, args.granularity, 'ec2', args.project_tag)
    
    # 生成成本比较图表
    chart_file = f"{args.output_dir}/cost_comparison.png"
    print(f"生成成本比较图表: {chart_file}")
    plot_cost_comparison(lambda_costs, fargate_costs, ec2_costs, chart_file)
    
    # 生成成本报告
    report_file = f"{args.output_dir}/cost_report.md"
    print(f"生成成本报告: {report_file}")
    generate_cost_report(lambda_costs, fargate_costs, ec2_costs, report_file)
    
    print("完成!")

if __name__ == "__main__":
    main()
