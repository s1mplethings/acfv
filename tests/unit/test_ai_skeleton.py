"""Unit tests for AI skeleton functionality"""
import pytest
from unittest.mock import patch, MagicMock
from src.acfv.enhance.rag.ai_skeleton import AISkeleton, get_ai_recommendation


class TestAISkeleton:
    """Test cases for AISkeleton class"""

    @patch('subprocess.check_call')
    @patch('builtins.__import__')
    def test_initialization_checks_libraries(self, mock_import, mock_subprocess):
        """Test that initialization checks for required libraries"""
        # Mock successful imports
        mock_import.side_effect = lambda name, *args, **kwargs: MagicMock()

        skeleton = AISkeleton()

        # Should check all required packages
        assert len(skeleton._libraries_loaded) == 3
        assert all(skeleton._libraries_loaded.values())

    @patch('subprocess.check_call')
    @patch('builtins.__import__')
    def test_is_ready_when_all_libraries_loaded(self, mock_import, mock_subprocess):
        """Test is_ready returns True when all libraries are loaded"""
        mock_import.side_effect = lambda name, *args, **kwargs: MagicMock()

        skeleton = AISkeleton()
        assert skeleton.is_ready() is True

    @patch('subprocess.check_call')
    @patch('builtins.__import__')
    def test_is_ready_when_libraries_missing(self, mock_import, mock_subprocess):
        """Test is_ready returns False when libraries are missing"""
        mock_import.side_effect = ImportError("No module")

        skeleton = AISkeleton()
        assert skeleton.is_ready() is False

    @patch('subprocess.check_call')
    @patch('builtins.__import__')
    def test_generate_recommendation_no_backend_available(self, mock_import, mock_subprocess):
        """Test behavior when no AI backend is available"""
        mock_import.side_effect = ImportError

        skeleton = AISkeleton()

        context = {'video_title': 'Test Video'}
        result = skeleton.generate_recommendation(context)

        assert result is None

    @patch('subprocess.check_call')
    @patch('builtins.__import__')
    def test_build_prompt_constructs_correct_prompt(self, mock_import, mock_subprocess):
        """Test prompt building with context"""
        mock_import.side_effect = lambda name, *args, **kwargs: MagicMock()

        skeleton = AISkeleton()

        context = {
            'video_title': 'Test Video',
            'duration': 300,
            'user_preferences': ['funny', 'effects']
        }

        prompt = skeleton._build_prompt(context)

        assert 'Test Video' in prompt
        assert '300 seconds' in prompt
        assert 'funny' in prompt
        assert 'effects' in prompt


class TestGetAIRecommendation:
    """Test cases for get_ai_recommendation function"""

    def test_get_ai_recommendation_calls_skeleton(self):
        """Test that get_ai_recommendation uses the global skeleton instance"""
        with patch('src.acfv.enhance.rag.ai_skeleton.ai_skeleton') as mock_skeleton:
            mock_skeleton.generate_recommendation.return_value = "Mock result"

            context = {'test': 'context'}
            result = get_ai_recommendation(context)

            mock_skeleton.generate_recommendation.assert_called_once_with(context)
            assert result == "Mock result"