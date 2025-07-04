"""
애플리케이션 설정 관리 모듈
환경 변수를 읽어와서 애플리케이션에서 사용할 수 있도록 관리합니다.
"""

import os
from urllib.parse import quote_plus
from dotenv import load_dotenv

# 환경 변수 로드
load_dotenv()

# AWS 설정
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID', '')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY', '')
AWS_REGION = os.getenv('AWS_REGION', 'ap-northeast-2')

# SQS 설정
SQS_QUEUE_URL = os.getenv('SQS_QUEUE_URL', '')

# S3 설정
S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME', '')
S3_WAVEFORM_BUCKET_NAME = os.getenv('S3_WAVEFORM_BUCKET_NAME', '')

# Celery 설정
# SQS를 브로커로 사용하는 URL 생성
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', '')
if not CELERY_BROKER_URL and AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
    # AWS 자격 증명을 URL 인코딩하여 특수문자 처리
    encoded_access_key = quote_plus(AWS_ACCESS_KEY_ID)
    encoded_secret_key = quote_plus(AWS_SECRET_ACCESS_KEY)
    CELERY_BROKER_URL = f'sqs://{encoded_access_key}:{encoded_secret_key}@'

# Result Backend 설정 - 웹훅 방식으로 처리하므로 불필요
CELERY_RESULT_BACKEND = 'cache'  # 기본 캐시만 사용

# 파일 처리 설정
ALLOWED_MIME_TYPES = os.getenv('ALLOWED_MIME_TYPES', 'audio/wav,audio/mpeg,audio/mp3,audio/flac,audio/ogg').split(',')
MAX_FILE_SIZE_MB = int(os.getenv('MAX_FILE_SIZE_MB', '100'))
DEFAULT_WAVEFORM_PEAKS = int(os.getenv('DEFAULT_WAVEFORM_PEAKS', '1024'))

# 로깅 설정
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FORMAT = os.getenv('LOG_FORMAT', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# 재시도 설정
MAX_RETRIES = int(os.getenv('MAX_RETRIES', '3'))
RETRY_DELAY = int(os.getenv('RETRY_DELAY', '60'))

# 웹훅 설정
WEBHOOK_URL = os.getenv('WEBHOOK_URL', '')

# 결과 저장 만료 시간 (초) - SQS 메시지 가시성 타임아웃 고려
CELERY_RESULT_EXPIRES = int(os.getenv('CELERY_RESULT_EXPIRES', '3600'))  # 1시간

# 필수 환경 변수 검증
REQUIRED_VARS = [
    'AWS_ACCESS_KEY_ID',
    'AWS_SECRET_ACCESS_KEY',
    'SQS_QUEUE_URL',
    'S3_BUCKET_NAME',
    'S3_WAVEFORM_BUCKET_NAME',
    'WEBHOOK_URL'
]

def validate_config():
    """필수 환경 변수가 설정되었는지 검증합니다."""
    missing_vars = []
    for var in REQUIRED_VARS:
        if not globals().get(var):
            missing_vars.append(var)
    
    if missing_vars:
        raise ValueError(f"필수 환경 변수가 설정되지 않았습니다: {', '.join(missing_vars)}")
    
    return True

def get_config():
    """전체 설정을 딕셔너리로 반환합니다."""
    return {
        'AWS_ACCESS_KEY_ID': AWS_ACCESS_KEY_ID,
        'AWS_SECRET_ACCESS_KEY': AWS_SECRET_ACCESS_KEY,
        'AWS_REGION': AWS_REGION,
        'SQS_QUEUE_URL': SQS_QUEUE_URL,
        'S3_BUCKET_NAME': S3_BUCKET_NAME,
        'S3_WAVEFORM_BUCKET_NAME': S3_WAVEFORM_BUCKET_NAME,
        'CELERY_BROKER_URL': CELERY_BROKER_URL,
        'WEBHOOK_URL': WEBHOOK_URL,
        'ALLOWED_MIME_TYPES': ALLOWED_MIME_TYPES,
        'MAX_FILE_SIZE_MB': MAX_FILE_SIZE_MB,
        'DEFAULT_WAVEFORM_PEAKS': DEFAULT_WAVEFORM_PEAKS,
        'LOG_LEVEL': LOG_LEVEL,
        'MAX_RETRIES': MAX_RETRIES,
        'RETRY_DELAY': RETRY_DELAY
    }

def get_result_backend_info():
    """현재 result backend 설정 정보를 반환합니다."""
    return {
        'backend_type': "Cache (웹훅 방식 사용)",
        'backend_url': CELERY_RESULT_BACKEND,
        'distributed_support': True
    } 