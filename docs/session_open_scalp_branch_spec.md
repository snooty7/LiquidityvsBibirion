# Session Open Scalp Branch Spec

## Objective
Create a separate scalping branch that stays consistent with the project philosophy:
- liquidity first
- explicit confirmation
- deterministic risk handling
- simple, testable rules

This branch is not meant to replace the main liquidity model.
It is a separate strategy branch with its own testing and deployment path.

## Working Name
`session_open_scalp_branch`

## Design Principles
- Use session timing as a primary context filter.
- Require a real liquidity event before entry.
- Require a `C1`-style micro confirmation after the liquidity event.
- Avoid trading in the middle of the opening range.
- Keep exits faster and tighter than the swing-style branches.
- Flat is acceptable outside the core session window.

## Candidate Session Windows
### London open model
- Session watch window: `06:00-09:00 UTC`
- Opening range definition: first `15m` from `06:00-06:15 UTC`

### New York open model
- Session watch window: `12:30-15:30 UTC`
- Opening range definition: first `15m` from `12:30-12:45 UTC`

Implementation note:
- Start with one session only in research, not both at once.
- London is the cleaner first candidate for EURUSD.

## Setup Pipeline
### 1. Precondition
Require one of these:
- overnight / pre-session compression
- narrow local range before session open
- nearby liquidity pool relative to opening range high/low

Minimal first version:
- use only a simple pre-open compression test
- avoid adding multiple regime heuristics at once

### 2. Liquidity Event
A valid setup requires one of:
- sweep above opening range high followed by reclaim
- sweep below opening range low followed by rejection
- breakout through opening range after a compression state

Sweep must be meaningful, not a 1-tick poke.

### 3. `C1` Confirmation
After the liquidity event, require a micro confirmation on `M1`.

Bullish example:
- price sweeps below a short-term low or opening range low
- then closes back above reclaimed local micro structure
- first pullback holds above the reclaimed area

Bearish example:
- price sweeps above a short-term high or opening range high
- then closes back below reclaimed local micro structure
- first pullback fails below that reclaimed area

For coding purposes, `C1` should mean:
- a local impulsive candle or 2-candle sequence
- a close back through the micro structure line
- optional retest hold within a limited bar count

## Entry Logic
Preferred first version:
- entry on first pullback after confirmed reclaim / rejection
- not on the raw spike candle

This is important because raw spike entries make the branch too noisy.

## Initial Risk Model
Suggested starting research defaults:
- entry timeframe: `M1`
- context timeframe: `M5`
- stop distance: `4-6 pips` on EURUSD
- target: `1.0R` to `1.5R` partial
- trail remainder aggressively or flat-all by session rule

## Exit Logic
Recommended first version:
- take partial at `+1R`
- move stop to break-even after partial
- close remainder on:
  - trailing stop
  - opposite micro structure break
  - hard session cut-off

Alternative simpler first version:
- full close at `1.5R`
- no runner

For engineering simplicity, start with the simpler version if needed.

## Filters
### Required
- session window filter
- opening range context filter
- liquidity sweep or breakout requirement
- `C1` micro confirmation
- spread cap
- one trade per setup

### Optional later
- trend alignment with `M5` or `M15`
- news blackout
- volatility normalization by ATR

## What to Avoid
- discretionary order-flow interpretation
- manual chart patterns
- too many nested conditions
- ?smart money? narrative without measurable thresholds
- immediate scaling or pyramiding

## Research Plan
### Phase 1
- implement opening range calculation
- implement simple liquidity sweep around OR high/low
- implement `C1` micro confirmation on `M1`
- fixed stop / fixed target
- single session only

### Phase 2
- backtest on EURUSD
- compare London vs NY session separately
- inspect trade count, PF, avg R, and slippage sensitivity

### Phase 3
- only if Phase 2 is promising:
  - add partial + trailing management
  - add higher-timeframe bias filter

## Success Criteria
To justify demo deployment, the branch should show:
- positive net result over at least 180 days
- acceptable PF, ideally > `1.2`
- enough trade count to avoid small-sample illusion
- better frequency than the swing branch without collapsing expectancy

## Recommendation
If we implement this branch, do it as a separate mode/module.
Do not blend it into the existing EURUSD M5 liquidity branch.
