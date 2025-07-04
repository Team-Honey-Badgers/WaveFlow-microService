#!/bin/bash

# EC2 배포 스크립트
set -e

BRANCH=${1:-main}
PROJECT_DIR="/home/ubuntu/audio-processor"

echo "🚀 배포 시작 - 브랜치: $BRANCH"

cd $PROJECT_DIR

# Git 업데이트
echo "📥 코드 업데이트..."
git fetch origin
git checkout $BRANCH
git pull origin $BRANCH

# 기존 컨테이너 중지
echo "🛑 기존 서비스 중지..."
sudo docker-compose down

# 새 이미지 빌드
echo "🔨 Docker 이미지 빌드..."
sudo docker-compose build --no-cache

# 서비스 시작
echo "🚀 서비스 시작..."
sudo docker-compose up -d

# 헬스 체크
echo "🔍 서비스 상태 확인..."
sleep 10
sudo docker-compose ps

# 로그 확인
echo "📋 최근 로그:"
sudo docker-compose logs --tail=20 audio-processor

echo "✅ 배포 완료!"