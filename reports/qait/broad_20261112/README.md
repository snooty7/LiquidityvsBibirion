# Fixed broader adaptive comparison

See `docs/qait/16_broader_validation_preregistration.md` for the design and data
provenance, and `registration.json` for the complete job registry. All four FX
instruments and both cost cases were frozen before replay. These are reused
development exports, **not untouched holdouts**. Settings are fixed. Accounts
are isolated per phase/fold; do not interpret sums across instruments as a
portfolio return. No broker connection or live trade is permitted.

The eight original protocols and original registration are immutable. The
separate harness amendment records the correction to the broker-access tripwire
before any results existed; its only exemption is the pure pip-size helper.

## Running the frozen study

From the repository root with the existing Python environment and saved histories:

```powershell
.venv/Scripts/python.exe -m tools.validate_qait_broad run --symbol EURUSD --scenario base
```

Repeat for the registered symbols and `base` / `doubled_costs`, always using fresh
output directories. An existing run is never overwritten. Source, input data,
protocol, effective config and local overrides must match their frozen hashes.
The worker forbids broker access even if a replay regression tries to use it.
Adaptive enabling occurs only in the existing offline in-memory research policy.
All saved configuration activation flags remain false, and research configs
additionally have `dry_run: true` and notifications disabled.

After all jobs finish:

```powershell
.venv/Scripts/python.exe -m tools.validate_qait_broad summarize
.venv/Scripts/python.exe -m tools.audit_qait_broad
.venv/Scripts/python.exe -m tools.qait_broad_artifacts pack
```

`summary.json` retains each completed arm's full metric breakdowns, including
test windows, sample counts, costs, sessions/regimes, descriptive bootstrap
intervals and unavailable metrics. Instrument money audits independently check
fill-price P&L, cost reconciliation, ending equity, volume steps and shadow
ledger equality. `contract_audit.json` checks frozen inputs, protected settings,
disjoint tests, complete arm pairs and disabled defaults. Unavailable phases
remain explicitly recorded with the original coverage rejection reason.

## Full ledgers and exact-byte restoration

Large `report.json` working files are ignored by Git. Their complete bytes,
including every observation, trade and raw provenance field, are retained in
`report.json.gz`; no observations are sampled or omitted. The artifact manifest
records compressed and raw SHA-256 digests and sizes. Packing verifies every
archive by streaming its decompressed content through a second digest.

To restore the ignored JSON files after checkout:

```powershell
.venv/Scripts/python.exe -m tools.qait_broad_artifacts unpack
```

Existing identical files are verified; conflicting files are rejected. To replay
from scratch, use a separate checkout with the same histories at the registered
paths, remove only the locally reproduced output directories after preserving
the committed archives, and follow the frozen commands. Do not rerun registration
to substitute a different experiment. Archives permit independent inspection
without access to MT5 or the original data files; reproducing signals requires
the exact saved history exports, which are not committed.
