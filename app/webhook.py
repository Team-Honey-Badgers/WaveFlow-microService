import requests
import json
from typing import Dict, Any
from .config import get_config
import logging

logger = logging.getLogger(__name__)

def send_hash_webhook(stem_id: str, result: Dict[str, Any]):
    """해시 생성 완료 시 웹서버로 webhook 전송"""
    config = get_config()
    webhook_url = config.get('WEBHOOK_URL')
    
    if not webhook_url:
        logger.error("WEBHOOK_URL이 설정되지 않았습니다.")
        return
    
    # 해시 웹훅 전용 엔드포인트 (NestJS 서버에서 중복 검사 처리)
    hash_webhook_url = f"{webhook_url}/hash-check"
    
    payload = {
        "stemId": stem_id,
        "userId": result.get('userId'),
        "trackId": result.get('trackId'),
        "filepath": result.get('filepath'),
        "sessionId": result.get('sessionId'),
        "audio_hash": result.get('audio_hash'),
        "timestamp": result.get('timestamp'),
        "original_filename": result.get('original_filename'),
        "status": "hash_generated"
    }
    
    try:
        response = requests.post(
            hash_webhook_url,
            json=payload,
            timeout=30,
            headers={'Content-Type': 'application/json'}
        )
        response.raise_for_status()
        logger.info(f"해시 웹훅 전송 성공: {stem_id}")
    except Exception as e:
        logger.error(f"해시 웹훅 전송 실패: {e}")
        raise

def send_completion_webhook(stem_id: str, result: Dict[str, Any], status: str = "SUCCESS"):
    """작업 완료 시 웹서버로 webhook 전송"""
    config = get_config()
    webhook_url = config.get('WEBHOOK_URL')
    
    if not webhook_url:
        logger.error("WEBHOOK_URL이 설정되지 않았습니다.")
        return
    
    # 완료 웹훅 전용 엔드포인트
    completion_webhook_url = f"{webhook_url}/completion"
    
    payload = {
        "stemId": stem_id,
        "userId": result.get('userId'),
        "trackId": result.get('trackId'),
        "status": status,
        "result": result,
        "timestamp": result.get('processed_at'),
        "original_filename": result.get('original_filename'),
        "processing_time": result.get('processing_time', 0)
    }
    
    try:
        response = requests.post(
            completion_webhook_url,
            json=payload,
            timeout=30,
            headers={'Content-Type': 'application/json'}
        )
        response.raise_for_status()
        logger.info(f"완료 웹훅 전송 성공: {stem_id}")
    except Exception as e:
        logger.error(f"완료 웹훅 전송 실패: {e}")
        raise

def send_waveform_update_webhook(stem_id: str, data: Dict[str, Any]):
    """파형 데이터 업데이트 시 웹서버로 webhook 전송"""
    config = get_config()
    webhook_url = config.get('WEBHOOK_URL')
    
    if not webhook_url:
        logger.error("WEBHOOK_URL이 설정되지 않았습니다.")
        return
    
    # 파형 업데이트 웹훅 전용 엔드포인트
    waveform_webhook_url = f"{webhook_url}/waveform-update"
    
    payload = {
        "stemId": data.get('stemId'),
        "userId": data.get('userId'),
        "trackId": data.get('trackId'),
        "stem_wave_form_path": data.get('stem_wave_form_path'),
        "timestamp": data.get('timestamp'),
        "original_filename": data.get('original_filename')
    }
    
    try:
        response = requests.post(
            waveform_webhook_url,
            json=payload,
            timeout=30,
            headers={'Content-Type': 'application/json'}
        )
        response.raise_for_status()
        logger.info(f"파형 데이터 업데이트 웹훅 전송 성공: {stem_id}")
    except Exception as e:
        logger.error(f"파형 데이터 업데이트 웹훅 전송 실패: {e}")
        raise

def send_duplicate_delete_complete_webhook(stem_id: str, result: Dict[str, Any]):
    """중복 파일 삭제 완료 시 웹서버로 webhook 전송"""
    config = get_config()
    webhook_url = config.get('WEBHOOK_URL')
    
    if not webhook_url:
        logger.error("WEBHOOK_URL이 설정되지 않았습니다.")
        return
    
    # 중복 파일 삭제 완료 웹훅 전용 엔드포인트
    delete_complete_webhook_url = f"{webhook_url}/duplicate-delete-complete"
    
    payload = {
        "stemId": stem_id,
        "userId": result.get('userId'),
        "trackId": result.get('trackId'),
        "filepath": result.get('filepath'),
        "audio_hash": result.get('audio_hash'),
        "timestamp": result.get('processed_at'),
        "original_filename": result.get('original_filename')
    }
    
    try:
        response = requests.post(
            delete_complete_webhook_url,
            json=payload,
            timeout=30,
            headers={'Content-Type': 'application/json'}
        )
        response.raise_for_status()
        logger.info(f"중복 파일 삭제 완료 웹훅 전송 성공: {stem_id}")
    except Exception as e:
        logger.error(f"중복 파일 삭제 완료 웹훅 전송 실패: {e}")
        raise

def send_file_processing_progress_webhook(stem_id: str, progress_data: Dict[str, Any]):
    """파일 처리 진행 상태 업데이트 시 웹서버로 webhook 전송"""
    config = get_config()
    webhook_url = config.get('WEBHOOK_URL')
    
    if not webhook_url:
        logger.error("WEBHOOK_URL이 설정되지 않았습니다.")
        return
    
    # 진행 상태 업데이트 웹훅 (기존 completion 엔드포인트 재사용)
    progress_webhook_url = f"{webhook_url}/completion"
    
    payload = {
        "stemId": stem_id,
        "userId": progress_data.get('userId'),
        "trackId": progress_data.get('trackId'),
        "status": "PROGRESS",
        "result": {
            "stage": progress_data.get('stage'),
            "progress": progress_data.get('progress'),
            "message": progress_data.get('message')
        },
        "timestamp": progress_data.get('timestamp'),
        "original_filename": progress_data.get('original_filename')
    }
    
    try:
        response = requests.post(
            progress_webhook_url,
            json=payload,
            timeout=30,
            headers={'Content-Type': 'application/json'}
        )
        response.raise_for_status()
        logger.info(f"파일 처리 진행 상태 웹훅 전송 성공: {stem_id}")
    except Exception as e:
        logger.error(f"파일 처리 진행 상태 웹훅 전송 실패: {e}")
        # 진행 상태 전송 실패는 심각한 오류가 아니므로 raise하지 않음
        pass