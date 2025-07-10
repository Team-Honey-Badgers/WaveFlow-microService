"""
Celery 태스크 정의 모듈
오디오 파일 처리를 위한 비동기 작업들을 정의합니다.
새로운 워크플로우: 해시 생성 -> 웹훅 -> 중복 검사 결과에 따른 분기 처리
"""

import os
import logging
import tempfile
import uuid
import hashlib
from celery import current_task
from celery.exceptions import Retry
from .celery_app import celery_app
from .audio_processor import AudioProcessor
from .aws_utils import aws_utils

logger = logging.getLogger(__name__)

@celery_app.task(name='app.tasks.generate_hash_and_webhook', bind=True)
def generate_hash_and_webhook(self, userId: str = None, trackId: str = None, 
                             stemId: str = None, filepath: str = None, 
                             timestamp: str = None, original_filename: str = None,
                             sessionId: str = None, file_name: str = None,
                             key: str = None, tag: str = None, 
                             description: str = None, category_id: str = None):
    """
    1단계: 해시 생성 및 웹훅 전송 테스크
    S3에서 파일을 다운로드하여 해시를 생성하고, 웹훅으로 NestJS 서버에 전송
    NestJS에서 중복 검사 후 중복이 아니면 DB 레코드 생성
    
    Args:
        userId: 사용자 ID
        trackId: 트랙 ID
        stemId: 임시 스템 ID (DB 레코드 생성 후 실제 ID로 변경됨)
        filepath: S3 파일 경로
        timestamp: 타임스탬프
        original_filename: 원본 파일명
        sessionId: 세션 ID
        file_name: 파일명
        key: 사용자 입력 키
        tag: 사용자 입력 태그
        description: 사용자 입력 설명
        category_id: 카테고리 ID
        
    Returns:
        dict: 처리 결과 (해시값 포함)
    """
    task_id = self.request.id
    local_filepath = None
    
    logger.info("====== 해시 생성 및 웹훅 전송 테스크 시작 ======")
    logger.info(f"Task ID: {task_id}")
    logger.info(f"입력 파라미터:")
    logger.info(f"  - userId: {userId}")
    logger.info(f"  - trackId: {trackId}")
    logger.info(f"  - stemId: {stemId}")
    logger.info(f"  - filepath: {filepath}")
    logger.info(f"  - timestamp: {timestamp}")
    logger.info(f"  - sessionId: {sessionId}")
    logger.info(f"  - file_name: {file_name}")
    logger.info(f"  - category_id: {category_id}")
    logger.info("===========================================")
    
    try:
        # 1. 임시 파일 생성
        file_ext = os.path.splitext(filepath)[1] or '.wav'
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:
            local_filepath = tmp_file.name
        
        # 2. S3에서 오디오 파일 다운로드
        logger.info("S3에서 파일 다운로드 시작: %s", filepath)
        if not aws_utils.download_from_s3(filepath, local_filepath):
            raise Exception("S3 파일 다운로드 실패")
        
        # 3. 파일 해시 생성
        logger.info("파일 해시 생성 시작")
        audio_hash = generate_file_hash(local_filepath)
        logger.info(f"생성된 해시: {audio_hash}")
        
        # 4. 웹훅으로 해시 전송
        webhook_result = {
            'task_id': task_id,
            'userId': userId,
            'trackId': trackId,
            'stemId': stemId,
            'filepath': filepath,
            'audio_hash': audio_hash,
            'timestamp': timestamp,
            'original_filename': original_filename,
            'sessionId': sessionId,
            'file_name': file_name,
            'key': key,
            'tag': tag,
            'description': description,
            'category_id': category_id,
            'status': 'hash_generated'
        }
        
        logger.info("웹훅 전송 시작")
        try:
            from .webhook import send_hash_webhook
            send_hash_webhook(stemId, webhook_result)
            logger.info("웹훅 전송 완료")
        except Exception as e:
            logger.error("웹훅 전송 실패: %s", e)
            raise
        
        # 5. 결과 반환 (S3 파일 경로만 포함, 임시 파일은 제외)
        result = {
            'task_id': task_id,
            'stemId': stemId,
            'audio_hash': audio_hash,
            'filepath': filepath,  # S3 파일 경로만 포함
            'status': 'hash_sent_to_webhook',
            'processed_at': aws_utils._get_current_timestamp()
        }
        
        logger.info("해시 생성 및 웹훅 전송 완료: stemId=%s, hash=%s", stemId, audio_hash)
        return result
        
    except Exception as e:
        logger.error("해시 생성 및 웹훅 전송 실패: stemId=%s, error=%s", stemId, str(e))
        
        # 재시도 로직
        if self.request.retries < self.max_retries:
            logger.info("작업 재시도 예약: stemId=%s, retry=%d/%d", 
                       stemId, self.request.retries + 1, self.max_retries)
            countdown = min(60 * (2 ** self.request.retries), 300)
            raise self.retry(exc=e, countdown=countdown)
        
        logger.error("최대 재시도 횟수 초과: stemId=%s", stemId)
        raise
        
    finally:
        # EC2 임시 파일 정리 (성공/실패와 관계없이 실행)
        if local_filepath and os.path.exists(local_filepath):
            try:
                os.unlink(local_filepath)
                logger.info("EC2 임시 파일 정리 완료: %s", local_filepath)
            except Exception as cleanup_error:
                logger.warning("EC2 임시 파일 정리 실패: %s", cleanup_error)


