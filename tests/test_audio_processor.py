"""
AudioProcessor 클래스의 단위 테스트 모듈
pytest와 moto를 사용하여 모든 핵심 로직을 테스트합니다.
"""

import pytest
import os
import json
import tempfile
import hashlib
import numpy as np
from unittest.mock import patch, MagicMock
from moto import mock_aws
import boto3

from app.audio_processor import AudioProcessor
from app import config

class TestAudioProcessor:
    """AudioProcessor 클래스의 테스트 클래스"""
    
    @pytest.fixture
    def sample_wav_file(self):
        """테스트용 WAV 파일 생성"""
        # 간단한 사인파 WAV 파일을 생성
        import wave
        import struct
        
        # 임시 파일 생성
        with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as tmp_file:
            wav_path = tmp_file.name
        
        # WAV 파일 헤더와 데이터 작성
        with wave.open(wav_path, 'wb') as wav_file:
            wav_file.setnchannels(1)  # 모노
            wav_file.setsampwidth(2)  # 16비트
            wav_file.setframerate(44100)  # 44.1kHz
            
            # 1초 분량의 440Hz 사인파 생성
            duration = 1.0
            sample_rate = 44100
            frequency = 440.0
            
            for i in range(int(sample_rate * duration)):
                value = int(32767 * np.sin(2 * np.pi * frequency * i / sample_rate))
                wav_file.writeframes(struct.pack('<h', value))
        
        yield wav_path
        
        # 정리
        if os.path.exists(wav_path):
            os.unlink(wav_path)
    
    @pytest.fixture
    def sample_text_file(self):
        """테스트용 텍스트 파일 생성 (유효하지 않은 오디오 파일)"""
        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt', mode='w') as tmp_file:
            tmp_file.write("This is not an audio file")
            text_path = tmp_file.name
        
        yield text_path
        
        # 정리
        if os.path.exists(text_path):
            os.unlink(text_path)
    
    @pytest.fixture
    def large_file(self):
        """파일 크기 테스트용 큰 파일 생성"""
        with tempfile.NamedTemporaryFile(delete=False, suffix='.bin') as tmp_file:
            # 101MB 파일 생성 (기본 최대 크기 100MB 초과)
            file_size = 101 * 1024 * 1024
            tmp_file.write(b'0' * file_size)
            large_path = tmp_file.name
        
        yield large_path
        
        # 정리
        if os.path.exists(large_path):
            os.unlink(large_path)
    
    def test_init_with_valid_file(self, sample_wav_file):
        """유효한 파일로 AudioProcessor 초기화 테스트"""
        processor = AudioProcessor(sample_wav_file)
        assert processor.filepath == sample_wav_file
        assert processor.audio_data is None
        assert processor.sample_rate is None
        assert processor._file_size is None
    
    def test_init_with_invalid_file(self):
        """존재하지 않는 파일로 초기화 시 예외 발생 테스트"""
        with pytest.raises(FileNotFoundError):
            AudioProcessor("/nonexistent/file.wav")
    
    def test_validate_file_size_valid(self, sample_wav_file):
        """유효한 파일 크기 검증 테스트"""
        processor = AudioProcessor(sample_wav_file)
        assert processor.validate_file_size() is True
        assert processor._file_size > 0
    
    def test_validate_file_size_too_large(self, large_file):
        """파일 크기 초과 시 예외 발생 테스트"""
        processor = AudioProcessor(large_file)
        with pytest.raises(ValueError, match="파일 크기가 허용 범위를 초과했습니다"):
            processor.validate_file_size()
    
    @patch('magic.from_file')
    def test_validate_mime_type_valid(self, mock_magic, sample_wav_file):
        """유효한 MIME 타입 검증 테스트"""
        mock_magic.return_value = 'audio/wav'
        processor = AudioProcessor(sample_wav_file)
        
        mime_type = processor.validate_mime_type()
        assert mime_type == 'audio/wav'
        mock_magic.assert_called_once_with(sample_wav_file, mime=True)
    
    @patch('magic.from_file')
    def test_validate_mime_type_invalid(self, mock_magic, sample_text_file):
        """유효하지 않은 MIME 타입 검증 테스트"""
        mock_magic.return_value = 'text/plain'
        processor = AudioProcessor(sample_text_file)
        
        with pytest.raises(ValueError, match="지원하지 않는 파일 형식입니다"):
            processor.validate_mime_type()
    
    @patch('magic.from_file')
    def test_validate_mime_type_mp3_normalization(self, mock_magic, sample_wav_file):
        """MP3 MIME 타입 정규화 테스트"""
        mock_magic.return_value = 'audio/mp3'
        processor = AudioProcessor(sample_wav_file)
        
        mime_type = processor.validate_mime_type()
        assert mime_type == 'audio/mpeg'
    
    def test_calculate_sha256(self, sample_wav_file):
        """SHA-256 해시 계산 테스트"""
        processor = AudioProcessor(sample_wav_file)
        hash_value = processor.calculate_sha256()
        
        # 해시 값이 64자의 16진수 문자열인지 확인
        assert len(hash_value) == 64
        assert all(c in '0123456789abcdef' for c in hash_value)
        
        # 같은 파일에 대해 동일한 해시가 나오는지 확인
        hash_value2 = processor.calculate_sha256()
        assert hash_value == hash_value2
        
        # 실제 파일 내용으로 해시 계산해서 비교
        with open(sample_wav_file, 'rb') as f:
            expected_hash = hashlib.sha256(f.read()).hexdigest()
        assert hash_value == expected_hash
    
    @patch('librosa.load')
    def test_load_audio_data(self, mock_librosa_load, sample_wav_file):
        """오디오 데이터 로드 테스트"""
        # 가상의 오디오 데이터 생성
        fake_audio_data = np.array([0.1, 0.2, 0.3, 0.4, 0.5])
        fake_sample_rate = 44100
        mock_librosa_load.return_value = (fake_audio_data, fake_sample_rate)
        
        processor = AudioProcessor(sample_wav_file)
        audio_data, sample_rate = processor.load_audio_data()
        
        assert np.array_equal(audio_data, fake_audio_data)
        assert sample_rate == fake_sample_rate
        assert np.array_equal(processor.audio_data, fake_audio_data)
        assert processor.sample_rate == fake_sample_rate
        
        mock_librosa_load.assert_called_once_with(sample_wav_file, sr=None)
    
    def test_get_audio_duration(self, sample_wav_file):
        """오디오 길이 계산 테스트"""
        processor = AudioProcessor(sample_wav_file)
        
        # 가상의 오디오 데이터 설정
        processor.audio_data = np.array([0.0] * 44100)  # 1초 분량
        processor.sample_rate = 44100
        
        duration = processor.get_audio_duration()
        assert duration == 1.0
    
    def test_generate_waveform_peaks(self, sample_wav_file):
        """파형 피크 데이터 생성 테스트"""
        processor = AudioProcessor(sample_wav_file)
        
        # 가상의 오디오 데이터 설정
        processor.audio_data = np.array([0.1, 0.8, 0.3, 0.9, 0.2, 0.7, 0.4, 0.6])
        processor.sample_rate = 8
        
        # 4개의 피크 생성
        peaks = processor.generate_waveform_peaks(num_peaks=4)
        
        assert len(peaks) == 4
        assert all(0.0 <= peak <= 1.0 for peak in peaks)
        assert isinstance(peaks, list)
        assert all(isinstance(peak, float) for peak in peaks)
    
    def test_generate_waveform_peaks_short_audio(self, sample_wav_file):
        """짧은 오디오에 대한 파형 피크 생성 테스트"""
        processor = AudioProcessor(sample_wav_file)
        
        # 피크 개수보다 적은 샘플 수
        processor.audio_data = np.array([0.1, 0.2])
        processor.sample_rate = 2
        
        peaks = processor.generate_waveform_peaks(num_peaks=4)
        
        assert len(peaks) == 4
        assert peaks[0] == 0.1
        assert peaks[1] == 0.2
        assert peaks[2] == 0.0  # 패딩
        assert peaks[3] == 0.0  # 패딩
    
    def test_generate_waveform_peaks_stereo(self, sample_wav_file):
        """스테레오 오디오에 대한 파형 피크 생성 테스트"""
        processor = AudioProcessor(sample_wav_file)
        
        # 스테레오 오디오 데이터 설정 (2D 배열)
        stereo_data = np.array([[0.1, 0.2], [0.3, 0.4], [0.5, 0.6], [0.7, 0.8]])
        processor.audio_data = stereo_data
        processor.sample_rate = 4
        
        peaks = processor.generate_waveform_peaks(num_peaks=2)
        
        assert len(peaks) == 2
        assert all(0.0 <= peak <= 1.0 for peak in peaks)
    
    def test_generate_waveform_json(self, sample_wav_file):
        """파형 JSON 데이터 생성 테스트"""
        processor = AudioProcessor(sample_wav_file)
        
        # 가상 데이터 설정
        processor.audio_data = np.array([0.1, 0.2, 0.3, 0.4])
        processor.sample_rate = 4
        
        json_data = processor.generate_waveform_json(num_peaks=2)
        
        # JSON 파싱 가능한지 확인
        parsed_data = json.loads(json_data)
        
        assert 'peaks' in parsed_data
        assert 'duration' in parsed_data
        assert 'sample_rate' in parsed_data
        assert 'num_peaks' in parsed_data
        assert 'created_at' in parsed_data
        
        assert len(parsed_data['peaks']) == 2
        assert parsed_data['duration'] == 1.0
        assert parsed_data['sample_rate'] == 4
        assert parsed_data['num_peaks'] == 2
    
    def test_save_waveform_to_file(self, sample_wav_file):
        """파형 데이터 파일 저장 테스트"""
        processor = AudioProcessor(sample_wav_file)
        
        # 가상 데이터 설정
        processor.audio_data = np.array([0.1, 0.2, 0.3, 0.4])
        processor.sample_rate = 4
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.json') as tmp_file:
            output_path = tmp_file.name
        
        try:
            success = processor.save_waveform_to_file(output_path, num_peaks=2)
            assert success is True
            
            # 파일이 생성되었는지 확인
            assert os.path.exists(output_path)
            
            # 파일 내용이 유효한 JSON인지 확인
            with open(output_path, 'r', encoding='utf-8') as f:
                saved_data = json.load(f)
            
            assert 'peaks' in saved_data
            assert len(saved_data['peaks']) == 2
            
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)
    
    @patch('magic.from_file')
    def test_process_all(self, mock_magic, sample_wav_file):
        """전체 처리 과정 테스트"""
        mock_magic.return_value = 'audio/wav'
        
        processor = AudioProcessor(sample_wav_file)
        
        # 가상 데이터 설정
        processor.audio_data = np.array([0.1, 0.2, 0.3, 0.4])
        processor.sample_rate = 4
        
        with patch.object(processor, 'load_audio_data', return_value=(processor.audio_data, processor.sample_rate)):
            result = processor.process_all(num_peaks=2)
        
        # 결과 검증
        assert 'mime_type' in result
        assert 'audio_data_hash' in result
        assert 'file_size' in result
        assert 'duration' in result
        assert 'sample_rate' in result
        assert 'waveform_peaks' in result
        assert 'num_peaks' in result
        assert 'processed_at' in result
        
        assert result['mime_type'] == 'audio/wav'
        assert result['duration'] == 1.0
        assert result['sample_rate'] == 4
        assert len(result['waveform_peaks']) == 2
        assert result['num_peaks'] == 2
    
    def test_process_all_with_exception(self, sample_wav_file):
        """처리 과정에서 예외 발생 테스트"""
        processor = AudioProcessor(sample_wav_file)
        
        # MIME 타입 검증에서 예외 발생하도록 설정
        with patch.object(processor, 'validate_mime_type', side_effect=ValueError("Test error")):
            with pytest.raises(ValueError, match="Test error"):
                processor.process_all()


