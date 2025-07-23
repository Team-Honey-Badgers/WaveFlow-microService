# 단일 스테이지 빌드로 단순화
FROM python:3.9-slim

# 메타데이터 추가
LABEL maintainer="audio-processor-team"
LABEL version="1.0"
LABEL description="음악 협업 플랫폼용 Python 비동기 워커 서버"

# 작업 디렉토리 설정
WORKDIR /usr/src/app

# 시스템 의존성 설치
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    libmagic1 \
    libmagic-dev \
    libsndfile1 \
    libsndfile1-dev \
    ffmpeg \
    curl \
    libcurl4-openssl-dev \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Python 의존성 업그레이드
RUN pip install --upgrade pip setuptools wheel

# requirements.txt 복사 및 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 소스 코드 복사
COPY app/ ./app/
COPY run_worker.sh ./
COPY run_tests.sh ./

# 실행 권한 부여
RUN chmod +x run_worker.sh run_tests.sh

# 비권한 사용자 생성 및 전환 (보안)
RUN groupadd -r appuser && useradd -r -g appuser appuser
RUN chown -R appuser:appuser /usr/src/app
# 로그는 stdout으로 출력
USER appuser

# 환경 변수 설정
ENV PYTHONPATH=/usr/src/app
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV LIBROSA_CACHE_DIR=/tmp
ENV LIBROSA_CACHE_LEVEL=0
ENV NUMBA_CACHE_DIR=/tmp
ENV NUMBA_DISABLE_JIT=1

# 헬스 체크 설정
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD python -c "from app.celery_app import celery_app; celery_app.control.inspect().ping()" || exit 1

# 볼륨 마운트 포인트 (로그 및 임시 파일용)
VOLUME ["/tmp", "/var/log"]

# 기본 포트 노출 (모니터링용)
EXPOSE 5555

# 실행 명령어
CMD ["./run_worker.sh"] 