@celery_app.task(name='app.tasks.process_duplicate_file', bind=True)
def process_duplicate_file(self, userId: str = None, trackId: str = None, 
                          stemId: str = None, filepath: str = None, 
                          audio_hash: str = None):
    """
    2단계: 중복 파일 처리 테스크
    중복된 해시값이 있는 경우 S3에서 파일을 삭제
    
    Args:
        userId: 사용자 ID
        trackId: 트랙 ID
        stemId: 스템 ID
        filepath: S3 파일 경로
        audio_hash: 오디오 해시값
        
    Returns:
        dict: 처리 결과
    """
    task_id = self.request.id
    
    logger.info("====== 중복 파일 처리 테스크 시작 ======")
    logger.info(f"Task ID: {task_id}")
    logger.info(f"입력 파라미터:")
    logger.info(f"  - userId: {userId}")
    logger.info(f"  - trackId: {trackId}")
    logger.info(f"  - stemId: {stemId}")
    logger.info(f"  - filepath: {filepath}")
    logger.info(f"  - audio_hash: {audio_hash}")
    logger.info("====================================")
    
    try:
        # 1. S3에서 중복 파일 삭제
        logger.info("S3에서 중복 파일 삭제 시작: %s", filepath)
        if not aws_utils.delete_from_s3(filepath):
            raise Exception("S3 파일 삭제 실패")
        
        # 2. 처리 결과 반환
        result = {
            'task_id': task_id,
            'stemId': stemId,
            'audio_hash': audio_hash,
            'filepath': filepath,
            'status': 'duplicate_file_deleted',
            'processed_at': aws_utils._get_current_timestamp()
        }
        
        # 3. 웹훅으로 완료 알림 전송
        try:
            from .webhook import send_completion_webhook
            send_completion_webhook(stemId, result, "SUCCESS")
        except Exception as e:
            logger.warning("웹훅 전송 실패: %s", e)
        
        logger.info("중복 파일 처리 완료: stemId=%s", stemId)
        return result
        
    except Exception as e:
        logger.error("중복 파일 처리 실패: stemId=%s, error=%s", stemId, str(e))
        
        # 재시도 로직
        if self.request.retries < self.max_retries:
            logger.info("작업 재시도 예약: stemId=%s, retry=%d/%d", 
                       stemId, self.request.retries + 1, self.max_retries)
            countdown = min(60 * (2 ** self.request.retries), 300)
            raise self.retry(exc=e, countdown=countdown)
        
        logger.error("최대 재시도 횟수 초과: stemId=%s", stemId)
        raise


