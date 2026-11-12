# Volatility and timeframe gate audit: results

Date: 2026-11-12. **No false historical high-volatility or timeframe-conflict rejection was found in the frozen windows. Controlled input-window and ATR initialization bugs are fixed. Numerical thresholds and risk controls are unchanged; everything remains disabled and no live trades were placed.**

## What changed

- `detect_regime` and `directions` now enforce the declared fixed feature window even when called directly with additional older history. Older prefixes could previously change ATR initialization/rank or reverse EMA direction. The replay already supplied fixed windows, but the public helpers did not enforce that contract.
- Adaptive regime ATR now initializes from 14 actual true ranges, each with an available previous close, before applying the same period's Wilder recurrence. The previous helper used an unknown first transition's high-low range in the seed. In a controlled constant-TR market this caused upward initialization drift and a false extreme rank. The repair retains the 100-bar window, 14-period setting, 85-value prior reference set, .98 cutoff and existing 1e-6 tie tolerance. Legacy strategy indicator helpers remain unchanged.
- Neutral/unavailable timeframe context still blocks but is labeled separately from genuine opposition. Missing/duplicate timeframe identities also block. The configured unanimous H1/H4 requirement is unchanged; no unknown value is silently treated as agreement.
- Malformed used regime prices or nonfinite indicators fail closed with finite unavailable outputs. Unused older prefixes do not influence the selected window.

The [decision record](11_volatility_timeframe_audit.md) documents source findings and controlled tests before replay. No ATR period, percentile limit, realized-volatility limit, EMA period, required timeframe, scoring weight, RR, risk budget or execution assumption was selected from historical returns.

## Independent audit

The stdlib-only `tools/audit_qait_gates.py` recomputes fully seeded ATR/rank, unannualized standard deviation of the last 20 log returns, and EMA20 directions directly from saved native closed candles, without importing strategy implementation. Its traces expose native candle boundaries, first/last input times, ATR sample count, cause flags, EMA values and direction.

For each cost scenario's 63 full-adaptive observations:

| Check | Result |
|---|---:|
| ATR-extreme rejections | 22, all verified |
| Realized-volatility-extreme rejections | 0 |
| Genuine opposite-timeframe rejections | 37, all verified |
| Unavailable entry feature window | 1, blocked |
| Distinct native H1/H4 closes checked against M1 | 104, all match |

The 104 native-close checks cover 52 unique candidate decision times across H1/H4; the same inputs are checked in each cost scenario, not counted as independent new evidence. All higher-timeframe bars satisfy `open_time + duration <= decision_time`. Controlled tests separately exercise neutral/missing context and the exact bar-close boundary.

The two score-eligible training cases remain correctly rejected:

| Case | Audited inputs | Unchanged outcome |
|---|---|---|
| SELL at epoch 1790878200 | M5 ATR .0006785749453; percentile 1.0 versus .98; realized volatility .00037707198 versus .01; H1/H4 both SELL | High volatility blocks |
| SELL at epoch 1791275400 | H1 BUY, H4 SELL; M5 regime RANGING | H1 opposition blocks |

The volatility gate is intentionally relative: low absolute return volatility does not override a genuine extreme ATR rank. The timeframe gate intentionally adds H1/H4 context; passing the baseline's M15 bias does not satisfy it. Treating either of these as permission to bypass a gate would change the policy rather than fix an implementation defect.

Across all five arms, every historical regime class and timeframe direction is unchanged. ATR numeric values are corrected, but no historical gate classification or trading ledger changes in this dataset. This does not establish absence of defects outside the tested windows.

## Frozen comparison and artifacts

Inputs, numeric adaptive settings, effective original configuration hash, data hash, costs, equity and chronological folds match the preceding lifecycle protocols. Source/code hashes change for the registered repair; old artifacts are immutable.

- [Base protocol](../../reports/qait/gates_92001/protocol.json) and [report](../../reports/qait/gates_92001/base/report.json).
- [Doubled-cost protocol](../../reports/qait/gates_92001/stress_protocol.json) and [report](../../reports/qait/gates_92001/doubled_costs/report.json).
- [Independent gate audit and numerical traces](../../reports/qait/gates_92001/gate_audit.json), [arithmetic audit](../../reports/qait/gates_92001/audit.json), and [repeat evidence](../../reports/qait/gates_92001/reproducibility.json).

All **60 phase/arm trade ledgers**—30 in each cost scenario—are identical to the lifecycle study. Scoring-only retains two fold-1 training positions (+14.91 base costs, +12.43 doubled costs), no other training/validation positions and no test positions. Full adaptive/ML shadow remains at zero positions. No OOS or risk-adjusted improvement is claimed.

## Verification and boundaries

- **401 Python tests passed; one pre-existing expected failure.** Dashboard JavaScript syntax and DOM checks pass.
- New controlled tests reproduce constant-TR seed drift and prefix-induced EMA reversal, preserve real ATR/realized-volatility rejection and inclusive boundaries, prove fixed-window invariance, and distinguish unavailable context while keeping it blocked.
- All 18 valid BUY/SELL/UNCERTAIN combinations for a BUY/SELL candidate preserve the previous unanimous-alignment allow/block decision. Missing/duplicate context rejects explicitly.
- Independent money/cost/equity/volume audit passes **96 trade rows across 60 ledgers**. Full-adaptive/shadow identity remains intact.
- Repeated base replay is byte-identical to the published report.
- `src/risk`, MT5 execution, live orchestration, service/numeric adaptive configuration, production profiles and legacy indicator helpers have no changes from `8ec8dab`.

Replay requires saved history and a fresh output directory:

```powershell
.venv/Scripts/python.exe -m src.tools.research_adaptive run --protocol reports/qait/gates_92001/protocol.json --output NEW_OUTPUT_DIRECTORY
```

The [research-only deployment boundaries](06_deployment_guide.md) remain. These are short development windows with prior research exposure, not an untouched holdout or approval for activation.
