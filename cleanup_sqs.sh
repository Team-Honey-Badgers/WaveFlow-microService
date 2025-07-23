#!/bin/bash

# SQS Cleanup Script
# This script purges messages from the specified SQS queue

set -e

echo "🧹 Starting SQS cleanup..."

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found. Please install it first."
    exit 1
fi

# Get queue URL from environment or use default
QUEUE_URL=${MY_QUEUE_URL:-"your-queue-url-here"}

if [ "$QUEUE_URL" = "your-queue-url-here" ]; then
    echo "❌ Please set MY_QUEUE_URL environment variable or update the script with your queue URL"
    exit 1
fi

echo "📋 Queue URL: $QUEUE_URL"

# Purge the queue
echo "🗑️  Purging SQS queue..."
aws sqs purge-queue --queue-url "$QUEUE_URL"

if [ $? -eq 0 ]; then
    echo "✅ SQS queue purged successfully!"
    echo "ℹ️  Note: It may take up to 60 seconds for the purge to complete."
else
    echo "❌ Failed to purge SQS queue"
    exit 1
fi

echo "🧹 SQS cleanup completed!"