@celery_app.task(name='app.tasks.process_audio_analysis', bind=True)
def process_audio_analysis(self, userId: str = None, trackId: str = None, 
                          stemId: str = None, filepath: str = None, 
                          audio_hash: str = None, timestamp: str = None,
                          original_filename: str = None, num_peaks: int = None,
                          sessionId: str = None):
    """
    3단계: 오디오 분석 테스크
    오디오 파일을 분석하여 파형 데이터를 생성하고 S3에 저장
    
    Args:
        userId: 사용자 ID
        trackId: 트랙 ID
        stemId: 스템 ID
        filepath: S3 파일 경로
        audio_hash: 오디오 해시값
        timestamp: 타임스탬프
        original_filename: 원본 파일명
        num_peaks: 생성할 파형 피크 개수
        sessionId: 세션 ID
        
    Returns:
        dict: 처리 결과
    """
    task_id = self.request.id
    local_filepath = None
    waveform_filepath = None
    
    logger.info("====== 오디오 분석 테스크 시작 ======")
    logger.info(f"Task ID: {task_id}")
    logger.info(f"입력 파라미터:")
    logger.info(f"  - userId: {userId}")
    logger.info(f"  - trackId: {trackId}")
    logger.info(f"  - stemId: {stemId}")
    logger.info(f"  - filepath: {filepath}")
    logger.info(f"  - audio_hash: {audio_hash}")
    logger.info(f"  - num_peaks: {num_peaks}")
    logger.info(f"  - sessionId: {sessionId}")
    logger.info("=================================")
    
    try:
        # 1. 임시 파일 생성
        file_ext = os.path.splitext(filepath)[1] or '.wav'
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:
            local_filepath = tmp_file.name
        
        # 2. S3에서 오디오 파일 다운로드
        logger.info("S3에서 파일 다운로드 시작: %s", filepath)
        if not aws_utils.download_from_s3(filepath, local_filepath):
            raise Exception("S3 파일 다운로드 실패")
        
        # 3. 오디오 파일 분석
        logger.info("오디오 파일 분석 시작")
        processor = AudioProcessor(local_filepath)
        
        # 모든 분석 과정 실행
        result = processor.process_all(num_peaks)
        
        # 4. 파형 데이터를 임시 파일로 저장
        waveform_filename = f"{stemId}_waveform_{uuid.uuid4().hex[:8]}.json"
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as tmp_waveform:
            waveform_filepath = tmp_waveform.name
            tmp_waveform.write(processor.generate_waveform_json(num_peaks))
        
        # 5. 파형 데이터를 S3에 업로드
        waveform_s3_path = f"waveforms/{waveform_filename}"
        logger.info("파형 데이터 S3 업로드 시작: %s", waveform_s3_path)
        
        if not aws_utils.upload_to_s3(waveform_filepath, waveform_s3_path):
            raise Exception("파형 데이터 S3 업로드 실패")
        
        # 6. 처리 결과 반환
        final_result = {
            'task_id': task_id,
            'stemId': stemId,
            'status': 'success',
            'audio_data_hash': audio_hash,
            'waveform_data_path': waveform_s3_path,
            'file_size': result['file_size'],
            'duration': result['duration'],
            'sample_rate': result['sample_rate'],
            'num_peaks': result['num_peaks'],
            'mime_type': result['mime_type'],
            'processed_at': result['processed_at']
        }
        
        # 7. 웹서버로 완료 알림 전송
        try:
            from .webhook import send_completion_webhook
            send_completion_webhook(stemId, final_result, "SUCCESS")
        except Exception as e:
            logger.warning("웹훅 전송 실패: %s", e)
        
        logger.info("오디오 분석 완료: stemId=%s", stemId)
        return final_result
        
    except Exception as e:
        logger.error("오디오 분석 실패: stemId=%s, error=%s", stemId, str(e))
        
        # 웹훅으로 에러 전송
        try:
            from .webhook import send_completion_webhook
            error_result = {
                'stemId': stemId,
                'error_message': str(e),
                'error_code': type(e).__name__,
                'timestamp': aws_utils._get_current_timestamp()
            }
            send_completion_webhook(stemId, error_result, "FAILURE")
        except Exception as webhook_error:
            logger.warning("웹훅 에러 전송 실패: %s", webhook_error)
        
        # 재시도 로직
        if self.request.retries < self.max_retries:
            logger.info("작업 재시도 예약: stemId=%s, retry=%d/%d", 
                       stemId, self.request.retries + 1, self.max_retries)
            countdown = min(60 * (2 ** self.request.retries), 300)
            raise self.retry(exc=e, countdown=countdown)
        
        logger.error("최대 재시도 횟수 초과: stemId=%s", stemId)
        raise
        
    finally:
        # ⚠️ 중요: S3 원본 파일은 절대 삭제하지 않음!
        # EC2 내의 임시 파일들만 정리
        
        # 1. 로컬 임시 오디오 파일 정리
        try:
            if local_filepath and os.path.exists(local_filepath):
                os.unlink(local_filepath)
                logger.info("EC2 임시 오디오 파일 정리 완료: %s", local_filepath)
        except Exception as e:
            logger.warning("EC2 임시 오디오 파일 정리 실패: %s", e)
        
        # 2. 로컬 임시 파형 파일 정리
        try:
            if waveform_filepath and os.path.exists(waveform_filepath):
                os.unlink(waveform_filepath)
                logger.info("EC2 임시 파형 파일 정리 완료: %s", waveform_filepath)
        except Exception as e:
            logger.warning("EC2 임시 파형 파일 정리 실패: %s", e)
        
        # 3. 추가 임시 파일 정리 (AudioProcessor에서 생성될 수 있는 파일들)
        try:
            import glob
            temp_dir = tempfile.gettempdir()
            
            # stemId가 None이 아닌 경우에만 패턴 검색
            if stemId:
                temp_pattern = f"tmp*{stemId}*"
                for temp_file in glob.glob(os.path.join(temp_dir, temp_pattern)):
                    if os.path.exists(temp_file):
                        os.unlink(temp_file)
                        logger.debug("추가 임시 파일 정리: %s", temp_file)
            else:
                logger.debug("stemId가 None이므로 패턴 기반 임시 파일 정리 건너뜀")
        except Exception as e:
            logger.warning("추가 임시 파일 정리 실패: %s", e)
        
        # 📝 참고: S3 원본 파일 (filepath)은 보존됨
        logger.info("S3 원본 파일 보존됨: %s", filepath)


