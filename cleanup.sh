#!/bin/bash

# 设置输出目录
OUTPUT_DIR=results

# 加载资源 ID
if [ -f "$OUTPUT_DIR/vpc_id.txt" ]; then
    VPC_ID=$(cat $OUTPUT_DIR/vpc_id.txt)
    echo "正在清理 VPC: $VPC_ID"
else
    echo "找不到 VPC ID 文件"
    exit 1
fi

# 加载其他资源 ID
IGW_ID=$(cat $OUTPUT_DIR/igw_id.txt 2>/dev/null || echo "")
SUBNET_ID_1=$(cat $OUTPUT_DIR/subnet_id_1.txt 2>/dev/null || echo "")
SUBNET_ID_2=$(cat $OUTPUT_DIR/subnet_id_2.txt 2>/dev/null || echo "")
ROUTE_TABLE_ID=$(cat $OUTPUT_DIR/route_table_id.txt 2>/dev/null || echo "")
SG_ID=$(cat $OUTPUT_DIR/sg_id.txt 2>/dev/null || echo "")

# 1. 删除所有相关的 ECS 服务和任务（可能已完成）
echo "确保 ECS 服务和任务已删除..."
aws ecs update-service --cluster serverless-benchmark-cluster --service app-service --desired-count 0 2>/dev/null || true
sleep 10
aws ecs delete-service --cluster serverless-benchmark-cluster --service app-service --force 2>/dev/null || true
aws ecs delete-cluster --cluster serverless-benchmark-cluster 2>/dev/null || true

# 2. 查找并删除相关的 ENI（弹性网络接口）
echo "查找并删除相关的弹性网络接口..."
ENIs=$(aws ec2 describe-network-interfaces --filters "Name=vpc-id,Values=$VPC_ID" --query 'NetworkInterfaces[*].NetworkInterfaceId' --output text)
for eni in $ENIs; do
    echo "正在删除弹性网络接口: $eni"
    aws ec2 delete-network-interface --network-interface-id $eni
done

# 3. 获取并释放 EIP（弹性 IP）
echo "释放相关的弹性 IP 地址..."
EIPs=$(aws ec2 describe-addresses --filters "Name=domain,Values=vpc" --query 'Addresses[*].AllocationId' --output text)
for eip in $EIPs; do
    echo "正在释放弹性 IP: $eip"
    aws ec2 release-address --allocation-id $eip
done

# 4. 确认负载均衡器已删除
echo "确认负载均衡器已删除..."
if [ -f "$OUTPUT_DIR/lb_arn.txt" ]; then
    LOAD_BALANCER_ARN=$(cat $OUTPUT_DIR/lb_arn.txt)
    aws elbv2 delete-load-balancer --load-balancer-arn $LOAD_BALANCER_ARN 2>/dev/null || true
    sleep 30  # 等待负载均衡器删除完成
fi

# 5. 确认监听器已删除
if [ -f "$OUTPUT_DIR/listener_arn.txt" ]; then
    LISTENER_ARN=$(cat $OUTPUT_DIR/listener_arn.txt)
    aws elbv2 delete-listener --listener-arn $LISTENER_ARN 2>/dev/null || true
fi

# 6. 确认目标组已删除
if [ -f "$OUTPUT_DIR/tg_arn.txt" ]; then
    TARGET_GROUP_ARN=$(cat $OUTPUT_DIR/tg_arn.txt)
    aws elbv2 delete-target-group --target-group-arn $TARGET_GROUP_ARN 2>/dev/null || true
fi

# 7. 等待一段时间，确保所有资源释放
echo "等待资源释放 (30秒)..."
sleep 30

# 8. 将互联网网关与 VPC 分离
if [ -n "$IGW_ID" ] && [ -n "$VPC_ID" ]; then
    echo "正在分离互联网网关: $IGW_ID 从 VPC: $VPC_ID"
    aws ec2 detach-internet-gateway --internet-gateway-id $IGW_ID --vpc-id $VPC_ID || true
fi

# 9. 删除互联网网关
if [ -n "$IGW_ID" ]; then
    echo "正在删除互联网网关: $IGW_ID"
    aws ec2 delete-internet-gateway --internet-gateway-id $IGW_ID || true
fi

# 10. 删除子网
if [ -n "$SUBNET_ID_1" ]; then
    echo "正在删除子网 1: $SUBNET_ID_1"
    aws ec2 delete-subnet --subnet-id $SUBNET_ID_1 || true
fi

if [ -n "$SUBNET_ID_2" ]; then
    echo "正在删除子网 2: $SUBNET_ID_2"
    aws ec2 delete-subnet --subnet-id $SUBNET_ID_2 || true
fi

# 11. 删除路由表
if [ -n "$ROUTE_TABLE_ID" ]; then
    echo "正在删除路由表: $ROUTE_TABLE_ID"
    aws ec2 delete-route-table --route-table-id $ROUTE_TABLE_ID || true
fi

# 12. 删除安全组
if [ -n "$SG_ID" ]; then
    echo "正在删除安全组: $SG_ID"
    aws ec2 delete-security-group --group-id $SG_ID || true
fi

# 13. 删除 VPC
if [ -n "$VPC_ID" ]; then
    echo "正在删除 VPC: $VPC_ID"
    aws ec2 delete-vpc --vpc-id $VPC_ID || true
fi

echo "VPC 清理操作完成"
