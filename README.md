# 🎵 오디오 처리 워커

음악 협업 플랫폼을 위한 Python 비동기 오디오 처리 워커입니다.

## 🎯 주요 기능

- **📁 파일 검증**: 실제 MIME 타입 검증
- **🔐 해시 계산**: SHA-256 오디오 파일 해시 생성
- **📊 파형 생성**: wavesurfer.js용 파형 피크 데이터 생성
- **☁️ AWS 연동**: SQS와 S3를 통한 클라우드 처리
- **🔄 웹훅 알림**: 처리 완료 시 웹서버로 즉시 알림

## 🏗️ 아키텍처

```
SQS Queue → Celery Worker → S3 Upload → Webhook → Web Server
```

## 🚀 빠른 시작

### 1. 환경 설정
```bash
cp example.env .env
# .env 파일을 실제 값으로 수정
```

### 2. 로컬 실행
```bash
chmod +x run_worker.sh
./run_worker.sh
```

### 3. Docker 실행
```bash
docker-compose up -d
```

## 📦 CI/CD 배포

1. GitHub Secrets 설정 (SECRETS_GUIDE.md 참고)
2. `ci-cd-test` 브랜치에 푸시
3. 자동 배포 완료!

## 🔧 주요 파일

- `app/audio_processor.py`: 핵심 오디오 처리 로직
- `app/tasks.py`: Celery 태스크 정의
- `app/webhook.py`: 웹서버 알림 처리
- `docker-compose.yml`: 컨테이너 설정
- `.github/workflows/ci.yml`: CI/CD 파이프라인

## 📊 모니터링

```bash
# 컨테이너 상태
docker-compose ps

# 로그 확인
docker-compose logs -f audio-processor

# 워커 상태
docker-compose exec audio-processor python -c "from app.celery_app import celery_app; print('OK')"
```

## 🔗 웹훅 데이터 형식

```json
{
  "job_id": "unique-job-123",
  "status": "SUCCESS",
  "result": {
    "audio_data_hash": "sha256...",
    "waveform_data_path": "waveforms/file.json",
    "duration": 180.5,
    "file_size": 5242880
  },
  "timestamp": "2024-01-01T12:00:00Z"
}
```