"""
Celery 태스크 정의 모듈
오디오 파일 처리를 위한 비동기 작업들을 정의합니다.
"""

import os
import logging
import tempfile
import uuid
from celery import current_task
from celery.exceptions import Retry
from .celery_app import celery_app
from .audio_processor import AudioProcessor
from .aws_utils import aws_utils

logger = logging.getLogger(__name__)

@celery_app.task(bind=True)
def process_audio_file(self, userId: str = None, trackId: str = None, filepath: str = None, 
                      stemId: str = None, timestamp: str = None, 
                      job_id: str = None, s3_path: str = None, original_filename: str = None, 
                      num_peaks: int = None):
    """
    오디오 파일 처리 메인 태스크
    
    Args:
        userId: 사용자 ID
        trackId: 트랙 ID  
        filepath: S3 파일 경로
        stemId: 스템 ID
        timestamp: 타임스탬프
        job_id: 작업 고유 ID (선택)
        s3_path: S3 경로 (선택)
        original_filename: 원본 파일명 (선택)
        num_peaks: 생성할 파형 피크 개수 (선택)
        
    Returns:
        dict: 처리 결과
    """
    task_id = self.request.id
    local_filepath = None
    waveform_filepath = None
    
    # 파라미터 정리
    job_id = job_id or stemId or task_id
    s3_path = s3_path or filepath
    
    try:
        logger.info("오디오 파일 처리 시작: userId=%s, trackId=%s, stemId=%s, filepath=%s", 
                   userId, trackId, stemId, filepath)
        
        # 1. 임시 파일 생성
        with tempfile.NamedTemporaryFile(delete=False, suffix='.audio') as tmp_file:
            local_filepath = tmp_file.name
        
        # 2. S3에서 오디오 파일 다운로드
        logger.info("S3에서 파일 다운로드 시작: %s", s3_path)
        if not aws_utils.download_from_s3(s3_path, local_filepath):
            raise Exception("S3 파일 다운로드 실패")
        
        # 3. 오디오 파일 처리
        logger.info("오디오 파일 처리 시작")
        processor = AudioProcessor(local_filepath)
        
        # 모든 처리 과정 실행
        result = processor.process_all(num_peaks)
        
        # 4. 파형 데이터를 임시 파일로 저장
        waveform_filename = f"{job_id}_waveform_{uuid.uuid4().hex[:8]}.json"
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as tmp_waveform:
            waveform_filepath = tmp_waveform.name
            tmp_waveform.write(processor.generate_waveform_json(num_peaks))
        
        # 5. 파형 데이터를 S3에 업로드 (같은 버킷에 waveforms 폴더로)
        waveform_s3_path = f"waveforms/{waveform_filename}"
        logger.info("파형 데이터 S3 업로드 시작: %s", waveform_s3_path)
        
        if not aws_utils.upload_to_s3(waveform_filepath, waveform_s3_path):
            raise Exception("파형 데이터 S3 업로드 실패")
        
        # 6. 웹훅으로 결과 전송 (아래에서 처리)
        
        # 7. 처리 결과 반환
        final_result = {
            'job_id': job_id,
            'task_id': task_id,
            'status': 'success',
            'audio_data_hash': result['audio_data_hash'],
            'waveform_data_path': waveform_s3_path,
            'file_size': result['file_size'],
            'duration': result['duration'],
            'sample_rate': result['sample_rate'],
            'num_peaks': result['num_peaks'],
            'mime_type': result['mime_type'],
            'processed_at': result['processed_at']
        }
        
        # 8. 웹서버로 완료 알림 전송
        try:
            from .webhook import send_completion_webhook
            send_completion_webhook(job_id, final_result, "SUCCESS")
        except Exception as e:
            logger.warning("Webhook 전송 실패: %s", e)
        
        logger.info("오디오 파일 처리 완료: job_id=%s", job_id)
        return final_result
        
    except Exception as e:
        logger.error("오디오 파일 처리 실패: job_id=%s, error=%s", job_id, str(e))
        
        # 웹훅으로 에러 전송
        try:
            from .webhook import send_completion_webhook
            error_result = {
                'job_id': job_id,
                'error_message': str(e),
                'error_code': type(e).__name__,
                'timestamp': aws_utils._get_current_timestamp()
            }
            send_completion_webhook(job_id, error_result, "FAILURE")
        except Exception as webhook_error:
            logger.warning("웹훅 에러 전송 실패: %s", webhook_error)
        
        # 재시도 로직
        if self.request.retries < self.max_retries:
            logger.info("작업 재시도 예약: job_id=%s, retry=%d/%d", 
                       job_id, self.request.retries + 1, self.max_retries)
            
            # 지수 백오프 적용
            countdown = min(60 * (2 ** self.request.retries), 300)  # 최대 5분
            
            raise self.retry(exc=e, countdown=countdown)
        
        # 최대 재시도 횟수 초과
        logger.error("최대 재시도 횟수 초과: job_id=%s", job_id)
        raise
        
    finally:
        # 임시 파일 정리
        try:
            if local_filepath and os.path.exists(local_filepath):
                os.unlink(local_filepath)
                logger.debug("임시 오디오 파일 삭제: %s", local_filepath)
        except Exception as e:
            logger.warning("임시 오디오 파일 삭제 실패: %s", e)
        
        try:
            if waveform_filepath and os.path.exists(waveform_filepath):
                os.unlink(waveform_filepath)
                logger.debug("임시 파형 파일 삭제: %s", waveform_filepath)
        except Exception as e:
            logger.warning("임시 파형 파일 삭제 실패: %s", e)


