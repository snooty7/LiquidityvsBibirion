# Strategy Knowledge Base

## Current live recommendation
- Trade only `EURUSD`.
- Keep `per_trade_loss_guard_mode = position_risk`.
- Keep `per_trade_loss_risk_multiple = 1.0`.
- Use `confirmation_mode = sweep_displacement_mss`.
- Use `confirm_expiry_bars = 3`.
- Use `range_filter_max_compression_ratio = 2.5`.
- Use `range_filter_min_overlap_ratio = 0.75`.
- Use `confirmation_displacement_body_ratio_min = 0.55`.
- Use `confirmation_displacement_range_multiple = 1.80`.
- Keep base `order_block_max_distance_pips = 8.0`.
- Do not enable the conditional order-block override in live config yet.

## Why this is the current recommendation
### EURUSD M5 tuned candidate
Validated on 180-day backtest window `2025-09-29` to `2026-03-27`.

- Previous current candidate:
  - `disp = 1.70`
  - `overlap = 0.75`
  - trades: `85`
  - net: `+52.25`
  - PF: `1.269`
  - avg R: `0.142`
  - max DD: `$49.14`
- Improved candidate:
  - `disp = 1.80`
  - `overlap = 0.75`
  - trades: `76`
  - net: `+68.08`
  - PF: `1.405`
  - avg R: `0.208`
  - max DD: `$44.83`

Interpretation:
- Fewer trades, but cleaner trades.
- Better profit factor and expectancy.
- Slightly lower drawdown.
- This is a meaningful improvement, not just a trade-count artifact.

## Displacement strictness adjustment
Observed live behavior on `2026-04-02`:
- several `EURUSD M5` setups reached `SETUP_PENDING`
- they stayed at `sdmss_wait_displacement`
- they expired before confirmation

Action taken:
- keep `confirmation_displacement_range_multiple = 1.80`
- loosen only `confirmation_displacement_body_ratio_min` from `0.60` to `0.55`

Reasoning:
- this is a smaller and safer relaxation than cutting the range multiple
- it accepts slightly less perfect displacement candles without fully opening the gate

Quick comparison on a moderate validation pass:
- baseline `0.60 / 1.80`: `78 trades`, net `-3.13`, PF `0.989`
- loosened `0.55 / 1.80`: `82 trades`, net `+6.86`, PF `1.023`

Interpretation:
- the loosened body-ratio gate is still weakly edged, not a dramatic improvement
- but it is the best result among the tested small relaxations
- therefore it is a reasonable tactical change for ongoing demo observation

## Multi-symbol expansion results
All tests used the same strategy family on a 180-day window.

### Rejected symbols
- `GBPUSD`: net `-34.85`, PF `0.820`
- `USDJPY`: net `-5.29`, PF `0.943`
- `USDCAD`: net `-49.41`, PF `0.688`
- `AUDUSD`: net `-19.72`, PF `0.873`
- `NZDUSD`: net `-75.82`, PF `0.681`
- `USDCHF`: net `-38.75`, PF `0.872`

Interpretation:
- `EURUSD` remains the only symbol with a defendable edge in the current model.
- Do not add the other symbols to live trading with a copy-paste config.

### Local shortlist for the next trading day
Prepared local candidates for Monday observation:
- `92021` `GBPUSD M1 trend_micro_burst_v2`
  - `102` trades
  - net `+6.19`
  - `PF 1.454`
- `92022` `GBPUSD M1 NY tight`
  - `8` trades
  - net `+6.79`
  - `PF 4.980`
  - small sample, keep expectations conservative
- `92023` `NZDUSD M30 liquidity_sweep`
  - `42` trades
  - net `+94.43`
  - `PF 1.791`
- `92024` `USDCHF M30 liquidity_sweep`
  - `36` trades
  - net `+83.75`
  - `PF 1.408`

Deployment note:
- these four are the current local expansion shortlist
- they should run in a separate profile from `92001`
- `92001` remains the production reference branch and is not part of this expansion set

