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

# 워커 설정 - EC2 c7-large 인스턴스 최적화 (2 vCPU, 4GB RAM)
WORKER_NAME="${WORKER_NAME:-audio-processor-worker}"
# 동시성 4개로 증가 - threads pool과 함께 최적화
CONCURRENCY="${CONCURRENCY:-4}"
# 워커 프로세스 수 - 2 vCPU 활용
WORKER_PROCESSES="${WORKER_PROCESSES:-2}"
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
echo "  - 워커 프로세스 수: $WORKER_PROCESSES"
echo "  - 동시 실행 수: $CONCURRENCY"
echo "  - 로그 레벨: $LOG_LEVEL"
echo "  - 큐 이름: $QUEUE_NAME"
echo "  - SQS 큐 URL: $SQS_QUEUE_URL"

# 그레이스풀 종료 핸들러
cleanup() {
    echo "워커 종료 신호 받음..."
    echo "진행 중인 작업 완료 대기 중..."
    
    # 모든 워커 프로세스에 종료 신호 전송
    for pid in "${WORKER_PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            echo "워커 프로세스 종료 중... (PID: $pid)"
            kill -TERM "$pid" 2>/dev/null || true
        fi
    done
    
    # 모든 워커 프로세스 종료 대기
    for pid in "${WORKER_PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            wait "$pid" 2>/dev/null || true
        fi
    done
    
    # 임시 파일 정리
    echo "임시 파일 정리 중..."
    find /tmp -name "tmp*" -type f -delete 2>/dev/null || true
    
    echo "모든 워커 종료 완료"
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

# 다중 워커 프로세스 시작
echo "다중 워커 프로세스 시작 중..."
export USE_CUSTOM_HANDLER=true

# 워커 PID 배열
WORKER_PIDS=()

# 워커 프로세스 시작 함수
start_worker() {
    local worker_id=$1
    echo "워커 #${worker_id} 시작 중..."
    
    # Python 스크립트 실행 (에러 처리 추가)
    python -c "
import sys
import os
import traceback

try:
    print(f'워커 #{worker_id}: Python 스크립트 시작')
    os.environ['WORKER_ID'] = '${worker_id}'
    print(f'워커 #{worker_id}: WORKER_ID 환경 변수 설정 완료')
    
    from app.celery_app import start_custom_handler
    print(f'워커 #{worker_id}: start_custom_handler import 완료')
    
    start_custom_handler()
    print(f'워커 #{worker_id}: start_custom_handler 호출 완료')
    
except Exception as e:
    print(f'워커 #{worker_id}: 에러 발생: {e}')
    print(f'워커 #{worker_id}: 트레이스백:')
    traceback.print_exc()
    sys.exit(1)
" &
    
    local pid=$!
    WORKER_PIDS+=($pid)
    echo "워커 #${worker_id} 시작됨 (PID: $pid)"
    
    # 워커 시작 후 잠시 대기하여 즉시 실패하는지 확인
    sleep 1
    if ! kill -0 "$pid" 2>/dev/null; then
        echo "❌ 워커 #${worker_id}가 즉시 실패했습니다 (PID: $pid)"
        return 1
    else
        echo "✅ 워커 #${worker_id} 정상 시작 확인됨 (PID: $pid)"
        return 0
    fi
}

# 모든 워커 프로세스 시작 (seq 대신 안전한 방법 사용)
echo "워커 프로세스 시작 시도: $WORKER_PROCESSES 개"
i=1
while [ $i -le $WORKER_PROCESSES ]; do
    echo "워커 $i/$WORKER_PROCESSES 시작 시도 중..."
    start_worker $i
    sleep 2  # 각 워커 시작 간격
    i=$((i + 1))
done

echo "모든 워커 프로세스 시작 완료"

# 모든 워커 프로세스 시작 확인
sleep 5
failed_workers=0
for pid in "${WORKER_PIDS[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
        echo "❌ 워커 프로세스 시작 실패 (PID: $pid)"
        failed_workers=$((failed_workers + 1))
    fi
done

if [ $failed_workers -gt 0 ]; then
    echo "❌ $failed_workers 개의 워커 프로세스 시작 실패"
    exit 1
else
    echo "✅ 모든 워커 프로세스 시작 완료"
fi

# 주기적 헬스 체크 및 임시 파일 정리
while true; do
    sleep 180  # 3분마다 실행 (더 빈번한 체크)
    
    # 모든 워커 프로세스 상태 확인
    failed_workers=0
    active_workers=0
    
    for pid in "${WORKER_PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            active_workers=$((active_workers + 1))
        else
            failed_workers=$((failed_workers + 1))
            echo "❌ 워커 프로세스 종료 감지됨 (PID: $pid)"
        fi
    done
    
    # 절반 이상의 워커가 실패하면 전체 재시작
    if [ $failed_workers -gt $((WORKER_PROCESSES / 2)) ]; then
        echo "❌ 너무 많은 워커 프로세스가 실패했습니다. ($failed_workers/$WORKER_PROCESSES)"
        exit 1
    fi
    
    # 실패한 워커가 있으면 재시작
    if [ $failed_workers -gt 0 ]; then
        echo "⚠️  $failed_workers 개의 워커 프로세스 재시작 중..."
        # 간단한 재시작 로직: 스크립트 자체를 재시작
        exec "$0"
    fi
    
    # 임시 파일 정리 (1시간 이상 된 파일)
    find /tmp -name "tmp*" -type f -mtime +0.04 -delete 2>/dev/null || true
    
    echo "모든 워커 프로세스 실행 중... (활성: $active_workers/$WORKER_PROCESSES)"
done 