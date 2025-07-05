#!/bin/bash

# Celery 워커 실행 스크립트
# 프로덕션 환경에서 안전하게 워커를 시작합니다.

set -e  # 에러 발생 시 스크립트 종료

echo "======================================"
echo "음악 협업 플랫폼 오디오 처리 워커 시작"
echo "======================================"

# 환경 변수 확인
echo "환경 변수 확인 중..."
# EC2 IAM Role 사용으로 AWS 자격 증명 환경변수 검증 불필요
echo "ℹ️  EC2 IAM Role을 사용하여 AWS 서비스에 접근합니다."

if [ -z "$SQS_QUEUE_URL" ]; then
    echo "❌ 필수 SQS 큐 URL이 설정되지 않았습니다."
    echo "   SQS_QUEUE_URL을 설정해주세요."
    exit 1
fi

if [ -z "$S3_BUCKET_NAME" ]; then
    echo "❌ 필수 S3 버킷이 설정되지 않았습니다."
    echo "   S3_BUCKET_NAME을 설정해주세요."
    exit 1
fi

echo "✅ 환경 변수 확인 완료"

# Python 경로 설정
export PYTHONPATH="${PYTHONPATH}:/usr/src/app"

# 로그는 stdout으로 출력 (Docker 로그로 수집)

# 임시 파일 정리 (시작 시)
echo "임시 파일 정리 중..."
find /tmp -name "tmp*" -type f -mtime +1 -delete 2>/dev/null || true

# 워커 설정
WORKER_NAME="${WORKER_NAME:-audio-processor-worker}"
CONCURRENCY="${CONCURRENCY:-2}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"

# 동적으로 큐 이름 설정 (SQS URL에서 추출)
if [ -n "$SQS_QUEUE_NAME" ]; then
    QUEUE_NAME="$SQS_QUEUE_NAME"
elif [ -n "$SQS_QUEUE_URL" ]; then
    # SQS URL에서 큐 이름 추출
    QUEUE_NAME=$(basename "$SQS_QUEUE_URL")
else
    QUEUE_NAME="${QUEUE_NAME:-audio-processing-queue}"
fi

echo "워커 설정:"
echo "  - 워커 이름: $WORKER_NAME"
echo "  - 동시 실행 수: $CONCURRENCY"
echo "  - 로그 레벨: $LOG_LEVEL"
echo "  - 큐 이름: $QUEUE_NAME"
echo "  - SQS 큐 URL: $SQS_QUEUE_URL"

# 그레이스풀 종료 핸들러
cleanup() {
    echo "워커 종료 신호 받음..."
    echo "진행 중인 작업 완료 대기 중..."
    
    # Celery 워커에 종료 신호 전송
    if [ ! -z "$CELERY_PID" ]; then
        kill -TERM "$CELERY_PID" 2>/dev/null || true
        wait "$CELERY_PID" 2>/dev/null || true
    fi
    
    # 임시 파일 정리
    echo "임시 파일 정리 중..."
    find /tmp -name "tmp*" -type f -delete 2>/dev/null || true
    
    echo "워커 종료 완료"
    exit 0
}

# 신호 핸들러 등록
trap cleanup SIGTERM SIGINT

# 시작 전 연결 테스트
echo "AWS 서비스 연결 테스트 중..."
python -c "
import sys
sys.path.insert(0, '/usr/src/app')
from app.config import validate_config
try:
    validate_config()
    print('✅ 설정 검증 완료')
except Exception as e:
    print(f'❌ 설정 검증 실패: {e}')
    sys.exit(1)
"

# Celery 워커 시작
echo "Celery 워커 시작 중..."
echo "명령어: celery -A app.celery_app worker --loglevel=$LOG_LEVEL --concurrency=$CONCURRENCY --hostname=$WORKER_NAME@%h --queues=$QUEUE_NAME"

# 백그라운드에서 워커 실행
celery -A app.celery_app worker \
    --loglevel="$LOG_LEVEL" \
    --concurrency="$CONCURRENCY" \
    --hostname="$WORKER_NAME@%h" \
    --queues="$QUEUE_NAME" \
    --without-gossip \
    --without-mingle \
    --without-heartbeat \
    --optimization=fair &

CELERY_PID=$!
echo "Celery 워커 시작됨 (PID: $CELERY_PID)"

# 워커 시작 확인
sleep 5
if ! kill -0 "$CELERY_PID" 2>/dev/null; then
    echo "❌ 워커 시작 실패"
    exit 1
fi

echo "✅ 워커 시작 완료"

# 주기적 헬스 체크 및 임시 파일 정리
while true; do
    sleep 300  # 5분마다 실행
    
    # 워커 프로세스 확인
    if ! kill -0 "$CELERY_PID" 2>/dev/null; then
        echo "❌ 워커 프로세스가 종료되었습니다."
        exit 1
    fi
    
    # 임시 파일 정리 (1시간 이상 된 파일)
    find /tmp -name "tmp*" -type f -mtime +0.04 -delete 2>/dev/null || true
    
    echo "워커 실행 중... (PID: $CELERY_PID)"
done 