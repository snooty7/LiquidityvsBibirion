# Broader fixed-parameter validation

Registered before replay on 2026-11-12. Machine-readable registration and eight
frozen protocols are in `reports/qait/broad_20261112/`.

## Question and fixed design

Does the audited adaptive implementation participate and improve the descriptive
risk/return comparison over substantially more saved history and FX instruments?
No signal thresholds, normalization, risk rules, or costs are selected from these
results. This is development validation, not confirmation of an independent edge.

The reference is the existing EURUSD 92001 liquidity strategy: M5 sweep, M1
confirmation. Its exact effective symbol settings are copied to EURUSD, GBPUSD,
USDCHF and NZDUSD, changing only the symbol. These matched research profiles do
not replace deployed profiles. All risk fields remain identical. Research copies
set dry-run true, disable notifications and remove notification credentials;
production configuration is untouched. Adaptive activation is confined to the
existing offline runner's in-memory research override.

Each instrument runs baseline, regime-only, scoring-only, full adaptive and full
adaptive plus unavailable ML shadow. No model is fitted. Each phase/fold starts
with EUR 10,000 independently; these are not synchronized portfolio accounts.
No aggregate account return or diversification claim is permissible.

Historical spreads, 3.5 money units per lot per side commission, and 0.2 pip
adverse slippage form the base case. The preregistered stress doubles observed
and fallback spreads, commission to 7, and slippage to 0.4. Both cases run for
every instrument, regardless of outcomes.

## Windows and coverage

Every fold uses 90 calendar days training, one day embargo, 30 days validation,
one day embargo and 180 days testing. Parameters remain fixed in every phase.
Test windows do not overlap. Existing coverage, freshness, gap and warm-up guards
remain authoritative; no synthetic bars or relaxed holiday exceptions are added.
Unavailable phases must be reported, not replaced by more favorable dates.

| Instruments | Requested range, end exclusive | Complete test windows |
| --- | --- | --- |
| EURUSD, GBPUSD, USDCHF | 2024-11-01 to 2026-11-11 | 2025-03-03 to 2025-08-30; 2025-08-30 to 2026-02-26; 2026-02-26 to 2026-08-25 |
| NZDUSD | 2025-08-15 to 2026-11-11 | 2025-12-15 to 2026-06-13 |

Incomplete terminal folds are discarded by the existing fold generator. They
are not represented as evaluated data. Extended exports contain history from
2024-10-01, providing prior warm-up for November starts. NZDUSD has a shorter
export beginning July 2025. File and effective configuration hashes, source
digest, costs, adaptive settings, exact windows and arm definitions are frozen
in every protocol. The registry hashes all protocols before workers start.

## Data provenance and untouched holdout

No verifiably untouched saved holdout is available. Earlier work already used
these exports: `reports/fx_htf/plan.json` includes extended EURUSD, GBPUSD and
USDCHF histories; `reports/walk_forward/report.json` includes the shorter FX
exports, including NZDUSD. Prior QAIT audits also reused October 2026 EURUSD.
Consequently all windows are labelled previously researched development data.
Chronological testing prevents within-replay lookahead but does not undo prior
research exposure. There is no claim that these are untouched out-of-sample data.

New observations after the saved exports' 2026-11-11 exclusive boundary would
need a separately frozen prospective protocol and verified provenance. This run
does not download data, connect to MT5, or invent a fresh holdout.

## Endpoints and interpretation

Report test participation, net money after costs, profit factor, mean R,
maximum realized drawdown, session/regime breakdowns and exact shadow-ledger
identity. Keep instrument and cost cases separate. Training/validation ledgers
are descriptive only; overlapping training periods are not independent samples.
Retain zero-trade arms and unavailable phases. Sparse samples and unavailable
confidence intervals cannot substantiate an improvement claim. Existing metric
definitions and bootstrap seed/eligibility remain fixed.

Independent ledger arithmetic audits must reconcile fill-price money, gross
and costs, ending equity, broker volume steps and adaptive/shadow identity for
both cases. Run the existing test suite and verify protected source and live
configuration have not changed. Tick paths, financing, dynamic historical
valuation, historical broker constraints, marked-equity drawdown and synchronized
portfolio risk remain limitations of this harness.

## Harness amendment before any results

The first eight attempts failed before any arm completed because the new
broker-access tripwire also blocked the adapter's pure static `pip_size`
calculation. The amendment exempts only that helper; broker-reading and trading
methods still raise immediately. No results existed or were inspected. Original
registration and all protocol bytes were retained; the amendment records the
corrected orchestration hash. Strategy source, thresholds, risk settings, inputs,
costs and windows are unchanged. Empty failed directories were archived outside
the evidence tree. See `harness_amendment.json`.

Nothing in this study authorizes enabling an adaptive mode or placing a live
trade. Deployment requires a separate decision supported by stronger evidence.
