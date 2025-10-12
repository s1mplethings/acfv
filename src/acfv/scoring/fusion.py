import numpy as np
from acfv.features.audio import AudioFeatures

def fuse_scores(feats: AudioFeatures, settings):
    w = settings.scoring.weights
    s = w["loudness"] * feats.loudness + w["pitch_var"] * feats.pitch_var
    s = (s - s.min()) / (s.ptp() + 1e-8)
    return {"t": feats.t, "score": s}
