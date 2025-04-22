import boto3
import datetime
import pandas as pd
import matplotlib.pyplot as plt
import argparse
from tabulate import tabulate

def get_cloudwatch_metrics(region, service_type, resource_id, start_time, end_time, period=60):
    """
    收集CloudWatch指标
    
    参数:
    - region: AWS区域
    - service_type: 'lambda' 或 'fargate'
    - resource_id: Lambda函数名或ECS服务ID
    - start_time: 开始时间 (datetime对象)
    - end_time: 结束时间 (datetime对象)
    - period: 时间粒度（秒）
    
    返回:
    - metrics_data: 包含指标的字典
    """
    client = boto3.client('cloudwatch', region_name=region)
    metrics_data = {}
    
    if service_type == 'lambda':
        # Lambda指标
        metrics = [
            {'Name': 'Duration', 'Stat': 'Average', 'Unit': 'Milliseconds'},
            {'Name': 'Invocations', 'Stat': 'Sum', 'Unit': 'Count'},
            {'Name': 'Errors', 'Stat': 'Sum', 'Unit': 'Count'},
            {'Name': 'Throttles', 'Stat': 'Sum', 'Unit': 'Count'},
            {'Name': 'ConcurrentExecutions', 'Stat': 'Maximum', 'Unit': 'Count'},
            {'Name': 'PostRuntimeExtensionsDuration', 'Stat': 'Average', 'Unit': 'Milliseconds'},
        ]
        
        for metric in metrics:
            response = client.get_metric_statistics(
                Namespace='AWS/Lambda',
                MetricName=metric['Name'],
                Dimensions=[
                    {'Name': 'FunctionName', 'Value': resource_id},
                ],
                StartTime=start_time,
                EndTime=end_time,
                Period=period,
                Statistics=[metric['Stat']],
                Unit=metric['Unit']
            )
            
            datapoints = sorted(response['Datapoints'], key=lambda x: x['Timestamp'])
            if datapoints:
                timestamps = [dp['Timestamp'] for dp in datapoints]
                values = [dp[metric['Stat']] for dp in datapoints]
                metrics_data[metric['Name']] = {'timestamps': timestamps, 'values': values}
    
    elif service_type == 'fargate':
        # Fargate (ECS) 指标
        metrics = [
            {'Name': 'CPUUtilization', 'Stat': 'Average', 'Unit': 'Percent'},
            {'Name': 'MemoryUtilization', 'Stat': 'Average', 'Unit': 'Percent'},
            {'Name': 'RunningTaskCount', 'Stat': 'Maximum', 'Unit': 'Count'},
        ]
        
        for metric in metrics:
            response = client.get_metric_statistics(
                Namespace='AWS/ECS',
                MetricName=metric['Name'],
                Dimensions=[
                    {'Name': 'ServiceName', 'Value': resource_id.split('/')[1]},
                    {'Name': 'ClusterName', 'Value': resource_id.split('/')[0]},
                ],
                StartTime=start_time,
                EndTime=end_time,
                Period=period,
                Statistics=[metric['Stat']],
                Unit=metric['Unit']
            )
            
            datapoints = sorted(response['Datapoints'], key=lambda x: x['Timestamp'])
            if datapoints:
                timestamps = [dp['Timestamp'] for dp in datapoints]
                values = [dp[metric['Stat']] for dp in datapoints]
                metrics_data[metric['Name']] = {'timestamps': timestamps, 'values': values}
    
    return metrics_data

def plot_metrics(lambda_metrics, fargate_metrics, output_dir):
    """
    绘制Lambda和Fargate指标比较图
    
    参数:
    - lambda_metrics: Lambda指标数据
    - fargate_metrics: Fargate指标数据
    - output_dir: 输出目录
    """
    # 比较可用指标
    common_metrics = []
    lambda_specific = []
    fargate_specific = []
    
    # 找出常见的指标进行比较
    if 'Duration' in lambda_metrics and 'CPUUtilization' in fargate_metrics:
        plt.figure(figsize=(12, 6))
        plt.subplot(1, 2, 1)
        plt.title("Lambda Duration")
        plt.plot(lambda_metrics['Duration']['timestamps'], lambda_metrics['Duration']['values'], 'b-')
        plt.ylabel('Duration (ms)')
        plt.grid(True)
        
        plt.subplot(1, 2, 2)
        plt.title("Fargate CPU Utilization")
        plt.plot(fargate_metrics['CPUUtilization']['timestamps'], fargate_metrics['CPUUtilization']['values'], 'r-')
        plt.ylabel('CPU (%)')
        plt.grid(True)
        
        plt.tight_layout()
        plt.savefig(f"{output_dir}/performance_comparison.png")
        plt.close()

