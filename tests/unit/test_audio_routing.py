"""Unit tests for audio routing module"""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.acfv.audio_routing.schemas import (
    VADSegment,
    DiarizationSegment,
    LabeledSegment,
    AudioRoutingConfig
)
from src.acfv.audio_routing.step3_vad import merge_vad_segments
from src.acfv.audio_routing.step4_diarization import align_diarization_to_vad


class TestVADMerge:
    """Test VAD segment merging"""
    
    def test_merge_close_segments(self):
        """Test merging segments with small gaps"""
        segments = [
            VADSegment(start=1.0, end=2.0),
            VADSegment(start=2.1, end=3.0),  # 0.1s gap
        ]
        
        merged = merge_vad_segments(segments, merge_gap=0.2, min_duration=0.5)
        
        assert len(merged) == 1
        assert merged[0].start == 1.0
        assert merged[0].end == 3.0
    
    def test_keep_distant_segments(self):
        """Test keeping segments with large gaps"""
        segments = [
            VADSegment(start=1.0, end=2.0),
            VADSegment(start=3.0, end=4.0),  # 1.0s gap
        ]
        
        merged = merge_vad_segments(segments, merge_gap=0.2, min_duration=0.5)
        
        assert len(merged) == 2
    
    def test_filter_short_segments(self):
        """Test filtering segments shorter than min_duration"""
        segments = [
            VADSegment(start=1.0, end=1.1),  # 0.1s - too short
            VADSegment(start=2.0, end=3.0),  # 1.0s - keep
        ]
        
        merged = merge_vad_segments(segments, merge_gap=0.2, min_duration=0.5)
        
        assert len(merged) == 1
        assert merged[0].start == 2.0


class TestDiarizationAlignment:
    """Test diarization alignment to VAD"""
    
    def test_align_perfect_overlap(self):
        """Test alignment with perfect VAD overlap"""
        diarization = [
            DiarizationSegment(start=1.0, end=2.0, speaker_id="spk_0")
        ]
        vad_segments = [
            VADSegment(start=1.0, end=2.0)
        ]
        
        aligned = align_diarization_to_vad(diarization, vad_segments)
        
        assert len(aligned) == 1
        assert aligned[0].start == 1.0
        assert aligned[0].end == 2.0
    
    def test_align_partial_overlap(self):
        """Test alignment with partial VAD overlap"""
        diarization = [
            DiarizationSegment(start=0.5, end=2.5, speaker_id="spk_0")
        ]
        vad_segments = [
            VADSegment(start=1.0, end=2.0)
        ]
        
        aligned = align_diarization_to_vad(diarization, vad_segments)
        
        assert len(aligned) == 1
        assert aligned[0].start == 1.0  # Clipped to VAD start
        assert aligned[0].end == 2.0    # Clipped to VAD end
    
    def test_align_no_overlap(self):
        """Test alignment with no VAD overlap"""
        diarization = [
            DiarizationSegment(start=1.0, end=2.0, speaker_id="spk_0")
        ]
        vad_segments = [
            VADSegment(start=3.0, end=4.0)
        ]
        
        aligned = align_diarization_to_vad(diarization, vad_segments)
        
        assert len(aligned) == 0  # No overlap


class TestAudioRoutingConfig:
    """Test configuration schema"""
    
    def test_default_config(self):
        """Test default configuration values"""
        config = AudioRoutingConfig()
        
        assert config.use_demucs is True
        assert config.vad.min_speech_sec == 0.25
        assert config.vad.merge_gap_sec == 0.20
        assert config.role_mapping.default_role == "game_speech"
    
    def test_custom_config(self):
        """Test custom configuration values"""
        config = AudioRoutingConfig(
            use_demucs=False,
            vad=AudioRoutingConfig.VADConfig(min_speech_sec=0.5)
        )
        
        assert config.use_demucs is False
        assert config.vad.min_speech_sec == 0.5


class TestLabeledSegment:
    """Test labeled segment schema"""
    
    def test_labeled_segment_creation(self):
        """Test creating labeled segment"""
        segment = LabeledSegment(
            start=1.0,
            end=2.0,
            speaker_id="spk_0",
            role="streamer",
            text="Hello world",
            words=None
        )
        
        assert segment.start == 1.0
        assert segment.role == "streamer"
        assert segment.text == "Hello world"
    
    def test_labeled_segment_with_words(self):
        """Test labeled segment with word timestamps"""
        from src.acfv.audio_routing.schemas import WordTimestamp
        
        segment = LabeledSegment(
            start=1.0,
            end=2.0,
            speaker_id="spk_0",
            role="tts",
            text="Hello",
            words=[WordTimestamp(w="Hello", s=1.0, e=1.5)]
        )
        
        assert len(segment.words) == 1
        assert segment.words[0].w == "Hello"
