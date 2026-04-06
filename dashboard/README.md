# Dashboard

Локален уеб dashboard за визуализация на:

- `EURUSD` и другите конфигурирани symbols
- `M1`, `M5`, `H1`, `D1`
- candles от MT5
- signal stages от `bot_events.csv`

## Старт

От repo root:

```powershell
python dashboard/server.py
```

После отвори:

```text
http://127.0.0.1:8765
```

## Какво показва

- `M1` и `M5`:
  - timeframe-specific signal arrows
- `H1` и `D1`:
  - по-широк контекст на движението
  - всички recent signal arrows по timestamp

## Цветове

- cyan: `LIQUIDITY_ALERT`
- amber: `SETUP_PENDING`
- violet: `SETUP_WAIT`
- green: `SETUP_CONFIRMED`
- bright green: `TRADE_OK`
- yellow: close / exit
- red: reject / skip / unconfirmed close
