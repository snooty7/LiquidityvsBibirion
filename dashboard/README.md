# Dashboard

Локален уеб dashboard за визуализация на:

- `EURUSD` и другите конфигурирани symbols
- `M1`, `M5`, `M15`, `M30`
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

За Monday live профила:

```powershell
python dashboard/server.py --config live/combined_live_92001_92024/settings.json
```

## Online export

За static online build:

```powershell
python dashboard/export_static.py
```

или за конкретен live профил:

```powershell
python dashboard/export_static.py --config live/combined_live_92001_92024/settings.json
```

Това генерира:

```text
dashboard/online_build
```

с готов `index.html`, `styles.css`, `app.js` и `data/*.json`, които могат да се качат на уеб сървър.

## Какво показва

- `M1` и `M5`:
  - timeframe-specific signal arrows
- `M15` и `M30`:
  - по-широк intraday контекст на движението
  - всички recent signal markers по timestamp

## Цветове

- cyan: `LIQUIDITY_ALERT`
- amber: `SETUP_PENDING`
- violet: `SETUP_WAIT`
- green: `SETUP_CONFIRMED`
- bright green: `TRADE_OK`
- yellow: close / exit
- red: reject / skip / unconfirmed close
