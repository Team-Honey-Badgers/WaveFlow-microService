"""
간단한 SQS 메시지 핸들러
kombu 없이 직접 boto3로 SQS 처리
"""

import json
import logging
import time
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

class SimpleSQSHandler:
    """직접 SQS 처리하는 간단한 핸들러"""
    
    def __init__(self, queue_url, region='ap-northeast-2'):
        self.queue_url = queue_url
        self.sqs = boto3.client('sqs', region_name=region)
        self.running = True
        
    def run(self):
        """메시지 처리 루프 시작"""
        logger.info(f"SQS 핸들러 시작: {self.queue_url}")
        
        while self.running:
            try:
                # 메시지 수신
                response = self.sqs.receive_message(
                    QueueUrl=self.queue_url,
                    MaxNumberOfMessages=1,
                    WaitTimeSeconds=20,
                    VisibilityTimeout=300
                )
                
                messages = response.get('Messages', [])
                
                for message in messages:
                    try:
                        self.handle_message(message)
                        
                        # 메시지 삭제
                        self.sqs.delete_message(
                            QueueUrl=self.queue_url,
                            ReceiptHandle=message['ReceiptHandle']
                        )
                        
                    except Exception as e:
                        logger.error(f"메시지 처리 실패: {e}")
                        
            except KeyboardInterrupt:
                logger.info("핸들러 종료 신호 받음")
                break
            except Exception as e:
                logger.error(f"SQS 폴링 에러: {e}")
                time.sleep(5)
                
    def handle_message(self, message):
        """메시지 처리"""
        try:
            body = json.loads(message['Body'])
            logger.info("메시지 수신 및 처리 시작")
            
            # Celery 표준 형식 확인
            if 'headers' in body and 'task' in body.get('headers', {}):
                # 표준 Celery 메시지
                task_name = body['headers']['task']
                task_body = json.loads(body['body'])
                args = task_body[0] if len(task_body) > 0 else []
                kwargs = task_body[1] if len(task_body) > 1 else {}
                task_id = body['headers']['id']
            else:
                # 직접 메시지
                task_name = body.get('task', 'app.tasks.process_audio_file')
                args = body.get('args', [])
                kwargs = body.get('kwargs', body)
                task_id = body.get('id', 'unknown')
            
            logger.info(f"태스크 실행: {task_name} (ID: {task_id})")
            
            # 태스크 직접 실행
            from .tasks import process_audio_file
            
            # 동기 실행 (간단하게)
            if task_name == 'app.tasks.process_audio_file':
                result = process_audio_file(**kwargs)
                logger.info(f"태스크 완료: {task_id}")
            else:
                logger.warning(f"알 수 없는 태스크: {task_name}")
                
        except Exception as e:
            logger.error(f"메시지 처리 실패: {e}")
            raise
    
    def stop(self):
        """핸들러 중지"""
        self.running = False