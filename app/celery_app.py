"""
Celery 애플리케이션 설정 및 초기화 모듈
AWS SQS를 브로커로 사용하는 Celery 인스턴스를 생성합니다.
"""

import os
import logging
from celery import Celery
from . import config

# 로깅 설정
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format=config.LOG_FORMAT
)

logger = logging.getLogger(__name__)

# EC2 IAM Role 사용 - 자격 증명을 환경변수로 설정하지 않음
# EC2 인스턴스 메타데이터에서 자동으로 IAM Role 자격 증명 사용
os.environ.setdefault('AWS_DEFAULT_REGION', config.AWS_REGION)

# Celery 애플리케이션 인스턴스 생성
celery_app = Celery('audio-processor')

# Celery 설정
celery_app.conf.update(
    # 브로커 설정 (AWS SQS)
    broker_url=config.CELERY_BROKER_URL,
    result_backend=config.CELERY_RESULT_BACKEND,
    
    # SQS 관련 설정
    broker_transport_options={
        'region': config.AWS_REGION,
        'visibility_timeout': 3600,
        'polling_interval': 5,
        'predefined_queues': {
            'waveflow-audio-process-queue-honeybadgers': {
                'url': config.SQS_QUEUE_URL,
            }
        },
        'wait_time_seconds': 20,
        'queue_name_prefix': '',
    },
    
    # 작업 실행 설정
    task_serializer='json',
    accept_content=['json', 'application/json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    
    # 메시지 라우팅 설정
    task_routes={
        'app.tasks.process_audio_file': {
            'queue': 'waveflow-audio-process-queue-honeybadgers'
        }
    },
    
    # 작업 신뢰성 설정
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    
    # 재시도 설정
    task_default_retry_delay=config.RETRY_DELAY,
    task_max_retries=config.MAX_RETRIES,
    
    # 워커 설정
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    worker_disable_rate_limits=True,
    
    # 결과 만료 설정
    result_expires=config.CELERY_RESULT_EXPIRES,
    
    # 웹훅 방식 사용으로 결과 저장 불필요
    task_ignore_result=True,
    
    # 로그 설정
    worker_log_format=config.LOG_FORMAT,
    worker_task_log_format=config.LOG_FORMAT,
)

# 작업 모듈 자동 검색 설정
celery_app.autodiscover_tasks(['app'])

# 태스크 등록 확인
logger.info("등록된 태스크 목록: %s", list(celery_app.tasks.keys()))

# 설정 검증 및 정보 출력
try:
    config.validate_config()
    result_backend_info = config.get_result_backend_info()
    
    logger.info("Celery 애플리케이션 설정 완료")
    logger.info("브로커: %s", config.CELERY_BROKER_URL)
    logger.info("Result Backend: %s (%s)", 
               result_backend_info['backend_type'], 
               '분산 지원' if result_backend_info['distributed_support'] else '로컬 전용')
    
    if not result_backend_info['distributed_support']:
        logger.warning("⚠️  현재 result backend는 로컬 전용입니다. 다른 EC2 인스턴스에서 결과 조회가 불가능합니다.")
        logger.warning("분산 환경에서는 SQS, Redis, 또는 데이터베이스를 result backend로 사용하세요.")
    
except Exception as e:
    logger.error("Celery 애플리케이션 설정 실패: %s", e)
    raise

if __name__ == '__main__':
    celery_app.start()