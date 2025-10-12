import numpy as np
from dataclasses import dataclass

@dataclass
class AudioFeatures:
    loudness: np.ndarray
    pitch_var: np.ndarray
    t: np.ndarray

def extract_audio_features(media_path: str, settings) -> AudioFeatures:
    t = np.linspace(0, 300, 3000)
    loudness = np.clip(np.sin(t/3) + 0.2*np.random.randn(t.size), -1, 3)
    pitch_var = np.clip(np.cos(t/5) + 0.2*np.random.randn(t.size), -1, 3)
    return AudioFeatures(loudness=loudness, pitch_var=pitch_var, t=t)
