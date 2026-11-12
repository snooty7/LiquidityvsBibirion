# Signal/timeframe alignment investigation

Decision record, 2026-11-12, before corrected historical replay. No target trade count, profitability target or threshold search is authorized by this change.

The frozen 92001 branch uses M5 sweeps, pivot length 5, a 500-bar configured history (the existing replay supplies at least 600 bars), and `sweep_displacement_mss` confirmation on M1 with four structure bars. The adaptive adapter instead supplied only M5/H1/H4, rediscovered a sweep with pivot length 3 over 100 bars, and required a separate M5 break. It could score a different sweep from the pending setup, omit the actual M1 confirmation, and divide break strength by the M5 ATR. This is a signal identity/timeframe defect, independent of profit outcomes.

Correction specified before rerunning:

- Preserve the original pending side, level and candle time as a typed candidate anchor, including source branch and configured confirmation settings.
- Verify the exact sweep against a previously confirmed pivot using the baseline pivot/history settings. Reject unavailable, already-consumed, invalid, future or stale anchors; never substitute another sweep.
- Load only completed candles from the actual confirmation timeframe. Reuse the existing displacement/recent-extrema confirmation definition with its unchanged branch thresholds, require confirmation after the sweep is knowable, and retain the adaptive ATR displacement floor. Label the result as a confirmation break rather than pretending it is a second M5 swing break.
- Normalize sweep strength in its own timeframe and confirmation break strength in its own timeframe. Keep the adaptive regime/zone windows unchanged despite the longer provenance history.
- Retain all existing risk gates, .65 score threshold, .30/.25/.20/.15/.10 weights, missing-order-flow policy, H1/H4 alignment, regime settings, stop buffer, RR, costs and test windows. No independent delayed-entry stream or relaxed no-trade rule is added.
- Test the contract on controlled candles before replay: genuine M5 sweep plus M1 confirmation, no M5 break, wrong anchor, consumed liquidity, pre-close/future confirmation, stale data, duplicate setup, unavailable history and unchanged risk rejection. Preserve baseline and ML-shadow ledger invariants.

Old protocols/results remain immutable. Corrected base/stress protocols use a separate directory and the same numerical settings, data and windows. Remaining no-trades must be reported as such; a successful repair does not require historical trades or establish profitability.

The first diagnostic correction (`reports/qait/alignment_92001`, code `1af628e`) exposed a provenance-window defect: applying the 100-bar feature gap policy to the entire 600-bar source history erased valid current features because of unrelated older holes. The final contract retains the existing feature-window checks, validates all provenance OHLC/order, and separately requires continuity in each actually used pivot-to-sweep and sweep/confirmation ATR interval. A synthetic test proves an irrelevant older hole is harmless and a hole in a required interval still blocks.

Source review also confirms that the existing `extract_pivot_levels` combines highs and lows into an untyped map. Exact-source verification must search both, preserve the original level kind explicitly, and retain the one-shot consumption check. It must not invent a different side-specific map and label a real source pivot missing. A controlled reclaimed-high BUY fixture verifies this contract. These are semantic/data-dependency repairs; numerical thresholds and risk controls remain unchanged. Final evidence is registered separately under `reports/qait/aligned_92001`.
