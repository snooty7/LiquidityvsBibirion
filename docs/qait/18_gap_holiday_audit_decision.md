# Gap and holiday audit

## Frozen policy and audit result

This audit investigates false rejections in the broader frozen comparison without
changing signal thresholds, risk settings, dates, costs or instruments. It does
not introduce a broker session or holiday calendar inferred from test outcomes.

The explicit adaptive option allows missing UTC Saturday/Sunday bar opens only,
with bar-open separation at most three days. It is disabled by default and true
only in the existing frozen research override. Weekday gaps remain unavailable.
Freshness uses the existing wall-clock limit of two timeframe durations after
the most recent closed bar. Coverage independently rejects calendar bar-open
separations over three days. These are the documented contracts, not business-day
or exchange-calendar measures. No tolerance is increased or reinterpreted here.

An independent raw-timestamp oracle checked **38,116 saved observations** across
all phases, arms and cost cases: 12,479 EURUSD, 11,718 GBPUSD, 11,657 USDCHF and
2,262 NZDUSD. It reconstructs fixed feature windows, longer anchor-proof windows,
closed-bar cutoffs, warm-up counts and wall-clock age. UTC weekdays use integer
epoch-day arithmetic rather than the production datetime calculation. Derived
M5 timestamps independently require every constituent M1 minute. All recorded
context gap, insufficient-history and staleness reason sets match the oracle.
No implementation discrepancy or safely demonstrated false rejection was found.
The full audit, gap categories and timestamp examples are retained in
`reports/qait/gaps_20261112/gap_audit.json`.

## Easter-period and rollover observations

EURUSD, GBPUSD and NZDUSD have no saved M1 or native higher-timeframe bars on
2026-04-03. USDCHF has 1,430 saved M1 bars, 24 H1 bars and six H4 bars that day.
Consequently a calendar-wide Good Friday exception applied to all instruments
would contradict the available data. Absence of bars alone cannot distinguish
an instrument-specific closure from a broker/export outage.

The EURUSD/GBPUSD/NZDUSD separation from 2026-04-02 23:59 UTC to 2026-04-06
00:05 UTC is 72 hours, six minutes. It includes missing Friday and Monday bar
opens as well as the UTC weekend. The existing coverage rejection therefore
matches the frozen calendar contract. Calling the entire interval a verified
closure would require broker/instrument session evidence absent from these
exports. A generic holiday date or a recurring rollover pattern is insufficient.

Incomplete M1-derived buckets are discarded under the existing resampling
contract. A native H1/H4 aggregate does not reconstruct missing M1 path, spread,
confirmation or stop-fill data. No OHLC is filled, forward-filled, borrowed from
another instrument/timeframe, or assembled from a different history export.

## Decision before rerunning

**No signal, gap, calendar, staleness or risk code change is justified by the
available evidence.** Adding holiday exceptions, increasing the gap limit,
pausing freshness clocks, allowing partially observed candles, or changing test
windows would change the frozen experiment. They are not treated as bug fixes.

The original eight broader protocols, source digest, history/configuration
hashes, arms, costs, chronological windows and resets remain immutable. A fresh
repeat registration freezes all jobs before replay. Each repeat runs offline
with all broker operations forbidden except the pure pip-size helper. The
acceptance check is exact equality of every complete report's bytes, including
all observations, trade ledgers, metrics and unavailable phases. The original
lossless archives remain the complete evidence if the repeat is identical;
redundant copies of identical large reports are not committed.

The oracle establishes consistency with the registered policy, not that the
policy is optimal or that every absent minute was tradable. A verified broker
session/holiday calendar would require a separate explicitly registered data
contract and tests for asset scope, timezone/DST, early closes, reopenings and
unexpected outages. No such calendar is guessed or activated in this task.

Adaptive features, ML, leverage and hedging remain disabled. Production profiles,
existing strategy/risk/execution source and all risk controls remain unchanged.
No live trades are placed.

## Completed frozen repeats

Completed on 2026-11-12. **All eight complete reports reproduced byte for byte**
under the original protocols and exact source implementation. This includes
every trade, feature, rejection, metric, unavailable phase and shadow record.
There are 270 completed arm ledgers, 54 full/shadow phase/cost pairs and six
explicit unavailable phase/cost slots, exactly as before. The original 618.89 MiB
of raw reports remain fully retained in their existing lossless archives; the
repeat verification records all raw hashes, sizes and archive pointers.

Fresh independent monetary audits on the repeated outputs passed for **7,519
trade rows across 270 ledgers**, including fill-price P&L, costs, equity, broker
volume and shadow identity. The closure audit also verified unchanged protocol,
history, configuration and implementation hashes, original archive hashes,
auditor source provenance, disabled adaptive/ML/leverage/hedging defaults and
unchanged protected strategy/risk/execution/production files.

The full Python suite passed: **436 passed, one pre-existing expected failure**.
Dashboard syntax and DOM checks also passed. No new dependency was installed.

The only correction made was to the new report-verification helper's Windows
path-separator lookup. Its original version is retained at `b9621f9`; the
explicit verifier/dispatch amendment records the corrected hash. All workers
already started with the original registered tool. This correction changed no
replay, calendar rule, risk setting, protocol or result. Original registration
and raw timestamp audit bytes were retained.

The empirical result is unchanged: full adaptive has one base-case test
position, net -2.8648, and none under doubled costs. EURUSD/GBPUSD fold-3 and
NZDUSD's sole test window remain unavailable under the fixed gap rule. Improved
tradeable performance remains unproven. No verified broker/instrument historical
session calendar was available to justify holiday or rollover exemptions.

See `reports/qait/gaps_20261112/repeat_verification.json`, `completion_audit.json`,
the per-instrument `money_audit.json` files and the evidence README. The previous
[broader validation results](17_broader_validation_results.md) and all original
frozen artifacts remain unchanged. No live trades were placed.
