# Baseline level lifecycle audit: decision before replay

Date: 2026-11-12. This audit corrects source-signal compatibility; it does not choose thresholds or target historical trades/profits.

`extract_pivot_levels` in `src/strategy/liquidity.py` rebuilds both high/low pivots from the supplied rolling rates, sorts them newest first, and retains `max_levels` entries. It has no consumed flag or wick-driven deletion. `detect_sweep_signal` scans that ordered map for the first buffered close-back sweep. The replay supplies at least `max(cfg.bars, 600)` closed signal bars plus its deterministic forming sentinel. Live orchestration has the same ranked-map detector, with its own configured rates window. Neither retires levels on a wick crossing.

Execution eligibility is separate: `semantic_setup_key` uses side/level, the replay/orchestrator suppress the previously seen key, pending setups have their own lifecycle and expiry, and recovery retains state. Those controls must not be removed or replaced by price-level deletion. A reusable source level does not imply permission to execute duplicate setups.

The anchored adaptive verifier's `any(low < level)` / `any(high > level)` test permanently rejected previously crossed levels. It even treated time spent below a source high (or above a source low) as consumption. That is not the source baseline's lifecycle. Its previous rejection counts were factual outputs of a mismatched rule, not evidence that the baseline levels were invalid.

Predeclared correction:

- Reconstruct the baseline's exact ordered map **as of the original sweep close**, with the existing pivot length, source lookback and `max_levels`. Reuse the actual extractor and detector. A level no longer in that source map, or a different higher-priority signal, must reject.
- Load enough past bars to reconstruct the original source window despite confirmation delay. Later map changes do not retroactively invalidate an already-created pending setup; source-map membership is checked at creation, not entry time.
- Retain confirmed-before-sweep provenance, required-history continuity, sweep geometry/significance, completed post-close confirmation and all other feature/guard contracts. Log source lifecycle and prior crossings explicitly; crossings are observations rather than a source retirement rule.
- Keep standalone adaptive structure/target rules distinct; this repair applies to baseline-anchored candidate eligibility. Do not silently change independent signal definitions or liquidity-target policy.
- Preserve baseline duplicate/pending/recovery behavior and the adaptive proposal-key guard. Risk sizing, monetary/exposure/daily/volume/spread checks, SL/TP/RR, numerical adaptive settings, ML shadow, disabled defaults and no-live-route boundaries stay unchanged.
- Prove the correction on controlled candles: prior crossings while a level remains active, actual rank/window retirement, exact detector priority, retention of pending identity after later map changes, BUY/SELL symmetry, source-window sufficiency, and duplicate/risk rejection. Then freeze new base/stress protocols with the same settings, costs, data and windows as `aligned_92001`.

New evidence is registered under `reports/qait/lifecycle_92001`; earlier evidence remains immutable. No active-trade count is required for acceptance, and no threshold search is permitted.
