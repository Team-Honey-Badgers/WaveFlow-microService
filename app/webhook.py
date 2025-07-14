import requests
import json
from typing import Dict, Any
from .config import get_config

def send_hash_webhook(stem_id: str, result: Dict[str, Any]):
    """해시 생성 완료 시 웹서버로 webhook 전송"""
    config = get_config()
    webhook_url = config.get('WEBHOOK_URL')
    
    if not webhook_url:
        print("WEBHOOK_URL이 설정되지 않았습니다.")
        return
    
    # 해시 웹훅 전용 엔드포인트 (NestJS 서버에서 중복 검사 처리)
    hash_webhook_url = f"{webhook_url}/hash-check"
    
    payload = {
        "stemId": stem_id,
        "userId": result.get('userId'),
        "trackId": result.get('trackId'),
        "filepath": result.get('filepath'),
        "stageId": result.get('stageId'),
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
        print(f"해시 웹훅 전송 성공: {stem_id}")
    except Exception as e:
        print(f"해시 웹훅 전송 실패: {e}")
        raise

def send_completion_webhook(stem_id: str, result: Dict[str, Any], status: str = "SUCCESS"):
    """오디오 분석 완료 시 웹서버로 webhook 전송"""
    config = get_config()
    webhook_url = config.get('WEBHOOK_URL')
    
    if not webhook_url:
        print("WEBHOOK_URL이 설정되지 않았습니다.")
        return
    
    # 완료 웹훅 전용 엔드포인트
    completion_webhook_url = f"{webhook_url}/completion"
    
    payload = {
        "stemId": stem_id,
        "userId": result.get('userId'),
        "trackId": result.get('trackId'),
        "status": status,
        "result": result.get('result'),
        "timestamp": result.get('timestamp'),
        "original_filename": result.get('original_filename'),
        "processing_time": result.get('processing_time'),
        "audio_wave_path": result.get('audio_wave_path')
    }
    
    try:
        response = requests.post(
            completion_webhook_url,
            json=payload,
            timeout=30,
            headers={'Content-Type': 'application/json'}
        )
        response.raise_for_status()
        print(f"완료 웹훅 전송 성공: {stem_id}")
    except Exception as e:
        print(f"완료 웹훅 전송 실패: {e}")
        raise

def send_mixing_webhook(stage_id: str, result: Dict[str, Any], status: str = "SUCCESS"):
    """믹싱 작업 완료 시 웹서버로 webhook 전송"""
    config = get_config()
    webhook_url = config.get('WEBHOOK_URL')
    
    if not webhook_url:
        print("WEBHOOK_URL이 설정되지 않았습니다.")
        return
    
    # 믹싱 완료 웹훅 전용 엔드포인트
    mixing_webhook_url = f"{webhook_url}/mixing-complete"
    
    payload = {
        "stageId": stage_id,
        "status": status,
        "mixed_file_path": result.get('mixed_file_path'),
        "waveform_data_path": result.get('waveform_data_path'),
        "stem_count": result.get('stem_count'),
        "stem_paths": result.get('stem_paths'),
        "task_id": result.get('task_id')
    }
    
    try:
        response = requests.post(
            mixing_webhook_url,
            json=payload,
            timeout=30,
            headers={'Content-Type': 'application/json'}
        )
        response.raise_for_status()
        print(f"믹싱 웹훅 전송 성공: {stage_id}")
    except Exception as e:
        print(f"믹싱 웹훅 전송 실패: {e}")
        raise