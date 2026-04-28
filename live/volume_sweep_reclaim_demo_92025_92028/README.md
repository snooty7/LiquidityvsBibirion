# Volume Sweep Reclaim Demo 92025-92028

Research-only demo profile. It is not included in the active live `config/settings.json`.

Branches:
- `92025` EURUSD M5 Volume Sweep Reclaim
- `92026` GBPUSD M5 Volume Sweep Reclaim
- `92027` USDCHF M5 Volume Sweep Reclaim
- `92028` NZDUSD M5 Volume Sweep Reclaim

Core logic:
- M5 candle sweeps the previous 20-bar high/low and closes back inside the level.
- Tick volume must be at least `1.8x` the prior 20-bar volume SMA.
- Reclaim candle body ratio must be at least `0.50`.
- Trade is taken against EMA50 location: buy below EMA50 after sellside reclaim, sell above EMA50 after buyside reclaim.
- Custom SL is behind the sweep wick by `0.3` pip.
- TP target is `8` pips from entry.
- Max hold is `12` M5 bars.
- Session is NY only: `12:00-18:00 UTC`.

Start demo dry-run:

```powershell
python -m src.engine.orchestrator --config live/volume_sweep_reclaim_demo_92025_92028/settings.json
```
