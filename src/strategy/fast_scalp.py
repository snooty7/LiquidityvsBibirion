"""Pure, causal M1/M5 scalp-entry hypotheses, independent of broker execution."""
from dataclasses import dataclass
from bisect import bisect_right
from datetime import datetime, timezone
import math

from src.strategy.filters import ema
from src.strategy.liquidity import SweepSignal

MODELS = ("m1_sweep_reclaim", "m1_ema_reclaim", "m5_sweep_m1_confirm")


@dataclass(frozen=True)
class ScalpEntry:
    """A closed-bar signal with immutable structural initial protection."""

    signal: SweepSignal
    stop_price: float
    note: str
    target_price: float = 0.0
    tp_r_multiple: float = 2.0
    risk_pct_override: float = 0.0


class ScalpFeatures:
    """Cache only backward-recursive indicators from validated bid OHLC history.

    Accessing index i never uses M1 bars after i or a M5 bar that has not yet
    closed. No centered pivots, future extrema or full-history normalization.
    """

    def __init__(self, m1, m5, pip):
        if not math.isfinite(pip) or pip <= 0:
            raise ValueError("A positive finite pip size is required")
        self.m1, self.m5, self.pip = m1, m5, pip
        self.m5_times = [int(b["time"]) for b in m5]
        self.ema1 = ema([float(b["close"]) for b in m1], 20)
        self.fast5 = ema([float(b["close"]) for b in m5], 20)
        self.slow5 = ema([float(b["close"]) for b in m5], 50)
        self.range_prefix = [0.0]
        for b in m1:
            self.range_prefix.append(self.range_prefix[-1] + float(b["high"])-float(b["low"]))

    def at(self, i, model):
        """Return a signal available at the close of M1 index i, or None."""
        if model not in MODELS:
            raise ValueError("Unknown fast-scalp hypothesis")
        if i < 24 or i >= len(self.m1):
            return None
        current, previous = self.m1[i], self.m1[i-1]
        decision_time = int(current["time"])+60
        j = bisect_right(self.m5_times, decision_time-300)-1
        if j < 54:
            return None
        # Bias precedes the most recent completed M5 setup bar.
        k = j-1
        direction = (1 if self.fast5[k] > self.slow5[k] and self.fast5[k] > self.fast5[k-3]
                     else -1 if self.fast5[k] < self.slow5[k] and self.fast5[k] < self.fast5[k-3] else 0)
        if not direction:
            return None
        span = float(current["high"])-float(current["low"])
        body = direction*(float(current["close"])-float(current["open"]))
        average = (self.range_prefix[i]-self.range_prefix[i-20])/20
        if span <= 0 or body/span < .6 or span < 1.2*average:
            return None
        side = "BUY" if direction == 1 else "SELL"
        low_side, high_side = ("low", "high") if direction == 1 else ("high", "low")
        extreme = min if direction == 1 else max
        close = float(current["close"])
        if model == "m1_sweep_reclaim":
            level = extreme(float(b[low_side]) for b in self.m1[i-13:i-1])
            if direction*(float(previous[low_side])-level) >= -.2*self.pip or direction*(float(previous["close"])-level) <= 0:
                return None
            if direction*(close-float(previous[high_side])) <= 0:
                return None
            setup_time, setup_extreme = int(previous["time"]), float(previous[low_side])
        elif model == "m1_ema_reclaim":
            level = extreme(float(b[low_side]) for b in self.m1[i-5:i-1])
            if direction*(float(previous[low_side])-level) >= -.2*self.pip:
                return None
            if direction*(float(previous["close"])-self.ema1[i-1]) >= 0 or direction*(close-self.ema1[i]) <= 0:
                return None
            if direction*(close-float(previous[high_side])) <= 0:
                return None
            setup_time, setup_extreme = int(previous["time"]), float(previous[low_side])
        else:
            sweep = self.m5[j]
            age = decision_time-(int(sweep["time"])+300)
            if not 0 < age <= 300:
                return None
            level = extreme(float(b[low_side]) for b in self.m5[j-12:j])
            if direction*(float(sweep[low_side])-level) >= -.2*self.pip or direction*(float(sweep["close"])-level) <= 0:
                return None
            confirmation_level = (max if direction == 1 else min)(float(b[high_side]) for b in self.m1[i-2:i])
            if direction*(close-confirmation_level) <= 0:
                return None
            setup_time, setup_extreme = int(sweep["time"]), float(sweep[low_side])
        structure = extreme([setup_extreme]+[float(b[low_side]) for b in self.m1[i-4:i+1]])
        stop = structure-direction*.2*self.pip
        distance = direction*(close-stop)/self.pip
        # Reject too-small/large structural stops; never pad them to a desired size.
        if not 6 <= distance <= 15:
            return None
        return ScalpEntry(SweepSignal(side, level, setup_time), stop,
                          f"{model}; M5_trend={side}; structural_stop={distance:.2f}pips")

    def signals(self, model, start, end):
        """Precompute causal setups once; suppress duplicate confirmations of one sweep."""
        output, seen = {}, set()
        for i, bar in enumerate(self.m1):
            timestamp = int(bar["time"])+60
            if not start <= timestamp < end:
                continue
            # Matches the fixed daylight policy; no test-outcome-driven hour filter.
            now = datetime.fromtimestamp(timestamp, timezone.utc)
            if now.weekday() >= 5 or not 5 <= now.hour < 18:
                continue
            entry = self.at(i, model)
            if entry is None:
                continue
            key = (entry.signal.side, entry.signal.candle_time, entry.signal.level)
            if key not in seen:
                output[timestamp] = entry
                seen.add(key)
        return output


class ScalpSignalProvider:
    """Offline replay adapter over a table of causally available closed-bar signals."""

    def __init__(self, signals):
        self.signals = signals

    def has_signal(self, timestamp):
        """Permit skipping entry feature construction only, never position management."""
        return timestamp in self.signals

    def __call__(self, cfg, pip, trigger_rates, closed_setup, closed_bias):
        if cfg.timeframe != "M1":
            raise ValueError("Fast scalp provider requires M1 decision timestamps")
        # Replay appends one dummy forming candle: its price is never consulted.
        if len(trigger_rates) < 2:
            return None, [], None
        timestamp = int(trigger_rates[-2]["time"])+60
        result = self.signals.get(timestamp)
        return (result.signal, [], result) if result else (None, [], None)
