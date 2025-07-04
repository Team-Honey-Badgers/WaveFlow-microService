#!/bin/bash

# 테스트 실행 스크립트
# pytest를 사용하여 모든 테스트를 실행합니다.

set -e  # 에러 발생 시 스크립트 종료

echo "====================================="
echo "음악 협업 플랫폼 오디오 처리 워커 테스트"
echo "====================================="

# Python 경로 설정
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# 테스트 환경 변수 설정
export AWS_ACCESS_KEY_ID="testing"
export AWS_SECRET_ACCESS_KEY="testing"
export AWS_REGION="us-east-1"
export SQS_QUEUE_URL="https://sqs.us-east-1.amazonaws.com/123456789012/test-queue"
export SQS_RESULT_QUEUE_URL="https://sqs.us-east-1.amazonaws.com/123456789012/test-result-queue"
export S3_BUCKET_NAME="test-bucket"
export S3_WAVEFORM_BUCKET_NAME="test-waveform-bucket"
export ALLOWED_MIME_TYPES="audio/wav,audio/mpeg,audio/mp3,audio/flac,audio/ogg"
export MAX_FILE_SIZE_MB="100"
export DEFAULT_WAVEFORM_PEAKS="1024"
export LOG_LEVEL="INFO"
export MAX_RETRIES="3"
export RETRY_DELAY="60"

echo "테스트 환경 변수 설정 완료"

# 테스트 디렉토리 확인
if [ ! -d "tests" ]; then
    echo "❌ tests 디렉토리를 찾을 수 없습니다."
    exit 1
fi

# 테스트 의존성 확인
echo "테스트 의존성 확인 중..."
python -c "
import sys
required_modules = ['pytest', 'moto', 'boto3', 'magic', 'librosa', 'numpy']
missing_modules = []

for module in required_modules:
    try:
        __import__(module)
    except ImportError:
        missing_modules.append(module)

if missing_modules:
    print(f'❌ 필수 모듈이 설치되지 않았습니다: {missing_modules}')
    sys.exit(1)
else:
    print('✅ 모든 필수 모듈이 설치되었습니다.')
"

# 테스트 실행 옵션 설정
PYTEST_ARGS=(
    "--verbose"
    "--tb=short"
    "--strict-markers"
    "--disable-warnings"
    "--color=yes"
    "--durations=10"
    "--cov=app"
    "--cov-report=term-missing"
    "--cov-report=html:htmlcov"
    "--cov-fail-under=80"
)

# 병렬 테스트 실행 여부 확인
if command -v pytest-xdist &> /dev/null; then
    echo "pytest-xdist 사용 가능 - 병렬 테스트 실행"
    PYTEST_ARGS+=("-n" "auto")
fi

# 테스트 임시 파일 정리
echo "테스트 임시 파일 정리 중..."
rm -rf .pytest_cache/ htmlcov/ .coverage 2>/dev/null || true

# 테스트 실행
echo "테스트 실행 중..."
echo "명령어: python -m pytest ${PYTEST_ARGS[@]} tests/"

# 테스트 타임아웃 설정 (30분)
timeout 1800 python -m pytest "${PYTEST_ARGS[@]}" tests/ || {
    exit_code=$?
    case $exit_code in
        124)
            echo "❌ 테스트 타임아웃 (30분 초과)"
            ;;
        *)
            echo "❌ 테스트 실패 (종료 코드: $exit_code)"
            ;;
    esac
    exit $exit_code
}

echo "✅ 모든 테스트 통과"

# 코드 품질 검사 (선택사항)
echo "코드 품질 검사 중..."

# Flake8 코드 스타일 검사
if command -v flake8 &> /dev/null; then
    echo "Flake8 코드 스타일 검사 실행 중..."
    flake8 app/ --max-line-length=120 --ignore=E203,W503,E501 || {
        echo "⚠️  코드 스타일 경고가 있습니다."
    }
else
    echo "Flake8이 설치되지 않아 코드 스타일 검사를 건너뜁니다."
fi

# Black 코드 포맷팅 검사
if command -v black &> /dev/null; then
    echo "Black 코드 포맷팅 검사 실행 중..."
    black --check app/ || {
        echo "⚠️  코드 포맷팅 경고가 있습니다."
        echo "   'black app/' 명령어로 자동 포맷팅 가능합니다."
    }
else
    echo "Black이 설치되지 않아 코드 포맷팅 검사를 건너뜁니다."
fi

# 테스트 결과 요약
echo "====================================="
echo "테스트 완료 요약"
echo "====================================="
echo "✅ 단위 테스트: 통과"
echo "✅ 커버리지 리포트: htmlcov/index.html"

if [ -f "htmlcov/index.html" ]; then
    echo "📊 커버리지 리포트가 생성되었습니다."
    echo "   브라우저에서 htmlcov/index.html을 열어 확인할 수 있습니다."
fi

echo "테스트 실행 완료 🎉" 