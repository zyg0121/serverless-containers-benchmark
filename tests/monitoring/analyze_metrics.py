import json
import pandas as pd
import matplotlib.pyplot as plt
import argparse
import os
from tabulate import tabulate

def process_jmeter_results(jtl_file):
    """
    处理JMeter结果文件并计算关键指标
    
    参数:
    - jtl_file: JMeter JTL结果文件
    
    返回:
    - metrics: 包含计算指标的字典
    """
    try:
        # 读取JTL文件 (CSV格式)
        df = pd.read_csv(jtl_file, sep=',')
        
        # 计算关键指标
        metrics = {
            'samples': len(df),
            'avg_response_time': df['elapsed'].mean(),
            'min_response_time': df['elapsed'].min(),
            'max_response_time': df['elapsed'].max(),
            'median_response_time': df['elapsed'].median(),
            'p90_response_time': df['elapsed'].quantile(0.90),
            'p95_response_time': df['elapsed'].quantile(0.95),
            'p99_response_time': df['elapsed'].quantile(0.99),
            'error_rate': (df['success'] == False).mean() * 100,
            'throughput': len(df) / (df['timeStamp'].max() - df['timeStamp'].min()) * 1000 if len(df) > 1 else 0
        }
        
        return metrics
    except Exception as e:
        print(f"处理JMeter结果文件时出错: {str(e)}")
        return {
            'samples': 0,
            'avg_response_time': 0,
            'min_response_time': 0,
            'max_response_time': 0,
            'median_response_time': 0,
            'p90_response_time': 0,
            'p95_response_time': 0,
            'p99_response_time': 0,
            'error_rate': 0,
            'throughput': 0
        }

def load_cloudwatch_metrics(metrics_files):
    """
    加载CloudWatch指标数据
    
    参数:
    - metrics_files: 包含指标文件路径的字典
    
    返回:
    - metrics: 指标数据字典
    """
    metrics = {}
    
    for metric_name, file_path in metrics_files.items():
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                metrics[metric_name] = data
        except Exception as e:
            print(f"加载指标文件 {file_path} 时出错: {str(e)}")
    
    return metrics

