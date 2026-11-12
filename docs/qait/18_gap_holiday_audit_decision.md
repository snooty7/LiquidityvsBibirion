# Gap and holiday audit decision

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
