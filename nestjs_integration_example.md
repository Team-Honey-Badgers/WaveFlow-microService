# NestJS 서버 통합 예제

새로운 워크플로우를 위한 NestJS 서버 통합 예제입니다.

## 1. SQS 메시지 전송 서비스

```typescript
// sqs.service.ts
import { Injectable, Logger } from '@nestjs/common';
import { SQSClient, SendMessageCommand } from '@aws-sdk/client-sqs';

@Injectable()
export class SqsService {
  private readonly logger = new Logger(SqsService.name);
  private readonly sqsClient: SQSClient;
  private readonly queueUrl = process.env.SQS_QUEUE_URL;

  constructor() {
    this.sqsClient = new SQSClient({
      region: process.env.AWS_REGION || 'ap-northeast-2',
    });
  }

  // 1단계: 해시 생성 요청
  async sendHashGenerationRequest(data: {
    userId: string;
    trackId: string;
    stemId: string;
    filepath: string;
    timestamp: string;
    original_filename: string;
  }) {
    const message = {
      task: 'app.tasks.generate_hash_and_webhook',
      id: `hash-${data.stemId}-${Date.now()}`,
      args: [],
      kwargs: {
        userId: data.userId,
        trackId: data.trackId,
        stemId: data.stemId,
        filepath: data.filepath,
        timestamp: data.timestamp,
        original_filename: data.original_filename,
      },
    };

    try {
      const command = new SendMessageCommand({
        QueueUrl: this.queueUrl,
        MessageBody: JSON.stringify(message),
      });

      const result = await this.sqsClient.send(command);
      this.logger.log(`해시 생성 요청 전송: ${data.stemId}`);
      return result;
    } catch (error) {
      this.logger.error('SQS 메시지 전송 실패:', error);
      throw error;
    }
  }

  // 2단계: 중복 파일 처리 요청
  async sendDuplicateFileRequest(data: {
    userId: string;
    trackId: string;
    stemId: string;
    filepath: string;
    audio_hash: string;
  }) {
    const message = {
      task: 'app.tasks.process_duplicate_file',
      id: `duplicate-${data.stemId}-${Date.now()}`,
      args: [],
      kwargs: {
        userId: data.userId,
        trackId: data.trackId,
        stemId: data.stemId,
        filepath: data.filepath,
        audio_hash: data.audio_hash,
      },
    };

    try {
      const command = new SendMessageCommand({
        QueueUrl: this.queueUrl,
        MessageBody: JSON.stringify(message),
      });

      const result = await this.sqsClient.send(command);
      this.logger.log(`중복 파일 처리 요청 전송: ${data.stemId}`);
      return result;
    } catch (error) {
      this.logger.error('SQS 메시지 전송 실패:', error);
      throw error;
    }
  }

  // 3단계: 오디오 분석 요청
  async sendAudioAnalysisRequest(data: {
    userId: string;
    trackId: string;
    stemId: string;
    filepath: string;
    audio_hash: string;
    timestamp: string;
    original_filename: string;
    num_peaks?: number;
  }) {
    const message = {
      task: 'app.tasks.process_audio_analysis',
      id: `analysis-${data.stemId}-${Date.now()}`,
      args: [],
      kwargs: {
        userId: data.userId,
        trackId: data.trackId,
        stemId: data.stemId,
        filepath: data.filepath,
        audio_hash: data.audio_hash,
        timestamp: data.timestamp,
        original_filename: data.original_filename,
        num_peaks: data.num_peaks || 1024,
      },
    };

    try {
      const command = new SendMessageCommand({
        QueueUrl: this.queueUrl,
        MessageBody: JSON.stringify(message),
      });

      const result = await this.sqsClient.send(command);
      this.logger.log(`오디오 분석 요청 전송: ${data.stemId}`);
      return result;
    } catch (error) {
      this.logger.error('SQS 메시지 전송 실패:', error);
      throw error;
    }
  }
}
```

## 2. 웹훅 처리 컨트롤러