def generate_comparison_report(lambda_jmeter, fargate_jmeter, lambda_metrics, fargate_metrics, output_file):
    """
    生成性能比较报告
    
    参数:
    - lambda_jmeter: Lambda JMeter指标
    - fargate_jmeter: Fargate JMeter指标
    - lambda_metrics: Lambda CloudWatch指标
    - fargate_metrics: Fargate CloudWatch指标
    - output_file: 输出文件路径
    """
    # 提取Lambda和Fargate的CloudWatch指标
    lambda_duration = extract_metric_stats(lambda_metrics, 'lambda_duration')
    lambda_invocations = extract_metric_stats(lambda_metrics, 'lambda_invocations')
    lambda_errors = extract_metric_stats(lambda_metrics, 'lambda_errors')
    
    fargate_cpu = extract_metric_stats(fargate_metrics, 'fargate_cpu')
    fargate_memory = extract_metric_stats(fargate_metrics, 'fargate_memory')
    
    # 计算错误率
    lambda_error_rate = calculate_error_rate(lambda_invocations, lambda_errors)
    
    # 创建比较表格
    jmeter_table = [
        ["指标", "AWS Lambda", "AWS Fargate", "差异 (Lambda - Fargate)"],
        ["平均响应时间 (ms)", f"{lambda_jmeter['avg_response_time']:.2f}", f"{fargate_jmeter['avg_response_time']:.2f}", f"{lambda_jmeter['avg_response_time'] - fargate_jmeter['avg_response_time']:.2f}"],
        ["最小响应时间 (ms)", f"{lambda_jmeter['min_response_time']:.2f}", f"{fargate_jmeter['min_response_time']:.2f}", f"{lambda_jmeter['min_response_time'] - fargate_jmeter['min_response_time']:.2f}"],
        ["最大响应时间 (ms)", f"{lambda_jmeter['max_response_time']:.2f}", f"{fargate_jmeter['max_response_time']:.2f}", f"{lambda_jmeter['max_response_time'] - fargate_jmeter['max_response_time']:.2f}"],
        ["中位数响应时间 (ms)", f"{lambda_jmeter['median_response_time']:.2f}", f"{fargate_jmeter['median_response_time']:.2f}", f"{lambda_jmeter['median_response_time'] - fargate_jmeter['median_response_time']:.2f}"],
        ["90百分位响应时间 (ms)", f"{lambda_jmeter['p90_response_time']:.2f}", f"{fargate_jmeter['p90_response_time']:.2f}", f"{lambda_jmeter['p90_response_time'] - fargate_jmeter['p90_response_time']:.2f}"],
        ["95百分位响应时间 (ms)", f"{lambda_jmeter['p95_response_time']:.2f}", f"{fargate_jmeter['p95_response_time']:.2f}", f"{lambda_jmeter['p95_response_time'] - fargate_jmeter['p95_response_time']:.2f}"],
        ["99百分位响应时间 (ms)", f"{lambda_jmeter['p99_response_time']:.2f}", f"{fargate_jmeter['p99_response_time']:.2f}", f"{lambda_jmeter['p99_response_time'] - fargate_jmeter['p99_response_time']:.2f}"],
        ["吞吐量 (请求/秒)", f"{lambda_jmeter['throughput']:.2f}", f"{fargate_jmeter['throughput']:.2f}", f"{lambda_jmeter['throughput'] - fargate_jmeter['throughput']:.2f}"],
        ["错误率 (%)", f"{lambda_jmeter['error_rate']:.2f}", f"{fargate_jmeter['error_rate']:.2f}", f"{lambda_jmeter['error_rate'] - fargate_jmeter['error_rate']:.2f}"],
    ]
    
    cloudwatch_table = [
        ["指标", "AWS Lambda", "AWS Fargate"],
        ["平均执行时间 (ms)", f"{lambda_duration['avg']:.2f}", "N/A"],
        ["平均CPU使用率 (%)", "N/A", f"{fargate_cpu['avg']:.2f}"],
        ["平均内存使用率 (%)", "N/A", f"{fargate_memory['avg']:.2f}"],
        ["最大执行时间 (ms)", f"{lambda_duration['max']:.2f}", "N/A"],
        ["最大CPU使用率 (%)", "N/A", f"{fargate_cpu['max']:.2f}"],
        ["最大内存使用率 (%)", "N/A", f"{fargate_memory['max']:.2f}"],
        ["调用次数", f"{lambda_invocations['sum']:.0f}", "N/A"],
        ["错误率 (%)", f"{lambda_error_rate:.2f}", "N/A"],
    ]
    
    # 写入报告文件
    with open(output_file, 'w') as f:
        f.write("# AWS无服务器容器性能比较报告\n\n")
        
        f.write("## JMeter负载测试结果\n\n")
        f.write(tabulate(jmeter_table, headers="firstrow", tablefmt="pipe"))
        f.write("\n\n")
        
        f.write("## CloudWatch指标\n\n")
        f.write(tabulate(cloudwatch_table, headers="firstrow", tablefmt="pipe"))
        f.write("\n\n")
        
        # 添加结论和分析
        f.write("## 性能分析\n\n")
        
        # 响应时间比较
        if lambda_jmeter['avg_response_time'] < fargate_jmeter['avg_response_time']:
            f.write("### 响应时间\n\n")
            f.write("AWS Lambda在平均响应时间方面**优于** AWS Fargate，")
            f.write(f"平均响应时间分别为 {lambda_jmeter['avg_response_time']:.2f} ms 和 {fargate_jmeter['avg_response_time']:.2f} ms。")
            f.write(f" Lambda比Fargate快 {fargate_jmeter['avg_response_time'] - lambda_jmeter['avg_response_time']:.2f} ms ({((fargate_jmeter['avg_response_time'] - lambda_jmeter['avg_response_time']) / fargate_jmeter['avg_response_time'] * 100):.1f}%)。\n\n")
        else:
            f.write("### 响应时间\n\n")
            f.write("AWS Fargate在平均响应时间方面**优于** AWS Lambda，")
            f.write(f"平均响应时间分别为 {fargate_jmeter['avg_response_time']:.2f} ms 和 {lambda_jmeter['avg_response_time']:.2f} ms。")
            f.write(f" Fargate比Lambda快 {lambda_jmeter['avg_response_time'] - fargate_jmeter['avg_response_time']:.2f} ms ({((lambda_jmeter['avg_response_time'] - fargate_jmeter['avg_response_time']) / lambda_jmeter['avg_response_time'] * 100):.1f}%)。\n\n")
        
        # 吞吐量比较
        if lambda_jmeter['throughput'] > fargate_jmeter['throughput']:
            f.write("### 吞吐量\n\n")
            f.write("AWS Lambda在吞吐量方面**优于** AWS Fargate，")
            f.write(f"吞吐量分别为 {lambda_jmeter['throughput']:.2f} 请求/秒 和 {fargate_jmeter['throughput']:.2f} 请求/秒。")
            f.write(f" Lambda的吞吐量比Fargate高 {lambda_jmeter['throughput'] - fargate_jmeter['throughput']:.2f} 请求/秒 ({((lambda_jmeter['throughput'] - fargate_jmeter['throughput']) / fargate_jmeter['throughput'] * 100):.1f}%)。\n\n")
        else:
            f.write("### 吞吐量\n\n")
            f.write("AWS Fargate在吞吐量方面**优于** AWS Lambda，")
            f.write(f"吞吐量分别为 {fargate_jmeter['throughput']:.2f} 请求/秒 和 {lambda_jmeter['throughput']:.2f} 请求/秒。")
            f.write(f" Fargate的吞吐量比Lambda高 {fargate_jmeter['throughput'] - lambda_jmeter['throughput']:.2f} 请求/秒 ({((fargate_jmeter['throughput'] - lambda_jmeter['throughput']) / lambda_jmeter['throughput'] * 100):.1f}%)。\n\n")
        
        # 错误率比较
        if lambda_jmeter['error_rate'] < fargate_jmeter['error_rate']:
            f.write("### 错误率\n\n")
            f.write("AWS Lambda在错误率方面**优于** AWS Fargate，")
            f.write(f"错误率分别为 {lambda_jmeter['error_rate']:.2f}% 和 {fargate_jmeter['error_rate']:.2f}%。\n\n")
        else:
            f.write("### 错误率\n\n")
            f.write("AWS Fargate在错误率方面**优于** AWS Lambda，")
            f.write(f"错误率分别为 {fargate_jmeter['error_rate']:.2f}% 和 {lambda_jmeter['error_rate']:.2f}%。\n\n")
        
        # 资源利用率
        f.write("### 资源利用率\n\n")
        f.write(f"AWS Lambda的平均执行时间为 {lambda_duration['avg']:.2f} ms。\n\n")
        f.write(f"AWS Fargate的平均CPU使用率为 {fargate_cpu['avg']:.2f}%，平均内存使用率为 {fargate_memory['avg']:.2f}%。\n\n")
        
        # 综合评估
        f.write("## 总结与建议\n\n")
        
        if lambda_jmeter['avg_response_time'] < fargate_jmeter['avg_response_time'] and lambda_jmeter['throughput'] > fargate_jmeter['throughput']:
            f.write("基于测试结果，**AWS Lambda** 在响应时间和吞吐量方面整体表现优于 AWS Fargate，特别适合于：\n\n")
            f.write("- 对响应时间要求较高的API和微服务\n")
            f.write("- 需要处理突发流量的场景\n")
            f.write("- 短时运行的任务和函数\n\n")
        elif fargate_jmeter['avg_response_time'] < lambda_jmeter['avg_response_time'] and fargate_jmeter['throughput'] > lambda_jmeter['throughput']:
            f.write("基于测试结果，**AWS Fargate** 在响应时间和吞吐量方面整体表现优于 AWS Lambda，特别适合于：\n\n")
            f.write("- 需要持续运行的容器化服务\n")
            f.write("- 对稳定性要求高的工作负载\n")
            f.write("- 需要更细粒度资源控制的应用\n\n")
        else:
            f.write("基于测试结果，AWS Lambda和AWS Fargate各有优势：\n\n")
            
            if lambda_jmeter['avg_response_time'] < fargate_jmeter['avg_response_time']:
                f.write("- **AWS Lambda** 在响应时间方面表现更好，适合于对延迟敏感的应用\n")
            else:
                f.write("- **AWS Fargate** 在响应时间方面表现更好，适合于需要稳定响应时间的应用\n")
            
            if lambda_jmeter['throughput'] > fargate_jmeter['throughput']:
                f.write("- **AWS Lambda** 在吞吐量方面表现更好，适合于需要处理大量请求的场景\n")
            else:
                f.write("- **AWS Fargate** 在吞吐量方面表现更好，适合于需要持续高吞吐量的场景\n")
        
        f.write("\n### 优化建议\n\n")
        f.write("#### AWS Lambda\n")
        f.write("- 优化内存配置以提高性能\n")
        f.write("- 考虑使用预置并发来减少冷启动延迟\n")
        f.write("- 优化代码和依赖项以减少初始化时间\n\n")
        
        f.write("#### AWS Fargate\n")
        f.write("- 优化容器镜像大小以加快启动时间\n")
        f.write("- 调整CPU和内存配置以适应工作负载特性\n")
        f.write("- 实现自动扩展以处理变化的流量模式\n\n")
        
        f.write("建议根据应用的具体需求和特性选择最适合的服务，或者在同一应用中结合使用两种服务，以发挥各自的优势。\n")

