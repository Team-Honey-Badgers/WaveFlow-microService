#!/usr/bin/env python3
"""
SQS 메시지 정리 스크립트
무효한 메시지들을 찾아서 삭제합니다.
"""

import os
import json
import boto3
from dotenv import load_dotenv

# 환경 변수 로드
load_dotenv()

def cleanup_invalid_messages():
    """SQS 큐에서 무효한 메시지들을 정리합니다."""
    
    # AWS 클라이언트 설정
    sqs = boto3.client('sqs', region_name='ap-northeast-2')
    queue_url = os.getenv('SQS_QUEUE_URL')
    
    if not queue_url:
        print("❌ SQS_QUEUE_URL 환경변수가 설정되지 않았습니다.")
        return
    
    print(f"🧹 SQS 큐 정리 시작: {queue_url}")
    print("=" * 50)
    
    deleted_count = 0
    checked_count = 0
    
    try:
        while True:
            # 메시지 수신
            response = sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=10,  # 한 번에 최대 10개
                WaitTimeSeconds=5,
                VisibilityTimeout=60
            )
            
            messages = response.get('Messages', [])
            
            if not messages:
                print("📭 더 이상 메시지가 없습니다.")
                break
            
            print(f"📥 {len(messages)}개 메시지 확인 중...")
            
            for msg in messages:
                checked_count += 1
                body_text = msg.get('Body', '')
                
                should_delete = False
                reason = ""
                
                # 빈 메시지 확인
                if not body_text or body_text.strip() == '':
                    should_delete = True
                    reason = "빈 메시지"
                
                # JSON 파싱 확인
                elif body_text.strip() in ['{}', 'null', '""', "''", '[]']:
                    should_delete = True
                    reason = "무효한 JSON"
                
                else:
                    try:
                        body = json.loads(body_text)
                        
                        # 빈 객체 확인
                        if not body or (isinstance(body, dict) and len(body) == 0):
                            should_delete = True
                            reason = "빈 객체"
                        
                        # 유효한 태스크 메시지인지 확인
                        elif isinstance(body, dict):
                            has_task = 'task' in body
                            has_headers = 'headers' in body and 'task' in body.get('headers', {})
                            
                            if not has_task and not has_headers:
                                print(f"⚠️  의심스러운 메시지: {body}")
                                # 사용자 확인 후 결정하도록 함
                        
                    except json.JSONDecodeError:
                        should_delete = True
                        reason = "JSON 파싱 실패"
                
                if should_delete:
                    try:
                        sqs.delete_message(
                            QueueUrl=queue_url,
                            ReceiptHandle=msg['ReceiptHandle']
                        )
                        deleted_count += 1
                        print(f"🗑️  삭제: {reason} - '{body_text[:50]}...'")
                    except Exception as e:
                        print(f"❌ 삭제 실패: {e}")
                else:
                    # 유효한 메시지는 가시성 복원
                    try:
                        sqs.change_message_visibility(
                            QueueUrl=queue_url,
                            ReceiptHandle=msg['ReceiptHandle'],
                            VisibilityTimeout=0
                        )
                        print(f"✅ 유효한 메시지 보존")
                    except Exception as e:
                        print(f"⚠️  가시성 복원 실패: {e}")
        
        print("=" * 50)
        print(f"✅ 정리 완료:")
        print(f"  - 확인한 메시지: {checked_count}개")
        print(f"  - 삭제한 메시지: {deleted_count}개")
        
    except Exception as e:
        print(f"❌ 에러 발생: {e}")

def purge_all_messages():
    """모든 메시지를 삭제합니다. (주의: 복구 불가능)"""
    
    sqs = boto3.client('sqs', region_name='ap-northeast-2')
    queue_url = os.getenv('SQS_QUEUE_URL')
    
    if not queue_url:
        print("❌ SQS_QUEUE_URL 환경변수가 설정되지 않았습니다.")
        return
    
    confirm = input("⚠️  모든 메시지를 삭제하시겠습니까? (yes/no): ")
    if confirm.lower() != 'yes':
        print("취소되었습니다.")
        return
    
    try:
        sqs.purge_queue(QueueUrl=queue_url)
        print("🧹 모든 메시지가 삭제되었습니다.")
    except Exception as e:
        print(f"❌ 에러 발생: {e}")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == '--purge':
        purge_all_messages()
    else:
        cleanup_invalid_messages() 