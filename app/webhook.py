import requests
import json
from typing import Dict, Any
from .config import get_config

def send_completion_webhook(job_id: str, result: Dict[str, Any], status: str = "SUCCESS"):
    """작업 완료 시 웹서버로 webhook 전송"""
    config = get_config()
    webhook_url = config.get('WEBHOOK_URL')
    
    if not webhook_url:
        return
    
    payload = {
        "job_id": job_id,
        "status": status,
        "result": result,
        "timestamp": result.get('processed_at')
    }
    
    try:
        response = requests.post(
            webhook_url,
            json=payload,
            timeout=10,
            headers={'Content-Type': 'application/json'}
        )
        response.raise_for_status()
    except Exception as e:
        print(f"Webhook 전송 실패: {e}")