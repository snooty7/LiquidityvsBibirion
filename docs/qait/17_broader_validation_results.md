# Broader preregistered validation

Completed on 2026-11-12: eight registered reports, 270 completed arm ledgers
and six explicit unavailable phase/cost slots. Full adaptive made one test
position, losing 2.86 after costs in the base case, and no test positions under
doubled costs. **Improved tradeable adaptive performance is not established.**

## Design and scope

The complete design was frozen in
[the preregistration](16_broader_validation_preregistration.md) and
`reports/qait/broad_20261112/registration.json` before replay. Source, input
histories, effective configurations, costs, arms and windows are hash checked.
The existing audited signal implementation and every numeric adaptive setting
are unchanged from the scoring study. Five arms run under base and doubled
costs, with no fitting or threshold selection.

Four FX instruments were registered. EURUSD, GBPUSD and USDCHF use saved exports
beginning October 2024; NZDUSD's export begins July 2025. The existing EURUSD
92001 M5/M1 profile is cloned for matched research comparisons, changing only
the symbol. This is not a simulation of each instrument's deployed profile.
Original production profiles remain unchanged. Risk sizing, risk budgets,
spread limits, loss guards and adaptive preflight settings are held fixed.
BTCUSDT is outside the unchanged six-letter FX currency/exposure mapping and
was not included or given a bypass.

Each phase/fold starts with 10,000 independently. Train/validation/test durations
are 90/30/180 calendar days with one-day embargoes. No training or validation
results select parameters. Test windows are nonoverlapping within an instrument;
training periods can overlap earlier test dates, as explicitly defined by the
rolling protocol. Instrument accounts are independent, not a portfolio.

No verifiably untouched saved holdout was available. These same exports have
already been used by earlier studies. Chronological test windows are therefore
development evidence, not a fresh confirmatory out-of-sample evaluation.

## Coverage exclusions

The unchanged coverage rule rejects any phase with a calendar bar separation
longer than three days. Independent raw timestamps show a 259,560-second
separation (72 hours, 6 minutes) from 2026-04-02 23:59 UTC to 2026-04-06 00:05
UTC in EURUSD, GBPUSD and NZDUSD. This spans Easter; bar timestamps alone do not
establish missing tradable prices. No holiday exception, fabricated bar, date
substitution or coverage-threshold change was introduced.

Consequently EURUSD/GBPUSD fold-3 tests and NZDUSD's sole test window remain
unavailable under both costs. NZDUSD training/validation ran but supply no test
evidence. USDCHF has no phase exceeding the fixed gap limit. Seven of ten
registered test windows are coverage eligible: two EURUSD, two GBPUSD and three
USDCHF, each under both cost cases. Incomplete terminal folds remain untested.
See `reports/qait/broad_20261112/coverage_audit.json` for every registered phase.

## Paired test results

Each cell is **closed positions / net account money after costs**. Each row is
an independent 10,000 reset account, not a component of a synchronized portfolio.
No cross-instrument return, compounded return or pooled drawdown is implied.
The shadow arm has exactly the same ledger as full adaptive in every phase.

### Base costs

| Instrument / fold | Test window (end exclusive) | Baseline | Regime only | Scoring only | Full adaptive |
| --- | --- | ---: | ---: | ---: | ---: |
| EURUSD / 1 | 2025-03-03 to 2025-08-30 | 240 / -39.46 | 51 / -12.80 | 13 / -8.65 | 0 / +0.00 |
| EURUSD / 2 | 2025-08-30 to 2026-02-26 | 269 / -293.23 | 38 / -62.30 | 7 / -25.27 | 0 / +0.00 |
| GBPUSD / 1 | 2025-03-03 to 2025-08-30 | 244 / -234.80 | 53 / -60.18 | 21 / +36.68 | 0 / +0.00 |
| GBPUSD / 2 | 2025-08-30 to 2026-02-26 | 244 / -553.91 | 35 / -68.67 | 4 / -5.96 | 0 / +0.00 |
| USDCHF / 1 | 2025-03-03 to 2025-08-30 | 276 / -1046.45 | 79 / -242.66 | 20 / -35.43 | 0 / +0.00 |
| USDCHF / 2 | 2025-08-30 to 2026-02-26 | 233 / -981.06 | 66 / -267.12 | 13 / -113.55 | 1 / -2.86 |
| USDCHF / 3 | 2026-02-26 to 2026-08-25 | 185 / -378.99 | 57 / -83.52 | 13 / -18.08 | 0 / +0.00 |

### Doubled costs

| Instrument / fold | Test window (end exclusive) | Baseline | Regime only | Scoring only | Full adaptive |
| --- | --- | ---: | ---: | ---: | ---: |
| EURUSD / 1 | 2025-03-03 to 2025-08-30 | 238 / -267.76 | 51 / -64.19 | 13 / -24.15 | 0 / +0.00 |
| EURUSD / 2 | 2025-08-30 to 2026-02-26 | 267 / -615.20 | 38 / -125.68 | 7 / -43.96 | 0 / +0.00 |
| GBPUSD / 1 | 2025-03-03 to 2025-08-30 | 244 / -519.99 | 53 / -129.64 | 19 / +12.70 | 0 / +0.00 |
| GBPUSD / 2 | 2025-08-30 to 2026-02-26 | 244 / -850.82 | 35 / -115.35 | 4 / -10.56 | 0 / +0.00 |
| USDCHF / 1 | 2025-03-03 to 2025-08-30 | 0 / +0.00 | 0 / +0.00 | 0 / +0.00 | 0 / +0.00 |
| USDCHF / 2 | 2025-08-30 to 2026-02-26 | 189 / -1222.95 | 49 / -234.10 | 8 / -63.80 | 0 / +0.00 |
| USDCHF / 3 | 2026-02-26 to 2026-08-25 | 184 / -911.04 | 56 / -400.74 | 11 / -74.17 | 0 / +0.00 |

