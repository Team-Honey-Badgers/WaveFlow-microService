"""
커스텀 SQS 메시지 핸들러
Celery 표준 형식이 아닌 메시지를 처리합니다.
"""

import json
import logging
from celery import current_app
from kombu import Consumer
from kombu.mixins import ConsumerMixin

logger = logging.getLogger(__name__)

class CustomSQSHandler(ConsumerMixin):
    """커스텀 SQS 메시지 핸들러"""
    
    def __init__(self, connection, celery_app):
        self.connection = connection
        self.celery_app = celery_app
        
    def get_consumers(self, Consumer, channel):
        return [Consumer(
            queues=[self.celery_app.conf.task_routes['app.tasks.process_audio_file']['queue']],
            callbacks=[self.handle_message],
            accept=['json']
        )]
    
    def handle_message(self, body, message):
        """커스텀 메시지 처리"""
        try:
            logger.info("커스텀 핸들러: 메시지 수신")
            
            # JSON 파싱
            if isinstance(body, str):
                data = json.loads(body)
            else:
                data = body
                
            # Celery 표준 형식인지 확인
            if 'headers' in data and 'task' in data.get('headers', {}):
                # 표준 Celery 메시지
                task_name = data['headers']['task']
                task_body = json.loads(data['body'])
                args = task_body[0] if len(task_body) > 0 else []
                kwargs = task_body[1] if len(task_body) > 1 else {}
                task_id = data['headers']['id']
            else:
                # 직접 전송된 메시지
                task_name = data.get('task', 'app.tasks.process_audio_file')
                args = data.get('args', [])
                kwargs = data.get('kwargs', data)  # kwargs가 없으면 전체 데이터 사용
                task_id = data.get('id', 'unknown')
            
            logger.info(f"태스크 실행: {task_name} (ID: {task_id})")
            logger.info(f"Args: {args}, Kwargs: {kwargs}")
            
            # 태스크 직접 실행
            from .tasks import process_audio_file
            result = process_audio_file.apply_async(
                args=args,
                kwargs=kwargs,
                task_id=task_id
            )
            
            logger.info(f"태스크 실행 완료: {result.id}")
            
            # 메시지 ACK
            message.ack()
            
        except Exception as e:
            logger.error(f"메시지 처리 실패: {e}")
            # 메시지 거부 (재시도를 위해)
            message.reject()