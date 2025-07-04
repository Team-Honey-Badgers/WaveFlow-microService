"""
AWS 서비스 연동 유틸리티 모듈
S3 파일 다운로드/업로드 및 SQS 메시지 전송 기능을 제공합니다.
"""

import json
import logging
import boto3
from botocore.exceptions import ClientError, NoCredentialsError

logger = logging.getLogger(__name__)

class AWSUtils:
    """AWS 서비스 연동을 위한 유틸리티 클래스"""
    
    def __init__(self):
        """AWS 클라이언트 초기화"""
        try:
            # config 모듈 직접 import 대신 환경 변수 사용
            import os
            self.config = type('Config', (), {
                'AWS_ACCESS_KEY_ID': os.getenv('AWS_ACCESS_KEY_ID'),
                'AWS_SECRET_ACCESS_KEY': os.getenv('AWS_SECRET_ACCESS_KEY'),
                'AWS_REGION': os.getenv('AWS_REGION', 'ap-northeast-2'),
                'S3_BUCKET_NAME': os.getenv('S3_BUCKET_NAME'),
                'SQS_QUEUE_URL': os.getenv('SQS_QUEUE_URL')
            })()
            
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=self.config.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=self.config.AWS_SECRET_ACCESS_KEY,
                region_name=self.config.AWS_REGION
            )
            self.sqs_client = boto3.client(
                'sqs',
                aws_access_key_id=self.config.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=self.config.AWS_SECRET_ACCESS_KEY,
                region_name=self.config.AWS_REGION
            )
        except NoCredentialsError as e:
            logger.error("AWS 자격 증명을 찾을 수 없습니다: %s", e)
            raise
        except Exception as e:
            logger.error("AWS 클라이언트 초기화 실패: %s", e)
            raise
    
    def download_from_s3(self, s3_path: str, local_path: str) -> bool:
        """
        S3에서 파일을 다운로드합니다.
        
        Args:
            s3_path: S3 객체 경로 (예: "folder/file.wav")
            local_path: 로컬 저장 경로
            
        Returns:
            bool: 다운로드 성공 여부
        """
        try:
            self.s3_client.download_file(
                Bucket=self.config.S3_BUCKET_NAME,
                Key=s3_path,
                Filename=local_path
            )
            logger.info("S3 파일 다운로드 완료: %s -> %s", s3_path, local_path)
            return True
        except ClientError as e:
            logger.error("S3 파일 다운로드 실패: %s", e)
            return False
        except Exception as e:
            logger.error("예상치 못한 오류 발생: %s", e)
            return False
    
    def upload_to_s3(self, local_path: str, s3_path: str) -> bool:
        """
        로컬 파일을 S3에 업로드합니다.
        
        Args:
            local_path: 업로드할 로컬 파일 경로
            s3_path: S3 저장 경로
            
        Returns:
            bool: 업로드 성공 여부
        """
        bucket = self.config.S3_BUCKET_NAME
        
        try:
            self.s3_client.upload_file(
                Filename=local_path,
                Bucket=bucket,
                Key=s3_path
            )
            logger.info("S3 파일 업로드 완료: %s -> s3://%s/%s", local_path, bucket, s3_path)
            return True
        except ClientError as e:
            logger.error("S3 파일 업로드 실패: %s", e)
            return False
        except Exception as e:
            logger.error("예상치 못한 오류 발생: %s", e)
            return False
    
    # 웹훅 방식으로 처리하므로 SQS 결과 전송 불필요
    
    def _get_current_timestamp(self) -> str:
        """현재 타임스탬프를 ISO 형식으로 반환합니다."""
        from datetime import datetime
        return datetime.utcnow().isoformat() + 'Z'

# 전역 인스턴스
aws_utils = AWSUtils() 