"""
FastAPI 기반 오디오 처리 마이크로서비스
파일 해시 생성, 오디오 분석, 파일 삭제 API 제공
"""

import os
import asyncio
import logging
from typing import Dict, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from .config import get_config, validate_config
from .audio_processor import AudioProcessor
from .aws_utils import download_from_s3, upload_to_s3, delete_from_s3
from .webhook import send_hash_webhook, send_completion_webhook

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI 앱 생성
app = FastAPI(
    title="WaveFlow Audio Processing API",
    description="오디오 파일 처리를 위한 마이크로서비스",
    version="1.0.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 환경 설정 검증
try:
    validate_config()
    config = get_config()
    logger.info("Configuration validated successfully")
except Exception as e:
    logger.error(f"Configuration validation failed: {e}")
    raise

# Request/Response 모델들
class HashGenerationRequest(BaseModel):
    userId: str
    trackId: str
    stemId: str
    filepath: str
    sessionId: str
    timestamp: str
    original_filename: str

class AudioAnalysisRequest(BaseModel):
    userId: str
    trackId: str
    stemId: str
    filepath: str
    sessionId: str
    audio_hash: str
    timestamp: str
    original_filename: str

class FileDeleteRequest(BaseModel):
    userId: str
    trackId: str
    stemId: str
    filepath: str
    audio_hash: str

class APIResponse(BaseModel):
    status: str
    message: str
    data: Dict[str, Any] = {}

# 오디오 프로세서 인스턴스
audio_processor = AudioProcessor()

@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {"status": "healthy", "service": "audio-processing-api"}

@app.post("/generate-hash", response_model=APIResponse)
async def generate_hash(
    request: HashGenerationRequest,
    background_tasks: BackgroundTasks
):
    """
    오디오 파일의 해시를 생성하고 NestJS 웹훅으로 결과 전송
    """
    logger.info(f"해시 생성 요청 수신: {request.stemId} (파일: {request.original_filename})")
    
    try:
        # 백그라운드에서 해시 생성 작업 실행
        background_tasks.add_task(
            _process_hash_generation,
            request.dict()
        )
        
        return APIResponse(
            status="accepted",
            message="해시 생성 작업이 큐에 추가되었습니다.",
            data={
                "stemId": request.stemId,
                "fileName": request.original_filename,
                "trackId": request.trackId
            }
        )
        
    except Exception as e:
        logger.error(f"해시 생성 요청 처리 실패: {request.stemId} - {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"해시 생성 요청 처리 실패: {str(e)}"
        )

@app.post("/analyze-audio", response_model=APIResponse)
async def analyze_audio(
    request: AudioAnalysisRequest,
    background_tasks: BackgroundTasks
):
    """
    오디오 파일 분석 수행 (파형 데이터 생성 등)
    """
    logger.info(f"오디오 분석 요청 수신: {request.stemId} (파일: {request.original_filename})")
    
    try:
        # 백그라운드에서 오디오 분석 작업 실행
        background_tasks.add_task(
            _process_audio_analysis,
            request.dict()
        )
        
        return APIResponse(
            status="accepted",
            message="오디오 분석 작업이 큐에 추가되었습니다.",
            data={
                "stemId": request.stemId,
                "fileName": request.original_filename,
                "trackId": request.trackId
            }
        )
        
    except Exception as e:
        logger.error(f"오디오 분석 요청 처리 실패: {request.stemId} - {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"오디오 분석 요청 처리 실패: {str(e)}"
        )

@app.post("/delete-file", response_model=APIResponse)
async def delete_file(request: FileDeleteRequest):
    """
    S3에서 중복 파일 삭제
    """
    logger.info(f"파일 삭제 요청 수신: {request.stemId} (경로: {request.filepath})")
    
    try:
        # S3에서 파일 삭제
        success = delete_from_s3(
            config['S3_BUCKET_NAME'],
            request.filepath
        )
        
        if success:
            logger.info(f"파일 삭제 완료: {request.filepath}")
            return APIResponse(
                status="success",
                message="파일이 성공적으로 삭제되었습니다.",
                data={
                    "stemId": request.stemId,
                    "filepath": request.filepath,
                    "trackId": request.trackId
                }
            )
        else:
            raise Exception("S3 파일 삭제 실패")
            
    except Exception as e:
        logger.error(f"파일 삭제 실패: {request.filepath} - {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"파일 삭제 실패: {str(e)}"
        )

# 백그라운드 작업 함수들
async def _process_hash_generation(request_data: Dict[str, Any]):
    """해시 생성 백그라운드 작업"""
    try:
        logger.info(f"해시 생성 작업 시작: {request_data['stemId']}")
        
        # S3에서 파일 다운로드
        local_path = download_from_s3(
            config['S3_BUCKET_NAME'],
            request_data['filepath']
        )
        
        if not local_path:
            raise Exception("S3 파일 다운로드 실패")
        
        # 오디오 해시 생성
        audio_hash = audio_processor.generate_audio_hash(local_path)
        
        # 임시 파일 정리
        if os.path.exists(local_path):
            os.remove(local_path)
        
        # 웹훅 데이터 준비
        webhook_result = {
            'userId': request_data['userId'],
            'trackId': request_data['trackId'],
            'filepath': request_data['filepath'],
            'sessionId': request_data['sessionId'],
            'audio_hash': audio_hash,
            'timestamp': request_data['timestamp'],
            'original_filename': request_data['original_filename'],
            'status': 'hash_generated'
        }
        
        # NestJS 웹훅 전송
        send_hash_webhook(request_data['stemId'], webhook_result)
        
        logger.info(f"해시 생성 완료: {request_data['stemId']} - {audio_hash}")
        
    except Exception as e:
        logger.error(f"해시 생성 작업 실패: {request_data['stemId']} - {str(e)}")
        
        # 실패 시에도 웹훅 전송 (오류 상태로)
        error_result = {
            'userId': request_data['userId'],
            'trackId': request_data['trackId'],
            'error': str(e),
            'status': 'hash_generation_failed'
        }
        
        try:
            send_completion_webhook(request_data['stemId'], error_result, "FAILURE")
        except Exception as webhook_error:
            logger.error(f"실패 웹훅 전송 실패: {webhook_error}")

async def _process_audio_analysis(request_data: Dict[str, Any]):
    """오디오 분석 백그라운드 작업"""
    try:
        logger.info(f"오디오 분석 작업 시작: {request_data['stemId']}")
        
        # S3에서 파일 다운로드
        local_path = download_from_s3(
            config['S3_BUCKET_NAME'],
            request_data['filepath']
        )
        
        if not local_path:
            raise Exception("S3 파일 다운로드 실패")
        
        # 오디오 분석 수행
        analysis_result = audio_processor.analyze_audio_file(
            local_path,
            request_data['stemId']
        )
        
        # 파형 데이터를 S3에 업로드
        waveform_key = f"waveforms/{request_data['userId']}/{request_data['trackId']}/{request_data['stemId']}_waveform.json"
        waveform_url = upload_to_s3(
            config['S3_BUCKET_NAME'],
            waveform_key,
            analysis_result['waveform_data'],
            content_type='application/json'
        )
        
        # 임시 파일 정리
        if os.path.exists(local_path):
            os.remove(local_path)
        
        # 결과 데이터 준비
        completion_result = {
            'audio_hash': request_data['audio_hash'],
            'waveform_data_path': waveform_url,
            'duration': analysis_result.get('duration', 0),
            'sample_rate': analysis_result.get('sample_rate', 0),
            'channels': analysis_result.get('channels', 0),
            'peak_amplitude': analysis_result.get('peak_amplitude', 0),
            'rms_energy': analysis_result.get('rms_energy', 0),
            'processed_at': request_data['timestamp']
        }
        
        # NestJS 완료 웹훅 전송
        send_completion_webhook(request_data['stemId'], completion_result, "SUCCESS")
        
        logger.info(f"오디오 분석 완료: {request_data['stemId']}")
        
    except Exception as e:
        logger.error(f"오디오 분석 작업 실패: {request_data['stemId']} - {str(e)}")
        
        # 실패 시 웹훅 전송
        error_result = {
            'error': str(e),
            'status': 'audio_analysis_failed'
        }
        
        try:
            send_completion_webhook(request_data['stemId'], error_result, "FAILURE")
        except Exception as webhook_error:
            logger.error(f"실패 웹훅 전송 실패: {webhook_error}")

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    ) 