@celery_app.task(name='health_check', bind=True)
def health_check(self):
    """
    워커 상태 확인을 위한 헬스 체크 태스크
    
    Returns:
        dict: 워커 상태 정보
    """
    try:
        logger.info("헬스 체크 실행: task_id=%s", self.request.id)
        
        # 기본 상태 정보
        status = {
            'status': 'healthy',
            'task_id': self.request.id,
            'worker_id': self.request.hostname,
            'timestamp': aws_utils._get_current_timestamp()
        }
        
        # AWS 서비스 연결 테스트
        try:
            # S3 연결 테스트 (버킷 존재 확인)
            aws_utils.s3_client.head_bucket(Bucket=aws_utils.config.S3_BUCKET_NAME)
            status['s3_connection'] = 'ok'
        except Exception as e:
            status['s3_connection'] = f'error: {str(e)}'
        
        try:
            # SQS 연결 테스트 (작업 큐 속성 확인)
            aws_utils.sqs_client.get_queue_attributes(
                QueueUrl=aws_utils.config.SQS_QUEUE_URL,
                AttributeNames=['QueueArn']
            )
            status['sqs_connection'] = 'ok'
        except Exception as e:
            status['sqs_connection'] = f'error: {str(e)}'
        
        logger.info("헬스 체크 완료: %s", status)
        return status
        
    except Exception as e:
        logger.error("헬스 체크 실패: %s", e)
        return {
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': aws_utils._get_current_timestamp()
        }


@celery_app.task(name='cleanup_temp_files', bind=True)
def cleanup_temp_files(self):
    """
    임시 파일 정리 태스크
    시스템의 임시 파일을 정리합니다.
    
    Returns:
        dict: 정리 결과
    """
    try:
        logger.info("임시 파일 정리 시작: task_id=%s", self.request.id)
        
        temp_dir = tempfile.gettempdir()
        cleaned_count = 0
        error_count = 0
        
        # 임시 디렉토리에서 오래된 파일 찾기
        import time
        current_time = time.time()
        max_age = 3600  # 1시간
        
        for filename in os.listdir(temp_dir):
            filepath = os.path.join(temp_dir, filename)
            
            # 우리가 생성한 임시 파일만 대상으로 함
            if not (filename.startswith('tmp') and 
                   (filename.endswith('.audio') or filename.endswith('.json'))):
                continue
            
            try:
                if os.path.isfile(filepath):
                    file_age = current_time - os.path.getmtime(filepath)
                    if file_age > max_age:
                        os.unlink(filepath)
                        cleaned_count += 1
                        logger.debug("임시 파일 삭제: %s", filepath)
            except Exception as e:
                error_count += 1
                logger.warning("임시 파일 삭제 실패: %s, error: %s", filepath, e)
        
        result = {
            'status': 'completed',
            'cleaned_count': cleaned_count,
            'error_count': error_count,
            'timestamp': aws_utils._get_current_timestamp()
        }
        
        logger.info("임시 파일 정리 완료: %s", result)
        return result
        
    except Exception as e:
        logger.error("임시 파일 정리 실패: %s", e)
        return {
            'status': 'error',
            'error': str(e),
            'timestamp': aws_utils._get_current_timestamp()
        } 