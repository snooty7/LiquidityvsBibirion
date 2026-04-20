# Live Profile: 1000 EUR / 92001

Това е изолиран live профил само за:
- `EURUSD`
- `M5`
- `magic = 92001`

Логиката на стратегията е оставена същата като production winner-а.
Променени са само live-risk параметрите за сметка около `1000 EUR`.

## Профил
- `risk_pct = 0.25`
- `max_lot = 0.10`
- `daily_loss_limit_usd = 30`
- `max_loss_per_trade_usd = 12`
- `max_open_positions_total = 1`
- `max_total_open_risk_pct = 0.25`

## Отделни live файлове
- DB: `live/mt5_1000eur_92001/bot_state.sqlite3`
- Log: `live/mt5_1000eur_92001/bot_events_live.csv`
- Archives: `live/mt5_1000eur_92001/state_archives/`

Това държи live run-а отделен от demo/research state.

## Push notifications
По подразбиране push е изключен в този профил.

Ако искаш да го включиш, попълни в `settings.json`:
- `push_notifications_enabled`
- `push_notification_url`
- `push_notification_token`

## Старт
От repo root:

```powershell
powershell -ExecutionPolicy Bypass -File live\mt5_1000eur_92001\run_live_92001.ps1
```

## Важно
- Не пускай едновременно demo config и този live profile срещу една и съща MT5 сметка.
- Този профил е направен за един активен branch. Не добавяй research branch-ове към него.
