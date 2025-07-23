"""
커스텀 SQS 메시지 핸들러
Celery 표준 형식이 아닌 메시지를 처리합니다.
새로운 3단계 워크플로우 지원
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
        from kombu import Queue
        # 큐를 직접 정의하여 ListQueues 권한 불필요
        queue = Queue(
            'waveflow-audio-process-queue-honeybadgers',
            routing_key='waveflow-audio-process-queue-honeybadgers'
        )
        return [Consumer(
            queues=[queue],
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
                task_name = data.get('task', 'app.tasks.generate_hash_and_webhook')
                args = data.get('args', [])
                kwargs = data.get('kwargs', data)  # kwargs가 없으면 전체 데이터 사용
                task_id = data.get('id', 'unknown')
            
            logger.info(f"태스크 실행: {task_name} (ID: {task_id})")
            logger.info(f"Args: {args}, Kwargs: {kwargs}")
            
            # 태스크 직접 실행
            result = self.execute_task(task_name, args, kwargs, task_id)
            
            if result:
                logger.info(f"태스크 실행 완료: {result.id if hasattr(result, 'id') else 'sync'}")
            
            # 메시지 ACK
            message.ack()
            
        except Exception as e:
            logger.error(f"메시지 처리 실패: {e}")
            # 메시지 거부 (재시도를 위해)
            message.reject()
    
    def execute_task(self, task_name, args, kwargs, task_id):
        """태스크 실행"""
        try:
            # 새로운 3단계 워크플로우 태스크들 import
            from .tasks import generate_hash_and_webhook, process_duplicate_file, process_audio_analysis
            
            # 태스크 이름에 따라 적절한 함수 호출
            if task_name == 'app.tasks.generate_hash_and_webhook':
                result = generate_hash_and_webhook.apply_async(
                    args=args,
                    kwargs=kwargs,
                    task_id=task_id
                )
                return result
            elif task_name == 'app.tasks.process_duplicate_file':
                result = process_duplicate_file.apply_async(
                    args=args,
                    kwargs=kwargs,
                    task_id=task_id
                )
                return result
            elif task_name == 'app.tasks.process_audio_analysis':
                result = process_audio_analysis.apply_async(
                    args=args,
                    kwargs=kwargs,
                    task_id=task_id
                )
                return result
            else:
                logger.warning(f"알 수 없는 태스크: {task_name}")
                return None
                
        except Exception as e:
            logger.error(f"태스크 실행 실패: {task_name}, 오류: {e}")
            raise