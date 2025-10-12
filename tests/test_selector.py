from acfv.selection.selector import select_clips

def test_select_basic():
    scores = {"t": [0,1,2,9,10,19], "score": [0.1,0.2,0.9,0.3,0.8,0.7]}
    class S: pass
    class Sel: pass
    S.selection = Sel()
    S.selection.min_gap_s = 8
    S.selection.lead_s = 0.4
    S.selection.tail_s = 0.6
    S.selection.topk = 2
    clips = select_clips(scores, S)
    assert len(clips) == 2