## USDJPY branch research
A small dedicated `USDJPY` branch was tested with adjusted spread tolerance and nearby threshold tuning.

Best branch tested on 180 days:
- `sl_pips = 10`
- `confirmation_displacement_range_multiple = 1.70`
- `range_filter_min_overlap_ratio = 0.70`
- `max_spread_pips = 2.6`
- trades: `58`
- net: `+1.91`
- PF: `1.023`
- avg R: `0.012`
- max DD: `$23.18`

Interpretation:
- Technically no longer negative.
- Practically too weak to justify a live slot.
- Keep as a research branch only.

## EURUSD timeframe research
Exploratory 180-day comparison:

- `M5 current candidate`:
  - trades: `76`
  - net: `+68.08`
  - PF: `1.405`
  - avg R: `0.208`
- `M15 exploratory`:
  - trades: `49`
  - net: `-113.80`
  - PF: `0.450`
  - avg R: `-0.359`
- `M30 exploratory`:
  - trades: `12`
  - net: `+40.17`
  - PF: `2.164`
  - avg R: `0.388`

Interpretation:
- `M15` is rejected.
- `M30` is interesting, but the sample is too small (`12` trades in 180 days).
- `M30` should stay in research only until it is validated on a longer window.
- Local tuning note:
  - `92008` performed better with `H4` bias than with `H1` bias or no bias on the `2026-01-11 -> 2026-04-10` branch-only backtest.
  - Reason: `H1` bias was blocking too many otherwise valid `M30` continuation entries.

## EURUSD trend micro-burst research
`Trend Micro-Burst v1` was tested as:
- `H4` trend context
- `M1` pullback + micro breakout entry
- fast exits via:
  - `1-2` adverse closes
  - or `1` large adverse `M1` bar

Test window:
- `2025-12-23` to `2026-03-31`

Best `London` cases:
- `SL=4`, `RR=2`, `pullback=2`, `2 adverse closes`
  - trades: `579`
  - net: `-0.49`
  - PF: `0.994`
  - avg R: `-0.001`
- `SL=4`, `RR=2`, `pullback=3`, `2 adverse closes`
  - trades: `597`
  - net: `-0.61`
  - PF: `0.993`
  - avg R: `-0.001`

Best `New York` case:
- trades: `674`
- net: `-7.18`
- PF: `0.945`
- avg R: `-0.015`

Interpretation:
- The branch generates the desired trade frequency.
- `London` is close to breakeven.
- `New York` is not acceptable.
- `v1` is not good enough for live deployment.
- The problem is no longer signal scarcity; the problem is expectancy.

Decision:
- Mark `Trend Micro-Burst v1` as `rejected-for-live / near-breakeven`.
- Do not add it to demo or production as-is.
- Continue only with a `London-only v2` branch and a different exit architecture.

## Order-block distance findings
Recent `SKIP_ORDER_BLOCK` cases were split into:
- `no local order block`
- `order block too far`

For the `too far` subgroup, the blocked outcomes were mixed.
A conditional override was implemented and tested historically.

Result:
- The override degraded both the 90-day and 180-day EURUSD results.
- Therefore the override must remain disabled in live config.

## LIQUIDITY_ALERT branch research
Question tested:
- what happens if the bot trades directly from the `LIQUIDITY_ALERT` stage
- meaning:
  - liquidity level found
  - sweep detected
  - sweep judged significant
  - entry allowed immediately, without waiting for displacement/BOS

Test window:
- `2025-09-29` to `2026-03-27`
- `EURUSD M5`

Variants tested:

### 1. Alert-only
- `confirmation_mode = none`
- no bias filter
- no order-block filter

Result:
- trades: `683`
- net: `-139.96`
- PF: `0.948`

Verdict:
- rejected

### 2. Alert + bias
- `confirmation_mode = none`
- bias filter on
- order-block filter off

