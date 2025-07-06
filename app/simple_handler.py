"""
간단한 SQS 메시지 핸들러
kombu 없이 직접 boto3로 SQS 처리
새로운 3단계 워크플로우 지원
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
            body_text = message['Body']
            if not body_text or body_text.strip() == '':
                logger.warning("빈 메시지 수신, 건너뜀")
                return
                
            body = json.loads(body_text)
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
                task_name = body.get('task', 'app.tasks.generate_hash_and_webhook')
                args = body.get('args', [])
                kwargs = body.get('kwargs', body)
                task_id = body.get('id', 'unknown')
            
            logger.info(f"태스크 실행: {task_name} (ID: {task_id})")
            
            # 태스크 직접 실행
            result = self.execute_task(task_name, args, kwargs)
            
            if result:
                logger.info(f"태스크 완료: {task_id}")
            else:
                logger.warning(f"태스크 실행 실패: {task_id}")
                
        except json.JSONDecodeError as e:
            logger.error(f"JSON 파싱 실패: {e}")
            logger.error(f"메시지 내용: {message.get('Body', '')}")
            raise
        except Exception as e:
            logger.error(f"메시지 처리 실패: {e}")
            raise
    
    def execute_task(self, task_name, args, kwargs):
        """태스크 실행"""
        try:
            # 새로운 3단계 워크플로우 태스크들 import
            from .tasks import generate_hash_and_webhook, process_duplicate_file, process_audio_analysis
            
            # 태스크 이름에 따라 적절한 함수 호출
            if task_name == 'app.tasks.generate_hash_and_webhook':
                result = generate_hash_and_webhook(**kwargs)
                return result
            elif task_name == 'app.tasks.process_duplicate_file':
                result = process_duplicate_file(**kwargs)
                return result
            elif task_name == 'app.tasks.process_audio_analysis':
                result = process_audio_analysis(**kwargs)
                return result
            else:
                logger.warning(f"알 수 없는 태스크: {task_name}")
                return None
                
        except Exception as e:
            logger.error(f"태스크 실행 실패: {task_name}, 오류: {e}")
            raise
    
    def stop(self):
        """핸들러 중지"""
        self.running = False