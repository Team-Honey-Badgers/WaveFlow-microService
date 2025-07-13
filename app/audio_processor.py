"""
오디오 파일 처리 핵심 로직 모듈
파일 검증, 해시 계산, 파형 데이터 생성 등의 기능을 제공합니다.
"""

import hashlib
import logging
import os
import json
import tempfile
import magic
import librosa
import numpy as np
import soundfile as sf
from typing import List, Tuple, Optional
from . import config

logger = logging.getLogger(__name__)

class AudioProcessor:
    """오디오 파일 처리를 위한 핵심 클래스"""
    
    def __init__(self, filepath: str):
        """
        AudioProcessor 초기화
        
        Args:
            filepath: 처리할 오디오 파일의 경로
        """
        self.filepath = filepath
        self.audio_data = None
        self.sample_rate = None
        self._file_size = None
        
        # 파일 존재 여부 확인
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {filepath}")
    
    def validate_file_size(self) -> bool:
        """
        파일 크기를 검증합니다.
        
        Returns:
            bool: 파일 크기가 허용 범위 내에 있는지 여부
            
        Raises:
            ValueError: 파일 크기가 허용 범위를 초과한 경우
        """
        try:
            file_size = os.path.getsize(self.filepath)
            self._file_size = file_size
            
            max_size_bytes = config.MAX_FILE_SIZE_MB * 1024 * 1024
            
            if file_size > max_size_bytes:
                raise ValueError(f"파일 크기가 허용 범위를 초과했습니다: {file_size / (1024*1024):.2f}MB > {config.MAX_FILE_SIZE_MB}MB")
            
            logger.info("파일 크기 검증 완료: %.2f MB", file_size / (1024*1024))
            return True
        except OSError as e:
            logger.error("파일 크기 확인 실패: %s", e)
            raise
    
    def validate_mime_type(self) -> str:
        """
        파일의 MIME 타입을 검증하고 반환합니다.
        
        Returns:
            str: 검증된 MIME 타입
            
        Raises:
            ValueError: 지원하지 않는 파일 형식인 경우
        """
        try:
            mime_type = magic.from_file(self.filepath, mime=True)
            logger.info("파일 MIME 타입 감지: %s", mime_type)
            
            # MIME 타입 정규화 (일부 시스템에서 audio/mp3 대신 audio/mpeg를 반환할 수 있음)
            if mime_type == 'audio/mp3':
                mime_type = 'audio/mpeg'
            
            if mime_type not in config.ALLOWED_MIME_TYPES:
                raise ValueError(f"지원하지 않는 파일 형식입니다: {mime_type}. 허용된 형식: {', '.join(config.ALLOWED_MIME_TYPES)}")
            
            logger.info("파일 MIME 타입 검증 완료: %s", mime_type)
            return mime_type
        except Exception as e:
            logger.error("MIME 타입 검증 실패: %s", e)
            raise
    
    def calculate_sha256(self) -> str:
        """
        파일의 SHA-256 해시를 계산합니다.
        
        Returns:
            str: 파일의 SHA-256 해시값 (16진수 문자열)
        """
        try:
            sha256_hash = hashlib.sha256()
            
            with open(self.filepath, 'rb') as f:
                # 큰 파일을 위해 청크 단위로 읽기
                for chunk in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(chunk)
            
            hash_value = sha256_hash.hexdigest()
            logger.info("SHA-256 해시 계산 완료: %s", hash_value)
            return hash_value
        except Exception as e:
            logger.error("SHA-256 해시 계산 실패: %s", e)
            raise
    
    def load_audio_data(self) -> Tuple[np.ndarray, int]:
        """
        오디오 파일을 로드하고 데이터를 반환합니다.
        
        Returns:
            Tuple[np.ndarray, int]: (오디오 데이터, 샘플 레이트)
        """
        try:
            logger.info("오디오 파일 로드 시작: %s", self.filepath)
            
            # 대안 1: soundfile 직접 사용 (더 안전함)
            try:
                logger.info("soundfile 라이브러리 사용하여 로드 시도")
                
                # soundfile로 로드
                self.audio_data, self.sample_rate = sf.read(self.filepath)
                
                # 스테레오를 모노로 변환 (필요시)
                if len(self.audio_data.shape) > 1:
                    self.audio_data = np.mean(self.audio_data, axis=1)
                
                logger.info("soundfile로 오디오 데이터 로드 완료: 샘플 레이트=%d, 길이=%d", 
                           self.sample_rate, len(self.audio_data))
                
                return self.audio_data, self.sample_rate
                
            except ImportError:
                logger.warning("soundfile 라이브러리가 없습니다. librosa 사용")
            except Exception as sf_error:
                logger.warning("soundfile로 로드 실패, librosa 시도: %s", sf_error)
            
            # 대안 2: librosa 안전 모드 사용
            logger.info("librosa 안전 모드로 로드 시도")
            
            # numba 캐싱 완전 비활성화 (전역 설정)
            import os
            os.environ['LIBROSA_CACHE_DIR'] = '/tmp'
            os.environ['LIBROSA_CACHE_LEVEL'] = '0'
            os.environ['NUMBA_CACHE_DIR'] = '/tmp'
            os.environ['NUMBA_DISABLE_JIT'] = '1'
            os.environ['NUMBA_DISABLE_CUDA'] = '1'
            
            # librosa 재import (환경 변수 적용)
            import importlib
            importlib.reload(librosa)
            
            # librosa로 로드 (안전 모드)
            self.audio_data, self.sample_rate = librosa.load(
                self.filepath, 
                sr=None,  # 원본 샘플 레이트 유지
                mono=True,  # 모노로 변환
                res_type='kaiser_fast'  # 빠른 리샘플링
            )
            
            logger.info("librosa로 오디오 데이터 로드 완료: 샘플 레이트=%d, 길이=%d", 
                       self.sample_rate, len(self.audio_data))
            
            return self.audio_data, self.sample_rate
            
        except Exception as e:
            logger.error("오디오 데이터 로드 실패: %s", e)
            logger.error("오류 타입: %s", type(e).__name__)
            
            # 대안 3: 기본 파일 읽기로 폴백 (WAV 파일의 경우)
            try:
                logger.info("기본 WAV 파일 읽기 시도")
                
                # WAV 파일인지 확인
                if self.filepath.lower().endswith('.wav'):
                    import wave
                    
                    with wave.open(self.filepath, 'rb') as wav_file:
                        frames = wav_file.readframes(-1)
                        self.sample_rate = wav_file.getframerate()
                        channels = wav_file.getnchannels()
                        sample_width = wav_file.getsampwidth()
                        
                        # 바이트 데이터를 numpy 배열로 변환
                        if sample_width == 1:
                            dtype = np.uint8
                        elif sample_width == 2:
                            dtype = np.int16
                        elif sample_width == 4:
                            dtype = np.int32
                        else:
                            raise ValueError(f"지원하지 않는 샘플 폭: {sample_width}")
                        
                        audio_array = np.frombuffer(frames, dtype=dtype)
                        
                        # 스테레오를 모노로 변환
                        if channels == 2:
                            audio_array = audio_array.reshape(-1, 2)
                            audio_array = np.mean(audio_array, axis=1)
                        
                        # float32로 정규화
                        if dtype == np.uint8:
                            self.audio_data = (audio_array.astype(np.float32) - 128) / 128.0
                        else:
                            max_val = np.iinfo(dtype).max
                            self.audio_data = audio_array.astype(np.float32) / max_val
                        
                        logger.info("기본 WAV 읽기로 로드 완료: 샘플 레이트=%d, 길이=%d", 
                                   self.sample_rate, len(self.audio_data))
                        
                        return self.audio_data, self.sample_rate
                
            except Exception as wav_error:
                logger.error("기본 WAV 읽기도 실패: %s", wav_error)
            
            # 모든 방법이 실패한 경우
            raise Exception(f"모든 오디오 로드 방법이 실패했습니다. 원본 오류: {e}")
    
    def get_audio_duration(self) -> float:
        """
        오디오 파일의 길이를 초 단위로 반환합니다.
        
        Returns:
            float: 오디오 길이 (초)
        """
        if self.audio_data is None or self.sample_rate is None:
            self.load_audio_data()
        
        duration = len(self.audio_data) / self.sample_rate
        logger.info("오디오 길이: %.2f초", duration)
        return duration
    
    def generate_waveform_peaks(self, num_peaks: int = None) -> List[float]:
        """
        오디오 파일의 파형 피크 데이터를 생성합니다.
        
        Args:
            num_peaks: 생성할 피크 개수 (기본값: config.DEFAULT_WAVEFORM_PEAKS)
            
        Returns:
            List[float]: 정규화된 파형 피크 데이터 (0.0 ~ 1.0 범위)
        """
        if num_peaks is None:
            num_peaks = config.DEFAULT_WAVEFORM_PEAKS
        
        try:
            # 오디오 데이터가 로드되지 않았다면 로드
            if self.audio_data is None:
                self.load_audio_data()
            
            # 모노 채널로 변환 (스테레오인 경우)
            if len(self.audio_data.shape) > 1:
                audio_mono = np.mean(self.audio_data, axis=1)
            else:
                audio_mono = self.audio_data
            
            # 절댓값 계산 (진폭의 크기)
            audio_abs = np.abs(audio_mono)
            
            # 전체 샘플을 num_peaks 개의 구간으로 나누기
            samples_per_peak = len(audio_abs) // num_peaks
            
            if samples_per_peak == 0:
                # 오디오가 너무 짧은 경우
                logger.warning("오디오가 너무 짧습니다. 전체 샘플 수: %d", len(audio_abs))
                peaks = audio_abs.tolist()
                # 패딩으로 num_peaks 개수 맞추기
                while len(peaks) < num_peaks:
                    peaks.append(0.0)
                peaks = peaks[:num_peaks]
            else:
                # 각 구간의 최대값을 피크로 사용
                peaks = []
                for i in range(num_peaks):
                    start_idx = i * samples_per_peak
                    end_idx = start_idx + samples_per_peak
                    
                    if end_idx > len(audio_abs):
                        end_idx = len(audio_abs)
                    
                    # 해당 구간의 최대값
                    peak_value = np.max(audio_abs[start_idx:end_idx])
                    peaks.append(peak_value)
            
            # 정규화 (0.0 ~ 1.0 범위)
            peaks = np.array(peaks)
            max_peak = np.max(peaks)
            
            if max_peak > 0:
                normalized_peaks = peaks / max_peak
            else:
                normalized_peaks = peaks
            
            # 소수점 처리를 위해 부동소수점 정확도 제한
            normalized_peaks = np.round(normalized_peaks, 4)
            
            logger.info("파형 피크 데이터 생성 완료: %d개 피크, 최대값=%.4f", 
                       len(normalized_peaks), max_peak)
            
            return normalized_peaks.tolist()
            
        except Exception as e:
            logger.error("파형 피크 데이터 생성 실패: %s", e)
            raise
    
    def generate_waveform_json(self, num_peaks: int = None) -> str:
        """
        파형 데이터를 JSON 형식으로 생성합니다.
        
        Args:
            num_peaks: 생성할 피크 개수
            
        Returns:
            str: JSON 형식의 파형 데이터
        """
        try:
            peaks = self.generate_waveform_peaks(num_peaks)
            duration = self.get_audio_duration()
            
            waveform_data = {
                'peaks': peaks,
                'duration': duration,
                'sample_rate': self.sample_rate,
                'num_peaks': len(peaks),
                'created_at': self._get_current_timestamp()
            }
            
            json_data = json.dumps(waveform_data, ensure_ascii=False, indent=2)
            logger.info("파형 JSON 데이터 생성 완료: %d바이트", len(json_data))
            
            return json_data
            
        except Exception as e:
            logger.error("파형 JSON 데이터 생성 실패: %s", e)
            raise
    
    def save_waveform_to_file(self, output_path: str, num_peaks: int = None) -> bool:
        """
        파형 데이터를 파일로 저장합니다.
        
        Args:
            output_path: 저장할 파일 경로
            num_peaks: 생성할 피크 개수
            
        Returns:
            bool: 저장 성공 여부
        """
        try:
            json_data = self.generate_waveform_json(num_peaks)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(json_data)
            
            logger.info("파형 데이터 파일 저장 완료: %s", output_path)
            return True
            
        except Exception as e:
            logger.error("파형 데이터 파일 저장 실패: %s", e)
            return False
    
    def process_all(self, num_peaks: int = None) -> dict:
        """
        모든 처리 과정을 실행하고 결과를 반환합니다.
        
        Args:
            num_peaks: 생성할 피크 개수
            
        Returns:
            dict: 처리 결과 데이터
        """
        try:
            logger.info("오디오 파일 전체 처리 시작: %s", self.filepath)
            
            # 1. 파일 크기 검증
            self.validate_file_size()
            
            # 2. MIME 타입 검증
            mime_type = self.validate_mime_type()
            
            # 3. SHA-256 해시 계산
            audio_hash = self.calculate_sha256()
            
            # 4. 오디오 데이터 로드
            self.load_audio_data()
            
            # 5. 파형 피크 데이터 생성
            peaks = self.generate_waveform_peaks(num_peaks)
            
            # 6. 오디오 길이 계산
            duration = self.get_audio_duration()
            
            result = {
                'mime_type': mime_type,
                'audio_data_hash': audio_hash,
                'file_size': self._file_size,
                'duration': duration,
                'sample_rate': self.sample_rate,
                'waveform_peaks': peaks,
                'num_peaks': len(peaks),
                'processed_at': self._get_current_timestamp()
            }
            
            logger.info("오디오 파일 전체 처리 완료")
            return result
            
        except Exception as e:
            logger.error("오디오 파일 처리 실패: %s", e)
            raise
    
    def _get_current_timestamp(self) -> str:
        """현재 타임스탬프를 ISO 형식으로 반환합니다."""
        from datetime import datetime
        return datetime.utcnow().isoformat() + 'Z'

    @staticmethod
    def mix_audio_files(file_paths: List[str], output_path: str) -> bool:
        """
        여러 오디오 파일들을 동시재생(믹스)하여 하나의 WAV 파일로 저장합니다.
        
        Args:
            file_paths: 믹스할 오디오 파일들의 경로 리스트
            output_path: 출력 파일 경로 (WAV 형식)
            
        Returns:
            bool: 믹스 성공 여부
        """
        try:
            if not file_paths:
                logger.error("믹스할 파일이 없습니다.")
                return False
                
            logger.info(f"오디오 파일 믹스 시작: {len(file_paths)}개 파일")
            
            # 각 파일을 로드하여 데이터와 샘플 레이트 수집
            audio_data_list = []
            sample_rates = []
            
            for i, file_path in enumerate(file_paths):
                logger.info(f"파일 {i+1}/{len(file_paths)} 로드 중: {file_path}")
                
                try:
                    # soundfile 우선 사용
                    audio_data, sample_rate = sf.read(file_path)
                    
                    # 스테레오를 모노로 변환
                    if len(audio_data.shape) > 1:
                        audio_data = np.mean(audio_data, axis=1)
                    
                    audio_data_list.append(audio_data)
                    sample_rates.append(sample_rate)
                    
                    logger.info(f"파일 로드 완료: 샘플 레이트={sample_rate}, 길이={len(audio_data)}")
                    
                except Exception as sf_error:
                    logger.warning(f"soundfile로 로드 실패, librosa 시도: {sf_error}")
                    
                    # librosa 사용
                    audio_data, sample_rate = librosa.load(file_path, sr=None, mono=True)
                    audio_data_list.append(audio_data)
                    sample_rates.append(sample_rate)
                    
                    logger.info(f"librosa로 파일 로드 완료: 샘플 레이트={sample_rate}, 길이={len(audio_data)}")
            
            # 모든 파일의 샘플 레이트가 동일한지 확인
            target_sample_rate = sample_rates[0]
            if not all(sr == target_sample_rate for sr in sample_rates):
                logger.warning("샘플 레이트가 다른 파일들이 있습니다. 리샘플링 수행")
                
                # 가장 높은 샘플 레이트로 통일
                target_sample_rate = max(sample_rates)
                
                for i, (audio_data, sample_rate) in enumerate(zip(audio_data_list, sample_rates)):
                    if sample_rate != target_sample_rate:
                        logger.info(f"파일 {i+1} 리샘플링: {sample_rate} -> {target_sample_rate}")
                        audio_data_list[i] = librosa.resample(
                            audio_data, 
                            orig_sr=sample_rate, 
                            target_sr=target_sample_rate
                        )
            
            # 모든 파일을 같은 길이로 맞춤 (가장 긴 파일 기준)
            max_length = max(len(audio_data) for audio_data in audio_data_list)
            logger.info(f"최대 길이: {max_length} 샘플")
            
            # 패딩 또는 자르기
            padded_audio_list = []
            for i, audio_data in enumerate(audio_data_list):
                if len(audio_data) < max_length:
                    # 짧은 파일은 0으로 패딩
                    padded_audio = np.pad(audio_data, (0, max_length - len(audio_data)), mode='constant')
                    logger.info(f"파일 {i+1} 패딩: {len(audio_data)} -> {max_length}")
                else:
                    # 긴 파일은 자르기
                    padded_audio = audio_data[:max_length]
                    if len(audio_data) > max_length:
                        logger.info(f"파일 {i+1} 자르기: {len(audio_data)} -> {max_length}")
                
                padded_audio_list.append(padded_audio)
            
            # 모든 오디오 데이터를 합산 (평균 사용하여 클리핑 방지)
            logger.info("오디오 데이터 믹스 중...")
            mixed_audio = np.mean(padded_audio_list, axis=0)
            
            # 클리핑 방지를 위한 정규화
            max_value = np.max(np.abs(mixed_audio))
            if max_value > 1.0:
                mixed_audio = mixed_audio / max_value
                logger.info(f"클리핑 방지를 위한 정규화 적용: {max_value:.3f}")
            
            # WAV 파일로 저장
            logger.info(f"믹스된 오디오를 WAV 파일로 저장: {output_path}")
            sf.write(output_path, mixed_audio, target_sample_rate)
            
            # 저장된 파일 크기 확인
            file_size = os.path.getsize(output_path)
            duration = len(mixed_audio) / target_sample_rate
            
            logger.info(f"믹스 완료: 길이={duration:.2f}초, 크기={file_size/1024/1024:.2f}MB")
            
            return True
            
        except Exception as e:
            logger.error(f"오디오 믹스 실패: {e}")
            return False 