def extract_metric_stats(metrics, metric_name):
    """
    从CloudWatch指标提取统计数据
    
    参数:
    - metrics: 指标数据字典
    - metric_name: 指标名称
    
    返回:
    - stats: 统计数据
    """
    stats = {'min': 0, 'max': 0, 'avg': 0, 'sum': 0}
    
    if metric_name not in metrics:
        return stats
    
    try:
        data = metrics[metric_name]
        datapoints = data.get('Datapoints', [])
        
        if not datapoints:
            return stats
        
        values = []
        for dp in datapoints:
            if 'Average' in dp:
                values.append(dp['Average'])
            elif 'Sum' in dp:
                stats['sum'] += dp['Sum']
            elif 'Maximum' in dp:
                values.append(dp['Maximum'])
        
        if values:
            stats['min'] = min(values)
            stats['max'] = max(values)
            stats['avg'] = sum(values) / len(values)
        
        return stats
    except Exception as e:
        print(f"提取指标 {metric_name} 的统计数据时出错: {str(e)}")
        return stats

def calculate_error_rate(invocations, errors):
    """
    计算错误率
    
    参数:
    - invocations: 调用指标
    - errors: 错误指标
    
    返回:
    - error_rate: 错误率百分比
    """
    try:
        total_invocations = invocations.get('sum', 0)
        total_errors = errors.get('sum', 0)
        
        if total_invocations == 0:
            return 0
        
        return (total_errors / total_invocations) * 100
    except Exception as e:
        print(f"计算错误率时出错: {str(e)}")
        return 0

