#!/bin/bash

# AWS无服务器Docker容器基准测试脚本

# 设置MongoDB连接字符串
if [ -z "$MONGODB_URI" ]; then
    echo "请设置MONGODB_URI环境变量"
    exit 1
fi

# 设置区域
export AWS_REGION=${AWS_REGION:-us-east-1}
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export OUTPUT_DIR=./results

mkdir -p $OUTPUT_DIR

# 步骤1: 部署Lambda
deploy_lambda() {
    echo "====== 部署Lambda ======"
    
    # 创建ECR仓库
    export ECR_REPO_NAME=serverless-benchmark-lambda
    
    aws ecr create-repository \
        --repository-name $ECR_REPO_NAME \
        --region $AWS_REGION
    
    # 登录ECR
    aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
    
    # 构建Docker镜像
    echo "构建Docker镜像..."
    cd src
    docker build -t serverless-benchmark .
    cd ..
    
    # 标记和推送镜像
    docker tag serverless-benchmark:latest $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO_NAME:latest
    docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO_NAME:latest
    
    # 创建IAM角色
    echo "创建Lambda执行角色..."
    aws iam create-role \
        --role-name lambda-execution-role \
        --assume-role-policy-document '{
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }]
        }'
    
    # 附加Lambda执行策略
    aws iam attach-role-policy \
        --role-name lambda-execution-role \
        --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
    
    # 等待角色传播
    echo "等待IAM角色传播 (10秒)..."
    sleep 10
    
    export LAMBDA_ROLE_ARN=$(aws iam get-role --role-name lambda-execution-role --query Role.Arn --output text)
    
    # 创建Lambda函数
    echo "创建Lambda函数..."
    aws lambda create-function \
        --function-name serverless-benchmark-function \
        --package-type Image \
        --code ImageUri=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO_NAME:latest \
        --role $LAMBDA_ROLE_ARN \
        --timeout 30 \
        --memory-size 1024 \
        --environment Variables="{MONGODB_URI=$MONGODB_URI,NODE_ENV=production}"
    
    # 创建API Gateway
    echo "创建API Gateway..."
    export API_ID=$(aws apigatewayv2 create-api \
        --name serverless-api-gateway \
        --protocol-type HTTP \
        --target arn:aws:lambda:$AWS_REGION:$AWS_ACCOUNT_ID:function:serverless-benchmark-function \
        --query ApiId \
        --output text)
    
    # 创建API阶段
    aws apigatewayv2 create-stage \
        --api-id $API_ID \
        --stage-name prod \
        --auto-deploy
    
    # 获取API URL
    export LAMBDA_API_URL=$(aws apigatewayv2 get-api --api-id $API_ID --query 'ApiEndpoint' --output text)
    
    # 添加Lambda权限
    aws lambda add-permission \
        --function-name serverless-benchmark-function \
        --statement-id apigateway-invoke \
        --action lambda:InvokeFunction \
        --principal apigateway.amazonaws.com \
        --source-arn "arn:aws:execute-api:$AWS_REGION:$AWS_ACCOUNT_ID:$API_ID/*/*"
    
    echo "Lambda API URL: $LAMBDA_API_URL"
    echo $LAMBDA_API_URL > $OUTPUT_DIR/lambda_api_url.txt
}

