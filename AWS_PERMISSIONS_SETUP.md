# AWS 권한 설정 가이드 🔒

## 문제 상황 분석

현재 Celery 워커가 다음과 같은 권한 오류로 시작되지 않는 상황입니다:

```
botocore.exceptions.ClientError: An error occurred (AccessDenied) when calling the GetQueueAttributes operation: User: arn:aws:iam::490004626839:user/Badgers-Github-Action is not authorized to perform: sqs:getqueueattributes on resource: arn:aws:sqs:ap-northeast-2:490004626839:waveflow-audio-process-queue-honeybadgers because no identity-based policy allows the sqs:getqueueattributes action
```

## 해결 방법

### 1. IAM 정책 생성 및 적용

AWS 콘솔에서 다음 단계를 따라 진행하세요:

#### Step 1: IAM 콘솔 접속
1. AWS Management Console → IAM 서비스 이동
2. 좌측 메뉴에서 "정책(Policies)" 선택

#### Step 2: 정책 생성
1. "정책 생성" 버튼 클릭
2. "JSON" 탭 선택
3. `scripts/aws-iam-policy.json` 파일의 내용을 복사하여 붙여넣기
4. 정책 이름: `WaveFlow-AudioProcessor-Policy`
5. 설명: `WaveFlow 오디오 처리 워커를 위한 SQS 및 S3 권한`

#### Step 3: 사용자에게 정책 연결
1. IAM → 사용자 → `Badgers-Github-Action` 선택
2. "권한 추가" 버튼 클릭
3. "기존 정책 직접 연결" 선택
4. 생성한 `WaveFlow-AudioProcessor-Policy` 정책 선택
5. "권한 추가" 완료

### 2. 환경 변수 설정

GitHub Secrets에 다음 환경 변수가 올바르게 설정되어 있는지 확인:

```bash
SQS_QUEUE_URL=https://sqs.ap-northeast-2.amazonaws.com/490004626839/waveflow-audio-process-queue-honeybadgers
SQS_QUEUE_NAME=waveflow-audio-process-queue-honeybadgers  # 선택적으로 설정 가능
```

### 3. 코드 수정 사항

다음 파일들이 수정되었습니다:

1. **`app/config.py`**
   - SQS 큐 이름을 동적으로 설정하는 함수 추가
   - 환경 변수 `SQS_QUEUE_NAME` 지원

2. **`app/celery_app.py`**
   - 큐 이름을 동적으로 설정하도록 수정
   - URL에서 큐 이름을 자동 추출

3. **`run_worker.sh`**
   - 큐 이름을 동적으로 설정하는 로직 추가
   - 디버깅을 위한 로그 출력 개선

## 필요한 AWS 리소스 권한

### SQS 권한
- `sqs:GetQueueAttributes` ✅
- `sqs:GetQueueUrl` ✅
- `sqs:ReceiveMessage` ✅
- `sqs:DeleteMessage` ✅
- `sqs:SendMessage` ✅
- `sqs:ChangeMessageVisibility` ✅

### S3 권한
- `s3:GetObject` ✅
- `s3:PutObject` ✅
- `s3:DeleteObject` ✅
- `s3:ListBucket` ✅

## 테스트 방법

권한 설정 후 다음 명령어로 테스트:

```bash
# EC2에서 워커 재시작
sudo docker-compose down
sudo docker-compose up -d

# 로그 확인
sudo docker-compose logs -f audio-processor
```

## 문제 해결 완료 확인

성공적으로 설정이 완료되면 다음과 같은 로그가 출력됩니다:

```
✅ 설정 검증 완료
Celery 워커 시작 중...
워커 설정:
  - 워커 이름: audio-processor-worker
  - 동시 실행 수: 4
  - 로그 레벨: INFO
  - 큐 이름: waveflow-audio-process-queue-honeybadgers
  - SQS 큐 URL: https://sqs.ap-northeast-2.amazonaws.com/490004626839/waveflow-audio-process-queue-honeybadgers
Connected to sqs://localhost//
✅ 워커 시작 완료
```

## 추가 참고 사항

1. **큐 이름 우선순위**:
   - 환경 변수 `SQS_QUEUE_NAME` (최우선)
   - SQS URL에서 자동 추출
   - 기본값: `audio-processing-queue`

2. **보안 권고사항**:
   - IAM 정책에서 최소 권한 원칙 적용
   - 특정 리소스 ARN 지정으로 권한 범위 제한
   - 정기적인 권한 검토 및 업데이트

3. **모니터링**:
   - CloudWatch Logs 권한 포함
   - 로그 그룹 자동 생성 가능
   - 워커 상태 모니터링 지원 