import numpy as np
import pytest

from mortality import insured

AGES = np.arange(18, 85)


def reference(ages=AGES):
    """A Gompertz-like population curve."""
    return np.clip(0.00015 * np.exp(0.095 * (np.asarray(ages) - 18) / 1.0) * 3.0, 1e-6, 0.9)


def simulate(a, b, exposure=200_000.0, seed=1, ages=AGES):
    q_ref = reference(ages)
    q = insured.special.expit(a + b * insured.logit(q_ref))
    rng = np.random.default_rng(seed)
    e = np.full(len(ages), exposure)
    return rng.binomial(e.astype(int), q), e, q_ref, q


def test_brass_recovers_planted_parameters_within_their_intervals():
    d, e, q_ref, _ = simulate(a=-1.6, b=0.93)
    fit = insured.fit_brass(d, e, q_ref)
    se = np.sqrt(np.diag(fit.cov))
    assert abs(fit.a - (-1.6)) < 3 * se[0]
    assert abs(fit.b - 0.93) < 3 * se[1]
    assert fit.n_ages == len(AGES)
    assert fit.dispersion < 2.0  # binomial data: close to 1


def test_brass_prediction_is_close_to_truth_and_intervals_cover_it():
    d, e, q_ref, q_true = simulate(a=-1.2, b=0.9, seed=4)
    fit = insured.fit_brass(d, e, q_ref)
    lo, hi = fit.interval(q_ref)
    assert np.all(lo < fit.predict(q_ref)) and np.all(fit.predict(q_ref) < hi)
    covered = np.mean((lo <= q_true) & (q_true <= hi))
    assert covered > 0.85


def test_brass_dispersion_widens_intervals_for_overdispersed_counts():
    d, e, q_ref, _ = simulate(a=-1.6, b=0.93, seed=2)
    rng = np.random.default_rng(9)
    noisy = np.maximum(0, d * np.exp(rng.normal(0, 0.15, len(d)))).round()
    clean = insured.fit_brass(d, e, q_ref)
    rough = insured.fit_brass(noisy, e, q_ref)
    assert rough.dispersion > clean.dispersion
    assert rough.cov[0, 0] > clean.cov[0, 0]


def test_extension_moves_the_ratio_to_one_and_stays_monotone():
    ages = np.arange(0, 111)
    q_ref = np.clip(0.0001 * np.exp(0.1 * ages), 0, 1)
    q_ref[-1] = 1.0
    q_fit = 0.2 * q_ref  # ratio 0.2 everywhere
    out = insured.extend_to_reference(ages, q_fit, q_ref, last_age=84, converge_age=105)
    assert np.allclose(out[:85], q_fit[:85])  # untouched up to the last fitted age
    ratio = out / q_ref
    assert ratio[84] == pytest.approx(0.2)
    assert ratio[105] == pytest.approx(1.0)
    assert np.all(np.diff(ratio[84:106]) >= -1e-12)
    assert np.all(np.diff(out) >= 0)
    assert out[-1] == 1.0
    assert np.allclose(out[106:], q_ref[106:])


def test_extension_leaves_the_young_age_dip_alone():
    """Infant mortality is higher than at 20: only the old ages are forced upward."""
    ages = np.arange(0, 111)
    q_ref = np.clip(0.0001 * np.exp(0.1 * ages), 0, 1)
    q_ref[0] = 0.01  # infant mortality above everything up to the 40s
    q_ref[-1] = 1.0
    q_fit = 0.2 * q_ref
    out = insured.extend_to_reference(ages, q_fit, q_ref, last_age=84, converge_age=105)
    assert out[0] == pytest.approx(0.002)
    assert out[20] == pytest.approx(0.2 * q_ref[20]) and out[20] < out[0]
    assert np.all(np.diff(out[84:]) >= 0)


def test_extension_never_goes_down_when_the_fit_is_above_the_reference():
    ages = np.arange(0, 111)
    q_ref = np.clip(0.0001 * np.exp(0.1 * ages), 0, 1)
    q_ref[-1] = 1.0
    out = insured.extend_to_reference(ages, 1.3 * q_ref, q_ref, last_age=84, converge_age=100)
    assert np.all(np.diff(out) >= 0) and out.max() <= 1.0


def test_extension_requires_convergence_above_the_last_age():
    ages = np.arange(0, 111)
    q = np.full(111, 0.01)
    with pytest.raises(ValueError):
        insured.extend_to_reference(ages, q, q, last_age=90, converge_age=90)