Result:
- trades: `480`
- net: `-71.41`
- PF: `0.962`

Verdict:
- rejected

### 3. Alert + bias + order block
- `confirmation_mode = none`
- bias filter on
- order-block filter on

Result:
- trades: `277`
- net: `-54.84`
- PF: `0.950`

Verdict:
- rejected as a two-sided branch

### 4. Alert + bias + order block, SELL-only
- same as variant 3
- but only `SELL` trades are allowed

Result:
- trades: `170`
- wins: `102`
- losses: `68`
- win rate: `60.00%`
- net: `+102.82`
- PF: `1.174`
- avg R: `0.070`
- max DD: `$68.11`

Interpretation:
- the raw `LIQUIDITY_ALERT` idea is not robust enough as a two-sided strategy
- but it does show a usable `SELL-only` pocket on `EURUSD M5`
- this is a research/demo branch candidate, not a production recommendation yet

Decision:
- do not run a two-sided `LIQUIDITY_ALERT` branch
- if experimenting live, only test the `SELL-only` branch with small risk

## Operational rules going forward
- Do not expand symbols unless a candidate is positive on at least 180 days with acceptable PF.
- Prefer improving `EURUSD` expectancy before adding breadth.
- Treat `USDJPY` and `EURUSD M30` as research branches, not production branches.
- Keep a strict separation between:
  - live config
  - historical experiment configs
  - research conclusions

## Useful report files
- `reports/eurusd_grid_90d.csv`
- `reports/eurusd_180d_validation.csv`
- `reports/eurusd_timeframe_compare_180d.csv`
- `reports/usdjpy_grid_90d.csv`
- `reports/usdjpy_180d_best_branch.csv`
- `reports/backtest_gbpusd_180d.csv`
- `reports/backtest_usdjpy_180d.csv`
- `reports/backtest_usdcad_180d.csv`
- `reports/backtest_audusd_180d.csv`
- `reports/backtest_nzdusd_180d.csv`
- `reports/backtest_usdchf_180d.csv`

## Future Branch Roadmap
### 1. `eurusd_m30_liquidity_branch`
Status:
- Enabled locally in demo as a low-risk secondary branch.
- Still under-validated because the usable historical sample is small.

Purpose:
- Capture slower, cleaner liquidity/structure moves than `EURUSD M5`.
- Accept lower trade frequency in exchange for potentially higher per-trade quality.

Current profile:
- `timeframe = M30`
- `bias_timeframe = H1`
- `confirmation timeframe = M5`
- `sl_pips = 20`
- `risk_pct = 0.05`
- `max_lot = 0.03`

Decision rule:
- Keep it live only on demo until meaningful sample size is collected.
- Do not promote it to the primary branch yet.

### 2. `usdjpy_liquidity_branch`
Status:
- Research only.

Purpose:
- Explore whether a JPY-specific liquidity model can become a second production branch.

Current evidence:
- Best tested branch is roughly flat, not convincingly profitable.
- It is not ready for live deployment.

Next research direction:
- Separate thresholds from `EURUSD`.
- Focus on spread handling, session timing, and confirmation strength.

### 3. `session_open_scalp_branch`
Status:
- Design stage only.

Purpose:
- Add a high-frequency, session-driven branch that still respects the core liquidity philosophy.
- This branch must not become an indicator-noise bot.

Local GBPUSD note:
- `GBPUSD` tested better in the New York session than in the London session.
- New local branch:
  - `92022`
  - `GBPUSD M1 NY tight`
  - tuned around the `92012` family
- Best retained compromise on `2026-01-07 -> 2026-04-07`:
  - `watch_minutes = 150`
  - `preopen_max_compression_ratio = 3.0`
  - `body_ratio_min = 0.42`
- Result:
  - `8` trades
  - net `+6.79`
  - `PF 4.980`
- Interpretation:
  - still too small a sample to trust
  - keep as a strict experimental branch only