class TestAudioProcessorIntegration:
    """AudioProcessor 통합 테스트 클래스"""
    
    @pytest.fixture
    def real_wav_file(self):
        """실제 WAV 파일 생성 (librosa 로드 가능)"""
        import soundfile as sf
        
        # 1초 분량의 440Hz 사인파 생성
        duration = 1.0
        sample_rate = 44100
        frequency = 440.0
        
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        audio_data = np.sin(2 * np.pi * frequency * t)
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as tmp_file:
            wav_path = tmp_file.name
        
        # soundfile을 사용해서 WAV 파일 생성
        sf.write(wav_path, audio_data, sample_rate)
        
        yield wav_path
        
        # 정리
        if os.path.exists(wav_path):
            os.unlink(wav_path)
    
    def test_full_processing_pipeline(self, real_wav_file):
        """전체 처리 파이프라인 통합 테스트"""
        processor = AudioProcessor(real_wav_file)
        
        # 파일 크기 검증
        assert processor.validate_file_size() is True
        
        # 해시 계산
        hash_value = processor.calculate_sha256()
        assert len(hash_value) == 64
        
        # 오디오 데이터 로드
        audio_data, sample_rate = processor.load_audio_data()
        assert len(audio_data) > 0
        assert sample_rate == 44100
        
        # 파형 피크 생성
        peaks = processor.generate_waveform_peaks(num_peaks=128)
        assert len(peaks) == 128
        assert all(0.0 <= peak <= 1.0 for peak in peaks)
        
        # 오디오 길이 계산
        duration = processor.get_audio_duration()
        assert 0.9 <= duration <= 1.1  # 약 1초 (오차 허용)
        
        # JSON 생성
        json_data = processor.generate_waveform_json(num_peaks=64)
        parsed_data = json.loads(json_data)
        assert len(parsed_data['peaks']) == 64
        
        # 전체 처리
        result = processor.process_all(num_peaks=32)
        assert result['num_peaks'] == 32
        assert result['duration'] == duration
        assert result['sample_rate'] == sample_rate
        assert result['audio_data_hash'] == hash_value


@pytest.fixture(scope='session')
def aws_credentials():
    """AWS 자격 증명 설정"""
    os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
    os.environ['AWS_SECURITY_TOKEN'] = 'testing'
    os.environ['AWS_SESSION_TOKEN'] = 'testing'
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'


@mock_aws
def test_aws_integration(aws_credentials):
    """AWS 서비스 통합 테스트 (moto 사용)"""
    # 이 테스트는 실제 AWS 서비스 연동을 테스트하지만
    # moto로 모킹되어 실제 AWS 리소스는 사용하지 않음
    
    # S3 버킷 생성
    s3 = boto3.client('s3', region_name='us-east-1')
    s3.create_bucket(Bucket='test-bucket')
    
    # SQS 큐 생성
    sqs = boto3.client('sqs', region_name='us-east-1')
    queue_url = sqs.create_queue(QueueName='test-queue')['QueueUrl']
    
    # 연결 테스트
    s3.head_bucket(Bucket='test-bucket')
    sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=['QueueArn'])
    
    # 테스트 통과 