The single full-adaptive position occurred in USDCHF fold 2 under base costs:
net -2.8648, mean R -1.4704, profit factor 0 and realized drawdown 2.8648.
The loss includes costs; initial-stop risk is not a guaranteed all-in loss bound.
Its sample cannot support a confidence interval or risk-adjusted edge claim.

GBPUSD scoring-only fold 1 was positive (+36.68 base / +12.70 stress), but its
base descriptive 95% block-bootstrap interval is [-43.64, +142.90]. The stress
sample has 19 positions, below the unchanged 20-position eligibility for that
interval. Fold 2 was negative in both cases. This is neither a confirmatory
result nor evidence for the full-adaptive arm. USDCHF stress fold 1 has zero
baseline positions too: stressed costs reapply existing spread/execution gates;
they are not merely subtracted from the base ledger.

Full metrics, per-window profit factors, mean R, realized drawdowns, costs,
calendar daily statistics and session/regime breakdowns are retained in
`reports/qait/broad_20261112/summary.json`. Undefined or ineligible statistics
remain null, including marked-equity drawdown and sparse-sample intervals.

## Participation diagnostics

These are nonexclusive rejection counts from base full-adaptive **test**
observations, not classifications proving that each rejection was necessary.
No gate was changed in response.

| Instrument | Candidate observations | Below score threshold | Uncertain regime | Timeframe conflict | M5 gapped/unordered | High volatility |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| EURUSD | 670 | 646 | 481 | 343 | 464 | 82 |
| GBPUSD | 629 | 601 | 432 | 333 | 488 | 93 |
| USDCHF | 1021 | 973 | 572 | 553 | 122 | 197 |

Data availability contributes materially, particularly for derived complete M5
buckets in EURUSD and GBPUSD. These counters do not establish that the fixed
thresholds are optimal or that every historical rejection is correct. Raw
feature/source provenance and all reasons are retained for review. No filling,
feature substitution, confidence rescaling or risk bypass was introduced.

## Verification and retained evidence

- All 7,519 saved trade rows across 270 completed ledgers passed independent
  fill-price P&L, gross/cost reconciliation, ending-equity and broker-volume audits.
- All 54 completed phase/cost pairs have identical full/shadow ledgers. Six
  unavailable phase/cost slots remain explicit; no arm is silently omitted.
- Initial stop risk was independently reconstructed from saved prices, volumes,
  tick metadata and pre-entry equity. All rows stayed within the configured
  risk and portfolio budgets; maximum utilization was 25.6125% of the tighter
  authorized budget. Configured volume bounds and initial protection direction
  passed. Saved final stops were never wider than initial stops. This does not
  reconstruct every intratrade stop update or bound gap/slippage losses.
- Frozen protocols, effective profiles, raw history hashes, unchanged production
  configuration, exact preceding-study source digest, adaptive thresholds and
  base/stress costs passed the contract audit. No strategy/risk/execution source
  changed. The full suite passed: **436 passed, 1 pre-existing expected failure**;
  dashboard syntax and DOM contracts also passed.
- Full reports are retained as lossless gzip archives with compressed and raw
  SHA-256 digests and exact-byte round-trip verification. Nothing is sampled
  out. See the evidence README and artifact manifest for restoration commands.
  Frozen tools retain identical bytes through a Windows checkout.

The pre-result pip-size tripwire correction is recorded separately in the
original harness amendment. Later redundant queued dispatcher submissions were
rejected by the exclusive output-directory guard before replay. Completed
reports were never replaced or selected from alternative runs. All eight
registered instrument/cost outputs were produced with the original protocols.

## Interpretation and limits

The fixed full-adaptive implementation remains effectively inactive: one test
position across 2,320 base-case candidate observations in the three eligible
instruments. Candidate observations are not independent trade samples. Unavailable
NZDUSD tests provide no evidence for or against performance. Any comparison must
retain zero activity as zero activity; holding cash while an active baseline loses does not establish a
tradeable adaptive edge. Scoring-only results do not establish full-adaptive
performance. Sparse samples, multiple descriptive comparisons, shared market
exposures and reused development histories prevent a confirmatory claim.

Realized drawdown is available; marked-equity drawdown is not. There is no tick
path reconstruction, financing, dynamic historical valuation or reconstructed
historical broker margin/stop constraints. All money uses each saved snapshot's
valuation. No synchronized multi-symbol exposure or continuous-account result
is reported. Full adaptive intersects baseline candidates rather than generating
an independent delayed entry stream. ML is unavailable and remains observational.

All adaptive activation flags remain false in saved configurations; the existing
offline runner alone uses an in-memory research override. Broker access is
blocked in the worker. No live trades were placed. No strategy, risk or execution
source, production profile or numeric signal threshold was changed for this study.

These results close the broader fixed-parameter comparison. A genuine prospective
holdout and synchronized account validation remain open work. Any calibration
would be a separately preregistered strategy hypothesis; this study does not
authorize changing gates or activation.
