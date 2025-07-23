#!/bin/bash

# AWS IAM 권한 설정 자동화 스크립트
# WaveFlow 오디오 처리 워커를 위한 권한 설정

set -e

echo "🔒 WaveFlow AWS IAM 권한 설정 시작..."

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 변수 설정
IAM_USER_NAME="Badgers-Github-Action"
POLICY_NAME="WaveFlow-AudioProcessor-Policy"
AWS_ACCOUNT_ID="490004626839"
AWS_REGION="ap-northeast-2"
SQS_QUEUE_NAME="waveflow-audio-process-queue-honeybadgers"

# AWS CLI 설치 확인
if ! command -v aws &> /dev/null; then
    echo -e "${RED}❌ AWS CLI가 설치되어 있지 않습니다.${NC}"
    echo "설치 후 다시 시도해주세요."
    exit 1
fi

# AWS 자격 증명 확인
if ! aws sts get-caller-identity &> /dev/null; then
    echo -e "${RED}❌ AWS 자격 증명이 설정되어 있지 않습니다.${NC}"
    echo "aws configure 명령어로 자격 증명을 설정해주세요."
    exit 1
fi

echo -e "${GREEN}✅ AWS CLI 및 자격 증명 확인 완료${NC}"

# IAM 정책 생성
echo "📝 IAM 정책 생성 중..."

# 기존 정책 확인
if aws iam get-policy --policy-arn "arn:aws:iam::${AWS_ACCOUNT_ID}:policy/${POLICY_NAME}" &> /dev/null; then
    echo -e "${YELLOW}⚠️  기존 정책이 있습니다. 새 버전으로 업데이트합니다.${NC}"
    
    # 새 정책 버전 생성
    aws iam create-policy-version \
        --policy-arn "arn:aws:iam::${AWS_ACCOUNT_ID}:policy/${POLICY_NAME}" \
        --policy-document file://scripts/aws-iam-policy.json \
        --set-as-default
    
    echo -e "${GREEN}✅ 정책 업데이트 완료${NC}"
else
    # 새 정책 생성
    aws iam create-policy \
        --policy-name "${POLICY_NAME}" \
        --policy-document file://scripts/aws-iam-policy.json \
        --description "WaveFlow 오디오 처리 워커를 위한 SQS 및 S3 권한"
    
    echo -e "${GREEN}✅ 정책 생성 완료${NC}"
fi

# 사용자에게 정책 연결
echo "🔗 사용자에게 정책 연결 중..."

# 기존 정책 연결 확인
if aws iam list-attached-user-policies --user-name "${IAM_USER_NAME}" | grep -q "${POLICY_NAME}"; then
    echo -e "${YELLOW}⚠️  정책이 이미 연결되어 있습니다.${NC}"
else
    # 정책 연결
    aws iam attach-user-policy \
        --user-name "${IAM_USER_NAME}" \
        --policy-arn "arn:aws:iam::${AWS_ACCOUNT_ID}:policy/${POLICY_NAME}"
    
    echo -e "${GREEN}✅ 정책 연결 완료${NC}"
fi

# 권한 검증
echo "🔍 권한 검증 중..."

# SQS 큐 속성 조회 테스트
SQS_QUEUE_URL="https://sqs.${AWS_REGION}.amazonaws.com/${AWS_ACCOUNT_ID}/${SQS_QUEUE_NAME}"

if aws sqs get-queue-attributes --queue-url "${SQS_QUEUE_URL}" --attribute-names All &> /dev/null; then
    echo -e "${GREEN}✅ SQS 권한 확인 완료${NC}"
else
    echo -e "${RED}❌ SQS 권한 확인 실패${NC}"
    echo "큐 URL: ${SQS_QUEUE_URL}"
    echo "큐가 존재하는지 확인해주세요."
fi

# 설정 완료 메시지
echo ""
echo -e "${GREEN}🎉 AWS IAM 권한 설정 완료!${NC}"
echo ""
echo "다음 단계:"
echo "1. GitHub Actions 워크플로우 재실행"
echo "2. EC2에서 워커 재시작:"
echo "   sudo docker-compose down && sudo docker-compose up -d"
echo "3. 로그 확인:"
echo "   sudo docker-compose logs -f audio-processor"
echo ""
echo "설정된 권한:"
echo "- SQS: ${SQS_QUEUE_NAME}"
echo "- S3: waveflow-audio-bucket, waveflow-waveform-bucket"
echo "- CloudWatch Logs: 로그 그룹 생성 및 로그 전송"
echo ""
echo -e "${YELLOW}💡 문제가 발생하면 AWS_PERMISSIONS_SETUP.md 파일을 참고하세요.${NC}" 