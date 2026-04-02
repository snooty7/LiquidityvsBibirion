# Trend Micro-Burst v2

## Status
- Research specification only.
- Not approved for live or demo deployment.

## Goal
Build a high-frequency `EURUSD` branch that follows trend logically instead of trying to predict the next pip in isolation.

The branch should:
- trade often enough to matter
- keep per-trade risk small
- exit quickly when momentum fails
- keep the core logic deterministic and testable

## Why `v1` was not enough
`Trend Micro-Burst v1` proved that the signal family can generate enough trades, but the expectancy was still negative:
- `London`: near breakeven
- `New York`: clearly negative

Main weakness:
- the exit model was too rigid
- fixed `RR` was not a good fit for short-duration trend continuation

## Core idea
This branch should not ask:
- `Will the next pip be up or down?`

It should ask:
- `Is the higher-timeframe trend clear?`
- `Did lower timeframe pull back against that trend?`
- `Is price now re-accelerating back with the trend?`

That is the correct structure for a fast trend branch.

## Session scope
- `London only`
- initial session window:
  - `06:00-09:00 UTC`

Do not mix London and New York in the same branch.

## Timeframes
- trend context: `H4`
- execution timeframe: `M1`

## Trend filter
Trend direction should be deterministic.

Minimum acceptable version:
- `H4 EMA20`
- `BUY` only if:
  - last closed `H4` close > `EMA20`
  - `EMA20` slope positive
- `SELL` only if:
  - last closed `H4` close < `EMA20`
  - `EMA20` slope negative

Optional later refinement:
- require at least `2` aligned `H4` closes in trend direction

## Setup definition
### 1. Pullback
Before entry, `M1` must pull back against the `H4` trend:
- bullish branch:
  - `2-4` bearish `M1` candles
- bearish branch:
  - `2-4` bullish `M1` candles

This avoids buying/selling in the middle of an already extended impulse.

### 2. Re-acceleration trigger
Entry is allowed only when a strong `M1` candle resumes in trend direction.

Minimum requirements:
- strong body ratio
- close through recent micro structure
- candle range not abnormally tiny

Bullish example:
- after bearish pullback
- current `M1` candle closes above the highs of the pullback cluster
- candle body ratio above threshold

Bearish example:
- after bullish pullback
- current `M1` candle closes below the lows of the pullback cluster
- candle body ratio above threshold

## Proposed parameters for v2 baseline
- `pullback_bars = 3`
- `body_ratio_min = 0.50`
- `sl_pips = 4.0`
- no order-block filter
- no liquidity-sweep requirement
- `cooldown_sec = 180`
- `max_spread_pips = 1.2`

These are baseline research values only.

## Exit model
This is the key change from `v1`.

### Primary exit philosophy
Do not rely on symmetric fixed `RR` as the main edge.

Use:
1. quick partial / quick realization
2. momentum failure exit
3. hard protective stop

### v2 exit proposal
Initial stop:
- fixed `4 pips`

Quick profit action:
- at `+0.8R`:
  - move stop to break-even or slightly positive

Momentum decay exit:
- exit on `2` consecutive adverse `M1` closes

Large adverse bar exit:
- exit on `1` large adverse `M1` body

Optional runner logic:
- keep a small runner only if momentum stays strong

For backtest simplicity, first implementation may approximate this with:
- modest TP
- plus early-exit rules

But the design intent is:
- fast capture
- fast invalidation

## What must be measured
For every backtest:
- trades
- net pnl
- avg R
- profit factor
- max drawdown
- win rate
- average hold time
- London-only breakdown

## Acceptance bar
Do not promote to live unless all of these are true:
- positive net pnl
- `PF > 1.10`
- enough trade count to matter
- drawdown acceptable relative to branch risk

Near-breakeven is not enough.

## Out of scope
- next-pip prediction
- martingale
- averaging down
- grid logic
- opaque ML classifier without interpretable baseline

## Implementation order
1. Add `trend_micro_burst_v2` signal detector
2. Backtest `London-only`
3. Compare against `v1`
4. Only then consider demo deployment