# 步骤2: 部署Fargate
deploy_fargate() {
    echo "====== 部署Fargate ======"
    
    # 创建ECR仓库
    export FARGATE_REPO_NAME=serverless-benchmark-fargate
    
    aws ecr create-repository \
        --repository-name $FARGATE_REPO_NAME \
        --region $AWS_REGION
    
    # 标记和推送镜像
    aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
    docker tag serverless-benchmark:latest $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$FARGATE_REPO_NAME:latest
    docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$FARGATE_REPO_NAME:latest
    
    # 创建VPC和网络组件
    echo "创建VPC和网络组件..."
    export VPC_ID=$(aws ec2 create-vpc \
        --cidr-block 10.0.0.0/16 \
        --query Vpc.VpcId \
        --output text)
    
    aws ec2 modify-vpc-attribute \
        --vpc-id $VPC_ID \
        --enable-dns-support
    aws ec2 modify-vpc-attribute \
        --vpc-id $VPC_ID \
        --enable-dns-hostnames
    
    # 子网
    export SUBNET_ID_1=$(aws ec2 create-subnet \
        --vpc-id $VPC_ID \
        --cidr-block 10.0.1.0/24 \
        --availability-zone ${AWS_REGION}a \
        --query Subnet.SubnetId \
        --output text)
    
    export SUBNET_ID_2=$(aws ec2 create-subnet \
        --vpc-id $VPC_ID \
        --cidr-block 10.0.2.0/24 \
        --availability-zone ${AWS_REGION}b \
        --query Subnet.SubnetId \
        --output text)
    
    # 互联网网关
    export IGW_ID=$(aws ec2 create-internet-gateway \
        --query InternetGateway.InternetGatewayId \
        --output text)
    
    aws ec2 attach-internet-gateway \
        --vpc-id $VPC_ID \
        --internet-gateway-id $IGW_ID
    
    # 路由表
    export ROUTE_TABLE_ID=$(aws ec2 create-route-table \
        --vpc-id $VPC_ID \
        --query RouteTable.RouteTableId \
        --output text)
    
    aws ec2 create-route \
        --route-table-id $ROUTE_TABLE_ID \
        --destination-cidr-block 0.0.0.0/0 \
        --gateway-id $IGW_ID
    
    aws ec2 associate-route-table \
        --subnet-id $SUBNET_ID_1 \
        --route-table-id $ROUTE_TABLE_ID
    
    aws ec2 associate-route-table \
        --subnet-id $SUBNET_ID_2 \
        --route-table-id $ROUTE_TABLE_ID
    
    # 配置子网自动分配公网IP
    aws ec2 modify-subnet-attribute \
        --subnet-id $SUBNET_ID_1 \
        --map-public-ip-on-launch
    
    aws ec2 modify-subnet-attribute \
        --subnet-id $SUBNET_ID_2 \
        --map-public-ip-on-launch
    
    # 安全组
    export SG_ID=$(aws ec2 create-security-group \
        --group-name serverless-benchmark-sg \
        --description "Security group for serverless benchmark app" \
        --vpc-id $VPC_ID \
        --query GroupId \
        --output text)
    
    aws ec2 authorize-security-group-ingress \
        --group-id $SG_ID \
        --protocol tcp \
        --port 3000 \
        --cidr 0.0.0.0/0
    
    aws ec2 authorize-security-group-egress \
        --group-id $SG_ID \
        --protocol -1 \
        --port -1 \
        --cidr 0.0.0.0/0
    
    # 创建ECS集群
    echo "创建ECS集群..."
    aws ecs create-cluster \
        --cluster-name serverless-benchmark-cluster
    
    # 创建任务执行角色
    echo "创建ECS任务执行角色..."
    aws iam create-role \
        --role-name ecsTaskExecutionRole \
        --assume-role-policy-document '{
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }]
        }'
    
    aws iam attach-role-policy \
        --role-name ecsTaskExecutionRole \
        --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
    
    # 等待角色传播
    echo "等待IAM角色传播 (10秒)..."
    sleep 10
    
    export ECS_EXECUTION_ROLE_ARN=$(aws iam get-role --role-name ecsTaskExecutionRole --query Role.Arn --output text)
    
    # 创建日志组
    aws logs create-log-group \
        --log-group-name /ecs/serverless-benchmark
    
    # 创建任务定义
    echo "创建ECS任务定义..."
    cat > task-definition.json << EOF
{
    "family": "serverless-benchmark",
    "networkMode": "awsvpc",
    "requiresCompatibilities": ["FARGATE"],
    "executionRoleArn": "${ECS_EXECUTION_ROLE_ARN}",
    "cpu": "256",
    "memory": "512",
    "containerDefinitions": [
        {
            "name": "app",
            "image": "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${FARGATE_REPO_NAME}:latest",
            "essential": true,
            "portMappings": [
                {
                    "containerPort": 3000,
                    "hostPort": 3000,
                    "protocol": "tcp"
                }
            ],
            "environment": [
                {
                    "name": "MONGODB_URI",
                    "value": "${MONGODB_URI}"
                },
                {
                    "name": "NODE_ENV",
                    "value": "production"
                }
            ],
            "logConfiguration": {
                "logDriver": "awslogs",
                "options": {
                    "awslogs-group": "/ecs/serverless-benchmark",
                    "awslogs-region": "${AWS_REGION}",
                    "awslogs-stream-prefix": "ecs"
                }
            }
        }
    ]
}
EOF
    
    aws ecs register-task-definition \
        --cli-input-json file://task-definition.json
    
    # 创建负载均衡器
    echo "创建负载均衡器..."
    export LOAD_BALANCER_ARN=$(aws elbv2 create-load-balancer \
        --name serverless-benchmark-lb \
        --subnets $SUBNET_ID_1 $SUBNET_ID_2 \
        --security-groups $SG_ID \
        --query LoadBalancers[0].LoadBalancerArn \
        --output text)
    
    export TARGET_GROUP_ARN=$(aws elbv2 create-target-group \
        --name serverless-benchmark-tg \
        --protocol HTTP \
        --port 3000 \
        --vpc-id $VPC_ID \
        --target-type ip \
        --health-check-path "/api/health" \
        --health-check-interval-seconds 30 \
        --health-check-timeout-seconds 5 \
        --healthy-threshold-count 3 \
        --unhealthy-threshold-count 3 \
        --query TargetGroups[0].TargetGroupArn \
        --output text)
    
    export LISTENER_ARN=$(aws elbv2 create-listener \
        --load-balancer-arn $LOAD_BALANCER_ARN \
        --protocol HTTP \
        --port 80 \
        --default-actions Type=forward,TargetGroupArn=$TARGET_GROUP_ARN \
        --query Listeners[0].ListenerArn \
        --output text)
    
    # 等待负载均衡器创建完成
    echo "等待负载均衡器变为可用 (30秒)..."
    sleep 30
    
    # 获取负载均衡器DNS名称
    export FARGATE_URL=$(aws elbv2 describe-load-balancers \
        --load-balancer-arns $LOAD_BALANCER_ARN \
        --query LoadBalancers[0].DNSName \
        --output text)
    
    # 创建ECS服务
    echo "创建ECS服务..."
    aws ecs create-service \
        --cluster serverless-benchmark-cluster \
        --service-name app-service \
        --task-definition serverless-benchmark \
        --desired-count 2 \
        --launch-type FARGATE \
        --platform-version LATEST \
        --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_ID_1,$SUBNET_ID_2],securityGroups=[$SG_ID],assignPublicIp=ENABLED}" \
        --load-balancers "targetGroupArn=$TARGET_GROUP_ARN,containerName=app,containerPort=3000"
    
    # 创建自动扩展
    echo "配置自动扩展..."
    aws application-autoscaling register-scalable-target \
        --service-namespace ecs \
        --resource-id service/serverless-benchmark-cluster/app-service \
        --scalable-dimension ecs:service:DesiredCount \
        --min-capacity 1 \
        --max-capacity 10
    
    aws application-autoscaling put-scaling-policy \
        --service-namespace ecs \
        --resource-id service/serverless-benchmark-cluster/app-service \
        --scalable-dimension ecs:service:DesiredCount \
        --policy-name cpu-scale-policy \
        --policy-type TargetTrackingScaling \
        --target-tracking-scaling-policy-configuration '{
            "TargetValue": 70.0,
            "PredefinedMetricSpecification": {
                "PredefinedMetricType": "ECSServiceAverageCPUUtilization"
            },
            "ScaleInCooldown": 300,
            "ScaleOutCooldown": 60
        }'
    
    echo "Fargate URL: http://$FARGATE_URL"
    echo "http://$FARGATE_URL" > $OUTPUT_DIR/fargate_url.txt
    
    # 保存资源IDs用于清理
    echo $VPC_ID > $OUTPUT_DIR/vpc_id.txt
    echo $SUBNET_ID_1 > $OUTPUT_DIR/subnet_id_1.txt
    echo $SUBNET_ID_2 > $OUTPUT_DIR/subnet_id_2.txt
    echo $IGW_ID > $OUTPUT_DIR/igw_id.txt
    echo $ROUTE_TABLE_ID > $OUTPUT_DIR/route_table_id.txt
    echo $SG_ID > $OUTPUT_DIR/sg_id.txt
    echo $LOAD_BALANCER_ARN > $OUTPUT_DIR/lb_arn.txt
    echo $TARGET_GROUP_ARN > $OUTPUT_DIR/tg_arn.txt
    echo $LISTENER_ARN > $OUTPUT_DIR/listener_arn.txt
}

