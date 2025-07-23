"""
Celery 태스크 정의 모듈
오디오 파일 처리를 위한 비동기 작업들을 정의합니다.
새로운 워크플로우: 해시 생성 -> 웹훅 -> 중복 검사 결과에 따른 분기 처리
믹싱 작업: 여러 스템 파일들을 하나의 믹싱된 오디오 파일로 생성
"""

import os
import logging
import tempfile
import uuid
import hashlib
from typing import Optional, List
import numpy as np
import librosa
import soundfile as sf
import psutil
from celery import current_task
from celery.exceptions import Retry
from .celery_app import celery_app
from .audio_processor import AudioProcessor
from .aws_utils import aws_utils

logger = logging.getLogger(__name__)

def log_memory_usage(task_name: str, stage: str):
    """메모리 사용량 로깅"""
    try:
        process = psutil.Process()
        memory_info = process.memory_info()
        memory_percent = process.memory_percent()
        
        logger.info(f"[{task_name}] {stage} - 메모리 사용량: {memory_info.rss / 1024 / 1024:.1f}MB ({memory_percent:.1f}%)")
    except Exception as e:
        logger.warning(f"메모리 사용량 로깅 실패: {e}")

@celery_app.task(name='app.tasks.generate_hash_and_webhook', bind=True)
def generate_hash_and_webhook(self, userId: Optional[str] = None, trackId: Optional[str] = None, 
                             stemId: Optional[str] = None, stageId: Optional[str] = None,
                             filepath: Optional[str] = None, timestamp: Optional[str] = None, 
                             original_filename: Optional[str] = None):
    """
    1단계: 해시 생성 및 웹훅 전송 테스크
    S3에서 파일을 다운로드하여 해시를 생성하고, 웹훅으로 NestJS 서버에 전송
    
    Args:
        userId: 사용자 ID
        trackId: 트랙 ID
        stemId: 스템 ID
        stageId: 스테이지 ID (새로 추가)
        filepath: S3 파일 경로
        timestamp: 타임스탬프
        original_filename: 원본 파일명
        
    Returns:
        dict: 처리 결과 (해시값 포함)
    """
    task_id = self.request.id
    local_filepath = None
    
    log_memory_usage("generate_hash_and_webhook", "시작")
    
    logger.info("====== 해시 생성 및 웹훅 전송 테스크 시작 ======")
    logger.info(f"Task ID: {task_id}")
    logger.info(f"입력 파라미터:")
    logger.info(f"  - userId: {userId}")
    logger.info(f"  - trackId: {trackId}")
    logger.info(f"  - stemId: {stemId}")
    logger.info(f"  - stageId: {stageId}")
    logger.info(f"  - filepath: {filepath}")
    logger.info(f"  - timestamp: {timestamp}")
    logger.info("===========================================")
    
    try:
        # 필수 파라미터 검증
        if not filepath:
            raise ValueError("filepath는 필수 파라미터입니다.")
        if not stemId:
            raise ValueError("stemId는 필수 파라미터입니다.")
        
        # 1. 임시 파일 생성
        file_ext = os.path.splitext(filepath)[1] or '.wav'
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:
            local_filepath = tmp_file.name
        
        # 2. S3에서 오디오 파일 다운로드
        logger.info("S3에서 파일 다운로드 시작: %s", filepath)
        if not aws_utils.download_from_s3(filepath, local_filepath):
            raise Exception("S3 파일 다운로드 실패")
        
        log_memory_usage("generate_hash_and_webhook", "파일 다운로드 완료")
        
        # 3. 파일 해시 생성
        logger.info("파일 해시 생성 시작")
        audio_hash = generate_file_hash(local_filepath)
        logger.info(f"생성된 해시: {audio_hash}")
        
        log_memory_usage("generate_hash_and_webhook", "해시 생성 완료")
        
        # 4. 웹훅으로 해시 전송
        webhook_result = {
            'task_id': task_id,
            'stemId': stemId,
            'userId': userId,
            'trackId': trackId,
            'filepath': filepath,
            'stageId': stageId,
            'audio_hash': audio_hash,
            'timestamp': timestamp,
            'original_filename': original_filename,
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
            'stageId': stageId,
            'audio_hash': audio_hash,
            'filepath': filepath,  # S3 파일 경로만 포함
            'status': 'hash_sent_to_webhook',
            'processed_at': aws_utils._get_current_timestamp()
        }
        
        log_memory_usage("generate_hash_and_webhook", "완료")
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
        
        log_memory_usage("generate_hash_and_webhook", "정리 완료")


