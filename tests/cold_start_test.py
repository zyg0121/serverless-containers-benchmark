import boto3
import json
import time
import argparse
import matplotlib.pyplot as plt
import pandas as pd
import requests
from datetime import datetime, timedelta
from tabulate import tabulate
import os
import numpy as np
from concurrent.futures import ThreadPoolExecutor

def invoke_lambda_function(function_name, payload=None):
    """
    调用Lambda函数并测量响应时间
    
    参数:
    - function_name: Lambda函数名
    - payload: 调用负载 (dict)
    
    返回:
    - elapsed: 响应时间 (ms)
    - status_code: HTTP状态码
    """
    client = boto3.client('lambda')
    start_time = time.time()
    
    try:
        response = client.invoke(
            FunctionName=function_name,
            InvocationType='RequestResponse',
            Payload=json.dumps(payload or {})
        )
        status_code = response['StatusCode']
        response_payload = json.loads(response['Payload'].read())
    except Exception as e:
        print(f"Lambda调用错误: {str(e)}")
        return None, None
    
    elapsed = (time.time() - start_time) * 1000  # 毫秒
    return elapsed, status_code

def invoke_api(url, method='GET', payload=None):
    """
    调用API并测量响应时间
    
    参数:
    - url: API URL
    - method: HTTP方法
    - payload: 请求正文 (dict)
    
    返回:
    - elapsed: 响应时间 (ms)
    - status_code: HTTP状态码
    """
    headers = {'Content-Type': 'application/json'}
    
    try:
        start_time = time.time()
        if method.upper() == 'GET':
            response = requests.get(url, headers=headers, timeout=10)
        else:
            response = requests.post(url, headers=headers, json=payload or {}, timeout=10)
        
        elapsed = (time.time() - start_time) * 1000  # 毫秒
        return elapsed, response.status_code
    
    except Exception as e:
        print(f"API调用错误: {str(e)}")
        return None, None