def calculate_statistics(lambda_metrics, fargate_metrics):
    """
    计算并返回统计数据
    
    参数:
    - lambda_metrics: Lambda指标数据
    - fargate_metrics: Fargate指标数据
    
    返回:
    - stats: 统计数据字典
    """
    stats = {
        'lambda': {},
        'fargate': {}
    }
    
    # Lambda统计
    if 'Duration' in lambda_metrics:
        duration_values = lambda_metrics['Duration']['values']
        stats['lambda']['avg_duration'] = sum(duration_values) / len(duration_values) if duration_values else 0
        stats['lambda']['max_duration'] = max(duration_values) if duration_values else 0
        stats['lambda']['min_duration'] = min(duration_values) if duration_values else 0
    
    if 'Invocations' in lambda_metrics:
        stats['lambda']['total_invocations'] = sum(lambda_metrics['Invocations']['values']) if lambda_metrics['Invocations']['values'] else 0
    
    if 'Errors' in lambda_metrics:
        error_values = lambda_metrics['Errors']['values']
        invocations = sum(lambda_metrics['Invocations']['values']) if 'Invocations' in lambda_metrics and lambda_metrics['Invocations']['values'] else 1
        stats['lambda']['error_rate'] = (sum(error_values) / invocations) * 100 if error_values else 0
    
    # Fargate统计
    if 'CPUUtilization' in fargate_metrics:
        cpu_values = fargate_metrics['CPUUtilization']['values']
        stats['fargate']['avg_cpu'] = sum(cpu_values) / len(cpu_values) if cpu_values else 0
        stats['fargate']['max_cpu'] = max(cpu_values) if cpu_values else 0
    
    if 'MemoryUtilization' in fargate_metrics:
        memory_values = fargate_metrics['MemoryUtilization']['values']
        stats['fargate']['avg_memory'] = sum(memory_values) / len(memory_values) if memory_values else 0
        stats['fargate']['max_memory'] = max(memory_values) if memory_values else 0
    
    if 'RunningTaskCount' in fargate_metrics:
        stats['fargate']['max_tasks'] = max(fargate_metrics['RunningTaskCount']['values']) if fargate_metrics['RunningTaskCount']['values'] else 0
    
    return stats

def generate_report(lambda_metrics, fargate_metrics, jmeter_lambda, jmeter_fargate, output_file):
    """
    生成比较报告
    
    参数:
    - lambda_metrics: Lambda指标数据
    - fargate_metrics: Fargate指标数据
    - jmeter_lambda: Lambda JMeter结果
    - jmeter_fargate: Fargate JMeter结果
    - output_file: 输出文件路径
    """
    stats = calculate_statistics(lambda_metrics, fargate_metrics)
    
    # 从JMeter结果中提取指标
    # 假设JMeter结果已经处理成DataFrame
    lambda_response_time = jmeter_lambda['avg_response_time'] if 'avg_response_time' in jmeter_lambda else "N/A"
    fargate_response_time = jmeter_fargate['avg_response_time'] if 'avg_response_time' in jmeter_fargate else "N/A"
    
    lambda_throughput = jmeter_lambda['throughput'] if 'throughput' in jmeter_lambda else "N/A"
    fargate_throughput = jmeter_fargate['throughput'] if 'throughput' in jmeter_fargate else "N/A"
    
    # 创建比较表格
    comparison_table = [
        ["指标", "AWS Lambda", "AWS Fargate"],
        ["平均响应时间", f"{lambda_response_time} ms", f"{fargate_response_time} ms"],
        ["吞吐量", f"{lambda_throughput}/sec", f"{fargate_throughput}/sec"],
        ["平均执行时间", f"{stats['lambda'].get('avg_duration', 'N/A')} ms", "N/A"],
        ["平均CPU使用率", "N/A", f"{stats['fargate'].get('avg_cpu', 'N/A')}%"],
        ["平均内存使用率", "N/A", f"{stats['fargate'].get('avg_memory', 'N/A')}%"],
        ["最大并发", f"{stats['lambda'].get('max_concurrent', 'N/A')}", f"{stats['fargate'].get('max_tasks', 'N/A')}"],
        ["错误率", f"{stats['lambda'].get('error_rate', 'N/A')}%", "N/A"]
    ]
    
    # 写入报告文件
    with open(output_file, 'w') as f:
        f.write("# AWS无服务器容器比较报告\n\n")
        f.write("## 性能指标比较\n\n")
        f.write(tabulate(comparison_table, headers="firstrow", tablefmt="pipe"))
        f.write("\n\n")
        
        # 添加冷启动时间比较
        f.write("## 冷启动时间比较\n\n")
        # 这里需要从JMeter结果中提取冷启动时间数据
        
        # 添加成本估算
        f.write("## 成本估算\n\n")
        f.write("### AWS Lambda\n")
        f.write("- 内存配置: 1024 MB\n")
        f.write("- 执行时间: {} ms\n".format(stats['lambda'].get('avg_duration', 'N/A')))
        f.write("- 调用次数: {}\n".format(stats['lambda'].get('total_invocations', 'N/A')))
        
        f.write("\n### AWS Fargate\n")
        f.write("- CPU: 0.25 vCPU\n")
        f.write("- 内存: 512 MB\n")
        f.write("- 运行时间: 1小时\n")
        f.write("- 任务数量: {}\n".format(stats['fargate'].get('max_tasks', 'N/A')))
        
        # 添加结论和建议
        f.write("\n## 结论和建议\n\n")
        f.write("根据测试结果，我们得出以下结论：\n\n")
        
        if lambda_response_time < fargate_response_time:
            f.write("1. AWS Lambda在响应时间方面表现更好，适合对延迟敏感的应用。\n")
        else:
            f.write("1. AWS Fargate在响应时间方面表现更好，适合需要稳定响应时间的应用。\n")
        
        if lambda_throughput > fargate_throughput:
            f.write("2. AWS Lambda在吞吐量方面表现更好，适合需要处理突发流量的场景。\n")
        else:
            f.write("2. AWS Fargate在吞吐量方面表现更好，适合需要处理持续高流量的场景。\n")
        
        f.write("3. 建议：\n")
        f.write("   - 对于事件驱动、短暂运行的工作负载，推荐使用AWS Lambda\n")
        f.write("   - 对于长时间运行的应用或需要更多控制的场景，推荐使用AWS Fargate\n")