def generate_file_hash(filepath: str) -> str:
    """
    파일의 해시값을 생성합니다.
    
    Args:
        filepath: 파일 경로
        
    Returns:
        str: SHA-256 해시값
    """
    hash_sha256 = hashlib.sha256()
    
    with open(filepath, "rb") as f:
        # 큰 파일을 위해 청크 단위로 읽기
        for chunk in iter(lambda: f.read(4096), b""):
            hash_sha256.update(chunk)
    
    return hash_sha256.hexdigest()


# 기존 테스크들 (호환성 유지)
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
    EC2 임시 파일 정리 태스크
    오디오 처리 과정에서 생성된 임시 파일들을 정리합니다.
    
    Returns:
        dict: 정리 결과
    """
    try:
        logger.info("EC2 임시 파일 정리 시작: task_id=%s", self.request.id)
        
        temp_dir = tempfile.gettempdir()
        cleaned_count = 0
        error_count = 0
        total_size_cleaned = 0
        
        # 임시 디렉토리에서 오래된 파일 찾기
        import time
        current_time = time.time()
        max_age = 1800  # 30분 (오디오 처리 후 충분한 시간)
        
        # 오디오 처리 관련 임시 파일 패턴들
        audio_extensions = ['.wav', '.mp3', '.flac', '.ogg', '.m4a', '.aac']
        temp_patterns = [
            'tmp',          # tempfile 모듈 기본 prefix
            'audio_',       # 오디오 관련 임시 파일
            'waveform_',    # 파형 관련 임시 파일
            'stem'          # stem 관련 임시 파일
        ]
        
        for filename in os.listdir(temp_dir):
            filepath = os.path.join(temp_dir, filename)
            
            # 파일인지 확인
            if not os.path.isfile(filepath):
                continue
            
            # 우리가 생성한 임시 파일인지 확인
            is_our_temp_file = False
            
            # 패턴 기반 확인
            for pattern in temp_patterns:
                if filename.startswith(pattern):
                    is_our_temp_file = True
                    break
            
            # 확장자 기반 확인 (오디오 파일)
            if not is_our_temp_file:
                for ext in audio_extensions:
                    if filename.endswith(ext) and (filename.startswith('tmp') or 'temp' in filename.lower()):
                        is_our_temp_file = True
                        break
            
            # JSON 파형 파일 확인
            if not is_our_temp_file and filename.endswith('.json'):
                if any(keyword in filename for keyword in ['waveform', 'peaks', 'audio']):
                    is_our_temp_file = True
            
            if not is_our_temp_file:
                continue
            
            try:
                # 파일 나이 확인
                file_age = current_time - os.path.getmtime(filepath)
                if file_age > max_age:
                    # 파일 크기 기록
                    file_size = os.path.getsize(filepath)
                    
                    # 파일 삭제
                    os.unlink(filepath)
                    cleaned_count += 1
                    total_size_cleaned += file_size
                    
                    logger.debug("임시 파일 정리: %s (크기: %d bytes, 나이: %.1f분)", 
                               filepath, file_size, file_age / 60)
                    
            except Exception as e:
                error_count += 1
                logger.warning("임시 파일 정리 실패: %s, error: %s", filepath, e)
        
        # 추가: 매우 오래된 파일들 강제 정리 (2시간 이상)
        very_old_age = 7200  # 2시간
        very_old_cleaned = 0
        
        try:
            import glob
            # 매우 오래된 임시 파일들 찾기
            for pattern in ['tmp*', 'audio_*', 'waveform_*']:
                for filepath in glob.glob(os.path.join(temp_dir, pattern)):
                    if os.path.isfile(filepath):
                        file_age = current_time - os.path.getmtime(filepath)
                        if file_age > very_old_age:
                            try:
                                file_size = os.path.getsize(filepath)
                                os.unlink(filepath)
                                very_old_cleaned += 1
                                total_size_cleaned += file_size
                                logger.info("매우 오래된 임시 파일 강제 정리: %s", filepath)
                            except Exception:
                                pass
        except Exception as e:
            logger.warning("매우 오래된 파일 정리 중 오류: %s", e)
        
        result = {
            'status': 'completed',
            'cleaned_count': cleaned_count + very_old_cleaned,
            'error_count': error_count,
            'total_size_cleaned_bytes': total_size_cleaned,
            'total_size_cleaned_mb': round(total_size_cleaned / (1024 * 1024), 2),
            'max_age_minutes': max_age / 60,
            'temp_directory': temp_dir,
            'timestamp': aws_utils._get_current_timestamp()
        }
        
        logger.info("EC2 임시 파일 정리 완료: %d개 파일 정리 (%.2f MB)", 
                   result['cleaned_count'], result['total_size_cleaned_mb'])
        return result
        
    except Exception as e:
        logger.error("EC2 임시 파일 정리 실패: %s", e)
        return {
            'status': 'error',
            'error': str(e),
            'timestamp': aws_utils._get_current_timestamp()
        } 