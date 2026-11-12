# Gap/holiday audit and unchanged frozen repeats

`gap_audit.json` compares every recorded context gap, warm-up and staleness
decision against an independent timestamp oracle: 38,116 observations, no
discrepancies. The exact production signal implementation is unchanged. No
holiday/session calendar is inferred from missing quotes or another instrument.
See `docs/qait/18_gap_holiday_audit_decision.md` for scope and limitations.

`holiday_scope.json` records the differing instrument-specific saved M1 and
native higher-timeframe observations on 2026-04-03. It is not a calendar or a
declaration that an absent quote was tradable. `repeat_registration.json`
freezes the original eight broader protocols before all repeat replays.

Commands from the repository root (original saved histories required):

```powershell
.venv/Scripts/python.exe -m tools.audit_qait_gaps run --symbol EURUSD --scenario base
.venv/Scripts/python.exe -m tools.audit_qait_gaps verify
```

Repeat the run command for each registered instrument/cost case in fresh output
directories. Outputs cannot overwrite existing runs. Worker broker operations
raise immediately; only the pure pip-size helper is exempt. Configuration,
source, effective local overrides, history and protocol hashes are verified by
the frozen runner. No live trade or adaptive activation is authorized.

The original timestamp audit/orchestrator version is retained in commit
`b9621f9`. `verification_amendment.json` records a subsequent Windows path
separator correction in the report lookup and its dispatch hash. All eight
workers had already started using the original registered version. No replay,
source, protocol, data or configuration changed; the original registration and
audit bytes remain immutable.

`repeat_verification.json` is written only when all eight complete reports match
the original raw report hashes and sizes exactly. Every trade, feature,
rejection, metric, unavailable phase and shadow observation is included in that
comparison. Identical originals are retained in the existing lossless archives
under `reports/qait/broad_20261112/`; no duplicate large archives are necessary.
Use that study's artifact manifest and unpack tool to inspect them.

The repeat JSON working files are ignored by Git. The original broader money,
risk and frozen-input audits apply to byte-identical repeats. If any report
differs, verification fails and this task cannot declare reproduction passed.
The original development-data and isolated-account limitations remain unchanged;
this audit creates no untouched holdout or improved-performance claim.