```typescript
// webhook.controller.ts
import { Controller, Post, Body, Logger, HttpStatus } from '@nestjs/common';
import { SqsService } from './sqs.service';
import { StemFileService } from './stem-file.service';

@Controller('webhook')
export class WebhookController {
  private readonly logger = new Logger(WebhookController.name);

  constructor(
    private readonly sqsService: SqsService,
    private readonly stemFileService: StemFileService,
  ) {}

  // 해시 검사 웹훅 처리
  @Post('hash-check')
  async handleHashCheck(@Body() data: {
    stemId: string;
    userId: string;
    trackId: string;
    filepath: string;
    audio_hash: string;
    timestamp: string;
    original_filename: string;
    status: string;
  }) {
    this.logger.log(`해시 검사 요청 수신: ${data.stemId}`);

    try {
      // 중복 해시 검사
      const isDuplicate = await this.stemFileService.checkDuplicateHash(
        data.userId,
        data.trackId,
        data.audio_hash,
      );

      if (isDuplicate) {
        // 중복 있음 시나리오: 파일 삭제 요청
        this.logger.log(`중복 해시 발견: ${data.stemId}`);
        await this.sqsService.sendDuplicateFileRequest({
          userId: data.userId,
          trackId: data.trackId,
          stemId: data.stemId,
          filepath: data.filepath,
          audio_hash: data.audio_hash,
        });
      } else {
        // 중복 없음 시나리오: 오디오 분석 요청
        this.logger.log(`새로운 해시 확인: ${data.stemId}`);
        await this.sqsService.sendAudioAnalysisRequest({
          userId: data.userId,
          trackId: data.trackId,
          stemId: data.stemId,
          filepath: data.filepath,
          audio_hash: data.audio_hash,
          timestamp: data.timestamp,
          original_filename: data.original_filename,
        });
      }

      return { status: 'success', message: '해시 검사 완료' };
    } catch (error) {
      this.logger.error('해시 검사 실패:', error);
      return { status: 'error', message: '해시 검사 실패' };
    }
  }

  // 완료 웹훅 처리
  @Post('completion')
  async handleCompletion(@Body() data: {
    stemId: string;
    status: string;
    result: any;
    timestamp: string;
  }) {
    this.logger.log(`작업 완료 알림 수신: ${data.stemId}`);

    try {
      if (data.status === 'SUCCESS') {
        // 성공 시 데이터베이스 업데이트
        await this.stemFileService.updateProcessingResult(
          data.stemId,
          data.result,
        );
        this.logger.log(`작업 완료 처리 성공: ${data.stemId}`);
      } else {
        // 실패 시 에러 처리
        this.logger.error(`작업 실패: ${data.stemId}`, data.result);
        await this.stemFileService.updateProcessingError(
          data.stemId,
          data.result,
        );
      }

      return { status: 'success', message: '완료 알림 처리 완료' };
    } catch (error) {
      this.logger.error('완료 알림 처리 실패:', error);
      return { status: 'error', message: '완료 알림 처리 실패' };
    }
  }
}
```

## 3. 스템 파일 서비스 (중복 검사)

```typescript
// stem-file.service.ts
import { Injectable, Logger } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { StemFile } from './stem-file.entity';

@Injectable()
export class StemFileService {
  private readonly logger = new Logger(StemFileService.name);

  constructor(
    @InjectRepository(StemFile)
    private readonly stemFileRepository: Repository<StemFile>,
  ) {}

  // 중복 해시 검사
  async checkDuplicateHash(
    userId: string,
    trackId: string,
    audioHash: string,
  ): Promise<boolean> {
    try {
      const existingFile = await this.stemFileRepository.findOne({
        where: {
          userId,
          trackId,
          audioHash,
        },
      });

      return !!existingFile;
    } catch (error) {
      this.logger.error('중복 해시 검사 실패:', error);
      throw error;
    }
  }

  // 처리 결과 업데이트
  async updateProcessingResult(stemId: string, result: any) {
    try {
      await this.stemFileRepository.update(
        { stemId },
        {
          audioHash: result.audio_data_hash,
          waveformDataPath: result.waveform_data_path,
          fileSize: result.file_size,
          duration: result.duration,
          sampleRate: result.sample_rate,
          numPeaks: result.num_peaks,
          processedAt: new Date(),
          status: 'completed',
        },
      );
    } catch (error) {
      this.logger.error('처리 결과 업데이트 실패:', error);
      throw error;
    }
  }

  // 처리 에러 업데이트
  async updateProcessingError(stemId: string, error: any) {
    try {
      await this.stemFileRepository.update(
        { stemId },
        {
          status: 'error',
          errorMessage: error.error_message,
          errorCode: error.error_code,
          processedAt: new Date(),
        },
      );
    } catch (error) {
      this.logger.error('처리 에러 업데이트 실패:', error);
      throw error;
    }
  }
}
```

## 4. 사용 예제

```typescript
// 오디오 업로드 후 처리 시작
@Post('upload-complete')
async handleUploadComplete(@Body() data: {
  userId: string;
  trackId: string;
  stemId: string;
  filepath: string;
  original_filename: string;
}) {
  // 1단계: 해시 생성 요청
  await this.sqsService.sendHashGenerationRequest({
    userId: data.userId,
    trackId: data.trackId,
    stemId: data.stemId,
    filepath: data.filepath,
    timestamp: new Date().toISOString(),
    original_filename: data.original_filename,
  });

  return { status: 'success', message: '처리 시작' };
}
```

## 5. 환경 설정

```env
# .env
AWS_REGION=ap-northeast-2
SQS_QUEUE_URL=https://sqs.ap-northeast-2.amazonaws.com/your-account/waveflow-audio-process-queue-honeybadgers
S3_BUCKET_NAME=your-bucket-name
```

이 예제를 통해 NestJS 서버에서 새로운 3단계 워크플로우를 구현할 수 있습니다. 