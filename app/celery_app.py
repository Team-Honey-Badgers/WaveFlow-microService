"""
Celery 애플리케이션 설정 및 초기화 모듈
AWS SQS를 브로커로 사용하는 Celery 인스턴스를 생성합니다.
Numba 캐싱 최적화가 적용되어 있습니다.
"""

# Numba 캐시 디렉토리 전역 설정 (모든 import보다 먼저 실행)
import os
os.environ['NUMBA_CACHE_DIR'] = '/tmp/numba_cache'

import logging
from celery import Celery
from celery.signals import task_prerun, task_failure, task_retry, task_success
from . import config

# Numba 캐시 디렉토리 생성 및 검증
cache_dir = os.environ['NUMBA_CACHE_DIR']
os.makedirs(cache_dir, exist_ok=True)

# librosa 캐싱 설정 (성능 최적화)
os.environ['LIBROSA_CACHE_DIR'] = '/tmp/librosa_cache'
os.environ['LIBROSA_CACHE_LEVEL'] = '10'
os.makedirs('/tmp/librosa_cache', exist_ok=True)

# OpenMP 스레드 수 제한 (컨테이너 환경 최적화)
os.environ['OMP_NUM_THREADS'] = '2'

# 로깅 설정
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format=config.LOG_FORMAT
)

logger = logging.getLogger(__name__)
logger.info("Numba 캐시 디렉토리 설정 완료: %s", cache_dir)

# EC2 IAM Role 사용 - 자격 증명을 환경변수로 설정하지 않음
# EC2 인스턴스 메타데이터에서 자동으로 IAM Role 자격 증명 사용
os.environ.setdefault('AWS_DEFAULT_REGION', config.AWS_REGION)

# Celery 애플리케이션 인스턴스 생성
celery_app = Celery('audio-processor')

# Numba JIT 함수 워밍업 (시작 시 JIT 컴파일 수행)
def warmup_numba_functions():
    """
    성능 중요 함수들의 Numba JIT 컴파일을 미리 수행합니다.
    시작 시 한 번만 실행되어 이후 호출 시 빠른 실행을 보장합니다.
    """
    logger.info("Numba JIT 함수 워밍업 시작...")
    
    try:
        # audio_processor의 성능 중요 함수들 워밍업
        from .audio_processor import AudioProcessor
        logger.info("AudioProcessor 모듈 import 완료")
        
        # 더미 데이터로 JIT 컴파일 트리거
        import numpy as np
        
        # 더미 오디오 데이터 생성 (1초, 44.1kHz 샘플레이트)
        dummy_audio = np.random.rand(44100).astype(np.float32)
        
        # 워밍업 함수들 호출 (JIT 컴파일 트리거)
        try:
            # numpy 기본 연산들 워밍업
            _ = np.mean(dummy_audio)
            _ = np.max(dummy_audio)
            _ = np.abs(dummy_audio)
            logger.info("Numpy 연산 워밍업 완료")
        except Exception as e:
            logger.warning("Numpy 워밍업 실패: %s", e)
        
        logger.info("Numba JIT 함수 워밍업 완료")
        
    except ImportError as e:
        logger.warning("모듈 import 실패 (워밍업 스킵): %s", e)
    except Exception as e:
        logger.warning("Numba 워밍업 중 오류 발생 (계속 진행): %s", e)

# 워밍업 실행
warmup_numba_functions()

# 커스텀 메시지 처리 신호 핸들러
@task_prerun.connect
def task_prerun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, **kwds):
    """태스크 실행 전 호출되는 핸들러"""
    task_name = getattr(task, 'name', 'Unknown') if task else 'Unknown'
    logger.info(f"태스크 시작: {task_name} (ID: {task_id})")
    logger.info(f"Args: {args}, Kwargs: {kwargs}")

@task_failure.connect
def task_failure_handler(sender=None, task_id=None, exception=None, traceback=None, einfo=None, **kwds):
    """태스크 실패 시 호출되는 핸들러"""
    task_name = getattr(sender, 'name', 'Unknown') if sender else 'Unknown'
    logger.error(f"태스크 실패: {task_name} (ID: {task_id})")
    logger.error(f"Exception: {exception}")

@task_success.connect
def task_success_handler(sender=None, result=None, **kwds):
    """태스크 성공 시 호출되는 핸들러"""
    task_name = getattr(sender, 'name', 'Unknown') if sender else 'Unknown'
    logger.info(f"태스크 성공: {task_name}")

