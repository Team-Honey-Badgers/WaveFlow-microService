"""
커스텀 SQS 메시지 핸들러
Celery 표준 형식이 아닌 메시지를 처리합니다.
새로운 3단계 워크플로우 지원
"""

import json
import logging
from celery import current_app

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
        
        # 태스크 이름 결정
        task_name = data.get('task', 'app.tasks.generate_hash_and_webhook')
        task_id = data.get('stemId', data.get('id', 'unknown'))
        
        # 태스크 실행
        result = execute_task(task_name, data, task_id)
        
        if result:
            logger.info("태스크 실행 완료: task_id=%s", result.id if hasattr(result, 'id') else 'sync')
        
        # 메시지 ACK
        message.ack()
        
    except Exception as e:
        logger.error("메시지 처리 실패: %s", e)
        # 메시지 거부 (재시도를 위해)
        message.reject()

def execute_task(task_name, data, task_id):
    """태스크 실행"""
    try:
        # 새로운 4단계 워크플로우 태스크들 import
        from .tasks import generate_hash_and_webhook, process_duplicate_file, process_audio_analysis, mix_stems_and_upload
        
        # 태스크 이름에 따라 적절한 함수 호출
        if task_name == 'app.tasks.generate_hash_and_webhook':
            result = generate_hash_and_webhook.apply_async(
                kwargs=data,
                task_id=task_id
            )
            return result
        elif task_name == 'app.tasks.process_duplicate_file':
            result = process_duplicate_file.apply_async(
                kwargs=data,
                task_id=task_id
            )
            return result
        elif task_name == 'app.tasks.process_audio_analysis':
            result = process_audio_analysis.apply_async(
                kwargs=data,
                task_id=task_id
            )
            return result
        elif task_name == 'app.tasks.mix_stems_and_upload':
            result = mix_stems_and_upload.apply_async(
                kwargs=data,
                task_id=task_id
            )
            return result
        else:
            logger.warning(f"알 수 없는 태스크: {task_name}")
            return None
            
    except Exception as e:
        logger.error(f"태스크 실행 실패: {task_name}, 오류: {e}")
        raise