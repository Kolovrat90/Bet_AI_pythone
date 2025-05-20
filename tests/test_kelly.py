from betai.models import Outcome, allocate_bank

def test_kelly_example():
    bank = 1000
    outs = [
        Outcome(fixture_id=1, date="", time="", league="", match="",
                market="1X2", pick_ru="", line=None,
                k_dec=2.10, p_model=0.540),
        Outcome(fixture_id=2, date="", time="", league="", match="",
                market="1X2", pick_ru="", line=None,
                k_dec=1.95, p_model=0.560),
        Outcome(fixture_id=3, date="", time="", league="", match="",
                market="1X2", pick_ru="", line=None,
                k_dec=3.60, p_model=0.310),
    ]
    for o in outs:
        o.compute_edge()
    allocate_bank(outs, bank)
    stakes = [o.stake_eur for o in outs]
    assert sum(stakes) == 150      # 15 % банка