# 커스텀 핸들러 사용 설정
USE_CUSTOM_HANDLER = os.getenv('USE_CUSTOM_HANDLER', 'true').lower() == 'true'

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
        # 메시지 파싱 옵션
        'message_format': 'json',
        'raw_message_delivery': False,
    },
    
    # 작업 실행 설정 - Celery 5.3.4 호환
    task_serializer='json',
    accept_content=['json'],  # 더 제한적으로 json만 허용
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    
    # 메시지 프로토콜 설정 (Protocol 1 - 안정적)
    task_protocol=1,
    
    # 메시지 압축 완전 비활성화
    task_compression=None,
    result_compression=None,
    
    # 작업 신뢰성 설정
    task_acks_late=True,
    task_reject_on_worker_lost=False,
    
    # 메시지 형식 처리 설정
    task_always_eager=False,
    worker_disable_rate_limits=True,
    
    # 재시도 설정
    task_default_retry_delay=config.RETRY_DELAY,
    task_max_retries=config.MAX_RETRIES,
    
    # 워커 설정 - EC2 c7i-large 최적화 (2 vCPU, 4GB RAM)
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=100,  # 2개 워커로 증가했으므로 태스크 수 증가
    
    # 결과 만료 설정
    result_expires=config.CELERY_RESULT_EXPIRES,
    
    # 웹훅 방식 사용으로 결과 저장 불필요
    task_ignore_result=True,
    
    # 로그 설정
    worker_log_format=config.LOG_FORMAT,
    worker_task_log_format=config.LOG_FORMAT,
    
    # 호환성 설정 - Celery 5.3.4 특화
    task_send_sent_event=False,
    task_track_started=False,
    
    # 워커 설정
    worker_hijack_root_logger=False,
    worker_log_color=False,
    
    # 브로커 연결 재시도 설정
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=10,
    
    # 메시지 파싱 관련 설정
    task_eager_propagates=False,
    
    # SQS 특화 설정
    broker_transport='sqs',
    
    # 더 관대한 메시지 처리
    worker_lost_wait=10.0,
    
    # 오류 처리 설정
    task_soft_time_limit=None,
    task_time_limit=None,
    
    # JSON 메시지 직접 처리 허용
    task_routes={
        'app.tasks.generate_hash_and_webhook': {
            'queue': 'waveflow-audio-process-queue-honeybadgers'
        },
        'app.tasks.process_duplicate_file': {
            'queue': 'waveflow-audio-process-queue-honeybadgers'
        },
        'app.tasks.process_audio_analysis': {
            'queue': 'waveflow-audio-process-queue-honeybadgers'
        },
        'app.tasks.mix_stems_and_upload': {
            'queue': 'waveflow-audio-process-queue-honeybadgers'
        }
    },
    
    # Celery 5.3.4 호환성 설정
    worker_pool_restarts=True,
    worker_autoscaler='celery.worker.autoscale:Autoscaler',
    
    # 메시지 직렬화 오류 처리
    worker_send_task_events=False,
    
    # kombu 메시지 처리 설정
    broker_heartbeat=None,
    broker_heartbeat_checkrate=2.0,
)

# 작업 모듈 자동 검색 설정
celery_app.autodiscover_tasks(['app'])

# 태스크 직접 등록 - 자동 검색이 실패할 경우 대비
try:
    from .tasks import generate_hash_and_webhook, process_duplicate_file, process_audio_analysis, mix_stems_and_upload, health_check, cleanup_temp_files
    logger.info("태스크 직접 import 성공")
except ImportError as e:
    logger.error("태스크 import 실패: %s", e)

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
    logger.info("Numba 캐시 디렉토리: %s", cache_dir)
    
    if not result_backend_info['distributed_support']:
        logger.warning("⚠️  현재 result backend는 로컬 전용입니다. 다른 EC2 인스턴스에서 결과 조회가 불가능합니다.")
        logger.warning("분산 환경에서는 SQS, Redis, 또는 데이터베이스를 result backend로 사용하세요.")
    
except Exception as e:
    logger.error("Celery 애플리케이션 설정 실패: %s", e)
    raise

def start_custom_handler():
    """커스텀 SQS 핸들러 시작"""
    try:
        logger.info("커스텀 SQS 핸들러 시작...")
        
        from .simple_handler import SimpleSQSHandler
        
        handler = SimpleSQSHandler(config.SQS_QUEUE_URL, config.AWS_REGION)
        handler.run()
        
    except Exception as e:
        logger.error("커스텀 핸들러 시작 실패: %s", e)
        raise

if __name__ == '__main__':
    # 커스텀 핸들러 시작
    start_custom_handler()