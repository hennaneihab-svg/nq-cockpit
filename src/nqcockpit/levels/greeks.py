"""Modèle Black-Scholes vectorisé pour le calcul des grecs et du gamma.

Adapté de Darthreign/gex-dashboard (MIT), copyright conservé.
"""

from __future__ import annotations

import math

import numpy as np

_EPS = 1e-12
_INV_SQRT_2 = 1.0 / math.sqrt(2.0)
_INV_SQRT_2PI = 1.0 / math.sqrt(2.0 * math.pi)

_vec_erf = np.vectorize(math.erf, otypes=[float])


def _norm_pdf(x: np.ndarray | float) -> np.ndarray:
    """Densité de probabilité de la loi normale centrée réduite N(0, 1)."""
    x_arr = np.asarray(x, dtype=float)
    return _INV_SQRT_2PI * np.exp(-0.5 * x_arr**2)


def _norm_cdf(x: np.ndarray | float) -> np.ndarray:
    """Fonction de répartition de la loi normale centrée réduite N(0, 1)."""
    x_arr = np.asarray(x, dtype=float)
    return 0.5 * (1.0 + _vec_erf(x_arr * _INV_SQRT_2))


def _d1_d2(s, k, t, r, sigma):
    s = np.asarray(s, dtype=float)
    k = np.asarray(k, dtype=float)
    t = np.maximum(np.asarray(t, dtype=float), _EPS)
    sigma = np.maximum(np.asarray(sigma, dtype=float), _EPS)
    d1 = (np.log(s / k) + (r + 0.5 * sigma**2) * t) / (sigma * np.sqrt(t))
    d2 = d1 - sigma * np.sqrt(t)
    return d1, d2


def call_price(s, k, t, r, sigma):
    """Prix théorique d'un call européen Black-Scholes."""
    d1, d2 = _d1_d2(s, k, t, r, sigma)
    return s * _norm_cdf(d1) - k * np.exp(-r * t) * _norm_cdf(d2)


def put_price(s, k, t, r, sigma):
    """Prix théorique d'un put européen Black-Scholes."""
    d1, d2 = _d1_d2(s, k, t, r, sigma)
    return k * np.exp(-r * t) * _norm_cdf(-d2) - s * _norm_cdf(-d1)


def gamma(s, k, t, r, sigma):
    """Gamma de l'option (identique calls et puts)."""
    d1, _ = _d1_d2(s, k, t, r, sigma)
    t = np.maximum(np.asarray(t, dtype=float), _EPS)
    sigma = np.maximum(np.asarray(sigma, dtype=float), _EPS)
    return _norm_pdf(d1) / (np.asarray(s, dtype=float) * sigma * np.sqrt(t))


def call_delta(s, k, t, r, sigma):
    """Delta du call."""
    d1, _ = _d1_d2(s, k, t, r, sigma)
    return _norm_cdf(d1)


def put_delta(s, k, t, r, sigma):
    """Delta du put."""
    return call_delta(s, k, t, r, sigma) - 1.0