## Branch policy
- `92001` is the production winner and must stay unchanged.
- Any new idea must be implemented as a new branch with:
  - a new `magic`
  - separate historical validation
  - separate local demo observation
- Do not change `92001` entry logic, exits, sessions, or filters in order to test new hypotheses.

## Close-path and observability work
Observed problem:
- real trades were opening
- some broker-side closes were ending as `POSITION_CLOSED_UNCONFIRMED`
- this made active trading days look quieter than they really were

Work completed:
- added fallback close-deal matching in the MT5 adapter
- if a close deal cannot be matched cleanly by `position_id`, fallback matching now uses:
  - `symbol`
  - `magic`
  - `volume`
  - `opened_at`
- hardened SQLite transactions with savepoint fallback so runtime checkpointing no longer crashes on nested transaction state

Operational meaning:
- close visibility is better than before
- daily trading activity is easier to reconstruct
- runtime persistence is more stable under overlapping transaction paths

## Daily review and missed-profit reporting
Problem:
- ad hoc console reading was not enough to understand:
  - how many setups almost became trades
  - how many profitable setups were missed
  - why they were missed

Work completed:
- added automatic startup report generation for the previous Sofia trading day
- output files:
  - `reports/daily_review_YYYY-MM-DD.txt`
  - `reports/day_near_trades_YYYY-MM-DD.csv`
- the report now includes:
  - actual `TRADE_OK` count
  - near-trades count
  - `confirmed-but-not-opened`
  - `pending-only`
  - per-setup what-if outcomes
  - per-branch net pips
  - missed-profit calculation in `EUR` using local `max_lot`

Current money-summary logic:
- uses local branch `max_lot` from `config/settings.json`
- uses symbol pip value in `EUR`
- reports:
  - branch-by-branch missed `pips -> EUR`
  - total missed `EUR`
  - special block for `92001`
  - positive-only missed `EUR`
  - `confirmed-but-not-opened` missed `EUR`

Interpretation:
- this is not a theoretical backtest-only number
- it is a practical “what was left on the table” view under the local sizing profile

## Push notification simplification
Problem:
- push notifications were too noisy
- ticket/setup-level metadata made them harder to scan on the phone

Work completed:
- push messages were reduced to only:
  - `event`
  - `symbol`
  - `side`
  - `time` in `Europe/Sofia`
  - `entry`
  - `sl`
  - `tp`
  - `trailing`

Interpretation:
- phone alerts are now operational, not forensic
- detailed reconstruction remains in:
  - `bot_events.csv`
  - `daily_review_YYYY-MM-DD.txt`
  - SQLite persistence

## Signal dashboard
Work completed:
- created a local web dashboard under `dashboard/`
- it visualizes:
  - `M1`
  - `M5`
  - `H1`
  - `D1`
- it overlays signal-stage markers directly on candles

Dashboard improvements already made:
- chart refresh no longer resets zoom/pan
- price display is fixed to 5 decimals
- markers were simplified from arrows to small colored letter markers
- live candle fetch was aligned to MT5 by switching to recent-bar retrieval instead of the earlier range path

Operational purpose:
- gives a TradingView-like monitoring surface for signal flow
- useful for understanding:
  - where a setup first appeared
  - how it progressed through stages
  - where it was rejected or executed

## M1 / New York branch research
### `opening_range_breakout_v2` (`92016`)
Status:
- best current `M1 / New York` candidate
- enabled locally as a demo research branch

Best tuned pocket found:
- `use_h1_bias = true`
- `sl_pips = 4.0`
- `rr = 1.0`
- `max_hold_bars = 4`
- `early_exit_consecutive_adverse_closes = 1`
- `body_ratio_min = 0.48`
- `range_multiple = 1.35`
- `pullback_bars = 2`
- `buffer_pips = 0.10`

Research result:
- `106` trades
- `+44.10 pips`
- `PF 1.699`
- `win rate 43.40%`
- `max DD 11.60 pips`

Decision:
- keep as demo research branch
- do not promote over `92001`