def plot_comparison_charts(lambda_jmeter, fargate_jmeter, output_dir):
    """
    绘制性能比较图表
    
    参数:
    - lambda_jmeter: Lambda JMeter指标
    - fargate_jmeter: Fargate JMeter指标
    - output_dir: 输出目录
    """
    # 响应时间比较
    plt.figure(figsize=(10, 6))
    
    metrics = ['avg_response_time', 'median_response_time', 'p95_response_time', 'p99_response_time']
    labels = ['avg_response_time', 'median_response_time', 'p95_response_time', 'p99_response_time']
    
    lambda_values = [lambda_jmeter[m] for m in metrics]
    fargate_values = [fargate_jmeter[m] for m in metrics]
    
    x = range(len(metrics))
    width = 0.35
    
    plt.bar([i - width/2 for i in x], lambda_values, width, label='AWS Lambda')
    plt.bar([i + width/2 for i in x], fargate_values, width, label='AWS Fargate')
    
    plt.ylabel('response_time(ms)')
    plt.title('Lambda vs Fargate response time compare')
    plt.xticks(x, labels)
    plt.legend()
    plt.grid(axis='y', linestyle='--', alpha=0.7)
    
    plt.savefig(f"{output_dir}/response_time_comparison.png")
    plt.close()
    
    # 吞吐量和错误率比较
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    
    # 吞吐量
    ax1.bar(['AWS Lambda', 'AWS Fargate'], [lambda_jmeter['throughput'], fargate_jmeter['throughput']])
    ax1.set_ylabel('request/s')
    ax1.set_title('compare request')
    ax1.grid(axis='y', linestyle='--', alpha=0.7)
    
    # 错误率
    ax2.bar(['AWS Lambda', 'AWS Fargate'], [lambda_jmeter['error_rate'], fargate_jmeter['error_rate']])
    ax2.set_ylabel('error rate(%)')
    ax2.set_title('compare with error rate')
    ax2.grid(axis='y', linestyle='--', alpha=0.7)
    
    plt.tight_layout()
    plt.savefig(f"{output_dir}/throughput_error_comparison.png")
    plt.close()

