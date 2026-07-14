from app.prompts.stats import (
    MIN_SAMPLE,
    two_proportion_z_test,
    welch_t_test,
)


def test_welch_t_test_clear_difference():
    # 两组均值差异明显，方差小 → 应显著 (p < 0.05)，diff>0
    a = [0.50, 0.52, 0.48, 0.51, 0.49] * 8  # n=40, mean≈0.50
    b = [0.70, 0.72, 0.68, 0.71, 0.69] * 8  # n=40, mean≈0.70
    res = welch_t_test(a, b)
    assert res.insufficient is False
    assert res.p_value is not None and res.p_value < 0.05
    assert res.diff is not None and 0.18 < res.diff < 0.22
    lo, hi = res.ci95
    assert lo < res.diff < hi


def test_welch_t_test_no_difference():
    a = [0.60, 0.62, 0.58, 0.61, 0.59] * 8
    b = [0.60, 0.62, 0.58, 0.61, 0.59] * 8
    res = welch_t_test(a, b)
    assert res.insufficient is False
    assert res.p_value is not None and res.p_value > 0.05
    assert abs(res.diff) < 1e-9


def test_welch_t_test_insufficient_sample():
    res = welch_t_test([0.5] * 10, [0.6] * 40)
    assert res.insufficient is True
    assert res.p_value is None
    assert res.diff is None
    assert res.ci95 is None


def test_welch_t_test_zero_variance_no_crash():
    # 两组方差均为 0 且均值相同：不应除零崩溃
    res = welch_t_test([0.5] * 40, [0.5] * 40)
    assert res.insufficient is False
    assert res.diff == 0.0


def test_welch_t_test_zero_variance_diff_nonzero():
    # 两组各自方差为 0 但均值不同 → se==0, diff!=0 → p=0.0
    res = welch_t_test([0.5] * 40, [0.6] * 40)
    assert res.insufficient is False
    assert res.p_value == 0.0
    assert abs(res.diff - 0.1) < 1e-9


def test_two_proportion_z_clear_difference():
    # A: 30/100 好评, B: 70/100 好评 → 显著
    res = two_proportion_z_test(up_a=30, n_a=100, up_b=70, n_b=100)
    assert res.insufficient is False
    assert res.p_value is not None and res.p_value < 0.05
    assert res.diff is not None and 0.38 < res.diff < 0.42


def test_two_proportion_z_insufficient():
    res = two_proportion_z_test(up_a=5, n_a=10, up_b=40, n_b=100)
    assert res.insufficient is True
    assert res.p_value is None
    assert res.diff is None
    assert res.ci95 is None


def test_two_proportion_z_se_pooled_zero():
    # 两组全好评 → pooled=1.0 → se_pooled==0, diff=0 → p=1.0
    # 注：se_pooled==0 且 diff!=0 的分支数学上不可达：
    # pooled∈{0,1} 时两组比例必然都相等（全 0 或全 1），diff 恒为 0
    res = two_proportion_z_test(up_a=40, n_a=40, up_b=40, n_b=40)
    assert res.insufficient is False
    assert res.p_value == 1.0
    assert res.diff == 0.0


def test_min_sample_is_30():
    assert MIN_SAMPLE == 30