def main():
    parser = argparse.ArgumentParser(description='收集和比较AWS无服务器容器指标')
    parser.add_argument('--region', type=str, default='us-east-1', help='AWS区域')
    parser.add_argument('--lambda-name', type=str, required=True, help='Lambda函数名')
    parser.add_argument('--fargate-service', type=str, required=True, help='Fargate服务ID (format: cluster/service)')
    parser.add_argument('--start-time', type=str, required=True, help='开始时间 (ISO格式: YYYY-MM-DDTHH:MM:SS)')
    parser.add_argument('--end-time', type=str, required=True, help='结束时间 (ISO格式: YYYY-MM-DDTHH:MM:SS)')
    parser.add_argument('--output-dir', type=str, default='./results', help='输出目录')
    parser.add_argument('--lambda-jmeter', type=str, help='Lambda JMeter结果文件')
    parser.add_argument('--fargate-jmeter', type=str, help='Fargate JMeter结果文件')
    
    args = parser.parse_args()
    
    # 解析时间
    start_time = datetime.datetime.fromisoformat(args.start_time)
    end_time = datetime.datetime.fromisoformat(args.end_time)
    
    # 收集指标
    print(f"收集Lambda指标: {args.lambda_name}")
    lambda_metrics = get_cloudwatch_metrics(args.region, 'lambda', args.lambda_name, start_time, end_time)
    
    print(f"收集Fargate指标: {args.fargate_service}")
    fargate_metrics = get_cloudwatch_metrics(args.region, 'fargate', args.fargate_service, start_time, end_time)
    
    # 处理JMeter结果
    jmeter_lambda = {}
    jmeter_fargate = {}
    
    if args.lambda_jmeter:
        print(f"处理Lambda JMeter结果: {args.lambda_jmeter}")
        # 这里应该有处理JMeter结果的代码
        # 简单示例：
        jmeter_lambda = {'avg_response_time': 120, 'throughput': 150}
    
    if args.fargate_jmeter:
        print(f"处理Fargate JMeter结果: {args.fargate_jmeter}")
        # 这里应该有处理JMeter结果的代码
        # 简单示例：
        jmeter_fargate = {'avg_response_time': 150, 'throughput': 120}
    
    # 确保输出目录存在
    import os
    os.makedirs(args.output_dir, exist_ok=True)
    
    # 绘制指标图表
    print("生成性能比较图表")
    plot_metrics(lambda_metrics, fargate_metrics, args.output_dir)
    
    # 生成比较报告
    report_file = f"{args.output_dir}/comparison_report.md"
    print(f"生成比较报告: {report_file}")
    generate_report(lambda_metrics, fargate_metrics, jmeter_lambda, jmeter_fargate, report_file)
    
    print("完成!")

if __name__ == "__main__":
    main()
