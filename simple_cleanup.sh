#!/bin/bash

echo "===== SQS 메시지 수동 정리 ====="

QUEUE_URL="https://sqs.ap-northeast-2.amazonaws.com/490004626839/waveflow-audio-process-queue-honeybadgers"

echo "메시지 수신 및 삭제 중..."

# 메시지를 받아서 삭제하는 방식 (권한이 적게 필요)
for i in {1..10}; do
    echo "배치 $i 처리 중..."
    
    # 메시지 수신
    MESSAGES=$(aws sqs receive-message --queue-url "$QUEUE_URL" --region ap-northeast-2 --max-number-of-messages 10 2>/dev/null)
    
    if [ -z "$MESSAGES" ] || [ "$MESSAGES" = "{}" ]; then
        echo "더 이상 메시지가 없습니다."
        break
    fi
    
    # 메시지 삭제
    echo "$MESSAGES" | jq -r '.Messages[]? | .ReceiptHandle' | while read receipt_handle; do
        if [ ! -z "$receipt_handle" ]; then
            aws sqs delete-message --queue-url "$QUEUE_URL" --region ap-northeast-2 --receipt-handle "$receipt_handle" 2>/dev/null
            echo "메시지 삭제됨"
        fi
    done
    
    sleep 1
done

echo "===== 정리 완료 ====="