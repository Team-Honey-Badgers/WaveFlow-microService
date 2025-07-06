# WaveFlow 마이크로서비스

오디오 파일 처리를 위한 Celery 기반 마이크로서비스입니다.

## 새로운 워크플로우

### 1. 해시 생성 및 웹훅 전송 단계
- **테스크**: `generate_hash_and_webhook`
- **역할**: S3에서 파일 다운로드 → 해시 생성 → 웹훅으로 NestJS 서버에 전송
- **메시지 형식**:
```json
{
  "userId": "user123",
  "trackId": "track456", 
  "stemId": "stem789",
  "filepath": "audio/sample.wav",
  "timestamp": "2024-01-01T10:00:00Z",
  "original_filename": "sample.wav"
}
```

### 2. 중복 파일 처리 단계
- **테스크**: `process_duplicate_file`
- **역할**: 중복된 해시값이 있는 경우 S3에서 파일 삭제
- **메시지 형식**:
```json
{
  "userId": "user123",
  "trackId": "track456",
  "stemId": "stem789", 
  "filepath": "audio/sample.wav",
  "audio_hash": "abc123..."
}
```

### 3. 오디오 분석 단계
- **테스크**: `process_audio_analysis`
- **역할**: 오디오 파일 분석 → 파형 데이터 생성 → S3 저장 → 파일 정리
- **메시지 형식**:
```json
{
  "userId": "user123",
  "trackId": "track456",
  "stemId": "stem789",
  "filepath": "audio/sample.wav", 
  "audio_hash": "abc123...",
  "timestamp": "2024-01-01T10:00:00Z",
  "original_filename": "sample.wav",
  "num_peaks": 1024
}
```

## 워크플로우 흐름

1. **NestJS 서버** → SQS에 `generate_hash_and_webhook` 메시지 전송
2. **Celery 워커** → 해시 생성 후 웹훅으로 NestJS 서버에 전송
3. **NestJS 서버** → 중복 검사 후 결과에 따라 분기:
   - **중복 없음**: SQS에 `process_audio_analysis` 메시지 전송
   - **중복 있음**: SQS에 `process_duplicate_file` 메시지 전송

## 웹훅 엔드포인트

### 해시 웹훅 (중복 검사 요청)
- **URL**: `{WEBHOOK_URL}/hash-check`
- **Method**: POST
- **Payload**:
```json
{
  "stemId": "stem789",
  "userId": "user123", 
  "trackId": "track456",
  "filepath": "audio/sample.wav",
  "audio_hash": "abc123...",
  "timestamp": "2024-01-01T10:00:00Z",
  "original_filename": "sample.wav",
  "status": "hash_generated"
}
```

### 완료 웹훅 (결과 전송)
- **URL**: `{WEBHOOK_URL}/completion`
- **Method**: POST
- **Payload**:
```json
{
  "stemId": "stem789",
  "status": "SUCCESS",
  "result": {
    "audio_data_hash": "abc123...",
    "waveform_data_path": "waveforms/stem789_waveform_12345.json",
    "file_size": 1024000,
    "duration": 30.5,
    "sample_rate": 44100,
    "num_peaks": 1024
  },
  "timestamp": "2024-01-01T10:05:00Z"
}
```

## 환경 변수

```env
# AWS 설정
AWS_REGION=ap-northeast-2
S3_BUCKET_NAME=your-bucket-name
SQS_QUEUE_URL=https://sqs.ap-northeast-2.amazonaws.com/your-account/your-queue

# 웹훅 설정
WEBHOOK_URL=https://your-nestjs-server.com/webhook

# 로깅 설정
LOG_LEVEL=INFO
```

## 실행 방법

```bash
# 워커 실행
celery -A app.celery_app worker --loglevel=info

# 또는 스크립트 실행
./run_worker.sh
```

## 주요 기능

- **3단계 워크플로우**: 해시 생성 → 중복 검사 → 분석 처리
- **S3 파일 관리**: 다운로드, 업로드, 삭제
- **웹훅 통합**: NestJS 서버와 실시간 통신
- **오류 처리**: 재시도 로직 및 실패 알림
- **임시 파일 정리**: 메모리 효율적인 처리

## 디렉토리 구조

```
app/
├── __init__.py
├── celery_app.py      # Celery 설정
├── tasks.py           # 태스크 정의 (새로운 3단계 워크플로우)
├── audio_processor.py # 오디오 분석 로직
├── aws_utils.py       # AWS S3/SQS 연동
├── webhook.py         # 웹훅 전송 (해시/완료)
└── config.py          # 환경 설정
```