import numpy as np
from typing import List, Tuple

def select_clips(score_dict, settings) -> List[Tuple[float, float]]:
    t = score_dict["t"]
    s = score_dict["score"]
    idxs = np.argsort(s)[::-1].tolist()
    chosen = []
    for i in idxs:
        ts = t[i]
        if all(abs(ts - (a+b)/2) >= settings.selection.min_gap_s for a,b in chosen):
            a = max(0.0, ts - settings.selection.lead_s)
            b = ts + settings.selection.tail_s
            chosen.append((a,b))
        if len(chosen) >= settings.selection.topk:
            break
    chosen.sort()
    return chosen
