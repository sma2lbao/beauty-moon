"""Significance tests implemented with the Python standard library only.

No numpy/scipy — t-distribution / normal tail probabilities use math.erf
and the regularized incomplete beta function (Numerical Recipes betai).
"""
import math
from dataclasses import dataclass
from statistics import mean, variance

MIN_SAMPLE = 30


@dataclass
class TTestResult:
    p_value: float | None
    diff: float | None
    ci95: tuple[float, float] | None
    insufficient: bool


@dataclass
class ZTestResult:
    p_value: float | None
    diff: float | None
    ci95: tuple[float, float] | None
    insufficient: bool


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Numerical Recipes)."""
    MAXIT = 200
    EPS = 3.0e-12
    FPMIN = 1.0e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < EPS:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    bt = math.exp(lbeta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _t_sf_two_sided(t: float, df: float) -> float:
    """Two-sided p-value for a t statistic with df degrees of freedom."""
    if df <= 0:
        return 1.0
    x = df / (df + t * t)
    return _betai(df / 2.0, 0.5, x)


def _normal_two_sided(z: float) -> float:
    """Two-sided p-value for a standard normal statistic."""
    return math.erfc(abs(z) / math.sqrt(2.0))


# 95% two-sided critical value from the standard normal (used for CIs)
_Z_95 = 1.959963984540054


def welch_t_test(a: list[float], b: list[float]) -> TTestResult:
    """Welch's t-test. diff = mean(b) - mean(a). Two-sided."""
    n_a, n_b = len(a), len(b)
    if n_a < MIN_SAMPLE or n_b < MIN_SAMPLE:
        return TTestResult(p_value=None, diff=None, ci95=None, insufficient=True)
    mean_a, mean_b = mean(a), mean(b)
    var_a = variance(a) if n_a > 1 else 0.0
    var_b = variance(b) if n_b > 1 else 0.0
    diff = mean_b - mean_a
    se2 = var_a / n_a + var_b / n_b
    se = math.sqrt(se2)
    if se == 0.0:
        # No variance: significant iff means differ, but avoid div-by-zero.
        p = 0.0 if diff != 0.0 else 1.0
        return TTestResult(p_value=p, diff=diff, ci95=(diff, diff), insufficient=False)
    t = diff / se
    df = se2 * se2 / (
        (var_a / n_a) ** 2 / (n_a - 1) + (var_b / n_b) ** 2 / (n_b - 1)
    )
    p = _t_sf_two_sided(t, df)
    margin = _Z_95 * se
    return TTestResult(
        p_value=p, diff=diff, ci95=(diff - margin, diff + margin), insufficient=False
    )


def two_proportion_z_test(
    up_a: int, n_a: int, up_b: int, n_b: int
) -> ZTestResult:
    """Two-proportion z-test. diff = p_b - p_a. Two-sided."""
    if n_a < MIN_SAMPLE or n_b < MIN_SAMPLE:
        return ZTestResult(p_value=None, diff=None, ci95=None, insufficient=True)
    p_a = up_a / n_a
    p_b = up_b / n_b
    diff = p_b - p_a
    pooled = (up_a + up_b) / (n_a + n_b)
    se_pooled = math.sqrt(pooled * (1.0 - pooled) * (1.0 / n_a + 1.0 / n_b))
    if se_pooled == 0.0:
        p = 0.0 if diff != 0.0 else 1.0
        return ZTestResult(p_value=p, diff=diff, ci95=(diff, diff), insufficient=False)
    z = diff / se_pooled
    p = _normal_two_sided(z)
    se_wald = math.sqrt(
        p_a * (1.0 - p_a) / n_a + p_b * (1.0 - p_b) / n_b
    )
    margin = _Z_95 * se_wald
    return ZTestResult(
        p_value=p, diff=diff, ci95=(diff - margin, diff + margin), insufficient=False
    )