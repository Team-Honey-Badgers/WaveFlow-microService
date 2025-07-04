#!/bin/bash

# EC2 서버 초기 설정 스크립트
set -e

echo "🚀 EC2 서버 설정 시작..."

# 시스템 업데이트
sudo apt-get update -y
sudo apt-get upgrade -y

# Docker 설치
if ! command -v docker &> /dev/null; then
    echo "📦 Docker 설치 중..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker ubuntu
    rm get-docker.sh
fi

# Docker Compose 설치
if ! command -v docker-compose &> /dev/null; then
    echo "📦 Docker Compose 설치 중..."
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
fi

# Git 설치
if ! command -v git &> /dev/null; then
    echo "📦 Git 설치 중..."
    sudo apt-get install -y git
fi

# 프로젝트 디렉토리 생성
PROJECT_DIR="/home/ubuntu/audio-processor"
if [ ! -d "$PROJECT_DIR" ]; then
    echo "📁 프로젝트 디렉토리 생성..."
    mkdir -p $PROJECT_DIR
    cd $PROJECT_DIR
    
    # Git 저장소 클론
    echo "📥 Git 저장소 클론..."
    git clone https://github.com/your-username/microService-python.git .
    # 또는 SSH: git clone git@github.com:your-username/microService-python.git .
else
    echo "📁 기존 프로젝트 디렉토리 사용"
    cd $PROJECT_DIR
fi

# 로그 디렉토리 생성
mkdir -p logs

# 환경 변수 파일 생성 (템플릿)
if [ ! -f ".env" ]; then
    echo "📝 환경 변수 파일 생성..."
    cat > .env << EOF
# AWS 설정
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_REGION=us-east-1

# SQS 설정
SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/123456789012/audio-queue
SQS_RESULT_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/123456789012/result-queue

# S3 설정
S3_BUCKET_NAME=your-audio-bucket
S3_WAVEFORM_BUCKET_NAME=your-waveform-bucket

# Celery 설정
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0
CONCURRENCY=4

# 로그 설정
LOG_LEVEL=INFO
EOF
    echo "⚠️  .env 파일을 실제 값으로 수정해주세요!"
fi

# Docker 서비스 시작
sudo systemctl enable docker
sudo systemctl start docker

echo "✅ EC2 서버 설정 완료!"
echo "📝 다음 단계:"
echo "1. .env 파일을 실제 AWS 자격증명으로 수정"
echo "2. GitHub Secrets에 EC2 정보 추가"
echo "3. docker-compose up -d 실행"