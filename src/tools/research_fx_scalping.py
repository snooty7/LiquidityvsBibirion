"""Offline four-pair intraday scalping comparison, with financing violations audited."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from src.backtesting.costs import ExecutionCosts
from src.backtesting.history import load_history
from src.backtesting.scalping import ScalpPolicy
from src.backtesting.swaps import SwapModel, rates_from_snapshot, weekday_weights
from src.tools import research_swap_2k as replay
from src.tools.capture_fx_history_swaps import PAIRS
from src.tools.research_spread_resilience import configurations
from src.tools.research_usdchf_m30 import _forbid_broker
from src.tools.research_usdchf_three_ideas import register
from src.tools.walk_forward import RISK_KEYS, default_config_paths, discover_branches, history_coverage

_paths = {}
_loaded_symbol = None


def initialize(paths):
    """Keep a single symbol history per worker, prohibiting all broker operations."""
    global _paths, _loaded_symbol
    _forbid_broker()
    _paths, _loaded_symbol = paths, None


def history_for(symbol):
    """Load the requested pair rather than accidentally reusing USDCHF valuation."""
    global _loaded_symbol
    if symbol != _loaded_symbol:
        replay._history = load_history(Path(_paths[symbol]))[symbol]
        _loaded_symbol = symbol
    return replay._history


def worker(task):
    """Replay one pair and retain every late close, overnight exposure or financing fee."""
    symbol, replay_task = task
    history_for(symbol)
    result = replay.worker(replay_task)
    policy, swaps = replay_task[9], replay_task[7]
    alternate = replace(swaps, timezone="Etc/GMT-2")
    late = overnight = alt_events = 0
    durations = []
    for t in result["trades"]:
        entry, exit_time = (int(datetime.fromisoformat(t[k]).timestamp()) for k in ("entry_time_utc", "exit_time_utc"))
        if policy.blocks_entry(t["side"], entry):
            raise ValueError("Scalp position entered outside the registered session")
        durations.append((exit_time-entry)/60)
        late += exit_time > policy.deadline(entry)
        overnight += datetime.fromtimestamp(entry, timezone.utc).date() != datetime.fromtimestamp(exit_time, timezone.utc).date()
        alt_events += len(list(alternate.events(entry, exit_time-1, t["side"], t["volume"])))
    result.update(symbol=symbol, duration_minutes=policy.max_minutes,
        max_actual_holding_minutes=max(durations, default=0), late_exits=late, utc_overnight_trades=overnight,
        financing_events=sum(len(t["swap_events"]) for t in result["trades"]), alternate_clock_financing_events=alt_events)
    result["no_overnight_and_no_swap"] = overnight == 0 and result["financing_events"] == 0 and alt_events == 0
    return result


def nominate(records):
    """Use earlier stressed net only; no-trade or financed paths cannot qualify."""
    eligible = [n for n, v in records.items() if v["metrics"]["trades"] > 0 and v["no_overnight_and_no_swap"]]
    ranking = sorted(eligible, key=lambda n: (-records[n]["metrics"]["net_pnl"],
        records[n]["account"]["m1_close_drawdown"], n))
    return (ranking[0] if ranking else None), ranking


def run(root, snapshot_path, output, workers=6):
    """Freeze three durations, choose on earlier data, then disclose all later/full outcomes."""
    _forbid_broker()
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    source = next(b for b in discover_branches(default_config_paths()) if b.branch_id == "92024-USDCHF-M30-3c27c3d9")
    base = replace(configurations(source.symbol)["trail_later_1_5"], risk_pct=.75)
    app = replace(source.config, runtime=replace(source.config.runtime, max_total_open_risk_pct=.75))
    windows = {"earlier": ("2025-09-01T00:00:00+00:00", "2026-03-01T00:00:00+00:00"),
               "later": ("2026-03-02T00:00:00+00:00", "2026-11-11T00:00:00+00:00"),
               "full": ("2025-09-01T00:00:00+00:00", "2026-11-11T00:00:00+00:00")}
    names = {p: p+(".json" if p == "NZDUSD" else "_extended.json") for p in PAIRS}
    paths = {p: str((root/name).resolve()) for p, name in names.items()}
    metadata, swaps = {}, {}
    for pair in PAIRS:
        h = load_history(Path(paths[pair]))[pair]
        cfg = replace(base, symbol=pair)
        for start, end in windows.values():
            reason = history_coverage(h, cfg, datetime.fromisoformat(start), datetime.fromisoformat(end), max_gap_days=4)
            if reason:
                raise ValueError(f"{pair}: {reason}")
        buy, sell = rates_from_snapshot(snapshot["symbols"][pair], h.symbol_info, snapshot["account_currency"])
        swaps[pair] = SwapModel(buy, sell, "Etc/GMT-3", weekday_weights(snapshot["symbols"][pair], 3))
        metadata[pair] = {"input_file": names[pair], "history_digest": h.digest(), "symbol_info": asdict(h.symbol_info)}
        del h
    plan = {"capital_per_account": 10000, "risk_pct": .75, "base_settings": asdict(base),
        "runtime": {k: getattr(app.runtime, k) for k in RISK_KEYS}, "pairs": metadata, "snapshot": snapshot,
        "durations_minutes": [15, 30, 60], "windows": windows,
        "entry_and_exit": "Both BUY and SELL; retain M30/M1 entries and existing protections. Weekday entries05:00 inclusive to18:00 exclusive UTC, intersected with original sessions. Deadline is elapsed15/30/60 minutes or19:00 UTC same day, whichever comes first. Close at first available M1 opening quote, after any gap; never fabricate a fill. Existing SL/TP triggered at that opening quote has priority over the timed exit; daily protection retained.",
        "costs": asdict(ExecutionCosts()), "stress_costs": asdict(ExecutionCosts("historical", 2, 7, .4)),
        "swaps": {p: asdict(s) for p, s in swaps.items()}, "triple_day_override": 3,
        "clock_sensitivity": "Run GMT+3 swap accounting. Audit each complete entry/exit interval under GMT+2 as well. If no financing events occur under either schedule, the alternate clock is path-equivalent because the scalp policy is UTC based. If any events occur, disclose a failed no-swap constraint, never set financing to zero or delete the trade.",
        "selection": "For each pair choose duration by earlier stressed net only; require at least one trade and no overnight/financing events under either clock. Tie lower sampled drawdown then name. Lock before later/full results. Report all12 configurations, including negative and disqualified paths. Pair rankings after testing are descriptive, not independent validation.",
        "history_note": "NZDUSD original history starts2025-07-28. Read-only extension attempt returned a shorter recent M1 slice and is not used. All pairs therefore share2025-09-01 to2026-11-11 with warm-up verified individually; no unequal-period ranking.",
        "code_digest": hashlib.sha256(b"".join(p.read_bytes() for p in sorted(Path("src").rglob("*.py")))).hexdigest(),
        "limitations": ["Prices and some strategy dates were examined previously; this is exploratory comparison, not untouched holdout evidence.",
            "Three fixed durations and one fixed daylight window, no pair-specific tuning or combinations. Initial stop remains20 pips, initial target2R, trailing activation1.5R/gap1R; this tests timed scalp exits on the existing entry family, not a new M1-only signal.",
            "Spread cap0.9 pips remains identical across pairs; low/no participation is disclosed. Every pair/window starts independently atEUR10,000, not a concurrent portfolio.",
            "Historical observed spreads; assumedEUR3.50/lot/side commission and0.2-pip adverse market/stop slippage. Stress doubles these and negative swap debits, credits unchanged; observed spreads unchanged and missing-spread fallback doubles1 to2 pips.",
            "Current swap snapshot held constant over history with explicit Wednesday triple assumption after invalid weekday7 metadata. Financing is retained if a missed exit crosses rollover. Strict no-swap and no-overnight status is reported separately from profit.",
            "Constant per-pair EUR tick valuation from historical exports. Historical margin, latency, tick paths, liquidity availability and changing broker minimum-stop requirements are not reconstructed.",
            "Timed exits are research only; live execution/settings unchanged. No bot or orders." ]}
    output.mkdir(parents=True, exist_ok=True)
    register(plan, output)
    records = {}
    def save():
        (output/"results.partial.json").write_text(json.dumps({"plan": plan, "results": records}, indent=2, allow_nan=False), encoding="utf-8")
    def task(pair, minutes, phase, stress):
        cfg = replace(base, symbol=pair)
        pair_app = replace(app, symbols=(cfg,))
        swap = replace(swaps[pair], debit_multiplier=2 if stress else 1)
        start, end = (datetime.fromisoformat(v) for v in windows[phase])
        name = f"{pair}_{minutes}"+("_stress" if stress else "")
        return pair, (name, phase, pair_app, cfg, start, end,
            ExecutionCosts(**plan["stress_costs" if stress else "costs"]), swap, 10000, ScalpPolicy(minutes))
    def batch(jobs, pool):
        futures = [pool.submit(worker, t) for t in jobs]
        for index, future in enumerate(as_completed(futures), 1):
            result = future.result()
            records.setdefault(result["scenario"], {})[result["window"]] = result
            save()
            print(result["scenario"], result["window"], round(result["metrics"]["net_pnl"], 2),
                "no_swap", result["no_overnight_and_no_swap"], index, "/", len(jobs), flush=True)
    with ProcessPoolExecutor(max_workers=workers, initializer=initialize, initargs=(paths,)) as pool:
        batch([task(p, m, "earlier", True) for p in PAIRS for m in plan["durations_minutes"]], pool)
        locked = {}
        for pair in PAIRS:
            selected, ranking = nominate({str(m): records[f"{pair}_{m}_stress"]["earlier"] for m in plan["durations_minutes"]})
            locked[pair] = {"selected_minutes": int(selected) if selected else None, "earlier_ranking": ranking}
        (output/"locked_selection.json").write_text(json.dumps(locked, indent=2), encoding="utf-8")
        print("LOCKED", json.dumps(locked), flush=True)
        batch([task(p, m, phase, stress) for p in PAIRS for m in plan["durations_minutes"]
               for phase, stress in [("later", True), ("full", False), ("full", True)]], pool)
    (output/"results.partial.json").replace(output/"report.json")
    print("COMPLETED:48 offline scalar accounts", flush=True)
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history-root", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("reports/fx_intraday_scalping"))
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("Positive worker count required")
    run(args.history_root, args.snapshot, args.output, args.workers)