@celery_app.task(name='app.tasks.process_duplicate_file', bind=True)
def process_duplicate_file(self, userId: Optional[str] = None, trackId: Optional[str] = None, 
                          stemId: Optional[str] = None, filepath: Optional[str] = None, 
                          audio_hash: Optional[str] = None):
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
        # 필수 파라미터 검증
        if not filepath:
            raise ValueError("filepath는 필수 파라미터입니다.")
        if not stemId:
            raise ValueError("stemId는 필수 파라미터입니다.")
        
        # 1. S3에서 중복 파일 삭제
        logger.info("S3에서 중복 파일 삭제 시작: %s", filepath)
        if not aws_utils.delete_from_s3(filepath):
            raise Exception("S3 파일 삭제 실패")
        
        # 2. 처리 결과 반환
        result = {
            'task_id': task_id,
            'stemId': stemId,
            'userId': userId,
            'trackId': trackId,
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
def process_audio_analysis(self, userId: Optional[str] = None, trackId: Optional[str] = None, 
                          stemId: Optional[str] = None, filepath: Optional[str] = None, 
                          audio_hash: Optional[str] = None, timestamp: Optional[str] = None,
                          original_filename: Optional[str] = None, num_peaks: int = 4000,
                          upstreamId: Optional[str] = None):
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
        num_peaks: 생성할 파형 피크 개수 (기본값: 4000)
        upstreamId: 업스트림 ID (선택적)
        
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
    logger.info(f"  - upstreamId: {upstreamId}")
    logger.info("=================================")
    
    try:
        # 필수 파라미터 검증
        if not filepath:
            raise ValueError("filepath는 필수 파라미터입니다.")
        if not stemId:
            raise ValueError("stemId는 필수 파라미터입니다.")
        
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
        
        # 4. 분석 결과를 S3에 저장
        logger.info("분석 결과 S3 저장 시작")
        
        # 파형 데이터 파일 생성
        waveform_filename = f"waveforms/{stemId}_waveform_{aws_utils._get_current_timestamp()}.json"
        waveform_json = processor.generate_waveform_json(num_peaks)
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as waveform_file:
            waveform_filepath = waveform_file.name
            waveform_file.write(waveform_json)
        
        # S3에 파형 데이터 업로드
        if not aws_utils.upload_to_s3(waveform_filepath, waveform_filename):
            raise Exception("S3 파형 데이터 업로드 실패")
        
        # 5. 최종 결과 구성
        final_result = {
            'task_id': task_id,
            'stemId': stemId,
            'userId': userId,
            'trackId': trackId,
            'upstreamId': upstreamId,
            'status': 'SUCCESS',
            'result': {
                'audio_data_hash': result['audio_data_hash'],
                'waveform_data_path': waveform_filename,
                'file_size': result['file_size'],
                'duration': result['duration'],
                'sample_rate': result['sample_rate'],
                'num_peaks': result['num_peaks']
            },
            'timestamp': aws_utils._get_current_timestamp(),
            'original_filename': original_filename,
            'processing_time': result.get('processing_time', 0),
            'audio_wave_path': waveform_filename
        }
        
        # 6. 웹훅으로 완료 알림 전송
        try:
            from .webhook import send_completion_webhook
            send_completion_webhook(stemId, final_result, "SUCCESS")
        except Exception as e:
            logger.warning("웹훅 전송 실패: %s", e)
        
        logger.info("오디오 분석 완료: stemId=%s", stemId)
        return final_result
        
    except Exception as e:
        logger.error("오디오 분석 실패: stemId=%s, error=%s", stemId, str(e))
        
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
        for file_path in [local_filepath, waveform_filepath]:
            if file_path and os.path.exists(file_path):
                try:
                    os.unlink(file_path)
                    logger.info("EC2 임시 파일 정리 완료: %s", file_path)
                except Exception as cleanup_error:
                    logger.warning("EC2 임시 파일 정리 실패: %s", cleanup_error)


@celery_app.task(name='app.tasks.mix_stems_and_upload', bind=True)
def mix_stems_and_upload(self, stageId: Optional[str] = None, upstreamId: Optional[str] = None, stem_paths: Optional[List[str]] = None, ):
    """
    믹싱 작업 테스크
    여러 스템 파일들을 다운로드하여 믹싱한 후 S3에 업로드
    
    Args:
        stageId: 스테이지 ID
        upstreamId: 업스트림 ID
        stem_paths: 스템 파일 경로 리스트
        
    Returns:
        dict: 처리 결과
    """
    task_id = self.request.id
    local_files = []
    mixed_file_path = None
    
    logger.info("====== 믹싱 작업 테스크 시작 ======")
    logger.info(f"Task ID: {task_id}")
    logger.info(f"입력 파라미터:")
    logger.info(f"  - stageId: {stageId}")
    logger.info(f"  - upstreamId: {upstreamId}")
    logger.info(f"  - stem_paths: {stem_paths}")
    logger.info(f"  - stem_count: {len(stem_paths) if stem_paths else 0}")
    logger.info("================================")
    
    try:
        if not stem_paths or len(stem_paths) == 0:
            raise ValueError("스템 파일 경로가 제공되지 않았습니다.")
        
        # 1. 모든 스템 파일을 S3에서 다운로드
        logger.info("스템 파일 다운로드 시작")
        audio_data_list = []
        sample_rate = None
        
        for i, stem_path in enumerate(stem_paths):
            # 임시 파일 생성
            file_ext = os.path.splitext(stem_path)[1] or '.wav'
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:
                local_path = tmp_file.name
                local_files.append(local_path)
            
            # S3에서 파일 다운로드
            logger.info(f"스템 파일 다운로드 ({i+1}/{len(stem_paths)}): {stem_path}")
            if not aws_utils.download_from_s3(stem_path, local_path):
                raise Exception(f"스템 파일 다운로드 실패: {stem_path}")
            
            # 오디오 데이터 로드 (AudioProcessor 사용)
            try:
                from .audio_processor import AudioProcessor
                
                # AudioProcessor로 오디오 로드
                processor = AudioProcessor(local_path)
                processor.load_audio_data()
                audio_data = processor.audio_data
                sr = processor.sample_rate
                
                if sample_rate is None:
                    sample_rate = sr
                elif sample_rate != sr:
                    # 샘플레이트가 다른 경우 경고 후 스킵 (임시 조치)
                    logger.warning(f"샘플레이트 불일치로 파일 스킵: {stem_path} (기준: {sample_rate}, 현재: {sr})")
                    continue  # 이 파일은 믹싱에서 제외
                
                audio_data_list.append(audio_data)
                logger.info(f"오디오 로드 완료: {stem_path} (길이: {len(audio_data)}, SR: {sr})")
                
            except Exception as e:
                logger.error(f"오디오 로드 실패: {stem_path}, 오류: {e}")
                raise
        
        # 2. 오디오 믹싱 수행
        logger.info("오디오 믹싱 시작")
        
        # 모든 오디오 데이터의 길이를 동일하게 맞춤
        max_length = max(len(audio) for audio in audio_data_list if audio is not None)
        
        # 패딩 및 믹싱
        mixed_audio = np.zeros(max_length, dtype=np.float32)
        
        for i, audio_data in enumerate(audio_data_list):
            # 길이가 짧은 오디오는 패딩
            if len(audio_data) < max_length:
                padded_audio = np.pad(audio_data, (0, max_length - len(audio_data)), 'constant')
            else:
                padded_audio = audio_data
            
            # 믹싱 (단순 덧셈)
            mixed_audio += padded_audio
            logger.info(f"스템 {i+1} 믹싱 완료")
        
        # 3. 볼륨 정규화 (클리핑 방지)
        if len(audio_data_list) > 1:
            mixed_audio = mixed_audio / len(audio_data_list)
        
        # 클리핑 방지를 위한 추가 정규화
        max_val = np.max(np.abs(mixed_audio))
        if max_val > 0.95:
            mixed_audio = mixed_audio * (0.95 / max_val)
        
        logger.info(f"믹싱 완료: 최종 길이 {len(mixed_audio)}, 최대값 {np.max(np.abs(mixed_audio))}")
        
        # 4. 믹싱된 파일을 임시 파일로 저장
        with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as tmp_mixed:
            mixed_file_path = tmp_mixed.name
        
        # WAV 파일로 저장
        sf.write(mixed_file_path, mixed_audio, sample_rate)
        logger.info(f"믹싱된 파일 저장 완료: {mixed_file_path}")
        
        # 5. S3에 업로드
        s3_mixed_path = f"mixed/{stageId}_mixed_{aws_utils._get_current_timestamp()}.wav"
        logger.info(f"S3 업로드 시작: {s3_mixed_path}")
        
        if not aws_utils.upload_to_s3(mixed_file_path, s3_mixed_path):
            raise Exception("S3 믹싱 파일 업로드 실패")
        
        # 6. 믹싱된 파일의 파형 분석
        logger.info("믹싱된 파일 파형 분석 시작")
        waveform_data_path = None
        
        try:
            from .audio_processor import AudioProcessor
            
            # 오디오 프로세서로 파형 분석
            processor = AudioProcessor(mixed_file_path)
            waveform_json = processor.generate_waveform_json(4000)  # 4000개 피크 생성
            
            # 파형 데이터를 S3에 저장
            waveform_filename = f"waveforms/{stageId}_mixed_waveform_{aws_utils._get_current_timestamp()}.json"
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as waveform_file:
                waveform_filepath = waveform_file.name
                waveform_file.write(waveform_json)
            
            # S3에 파형 데이터 업로드
            if aws_utils.upload_to_s3(waveform_filepath, waveform_filename):
                waveform_data_path = waveform_filename
                logger.info(f"파형 데이터 S3 업로드 완료: {waveform_filename}")
            else:
                logger.warning("파형 데이터 S3 업로드 실패")
            
            # 파형 임시 파일 정리
            if os.path.exists(waveform_filepath):
                os.unlink(waveform_filepath)
                
        except Exception as e:
            logger.warning(f"파형 분석 실패: {e}")
            # 파형 분석 실패해도 믹싱 작업은 계속 진행
        
        # 7. 결과 구성
        result = {
            'task_id': task_id,
            'stageId': stageId,
            'upstreamId': upstreamId,
            'status': 'SUCCESS',
            'mixed_file_path': s3_mixed_path,
            'waveform_data_path': waveform_data_path,
            'stem_count': len(stem_paths),
            'stem_paths': stem_paths,
            'processed_at': aws_utils._get_current_timestamp()
        }
        
        # 7. 웹훅으로 완료 알림 전송
        if stageId:
            try:
                from .webhook import send_mixing_webhook
                send_mixing_webhook(stageId, result, "SUCCESS")
            except Exception as e:
                logger.warning("웹훅 전송 실패: %s", e)
        
        logger.info("믹싱 작업 완료: stageId=%s, upstreamId=%s, mixed_file=%s", stageId, upstreamId, s3_mixed_path)
        return result
        
    except Exception as e:
        logger.error("믹싱 작업 실패: stageId=%s, upstreamId=%s, error=%s", stageId, upstreamId, str(e))
        
        # 재시도 로직
        if self.request.retries < self.max_retries:
            logger.info("작업 재시도 예약: stageId=%s, upstreamId=%s, retry=%d/%d", 
                       stageId, upstreamId, self.request.retries + 1, self.max_retries)
            countdown = min(60 * (2 ** self.request.retries), 300)
            raise self.retry(exc=e, countdown=countdown)
        
        logger.error("최대 재시도 횟수 초과: stageId=%s, upstreamId=%s", stageId, upstreamId)
        raise
        
    finally:
        # EC2 임시 파일 정리 (성공/실패와 관계없이 실행)
        all_files = local_files + ([mixed_file_path] if mixed_file_path else [])
        for file_path in all_files:
            if file_path and os.path.exists(file_path):
                try:
                    os.unlink(file_path)
                    logger.info("EC2 임시 파일 정리 완료: %s", file_path)
                except Exception as cleanup_error:
                    logger.warning("EC2 임시 파일 정리 실패: %s", cleanup_error)


def generate_file_hash(filepath: str) -> str:
    """
    파일의 SHA-256 해시를 생성합니다.
    
    Args:
        filepath: 해시를 생성할 파일 경로
        
    Returns:
        str: SHA-256 해시 문자열
    """
    try:
        sha256_hash = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
    except Exception as e:
        logger.error("파일 해시 생성 실패: %s", e)
        raise


@celery_app.task(name='health_check', bind=True)
def health_check(self):
    """
    시스템 상태 확인 태스크
    워커와 AWS 서비스 연결 상태를 확인합니다.
    """
    try:
        # AWS 서비스 연결 확인
        test_result = aws_utils.test_connections()
        
        # 시스템 리소스 확인
        import psutil
        memory_percent = psutil.virtual_memory().percent
        cpu_percent = psutil.cpu_percent(interval=1)
        
        result = {
            'task_id': self.request.id,
            'status': 'healthy',
            'timestamp': aws_utils._get_current_timestamp(),
            'aws_connections': test_result,
            'system_resources': {
                'memory_usage_percent': memory_percent,
                'cpu_usage_percent': cpu_percent
            }
        }
        
        logger.info("헬스 체크 완료: %s", result)
        return result
        
    except Exception as e:
        logger.error("헬스 체크 실패: %s", e)
        return {
            'task_id': self.request.id,
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': aws_utils._get_current_timestamp()
        }


@celery_app.task(name='cleanup_temp_files', bind=True)
def cleanup_temp_files(self):
    """
    임시 파일 정리 태스크
    오래된 임시 파일들을 정리합니다.
    """
    try:
        import glob
        import time
        
        # 1시간(3600초) 이상 된 임시 파일 정리
        cutoff_time = time.time() - 3600
        
        temp_patterns = [
            '/tmp/tmp*',
            '/tmp/*audio*',
            '/tmp/*waveform*',
            '/tmp/*mixed*'
        ]
        
        cleaned_files = []
        
        for pattern in temp_patterns:
            for filepath in glob.glob(pattern):
                try:
                    if os.path.isfile(filepath) and os.path.getmtime(filepath) < cutoff_time:
                        os.unlink(filepath)
                        cleaned_files.append(filepath)
                except Exception as e:
                    logger.warning("파일 정리 실패: %s, 오류: %s", filepath, e)
        
        result = {
            'task_id': self.request.id,
            'status': 'completed',
            'cleaned_files_count': len(cleaned_files),
            'cleaned_files': cleaned_files[:10],  # 최대 10개만 로그에 표시
            'timestamp': aws_utils._get_current_timestamp()
        }
        
        logger.info("임시 파일 정리 완료: %d개 파일 정리", len(cleaned_files))
        return result
        
    except Exception as e:
        logger.error("임시 파일 정리 실패: %s", e)
        return {
            'task_id': self.request.id,
            'status': 'failed',
            'error': str(e),
            'timestamp': aws_utils._get_current_timestamp()
        } 