# 步骤3: 运行测试
run_tests() {
    echo "====== 运行测试 ======"
    
    # 加载端点URLs
    if [ -f "$OUTPUT_DIR/lambda_api_url.txt" ]; then
        LAMBDA_API_URL=$(cat $OUTPUT_DIR/lambda_api_url.txt)
    else
        echo "找不到Lambda API URL。请先运行部署步骤。"
        exit 1
    fi
    
    if [ -f "$OUTPUT_DIR/fargate_url.txt" ]; then
        FARGATE_URL=$(cat $OUTPUT_DIR/fargate_url.txt)
    else
        echo "找不到Fargate URL。请先运行部署步骤。"
        exit 1
    fi
    
    # 设置测试开始时间
    START_TIME=$(date -u +"%Y-%m-%dT%H:%M:%S")
    
    # 等待服务完全启动
    echo "等待服务完全启动 (60秒)..."
    sleep 60
    
    # 运行冷启动测试
    echo "运行冷启动测试..."
    python tests/cold_start_test.py \
        --lambda-function serverless-benchmark-function \
        --lambda-payload '{"path": "/api/health", "httpMethod": "GET"}' \
        --fargate-url "${FARGATE_URL}/api/health" \
        --cold-iterations 5 \
        --warm-iterations 10 \
        --idle-time 180 \
        --output-dir $OUTPUT_DIR
    
    # 运行JMeter负载测试
    echo "运行Lambda JMeter测试..."
    jmeter -n -t tests/jmeter/load_test.jmx \
        -Jhost=$(echo $LAMBDA_API_URL | sed 's/https:\/\///') \
        -Jpath="" \
        -l $OUTPUT_DIR/lambda_results.jtl \
        -j $OUTPUT_DIR/lambda_jmeter.log
    
    echo "等待系统冷却 (60秒)..."
    sleep 60
    
    echo "运行Fargate JMeter测试..."
    jmeter -n -t tests/jmeter/load_test.jmx \
        -Jhost=$(echo $FARGATE_URL | sed 's/http:\/\///') \
        -Jpath="/api" \
        -l $OUTPUT_DIR/fargate_results.jtl \
        -j $OUTPUT_DIR/fargate_jmeter.log
    
    # 设置测试结束时间
    END_TIME=$(date -u +"%Y-%m-%dT%H:%M:%S")
    
    # 保存测试时间范围用于指标收集
    cat > $OUTPUT_DIR/test_timerange.json << EOF
{
    "start_time": "$START_TIME",
    "end_time": "$END_TIME"
}
EOF
    
    echo "测试完成。结果保存在 $OUTPUT_DIR 目录中"
}