### `ny_micro_pullback_drift`
Status:
- research only

Result:
- there is some life in the idea
- but it remains weaker than `NY ORB v2`

Decision:
- rejected for live deployment
- useful as a directional research reference only

### `ny_reclaim_continuation`
Status:
- research only

Result:
- too few trades
- negative first-pass outcome

Decision:
- rejected

## New branch for missed-continuation pain point
Problem observed:
- many strong continuation moves were staying `pending-only`
- some good confirmed setups were blocked by:
  - `SKIP_ORDER_BLOCK`
  - `SKIP_PORTFOLIO_CAP`

New branch idea:
- `92017`
- separate from `92001`
- intended to address:
  - longer pending lifetime
  - wider order-block tolerance
  - optional portfolio-cap bypass on the experimental branch only

Research result on the reference 90-day window:
- `92001 baseline`
  - trades: `73`
  - net: `+517.68`
  - PF: `1.690`
  - avg R: `0.331`
  - max DD: `139.76`
- `92017` candidate with `confirm_expiry_bars = 5`, `order_block_max_distance_pips = 12`, `ignore_portfolio_cap = true`
  - trades: `135`
  - net: `+574.72`
  - PF: `1.419`
  - avg R: `0.199`
  - max DD: `174.28`

Interpretation:
- statistically acceptable as a separate branch
- not cleaner than `92001`
- higher trade count, lower PF, higher drawdown
- must remain separate and low-risk if used

Decision:
- do not merge its behavior into `92001`
- if observed live, treat it strictly as an experimental companion branch
- Local tuning note:
  - `confirm_expiry_bars = 6` was a better compromise than `5` or `7` on the `2026-01-11 -> 2026-04-10` branch-only backtest.
  - `7` increased trade count but reduced quality too much.

## 92001 fast-path research outcome
Question tested:
- can `92001` be made more active by skipping confirmation or accelerating entry?

Result:
- fast-entry variants increased trade count
- but degraded profit factor, expectancy, and drawdown materially

Interpretation:
- some single days make fast entry look attractive
- over the full test window, it weakens the model

Decision:
- do not change `92001`
- solve “missed continuation” only through separate experimental branches

Core idea:
- Opening range liquidity event
- Followed by `C1`-style micro confirmation
- Fast management, fast invalidation, and session-bound exits

Research requirement:
- Build and backtest it as a separate branch, not as a patch on the current `M5` liquidity model.

### 4. `trend_micro_burst_v2_branch`
Status:
- Specification only.

Purpose:
- Build a fast, trend-following micro branch with many trades, but without falling into `next pip` noise.
- Keep the model aligned with the current philosophy:
  - higher-timeframe context
  - lower-timeframe trigger
  - fast invalidation

What was learned from `v1`:
- H4 context is useful.
- Fixed-RR exits are too rigid for this branch.
- London session is materially better than New York.

Research direction:
- `London-only`
- `H4` trend filter
- `M1` breakout-pullback-reacceleration entry
- no symmetric fixed-RR as the primary exit
- favor:
  - quick partial
  - fail-fast momentum exit
  - trend-decay exit

Preliminary implementation result:
- `London-only` does show a positive pocket.
- Best tested `v2` case so far:
  - `pullback_bars = 3`
  - `body_ratio = 0.45`
  - `range_multiple = 1.4`
  - `SL = 4 pips`
  - `RR = 1.5`
  - `2 adverse closes`
  - `large_adverse_body_r = 0.6`
  - trades: `114`
  - net: `+4.61`
  - PF: `1.352`
  - avg R: `0.058`
  - max DD: `$3.50`

Interpretation:
- Better than `v1`.
- Still modest, but now positive and testable.
- This is a research candidate for demo, not a production branch yet.

Local GBPUSD note:
- New local branch:
  - `92021`
  - `GBPUSD M1 trend_micro_burst_v2`
