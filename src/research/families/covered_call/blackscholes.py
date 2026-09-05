"""Black-Scholes, used only to *label* strikes — never to price them.

WHY A MODEL IS ALLOWED IN HERE AT ALL
Every rupee of P&L in this family comes from an observed price: the option's
own settlement mark on the day it is written, and the index close on the day it
settles. Nothing is marked to a model. The model exists for one job — to answer
"which of these listed strikes is the 0.15-delta call?" — because that is how
the strategy under test is specified, and a fixed-percentage rule is a different
strategy that happens to look similar.

The implied volatility is backed out of the option's *own* traded settlement
price, so the delta is a restatement of the market's price rather than an
opinion about it. If the price is wrong the delta is wrong in the same
direction, which is the correct behaviour for a labelling device.

NSE index options are European and cash-settled, so the textbook formula applies
without an early-exercise correction. The dividend yield is the Nifty 50 yield
published alongside the index close, which matters more than it sounds: at a
1.2-1.4% yield and a one-week horizon it moves delta in the third decimal, but
over a monthly comparison it is the difference between a 0.15-delta call and a
0.16-delta one.

NO SCIPY
This project's environment does not carry scipy, and a strategy study is not a
reason to add a dependency to it. `erf` comes from the standard library and the
inversion is a bracketed bisection: slower than Brent by a constant factor,
identical to six decimals, and it cannot fail to converge on a bracket that has
already been checked for a sign change.
"""
from __future__ import annotations

import math

import numpy as np

SQRT2 = math.sqrt(2.0)


def norm_cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / SQRT2)


def d1(spot: float, strike: float, rate: float, yield_: float, vol: float,
       years: float) -> float:
    return ((math.log(spot / strike) + (rate - yield_ + 0.5 * vol * vol) * years)
            / (vol * math.sqrt(years)))


def call_price(spot: float, strike: float, rate: float, yield_: float,
               vol: float, years: float) -> float:
    if years <= 0 or vol <= 0:
        return max(0.0, spot * math.exp(-yield_ * max(years, 0.0))
                   - strike * math.exp(-rate * max(years, 0.0)))
    first = d1(spot, strike, rate, yield_, vol, years)
    second = first - vol * math.sqrt(years)
    return (spot * math.exp(-yield_ * years) * norm_cdf(first)
            - strike * math.exp(-rate * years) * norm_cdf(second))


def put_price(spot: float, strike: float, rate: float, yield_: float,
              vol: float, years: float) -> float:
    if years <= 0 or vol <= 0:
        return max(0.0, strike * math.exp(-rate * max(years, 0.0))
                   - spot * math.exp(-yield_ * max(years, 0.0)))
    first = d1(spot, strike, rate, yield_, vol, years)
    second = first - vol * math.sqrt(years)
    return (strike * math.exp(-rate * years) * norm_cdf(-second)
            - spot * math.exp(-yield_ * years) * norm_cdf(-first))


def implied_vol(price: float, spot: float, strike: float, rate: float,
                yield_: float, years: float, option_type: str,
                lo: float = 1e-3, hi: float = 5.0, tol: float = 1e-6) -> float:
    """Solve for the volatility that reproduces an observed premium.

    Returns NaN rather than a number when the quote is not invertible — below
    intrinsic, at zero, or already expired. A deep out-of-the-money weekly
    trading at its ₹0.05 tick is arithmetically invertible and economically
    meaningless, so callers filter on price before trusting the result.
    """
    if not (np.isfinite(price) and price > 0 and years > 0 and spot > 0):
        return float("nan")
    fn = call_price if option_type == "CE" else put_price
    low, high = fn(spot, strike, rate, yield_, lo, years), fn(
        spot, strike, rate, yield_, hi, years)
    if not (low - price) * (high - price) < 0:
        return float("nan")
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        value = fn(spot, strike, rate, yield_, mid, years)
        if abs(value - price) < tol or hi - lo < tol:
            return mid
        if (value - price) * (low - price) < 0:
            hi = mid
        else:
            lo, low = mid, value
    return 0.5 * (lo + hi)


def delta(spot: float, strike: float, rate: float, yield_: float, vol: float,
          years: float, option_type: str) -> float:
    if not (np.isfinite(vol) and vol > 0 and years > 0):
        return float("nan")
    carry = math.exp(-yield_ * years)
    value = carry * norm_cdf(d1(spot, strike, rate, yield_, vol, years))
    return float(value if option_type == "CE" else value - carry)


def chain_delta(strikes, prices, spot: float, rate: float, yield_: float,
                years: float, option_type: str) -> np.ndarray:
    """Delta for a whole listed chain, each from its own quote."""
    out = np.full(len(strikes), np.nan)
    for i, (strike, price) in enumerate(zip(strikes, prices)):
        vol = implied_vol(float(price), spot, float(strike), rate, yield_,
                          years, option_type)
        out[i] = delta(spot, float(strike), rate, yield_, vol, years,
                       option_type)
    return out


__all__ = ["call_price", "chain_delta", "d1", "delta", "implied_vol",
           "norm_cdf", "put_price"]