# 步骤4: 收集和分析指标
collect_metrics() {
    echo "====== 收集和分析指标 ======"
    
    # 获取测试时间范围
    if [ -f "$OUTPUT_DIR/test_timerange.json" ]; then
        START_TIME=$(jq -r .start_time $OUTPUT_DIR/test_timerange.json)
        END_TIME=$(jq -r .end_time $OUTPUT_DIR/test_timerange.json)
    else
        # 如果找不到时间范围文件，使用当前时间向前推1小时
        END_TIME=$(date -u +"%Y-%m-%dT%H:%M:%S")
        START_TIME=$(date -u -d '1 hour ago' +"%Y-%m-%dT%H:%M:%S")
    fi
    
    # 收集Lambda指标
    echo "收集Lambda指标..."
    aws cloudwatch get-metric-statistics \
        --namespace AWS/Lambda \
        --metric-name Duration \
        --dimensions Name=FunctionName,Value=serverless-benchmark-function \
        --start-time $START_TIME \
        --end-time $END_TIME \
        --period 60 \
        --statistics Average \
        > $OUTPUT_DIR/lambda_duration.json
    
    aws cloudwatch get-metric-statistics \
        --namespace AWS/Lambda \
        --metric-name Invocations \
        --dimensions Name=FunctionName,Value=serverless-benchmark-function \
        --start-time $START_TIME \
        --end-time $END_TIME \
        --period 60 \
        --statistics Sum \
        > $OUTPUT_DIR/lambda_invocations.json
    
    aws cloudwatch get-metric-statistics \
        --namespace AWS/Lambda \
        --metric-name Errors \
        --dimensions Name=FunctionName,Value=serverless-benchmark-function \
        --start-time $START_TIME \
        --end-time $END_TIME \
        --period 60 \
        --statistics Sum \
        > $OUTPUT_DIR/lambda_errors.json
    
    # 收集Fargate指标
    echo "收集Fargate指标..."
    aws cloudwatch get-metric-statistics \
        --namespace AWS/ECS \
        --metric-name CPUUtilization \
        --dimensions Name=ServiceName,Value=app-service Name=ClusterName,Value=serverless-benchmark-cluster \
        --start-time $START_TIME \
        --end-time $END_TIME \
        --period 60 \
        --statistics Average \
        > $OUTPUT_DIR/fargate_cpu.json
    
    aws cloudwatch get-metric-statistics \
        --namespace AWS/ECS \
        --metric-name MemoryUtilization \
        --dimensions Name=ServiceName,Value=app-service Name=ClusterName,Value=serverless-benchmark-cluster \
        --start-time $START_TIME \
        --end-time $END_TIME \
        --period 60 \
        --statistics Average \
        > $OUTPUT_DIR/fargate_memory.json
    
    # 获取成本数据
    echo "获取成本数据..."
    START_DATE=$(date -u -d '30 days ago' +"%Y-%m-%d")
    END_DATE=$(date -u +"%Y-%m-%d")
    
    aws ce get-cost-and-usage \
        --time-period Start=$START_DATE,End=$END_DATE \
        --granularity DAILY \
        --metrics BlendedCost UsageQuantity \
        --group-by Type=DIMENSION,Key=SERVICE \
        --filter '{"Dimensions": {"Key": "SERVICE", "Values": ["AWS Lambda"]}}' \
        > $OUTPUT_DIR/lambda_cost.json
    
    aws ce get-cost-and-usage \
        --time-period Start=$START_DATE,End=$END_DATE \
        --granularity DAILY \
        --metrics BlendedCost UsageQuantity \
        --group-by Type=DIMENSION,Key=SERVICE \
        --filter '{"Dimensions": {"Key": "SERVICE", "Values": ["Amazon Elastic Container Service"]}}' \
        > $OUTPUT_DIR/fargate_cost.json
    
    aws ce get-cost-and-usage \
        --time-period Start=$START_DATE,End=$END_DATE \
        --granularity DAILY \
        --metrics BlendedCost UsageQuantity \
        --group-by Type=DIMENSION,Key=SERVICE \
        --filter '{"Dimensions": {"Key": "SERVICE", "Values": ["Amazon Elastic Compute Cloud - Compute"]}}' \
        > $OUTPUT_DIR/ec2_cost.json
    
    echo "指标和成本数据收集完成。数据保存在 $OUTPUT_DIR 目录中"
    
    # 运行指标分析脚本
    echo "运行指标分析脚本..."
    python tests/monitoring/analyze_metrics.py --output-dir $OUTPUT_DIR
}

