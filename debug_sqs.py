#!/usr/bin/env python3
"""
SQS 메시지 디버깅 스크립트
큐에 있는 메시지들을 확인하고 분석합니다.
"""

import os
import json
import boto3
from dotenv import load_dotenv

# 환경 변수 로드
load_dotenv()

def debug_sqs_messages():
    """SQS 큐의 메시지들을 확인합니다."""
    
    # AWS 클라이언트 설정
    sqs = boto3.client('sqs', region_name='ap-northeast-2')
    queue_url = os.getenv('SQS_QUEUE_URL')
    
    if not queue_url:
        print("❌ SQS_QUEUE_URL 환경변수가 설정되지 않았습니다.")
        return
    
    print(f"🔍 SQS 큐 확인: {queue_url}")
    print("=" * 50)
    
    try:
        # 큐 속성 확인
        attrs = sqs.get_queue_attributes(
            QueueUrl=queue_url,
            AttributeNames=['All']
        )
        
        print("📊 큐 상태:")
        print(f"  - 대기 중인 메시지: {attrs['Attributes'].get('ApproximateNumberOfMessages', '0')}")
        print(f"  - 처리 중인 메시지: {attrs['Attributes'].get('ApproximateNumberOfMessagesNotVisible', '0')}")
        print(f"  - 지연된 메시지: {attrs['Attributes'].get('ApproximateNumberOfMessagesDelayed', '0')}")
        print()
        
        # 메시지 수신 (삭제하지 않고 확인만)
        print("📥 메시지 확인 중...")
        
        for i in range(3):  # 최대 3개 메시지 확인
            response = sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=5,
                VisibilityTimeout=30
            )
            
            messages = response.get('Messages', [])
            
            if not messages:
                print(f"  {i+1}. 메시지 없음")
                continue
            
            for msg in messages:
                print(f"  {i+1}. 메시지 발견:")
                print(f"     - 메시지 ID: {msg.get('MessageId', 'N/A')}")
                print(f"     - Body 타입: {type(msg.get('Body', ''))}")
                print(f"     - Body 길이: {len(msg.get('Body', ''))}")
                print(f"     - Body 내용: '{msg.get('Body', '')}'")
                
                # JSON 파싱 시도
                try:
                    body = json.loads(msg.get('Body', ''))
                    print(f"     - JSON 파싱: ✅ 성공")
                    print(f"     - 파싱된 내용: {json.dumps(body, indent=2, ensure_ascii=False)}")
                except json.JSONDecodeError as e:
                    print(f"     - JSON 파싱: ❌ 실패 ({e})")
                
                print()
                
                # 메시지 가시성 복원 (삭제하지 않음)
                try:
                    sqs.change_message_visibility(
                        QueueUrl=queue_url,
                        ReceiptHandle=msg['ReceiptHandle'],
                        VisibilityTimeout=0
                    )
                except Exception as e:
                    print(f"     - 가시성 복원 실패: {e}")
        
        print("✅ 디버깅 완료")
        
    except Exception as e:
        print(f"❌ 에러 발생: {e}")

if __name__ == "__main__":
    debug_sqs_messages() 