def measure_cold_start(target_type, target, iterations=10, idle_time=300, payload=None, method='GET'):
    """
    测量冷启动时间
    
    参数:
    - target_type: 'lambda' 或 'api'
    - target: Lambda函数名或API URL
    - iterations: 测试迭代次数
    - idle_time: 空闲时间 (秒)
    - payload: 请求负载
    - method: HTTP方法 (针对API)
    
    返回:
    - results: 包含测量结果的列表
    """
    results = []
    
    print(f"开始{target_type}冷启动测量 ({iterations}次迭代, {idle_time}秒间隔)")
    
    for i in range(iterations):
        print(f"迭代 {i+1}/{iterations}")
        
        # 执行调用并测量
        if target_type == 'lambda':
            elapsed, status_code = invoke_lambda_function(target, payload)
        else:  # api
            elapsed, status_code = invoke_api(target, method, payload)
        
        if elapsed is not None:
            results.append({
                'iteration': i + 1,
                'elapsed_time': elapsed,
                'status_code': status_code,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            print(f"响应时间: {elapsed:.2f} ms, 状态码: {status_code}")
        
        # 等待足够长的时间以确保函数被回收
        if i < iterations - 1:
            print(f"等待{idle_time}秒...")
            time.sleep(idle_time)
    
    return results

def measure_warm_start(target_type, target, iterations=10, delay=1, payload=None, method='GET'):
    """
    测量预热启动时间
    
    参数:
    - target_type: 'lambda' 或 'api'
    - target: Lambda函数名或API URL
    - iterations: 测试迭代次数
    - delay: 调用之间的延迟 (秒)
    - payload: 请求负载
    - method: HTTP方法 (针对API)
    
    返回:
    - results: 包含测量结果的列表
    """
    results = []
    
    print(f"开始{target_type}预热启动测量 ({iterations}次迭代, {delay}秒间隔)")
    
    # 先进行一次预热调用
    if target_type == 'lambda':
        _, _ = invoke_lambda_function(target, payload)
    else:  # api
        _, _ = invoke_api(target, method, payload)
    
    time.sleep(1)  # 短暂等待
    
    for i in range(iterations):
        print(f"迭代 {i+1}/{iterations}")
        
        # 执行调用并测量
        if target_type == 'lambda':
            elapsed, status_code = invoke_lambda_function(target, payload)
        else:  # api
            elapsed, status_code = invoke_api(target, method, payload)
        
        if elapsed is not None:
            results.append({
                'iteration': i + 1,
                'elapsed_time': elapsed,
                'status_code': status_code,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            print(f"响应时间: {elapsed:.2f} ms, 状态码: {status_code}")
        
        # 短暂延迟以避免限流
        if i < iterations - 1:
            time.sleep(delay)
    
    return results

def plot_comparison(lambda_cold_results, lambda_warm_results, 
                    fargate_cold_results, fargate_warm_results, output_file):
    """
    绘制冷启动和预热启动时间比较图表
    
    参数:
    - lambda_cold_results: Lambda冷启动结果
    - lambda_warm_results: Lambda预热启动结果
    - fargate_cold_results: Fargate冷启动结果
    - fargate_warm_results: Fargate预热启动结果
    - output_file: 输出文件路径
    """
    plt.figure(figsize=(12, 8))
    
    # 提取响应时间数据
    lambda_cold_times = [r['elapsed_time'] for r in lambda_cold_results]
    lambda_warm_times = [r['elapsed_time'] for r in lambda_warm_results]
    fargate_cold_times = [r['elapsed_time'] for r in fargate_cold_results]
    fargate_warm_times = [r['elapsed_time'] for r in fargate_warm_results]
    
    # 确保 x 和 y 的长度一致
    iterations_lambda_cold = list(range(1, len(lambda_cold_times) + 1))
    iterations_lambda_warm = list(range(1, len(lambda_warm_times) + 1))
    iterations_fargate_cold = list(range(1, len(fargate_cold_times) + 1))
    iterations_fargate_warm = list(range(1, len(fargate_warm_times) + 1))
    
    # 绘制冷启动和预热启动时间趋势线
    plt.plot(iterations_lambda_cold, lambda_cold_times, 'bo-', label='Lambda Cold Start')
    plt.plot(iterations_lambda_warm, lambda_warm_times, 'go-', label='Lambda Warm Start')
    plt.plot(iterations_fargate_cold, fargate_cold_times, 'ro-', label='Fargate Cold Start')
    plt.plot(iterations_fargate_warm, fargate_warm_times, 'mo-', label='Fargate Warm Start')
    
    # 图表设置
    plt.title('Cold Start vs Warm Start Response Times')
    plt.xlabel('Iteration')
    plt.ylabel('Response Time (ms)')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    
    # 保存图表
    plt.savefig(output_file)
    plt.close()

def generate_report(lambda_cold_results, lambda_warm_results, 
                   fargate_cold_results, fargate_warm_results, output_file):
    """
    生成冷启动时间报告
    
    参数:
    - lambda_cold_results: Lambda冷启动结果
    - lambda_warm_results: Lambda预热启动结果
    - fargate_cold_results: Fargate冷启动结果
    - fargate_warm_results: Fargate预热启动结果
    - output_file: 输出文件路径
    """
    # 计算统计数据
    def get_stats(results):
        if not results:
            return {'min': 0, 'max': 0, 'mean': 0, 'median': 0, 'p95': 0, 'p99': 0, 'std': 0}
        
        times = [r['elapsed_time'] for r in results]
        return {
            'min': np.min(times),
            'max': np.max(times),
            'mean': np.mean(times),
            'median': np.median(times),
            'p95': np.percentile(times, 95),
            'p99': np.percentile(times, 99),
            'std': np.std(times)
        }
    
    lambda_cold_stats = get_stats(lambda_cold_results)
    lambda_warm_stats = get_stats(lambda_warm_results)
    fargate_cold_stats = get_stats(fargate_cold_results)
    fargate_warm_stats = get_stats(fargate_warm_results)
    
    # 创建比较表格
    stats_table = [
        ["统计量", "Lambda 冷启动", "Lambda 预热启动", "Fargate 冷启动", "Fargate 预热启动"],
        ["最小值 (ms)", f"{lambda_cold_stats['min']:.2f}", f"{lambda_warm_stats['min']:.2f}", f"{fargate_cold_stats['min']:.2f}", f"{fargate_warm_stats['min']:.2f}"],
        ["最大值 (ms)", f"{lambda_cold_stats['max']:.2f}", f"{lambda_warm_stats['max']:.2f}", f"{fargate_cold_stats['max']:.2f}", f"{fargate_warm_stats['max']:.2f}"],
        ["平均值 (ms)", f"{lambda_cold_stats['mean']:.2f}", f"{lambda_warm_stats['mean']:.2f}", f"{fargate_cold_stats['mean']:.2f}", f"{fargate_warm_stats['mean']:.2f}"],
        ["中位数 (ms)", f"{lambda_cold_stats['median']:.2f}", f"{lambda_warm_stats['median']:.2f}", f"{fargate_cold_stats['median']:.2f}", f"{fargate_warm_stats['median']:.2f}"],
        ["95百分位 (ms)", f"{lambda_cold_stats['p95']:.2f}", f"{lambda_warm_stats['p95']:.2f}", f"{fargate_cold_stats['p95']:.2f}", f"{fargate_warm_stats['p95']:.2f}"],
        ["99百分位 (ms)", f"{lambda_cold_stats['p99']:.2f}", f"{lambda_warm_stats['p99']:.2f}", f"{fargate_cold_stats['p99']:.2f}", f"{fargate_warm_stats['p99']:.2f}"],
        ["标准差", f"{lambda_cold_stats['std']:.2f}", f"{lambda_warm_stats['std']:.2f}", f"{fargate_cold_stats['std']:.2f}", f"{fargate_warm_stats['std']:.2f}"]
    ]
    
    # 计算冷启动开销
    lambda_overhead = lambda_cold_stats['mean'] - lambda_warm_stats['mean']
    fargate_overhead = fargate_cold_stats['mean'] - fargate_warm_stats['mean']
    
    # 写入报告
    with open(output_file, 'w') as f:
        f.write("# AWS无服务器容器冷启动时间分析\n\n")
        f.write("## 启动时间统计\n\n")
        f.write(tabulate(stats_table, headers="firstrow", tablefmt="pipe"))
        f.write("\n\n")
        
        f.write("## 冷启动开销\n\n")
        f.write(f"- Lambda冷启动开销: **{lambda_overhead:.2f} ms** (相对于预热启动)\n")
        f.write(f"- Fargate冷启动开销: **{fargate_overhead:.2f} ms** (相对于预热启动)\n")
        
        # 添加比较结论
        f.write("\n## 启动时间比较分析\n\n")
        
        if lambda_cold_stats['mean'] < fargate_cold_stats['mean']:
            f.write("- Lambda在冷启动性能方面**优于**Fargate\n")
        else:
            f.write("- Fargate在冷启动性能方面**优于**Lambda\n")
        
        if lambda_warm_stats['mean'] < fargate_warm_stats['mean']:
            f.write("- Lambda在预热启动性能方面**优于**Fargate\n")
        else:
            f.write("- Fargate在预热启动性能方面**优于**Lambda\n")
        
        # 稳定性分析
        lambda_cold_variability = lambda_cold_stats['std'] / lambda_cold_stats['mean'] * 100
        fargate_cold_variability = fargate_cold_stats['std'] / fargate_cold_stats['mean'] * 100
        
        f.write("\n## 启动时间稳定性分析\n\n")
        f.write(f"- Lambda冷启动变异系数: **{lambda_cold_variability:.2f}%**\n")
        f.write(f"- Fargate冷启动变异系数: **{fargate_cold_variability:.2f}%**\n")
        
        if lambda_cold_variability < fargate_cold_variability:
            f.write("- Lambda的冷启动时间**更稳定**\n")
        else:
            f.write("- Fargate的冷启动时间**更稳定**\n")
        
        # 建议和最佳实践
        f.write("\n## 建议和最佳实践\n\n")
        f.write("### Lambda\n")
        f.write("- 优化代码初始化以减少冷启动时间\n")
        f.write("- 考虑使用预置并发以消除冷启动延迟\n")
        f.write("- 监控并优化依赖项加载\n")
        
        f.write("\n### Fargate\n")
        f.write("- 使用较小的容器镜像以加快启动\n")
        f.write("- 优化应用程序初始化逻辑\n")
        f.write("- 为高峰期提前扩展服务\n")
        
        f.write("\n### 一般建议\n")
        if lambda_cold_stats['mean'] < fargate_cold_stats['mean']:
            f.write("- 对于对延迟敏感的应用，选择Lambda并使用预置并发\n")
            f.write("- 对于可以接受较长冷启动但需要更长运行时间的应用，选择Fargate\n")
        else:
            f.write("- 对于需要快速冷启动的应用，选择Fargate\n")
            f.write("- 对于短期运行且功能执行时间短的任务，选择Lambda\n")

def main():
    parser = argparse.ArgumentParser(description='AWS无服务器容器冷启动测试')
    parser.add_argument('--lambda-function', type=str, help='Lambda函数名')
    parser.add_argument('--lambda-payload', type=str, help='Lambda函数负载 (JSON)')
    parser.add_argument('--fargate-url', type=str, help='Fargate API URL')
    parser.add_argument('--fargate-method', type=str, default='GET', choices=['GET', 'POST'], help='Fargate API方法')
    parser.add_argument('--fargate-payload', type=str, help='Fargate API负载 (JSON)')
    parser.add_argument('--cold-iterations', type=int, default=10, help='冷启动测试迭代次数')
    parser.add_argument('--warm-iterations', type=int, default=10, help='预热启动测试迭代次数')
    parser.add_argument('--idle-time', type=int, default=300, help='冷启动测试的空闲时间(秒)')
    parser.add_argument('--warm-delay', type=int, default=2, help='预热测试的调用延迟(秒)')
    parser.add_argument('--output-dir', type=str, default='./results', help='输出目录')
    
    args = parser.parse_args()
    
    # 确保输出目录存在
    os.makedirs(args.output_dir, exist_ok=True)
    
    lambda_cold_results = []
    lambda_warm_results = []
    fargate_cold_results = []
    fargate_warm_results = []
    
    # 解析JSON负载
    lambda_payload = json.loads(args.lambda_payload) if args.lambda_payload else None
    fargate_payload = json.loads(args.fargate_payload) if args.fargate_payload else None
    
    # 执行Lambda测试
    if args.lambda_function:
        print("开始Lambda冷启动测试...")
        lambda_cold_results = measure_cold_start(
            'lambda', args.lambda_function, args.cold_iterations, args.idle_time, lambda_payload
        )
        
        print("\n开始Lambda预热启动测试...")
        lambda_warm_results = measure_warm_start(
            'lambda', args.lambda_function, args.warm_iterations, args.warm_delay, lambda_payload
        )
    
    # 执行Fargate测试
    if args.fargate_url:
        print("\n开始Fargate冷启动测试...")
        fargate_cold_results = measure_cold_start(
            'api', args.fargate_url, args.cold_iterations, args.idle_time, 
            fargate_payload, args.fargate_method
        )
        
        print("\n开始Fargate预热启动测试...")
        fargate_warm_results = measure_warm_start(
            'api', args.fargate_url, args.warm_iterations, args.warm_delay,
            fargate_payload, args.fargate_method
        )
    
    # 绘制比较图表
    chart_file = f"{args.output_dir}/cold_start_comparison.png"
    print(f"\n生成比较图表: {chart_file}")
    plot_comparison(
        lambda_cold_results, lambda_warm_results, 
        fargate_cold_results, fargate_warm_results,
        chart_file
    )
    
    # 生成报告
    report_file = f"{args.output_dir}/cold_start_report.md"
    print(f"生成冷启动报告: {report_file}")
    generate_report(
        lambda_cold_results, lambda_warm_results,
        fargate_cold_results, fargate_warm_results,
        report_file
    )
    
    print("完成!")

if __name__ == "__main__":
    main()