# 步骤5: 清理资源
cleanup_resources() {
    echo "====== 清理资源 ======"
    
    # 删除Lambda资源
    echo "清理Lambda资源..."
    aws lambda delete-function --function-name serverless-benchmark-function
    
    if [ -f "$OUTPUT_DIR/lambda_api_url.txt" ]; then
        API_ID=$(aws apigatewayv2 get-apis --query 'Items[?Name==`serverless-api-gateway`].ApiId' --output text)
        if [ ! -z "$API_ID" ]; then
            aws apigatewayv2 delete-api --api-id $API_ID
        fi
    fi
    
    aws ecr delete-repository \
        --repository-name serverless-benchmark-lambda \
        --force
    
    # 删除ECS服务
    echo "清理ECS服务..."
    aws ecs update-service \
        --cluster serverless-benchmark-cluster \
        --service app-service \
        --desired-count 0
    
    # 等待服务缩减到零
    echo "等待服务缩减到零 (30秒)..."
    sleep 30
    
    aws ecs delete-service \
        --cluster serverless-benchmark-cluster \
        --service app-service \
        --force
    
    aws ecs delete-cluster --cluster serverless-benchmark-cluster
    
    aws ecr delete-repository \
        --repository-name serverless-benchmark-fargate \
        --force
    
    # 删除负载均衡器资源
    echo "清理负载均衡器资源..."
    if [ -f "$OUTPUT_DIR/listener_arn.txt" ]; then
        LISTENER_ARN=$(cat $OUTPUT_DIR/listener_arn.txt)
        aws elbv2 delete-listener --listener-arn $LISTENER_ARN
    fi
    
    if [ -f "$OUTPUT_DIR/lb_arn.txt" ]; then
        LOAD_BALANCER_ARN=$(cat $OUTPUT_DIR/lb_arn.txt)
        aws elbv2 delete-load-balancer --load-balancer-arn $LOAD_BALANCER_ARN
    fi
    
    # 等待负载均衡器删除完成
    echo "等待负载均衡器删除完成 (30秒)..."
    sleep 30
    
    if [ -f "$OUTPUT_DIR/tg_arn.txt" ]; then
        TARGET_GROUP_ARN=$(cat $OUTPUT_DIR/tg_arn.txt)
        aws elbv2 delete-target-group --target-group-arn $TARGET_GROUP_ARN
    fi
    
    # 删除网络资源
    echo "清理网络资源..."
    if [ -f "$OUTPUT_DIR/igw_id.txt" ] && [ -f "$OUTPUT_DIR/vpc_id.txt" ]; then
        IGW_ID=$(cat $OUTPUT_DIR/igw_id.txt)
        VPC_ID=$(cat $OUTPUT_DIR/vpc_id.txt)
        aws ec2 detach-internet-gateway --internet-gateway-id $IGW_ID --vpc-id $VPC_ID
        aws ec2 delete-internet-gateway --internet-gateway-id $IGW_ID
    fi
    
    if [ -f "$OUTPUT_DIR/subnet_id_1.txt" ]; then
        SUBNET_ID_1=$(cat $OUTPUT_DIR/subnet_id_1.txt)
        aws ec2 delete-subnet --subnet-id $SUBNET_ID_1
    fi
    
    if [ -f "$OUTPUT_DIR/subnet_id_2.txt" ]; then
        SUBNET_ID_2=$(cat $OUTPUT_DIR/subnet_id_2.txt)
        aws ec2 delete-subnet --subnet-id $SUBNET_ID_2
    fi
    
    if [ -f "$OUTPUT_DIR/route_table_id.txt" ]; then
        ROUTE_TABLE_ID=$(cat $OUTPUT_DIR/route_table_id.txt)
        aws ec2 delete-route-table --route-table-id $ROUTE_TABLE_ID
    fi
    
    if [ -f "$OUTPUT_DIR/sg_id.txt" ]; then
        SG_ID=$(cat $OUTPUT_DIR/sg_id.txt)
        aws ec2 delete-security-group --group-id $SG_ID
    fi
    
    if [ -f "$OUTPUT_DIR/vpc_id.txt" ]; then
        VPC_ID=$(cat $OUTPUT_DIR/vpc_id.txt)
        aws ec2 delete-vpc --vpc-id $VPC_ID
    fi
    
    # 删除IAM角色
    echo "清理IAM资源..."
    aws iam detach-role-policy \
        --role-name lambda-execution-role \
        --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
    
    aws iam delete-role --role-name lambda-execution-role
    
    aws iam detach-role-policy \
        --role-name ecsTaskExecutionRole \
        --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
    
    aws iam delete-role --role-name ecsTaskExecutionRole
    
    # 删除CloudWatch日志组
    echo "清理CloudWatch资源..."
    aws logs delete-log-group --log-group-name /ecs/serverless-benchmark
    
    echo "资源清理完成。"
}