- Result on `2026-01-07 -> 2026-04-07`:
  - `102` trades
  - net `+6.19`
  - `PF 1.454`
  - `avg R 0.089`
- Interpretation:
  - this is the first `GBPUSD` branch with enough sample and positive expectancy to justify continued demo observation
  - if `GBPUSD` is expanded further, this is the cleaner first candidate

### 5. `M1 archetype research`
Status:
- Research complete for first pass.

Goal:
- Test whether a very short-hold `M1` family can produce enough positive expectancy to justify a new branch.
- Keep the objective practical:
  - small pip targets
  - few candles in the trade
  - explicit cost-aware results

Test window:
- `EURUSD`
- `2025-12-23` -> `2026-03-31`
- PnL includes a simple entry spread penalty, because `M1` results without costs are misleading.

Archetypes tested:
1. `two_candle_momentum`
- Idea:
  - two strong candles in the same direction
  - continuation break beyond the first candle
  - `H1` bias filter enabled
- Result:
  - `London`: `656` trades, `-77.60 pips`, `PF 0.848`
  - `New York`: `658` trades, `-4.60 pips`, `PF 0.993`
- Verdict:
  - Not good enough.
  - The naive idea "two bullish candles = buy" is too noisy.

2. `opening_range_breakout`
- Idea:
  - first `15m` range of the session
  - take continuation breakout beyond that range
  - `H1` bias filter enabled
- Result:
  - `London`: `845` trades, `-99.70 pips`, `PF 0.866`
  - `New York`: `819` trades, `+50.40 pips`, `PF 1.052`
- Verdict:
  - `London` rejected.
  - `New York` is the only first-pass positive pocket, but still thin.
  - This is the only archetype from the first pass worth carrying into a second research iteration.

3. `overreaction_fade`
- Idea:
  - fade a statistically stretched `M1` bar after local overextension
  - no higher-timeframe bias
- Result:
  - `London`: `298` trades, `-15.20 pips`, `PF 0.909`
  - `New York`: `219` trades, `-24.90 pips`, `PF 0.877`
- Verdict:
  - Rejected.
  - There is not enough edge after costs.

First-pass conclusion:
- `M1` is not solved by simple candle color logic.
- The first pass rejects:
  - `two_candle_momentum`
  - `overreaction_fade`
  - `London opening_range_breakout`
- The only candidate worth a second pass is:
  - `New York opening_range_breakout`

Next research direction:
- Build `M1 NY ORB v2` instead of adding more naive candle-pattern rules.
- Focus on:
  - `New York only`
  - stricter quality filter after breakout
  - small target / fast invalidation
  - no blind two-candle entry logic

Second-pass result:
- `M1 NY ORB v2` improved meaningfully versus the raw ORB branch.

Best tested case:
- `opening_range_breakout_v2_newyork_tight`
- `116` trades
- `+33.20 pips`
- `PF 1.459`
- `win rate 40.52%`
- `avg R 0.072`
- `max DD 14.90 pips`

Interpretation:
- This is better quality than the raw `New York opening_range_breakout` branch:
  - fewer trades
  - lower drawdown
  - materially higher `PF`
- It is still a research candidate, not a production branch.
- But this is now the strongest `M1` continuation idea tested so far.

Decision:
- Continue from `M1 NY ORB v2 tight`.
- Do not continue with:
  - `two_candle_momentum`
  - `overreaction_fade`
  - `London ORB`

Latest rerun and tuning status:
- After the final detector patch, `NY Micro-Pullback Drift` stayed positive, but weaker than the first optimistic run:
  - `ny_micro_pullback_drift_newyork`
  - `249` trades
  - `+9.50 pips`
  - `PF 1.060`
  - verdict: research-only, too thin for live
- The tighter variant is better:
  - `ny_micro_pullback_drift_newyork_tight`
  - `162` trades
  - `+26.70 pips`
  - `PF 1.308`
  - verdict: promising, but still secondary to ORB v2

