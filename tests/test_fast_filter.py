from betai.fast_filter import fast_filter_1x2, FastParams


def test_fast_filter_basic():
    p_est = {"Home": 0.6, "Draw": 0.2, "Away": 0.2}
    res = fast_filter_1x2(2.0, 3.5, 4.0, p_est, bk_cnt=4)
    assert len(res) == 1
    assert res[0].side == "Home"


def test_fast_filter_ev_cutoff():
    p_est = {"Home": 0.4, "Draw": 0.3, "Away": 0.3}
    params = FastParams(EV_min=0.2)
    res = fast_filter_1x2(1.5, 5.0, 6.0, p_est, bk_cnt=4, params=params)
    sides = {s.side for s in res}
    assert sides == {"Draw", "Away"}
