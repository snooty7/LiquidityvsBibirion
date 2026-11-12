# QAIT public technical research

Research date: 2026-11-12 (Europe/Sofia). Scope is public unauthenticated material only. This assessment does not establish access to QAIT trading infrastructure, proprietary algorithms, accounts or private APIs.

## Evidence and access limitations

| ID | Public source / method | Observed result |
|---|---|---|
| E1 | [qait.app](https://qait.app/), browser-text retrieval and ordinary Python HTTPS GET | Text retrieval inaccessible; Python request returned HTTP 403. No evasion attempted |
| E2 | [www.qait.app](https://www.qait.app/), indexed search result and direct retrieval | Indexed landing description and dashboard access link; direct text retrieval returned 502, Python DNS resolution failed |
| E3 | [campaign](https://promo.qait.app/qait-campaign), search-index extraction | Substantial indexed marketing text, feature headings, an illustrative client snippet, dashboard/demo labels and performance tables |
| E4 | Same campaign, direct text retrieval and ordinary Python HTTPS GET | Initial text retrieval exposed no readable lines; subsequent retrieval returned 502; Python DNS resolution failed |

The search service described E2 as crawled five months ago and E3 as crawled three months ago; another campaign response reported seven months. These are index metadata, not publication dates or proof of current deployed content. A 403 is an access restriction, whereas DNS/502 failures may be environmental or transient; neither proves the service is absent. Indexed excerpts cannot establish that an interactive dashboard or backend works today.

HTML/JavaScript bundle inventory, source maps, browser interactions and network request/response traces could not be obtained from successful direct page loads. No bundle hashes, authenticated endpoints or API schemas were observed. No endpoint guessing, access-control bypass, credentials, purchases, account registration, rate-limit circumvention or trade submission was used. No raw-page capture is supplied because no usable direct response was obtained. Revisit through an ordinary accessible public page if availability changes.

## Classification rules

**VERIFIED** means the stated observation is directly evidenced. An observable advertisement verifies that a claim is made, not that its trading mechanism or results work. **INFERRED** means a plausible technical interpretation without confirmation. **UNKNOWN** means insufficient evidence. The two status columns below deliberately separate public presentation from implemented behavior.

| Requested feature | Public presentation | Implemented behavior | Evidence and independent interpretation |
|---|---|---|---|
| Multi-timeframe | VERIFIED claim | UNKNOWN | E3 advertises six timeframes; exact periods, synchronization and candle-finality rules unavailable |
| Market regimes | VERIFIED broad adaptation claim | UNKNOWN | E3 describes adaptation to conditions; explicit regime taxonomy and transition rules absent |
| AI/ML signals | VERIFIED claim | UNKNOWN | E2/E3 describe neural/quantum-inspired signals; training data, models, calibration and reproducibility unavailable |
| Dynamic leverage | VERIFIED claim | UNKNOWN | E3 describes adaptive sizing/leverage; actual constraints, margin behavior and account safeguards unavailable |
| Adaptive SL/TP | VERIFIED claim | UNKNOWN | E3 describes changing protection; no executable tightening, invalidation or target rules observed |
| Order flow | VERIFIED claim | UNKNOWN | E3 mentions exchange books; feeds, timestamps, venues and aggregation unavailable |
| Correlation/hedging | VERIFIED claim | UNKNOWN | E3 describes cross-asset hedging and shows example pairs; estimation and execution details unavailable |
| Strategy selection | VERIFIED claim | UNKNOWN | E3 advertises a strategy matrix; eligibility, selection objective and switching costs unavailable |
| Risk management | VERIFIED claim | UNKNOWN | E2/E3 advertise risk controls; enforceable limits, kill-switch behavior and independent audit unavailable |

**INFERRED:** a system implementing such capabilities would need synchronized observations, position state and a decision/risk layer. That is an engineering interpretation, not a discovery about QAIT architecture. None of the nine underlying trading capabilities is verified by a witnessed trade, code path, reproducible dataset or API response in this investigation.

## API, demo and performance assessment

E3 contains illustrative JavaScript client subscription code. This verifies the presence of an example in indexed copy only. It does not establish a published package, functioning API, authentication contract, SLA or compatibility with MT5. Do not install an advertised client or use it as an implementation dependency without separate provenance and interface verification.

Demo/chart labels and speed comparisons are observable marketing presentation, not measured execution traces. No claims about live prices, real fills, exchange routing, quantum hardware, C++ latency, CUDA acceleration or self-learning behavior can be validated here.

The indexed campaign also presents performance and leverage tables. No underlying trade ledger, data provenance, cost model, independent audit, fold boundaries, uncertainty estimates or reproducible benchmark was obtained. These tables cannot support a claim of improved risk-adjusted returns. Their values are intentionally not adopted as design targets or reported as measured results for this bot.

## Comparison against this repository

| Area | Repository evidence | Independent design consequence |
|---|---|---|
| Context | Configurable entry/bias/setup timeframes, EMA and ATR/ADX helpers | Extend closed-time alignment and D1 history support rather than inventing a new feed |
| Signals | Price-based sweep, displacement/structure, order-block detectors; isolated FVG research | Reuse audited definitions and promote FVG carefully into shared strategy code |
| Adaptation | Deterministic branches, static settings, offline walk-forward selection | Add explainable regime eligibility and scores; no need to copy unobservable ML claims |
| Risk | Risk-based lots, broker step/minimum rejection, loss/portfolio guards | Preserve guard semantics and add explicit preflight/concentration checks |
| Exits | Fixed/model protection, R trailing, time/adverse exits | Share causal exit policies, tighten stops only, test independently |
| Flow data | OHLC and tick-volume ratios | Tick volume is a proxy, not exchange-book or aggressor-flow confirmation |
| Correlation | No general correlation gate found | Add conservative exposure controls; hedging and leverage remain disabled |
| Validation | Offline bid history, modeled costs, chronological fold infrastructure | Extend objective comparisons and uncertainty reporting instead of trusting public tables |
| Display | Existing local JSON snapshot and static export | Add optional observations to current dashboard |

Decision: proceed only with independently specified, deterministic, offline-testable ideas. QAIT is inspiration for feature categories, not a source of verified signal definitions or performance assumptions. The [implementation proposal](03_adaptive_architecture.md) is subject to the user's explicit approval; no trading engine or production integration is introduced by this research.