def main():
    parser = argparse.ArgumentParser(description='分析AWS无服务器容器性能指标')
    parser.add_argument('--output-dir', type=str, default='./results', help='输出目录')
    parser.add_argument('--lambda-jtl', type=str, help='Lambda JMeter JTL结果文件')
    parser.add_argument('--fargate-jtl', type=str, help='Fargate JMeter JTL结果文件')
    
    args = parser.parse_args()
    
    # 确保输出目录存在
    os.makedirs(args.output_dir, exist_ok=True)
    
    # 自动查找JTL文件（如果未指定）
    if not args.lambda_jtl:
        lambda_jtl = os.path.join(args.output_dir, 'lambda_results.jtl')
        if not os.path.exists(lambda_jtl):
            lambda_jtl = None
    else:
        lambda_jtl = args.lambda_jtl
    
    if not args.fargate_jtl:
        fargate_jtl = os.path.join(args.output_dir, 'fargate_results.jtl')
        if not os.path.exists(fargate_jtl):
            fargate_jtl = None
    else:
        fargate_jtl = args.fargate_jtl
    
    # 处理JMeter结果
    lambda_jmeter = {}
    fargate_jmeter = {}
    
    if lambda_jtl:
        print(f"处理Lambda JMeter结果: {lambda_jtl}")
        lambda_jmeter = process_jmeter_results(lambda_jtl)
    else:
        print("未找到Lambda JMeter结果文件，使用默认值")
        lambda_jmeter = {
            'samples': 0,
            'avg_response_time': 0,
            'min_response_time': 0,
            'max_response_time': 0,
            'median_response_time': 0,
            'p90_response_time': 0,
            'p95_response_time': 0,
            'p99_response_time': 0,
            'error_rate': 0,
            'throughput': 0
        }
    
    if fargate_jtl:
        print(f"处理Fargate JMeter结果: {fargate_jtl}")
        fargate_jmeter = process_jmeter_results(fargate_jtl)
    else:
        print("未找到Fargate JMeter结果文件，使用默认值")
        fargate_jmeter = {
            'samples': 0,
            'avg_response_time': 0,
            'min_response_time': 0,
            'max_response_time': 0,
            'median_response_time': 0,
            'p90_response_time': 0,
            'p95_response_time': 0,
            'p99_response_time': 0,
            'error_rate': 0,
            'throughput': 0
        }
    
    # 查找CloudWatch指标文件
    lambda_metrics_files = {
        'lambda_duration': os.path.join(args.output_dir, 'lambda_duration.json'),
        'lambda_invocations': os.path.join(args.output_dir, 'lambda_invocations.json'),
        'lambda_errors': os.path.join(args.output_dir, 'lambda_errors.json')
    }
    
    fargate_metrics_files = {
        'fargate_cpu': os.path.join(args.output_dir, 'fargate_cpu.json'),
        'fargate_memory': os.path.join(args.output_dir, 'fargate_memory.json')
    }
    
    # 加载CloudWatch指标
    print("加载CloudWatch指标...")
    lambda_metrics = load_cloudwatch_metrics(lambda_metrics_files)
    fargate_metrics = load_cloudwatch_metrics(fargate_metrics_files)
    
    # 绘制比较图表
    print("生成比较图表...")
    plot_comparison_charts(lambda_jmeter, fargate_jmeter, args.output_dir)
    
    # 生成比较报告
    report_file = os.path.join(args.output_dir, 'performance_analysis.md')
    print(f"生成性能分析报告: {report_file}")
    generate_comparison_report(lambda_jmeter, fargate_jmeter, lambda_metrics, fargate_metrics, report_file)
    
    print("分析完成!")

if __name__ == "__main__":
    main()
