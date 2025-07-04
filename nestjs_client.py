"""
NestJS용 Celery 클라이언트 유틸리티
다른 EC2 인스턴스에서 실행되는 NestJS가 Celery 작업 결과를 조회할 수 있도록 지원합니다.

사용법:
    from nestjs_client import CeleryClient
    
    client = CeleryClient()
    result = client.get_task_result("task-id-here")
"""

import os
import logging
from typing import Dict, Optional, Any
from celery import Celery
from dotenv import load_dotenv

# 환경 변수 로드
load_dotenv()

logger = logging.getLogger(__name__)

class CeleryClient:
    """NestJS에서 Celery 작업 결과를 조회하기 위한 클라이언트"""
    
    def __init__(self):
        """Celery 클라이언트 초기화"""
        self.aws_region = os.getenv('AWS_REGION', 'ap-northeast-2')
        self.aws_access_key_id = os.getenv('AWS_ACCESS_KEY_ID', '')
        self.aws_secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY', '')
        
        # Result backend URL 구성
        self.result_backend = os.getenv('CELERY_RESULT_BACKEND', '')
        if not self.result_backend and self.aws_access_key_id and self.aws_secret_access_key:
            self.result_backend = f'sqs://{self.aws_access_key_id}:{self.aws_secret_access_key}@'
        
        if not self.result_backend:
            raise ValueError("CELERY_RESULT_BACKEND 환경 변수가 설정되지 않았습니다.")
        
        # Celery 앱 인스턴스 생성 (결과 조회용)
        self.celery_app = Celery('nestjs-client')
        self.celery_app.conf.update(
            result_backend=self.result_backend,
            result_backend_transport_options={
                'region': self.aws_region,
                'visibility_timeout': 3600,
                'polling_interval': 3,
            },
            task_serializer='json',
            result_serializer='json',
            accept_content=['json'],
        )
        
        logger.info("Celery 클라이언트 초기화 완료 - Result Backend: %s", 
                   self.result_backend.split('@')[0] + '@***' if '@' in self.result_backend else self.result_backend)
    
    def get_task_result(self, task_id: str, timeout: float = 10.0) -> Dict[str, Any]:
        """
        작업 결과를 조회합니다.
        
        Args:
            task_id: Celery 작업 ID
            timeout: 결과 대기 시간 (초)
            
        Returns:
            dict: 작업 결과 정보
                - status: SUCCESS, FAILURE, PENDING, PROGRESS 등
                - result: 작업 결과 데이터 (성공 시)
                - error: 오류 메시지 (실패 시)
                - task_id: 작업 ID
        """
        try:
            result = self.celery_app.AsyncResult(task_id)
            
            if result.ready():
                if result.successful():
                    return {
                        'status': 'SUCCESS',
                        'result': result.result,
                        'task_id': task_id,
                        'timestamp': result.date_done.isoformat() if result.date_done else None
                    }
                else:
                    return {
                        'status': 'FAILURE',
                        'error': str(result.result),
                        'task_id': task_id,
                        'traceback': result.traceback
                    }
            else:
                return {
                    'status': result.status,  # PENDING, PROGRESS 등
                    'task_id': task_id,
                    'info': result.info if hasattr(result, 'info') else None
                }
                
        except Exception as e:
            logger.error("작업 결과 조회 실패: %s", e)
            return {
                'status': 'ERROR',
                'error': str(e),
                'task_id': task_id
            }
    
    def wait_for_result(self, task_id: str, timeout: float = 300.0, propagate: bool = False) -> Dict[str, Any]:
        """
        작업 완료까지 대기하고 결과를 반환합니다.
        
        Args:
            task_id: Celery 작업 ID
            timeout: 최대 대기 시간 (초)
            propagate: 예외를 발생시킬지 여부
            
        Returns:
            dict: 작업 결과 정보
        """
        try:
            result = self.celery_app.AsyncResult(task_id)
            
            # 작업 완료까지 대기
            final_result = result.get(timeout=timeout, propagate=propagate)
            
            return {
                'status': 'SUCCESS',
                'result': final_result,
                'task_id': task_id,
                'timestamp': result.date_done.isoformat() if result.date_done else None
            }
            
        except Exception as e:
            logger.error("작업 대기 실패: %s", e)
            return {
                'status': 'ERROR',
                'error': str(e),
                'task_id': task_id
            }
    
    def revoke_task(self, task_id: str, terminate: bool = False) -> Dict[str, Any]:
        """
        실행 중인 작업을 취소합니다.
        
        Args:
            task_id: Celery 작업 ID
            terminate: 강제 종료 여부
            
        Returns:
            dict: 취소 결과
        """
        try:
            self.celery_app.control.revoke(task_id, terminate=terminate)
            return {
                'status': 'REVOKED',
                'task_id': task_id,
                'terminated': terminate
            }
        except Exception as e:
            logger.error("작업 취소 실패: %s", e)
            return {
                'status': 'ERROR',
                'error': str(e),
                'task_id': task_id
            }
    
    def get_active_tasks(self) -> Dict[str, Any]:
        """
        현재 실행 중인 작업 목록을 조회합니다.
        
        Returns:
            dict: 활성 작업 목록
        """
        try:
            inspect = self.celery_app.control.inspect()
            active_tasks = inspect.active()
            return {
                'status': 'SUCCESS',
                'active_tasks': active_tasks
            }
        except Exception as e:
            logger.error("활성 작업 조회 실패: %s", e)
            return {
                'status': 'ERROR',
                'error': str(e)
            }

# 편의 함수들 (전역 함수로 사용 가능)
_client = None

def get_client() -> CeleryClient:
    """글로벌 Celery 클라이언트 인스턴스를 반환합니다."""
    global _client
    if _client is None:
        _client = CeleryClient()
    return _client

def get_task_result(task_id: str) -> Dict[str, Any]:
    """작업 결과를 조회합니다. (편의 함수)"""
    return get_client().get_task_result(task_id)

def wait_for_result(task_id: str, timeout: float = 300.0) -> Dict[str, Any]:
    """작업 완료까지 대기합니다. (편의 함수)"""
    return get_client().wait_for_result(task_id, timeout)