Final focused tuning pass for `NY ORB v2`:
- Best validated candidate:
  - `opening_range_breakout_v2`
  - `New York only`
  - `use_h1_bias = true`
  - `sl_pips = 4.0`
  - `rr = 1.0`
  - `max_hold_bars = 4`
  - `adverse_limit = 1`
  - `body_ratio_min = 0.48`
  - `range_multiple = 1.35`
  - `pullback_bars = 2`
  - `buffer_pips = 0.10`
- Result:
  - `106` trades
  - `+44.10 pips`
  - `PF 1.699`
  - `win rate 43.40%`
  - `avg R 0.104`
  - `max DD 11.60 pips`

Current decision:
- `NY ORB v2` is now the strongest `M1` research branch.
- `NY Micro-Pullback Drift` remains useful research context, but not the branch to prioritize for live demo sampling.

## 2026-04-13 live tuning note

Context:
- running the full `16`-branch live stack from `config/settings.json`
- focus was on the two branches that showed same-day missed-but-small positive near-trades:
  - `92010` `EURUSD M1`
  - `92018` `EURUSD M5`

Same-day what-if result:
- `92010` expired setup `c8fd3272`:
  - outcome if entered: `+2.1 pips`
  - interpretation: slightly too strict on confirmation expiry
- `92018` expired setup `2aeb6438`:
  - outcome if entered: `+3.5 pips`
  - interpretation: tempting to extend expiry, but must be tested against full-window quality
- `92021` confirmed setup `754bd3a4` was blocked by session filter:
  - what-if outcome: `-1.5 pips`
  - interpretation: session filter was correct for that sample

Focused backtest pass:
- reference window:
  - `2026-01-07 -> 2026-04-13 11:00 UTC`

`92010`:
- baseline `confirm_expiry_bars = 5`
  - `15` trades
  - `net +2.45`
  - `PF 1.572`
- variant `confirm_expiry_bars = 7`
  - `17` trades
  - `net +5.59`
  - `PF 2.308`
- variant `confirm_expiry_bars = 8`
  - same result as `7`
- decision:
  - promote `92010` to `confirm_expiry_bars = 7`
  - this improves trade count, net, and PF without increasing max DD in the tested window

`92018`:
- baseline `confirm_expiry_bars = 3`
  - `91` trades
  - `net +419.95`
  - `PF 1.546`
  - `max DD 98.49`
- variant `confirm_expiry_bars = 4`
  - `114` trades
  - `net +417.90`
  - `PF 1.436`
  - `max DD 108.06`
- variant `confirm_expiry_bars = 5`
  - `134` trades
  - `net +377.37`
  - `PF 1.315`
  - `max DD 116.10`
- decision:
  - keep `92018` unchanged at `confirm_expiry_bars = 3`
  - extending expiry adds trades but degrades edge and drawdown profile

Operational outcome:
- live config updated:
  - `92010 confirm_expiry_bars = 7`
  - `92018` unchanged
- `GBPUSD 92021/92022` lot cap in active `config/settings.json` was aligned to `0.20`
- live orchestrator restarted after the change

Takeaway:
- `92010` was genuinely too tight and earned a live tuning change
- `92018` looked tight in the moment, but the broader test says the current version is still the better one

## 2026-04-28 Volume Sweep Reclaim research branch

Hypothesis:
- user-observed pattern: larger M5 tick volume often appears around sweep candles
- tested edge: high tick volume should not be traded alone; it needs a liquidity sweep and reclaim

Initial statistical read:
- high tick volume roughly increases the probability of a sweep, but also increases breakout/continuation frequency
- raw rule `volume spike -> sweep/reclaim` was negative in the first broad test
- the only promising variant was mean-reversion context:
  - buy below EMA50 after sellside sweep/reclaim
  - sell above EMA50 after buyside sweep/reclaim

