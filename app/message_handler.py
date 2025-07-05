"""
커스텀 SQS 메시지 핸들러
Celery 표준 형식이 아닌 메시지를 처리합니다.
"""

import json
import logging
from celery import current_app
from .tasks import process_audio_file

logger = logging.getLogger(__name__)

def handle_custom_message(body, message):
    """
    커스텀 메시지 형식을 처리합니다.
    
    Args:
        body: 메시지 본문
        message: SQS 메시지 객체
    """
    try:
        # JSON 파싱
        if isinstance(body, str):
            data = json.loads(body)
        else:
            data = body
            
        logger.info("커스텀 메시지 수신: %s", data)
        
        # process_audio_file 태스크 직접 호출
        result = process_audio_file.apply_async(
            kwargs=data,
            task_id=data.get('stemId', 'unknown')
        )
        
        logger.info("태스크 실행 완료: task_id=%s", result.id)
        
        # 메시지 ACK
        message.ack()
        
    except Exception as e:
        logger.error("메시지 처리 실패: %s", e)
        # 메시지 거부 (재시도를 위해)
        message.reject()