# 显示帮助信息
show_help() {
    echo "AWS无服务器Docker容器基准测试"
    echo "用法: $0 [选项] [命令]"
    echo ""
    echo "命令:"
    echo "  deploy      部署Lambda和Fargate基础设施"
    echo "  test        运行测试套件"
    echo "  metrics     收集和分析指标"
    echo "  cleanup     清理所有资源"
    echo "  all         执行所有步骤 (deploy -> test -> metrics)"
    echo ""
    echo "选项:"
    echo "  -h, --help  显示此帮助信息"
    echo ""
    echo "环境变量:"
    echo "  MONGODB_URI 必须设置MongoDB连接字符串"
    echo "  AWS_REGION  AWS区域 (默认: us-east-1)"
    echo ""
    echo "示例:"
    echo "  $0 deploy"
    echo "  $0 test"
    echo "  $0 all"
}

# 处理命令行参数
case "$1" in
    -h|--help)
        show_help
        exit 0
        ;;
    deploy)
        deploy_lambda
        deploy_fargate
        ;;
    test)
        run_tests
        ;;
    metrics)
        collect_metrics
        ;;
    cleanup)
        cleanup_resources
        ;;
    all)
        deploy_lambda
        deploy_fargate
        run_tests
        collect_metrics
        ;;
    *)
        show_help
        exit 1
        ;;
esac

exit 0