Implemented research/demo branch:
- folder: `live/volume_sweep_reclaim_demo_92025_92028`
- strategy mode: `volume_sweep_reclaim`
- branches:
  - `92025` EURUSD M5
  - `92026` GBPUSD M5
  - `92027` USDCHF M5
  - `92028` NZDUSD M5

Core rules:
- previous liquidity window: `20` M5 candles
- tick volume must be at least `1.8x` prior `20` candle volume SMA
- reclaim candle body ratio must be at least `0.50`
- EMA context: trade against EMA50 location
- SL: behind sweep wick by `0.3` pip
- TP: fixed `8` pip target through custom TP risk context
- max hold: `12` M5 bars
- session: `12:00-18:00 UTC`

Backtest window:
- `2025-08-25 -> 2026-04-28`
- dry-run research profile, `0.01` max lot

Results:
- `92025` EURUSD M5:
  - `7` trades
  - `+23.0` pips
  - pip PF `3.347`
  - win rate `71.43%`
- `92026` GBPUSD M5:
  - `8` trades
  - `-35.1` pips
  - pip PF `0.129`
  - win rate `12.50%`
- `92027` USDCHF M5:
  - `3` trades
  - `-3.1` pips
  - pip PF `0.640`
  - win rate `33.33%`
- `92028` NZDUSD M5:
  - `6` trades
  - `+12.5` pips
  - pip PF `2.582`
  - win rate `66.67%`

Decision:
- not ready for live money because trade count is too small
- EURUSD and NZDUSD are worth monitoring in demo/research only
- GBPUSD and USDCHF do not currently validate this edge
- this strategy should not be merged into the active top live branches until it produces a larger validated sample

## 2026-04-28 HTF Liquidity Sweep BOS FVG research

Strategy idea:
- HTF: `M15`
- LTF confirmation: `M1`
- flow:
  - sweep HTF liquidity
  - close back inside level
  - BOS in the opposite direction
  - form FVG or order block
  - price retests the zone
  - M1 BOS confirms the entry
  - SL beyond sweep
  - TP tested as fixed `2R`

Implemented research tool:
- `src/tools/research_htf_liquidity_sweep_bos_fvg.py`

Conservative implementation details:
- sweep types:
  - previous day high
  - previous day low
  - equal highs
  - equal lows
- BOS requires:
  - close through recent M15 structure
  - body ratio filter
  - impulse range filter
- entry zone:
  - FVG if available
  - fallback to last opposite-candle order block
- entry requires M1 BOS during the M15 retest candle

Backtest window:
- `2025-08-25 -> 2026-04-28`

Base result, `RR=2.0`:
- `EURUSD`:
  - `63` trades
  - `+17.6` pips
  - PF `1.066`
  - win rate `36.5%`
  - avg R `-0.017`
- `GBPUSD`:
  - `64` trades
  - `-113.8` pips
  - PF `0.755`
  - win rate `34.4%`
- `NZDUSD`:
  - `55` trades
  - `-92.2` pips
  - PF `0.571`
  - win rate `29.1%`
- `USDCHF`:
  - `55` trades
  - `+125.0` pips
  - PF `1.636`
  - win rate `49.1%`
  - avg R `0.276`

Focused tuning pass:
- `EURUSD` did not hold edge:
  - base: `+17.6` pips, PF `1.066`
  - `RR=1.5`: `-29.6` pips, PF `0.890`
  - stricter equal levels: `+0.1` pips, PF `1.000`
  - faster BOS/retest: `-45.4` pips, PF `0.784`
- `USDCHF` stayed positive across variants:
  - base: `+125.0` pips, PF `1.636`
  - `RR=1.5`: `+87.5` pips, PF `1.455`
  - stricter equal levels: `+99.7` pips, PF `1.532`
  - faster BOS/retest: `+29.9` pips, PF `1.214`

Decision:
- not a EURUSD live candidate at this stage
- USDCHF is a real research candidate because it stayed positive across several variants
- next useful step is to convert only the USDCHF version into a demo branch after adding a stronger TP target selector toward opposing liquidity
