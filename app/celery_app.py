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

# AWS 자격 증명을 환경 변수로 설정
os.environ.setdefault('AWS_ACCESS_KEY_ID', config.AWS_ACCESS_KEY_ID)
os.environ.setdefault('AWS_SECRET_ACCESS_KEY', config.AWS_SECRET_ACCESS_KEY)
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
        'queue_name_prefix': 'waveflow-audio-',
    },

    
    # 작업 실행 설정
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    
    # 작업 신뢰성 설정
    task_acks_late=True,            # 작업 완료 후 ACK (실패 시 재시도 가능)
    task_reject_on_worker_lost=True, # 워커 손실 시 작업 거부
    
    # 재시도 설정
    task_default_retry_delay=config.RETRY_DELAY,
    task_max_retries=config.MAX_RETRIES,
    
    # 워커 설정
    worker_prefetch_multiplier=1,    # 한 번에 하나의 작업만 처리
    worker_max_tasks_per_child=1000, # 메모리 누수 방지
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

# NestJS에서 결과 조회를 위한 헬퍼 함수
def get_task_result(task_id: str):
    """
    태스크 결과를 조회합니다.
    NestJS에서 이 함수를 사용하여 결과를 가져올 수 있습니다.
    
    Args:
        task_id: Celery 태스크 ID
        
    Returns:
        dict: 태스크 결과 또는 None
    """
    try:
        result = celery_app.AsyncResult(task_id)
        
        if result.ready():
            if result.successful():
                return {
                    'status': 'SUCCESS',
                    'result': result.result,
                    'task_id': task_id
                }
            else:
                return {
                    'status': 'FAILURE',
                    'error': str(result.result),
                    'task_id': task_id
                }
        else:
            return {
                'status': result.status,  # PENDING, PROGRESS 등
                'task_id': task_id
            }
    except Exception as e:
        logger.error("태스크 결과 조회 실패: %s", e)
        return {
            'status': 'ERROR',
            'error': str(e),
            'task_id': task_id
        }

if __name__ == '__main__':
    celery_app.start() 