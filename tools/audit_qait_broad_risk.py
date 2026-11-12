"""Independent arithmetic audit of saved initial risk and stop direction."""
from datetime import datetime
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "reports/qait/broad_20261112"


def audit():
    """Reconstruct pre-entry equity and check existing budget/volume/stop limits."""
    records = []
    for symbol in ("EURUSD", "GBPUSD", "USDCHF", "NZDUSD"):
        protocol = json.loads((STUDY / symbol / "base_protocol.json").read_text())
        history = json.loads(Path(protocol["history"]).read_bytes())
        info = history["symbols"][symbol]["symbol_info"]
        del history
        cfg = protocol["effective_config"]["symbols"][0]
        runtime = protocol["effective_config"]["runtime"]
        assert not cfg["ignore_portfolio_cap"]
        assert protocol["adaptive"]["partial_exit_r"] == 0
        for scenario in ("base", "doubled_costs"):
            report = json.loads((STUDY / symbol / scenario / "report.json").read_text())
            checked = 0
            max_utilization = 0.0
            for row in report["comparisons"]:
                if row["status"] != "complete":
                    continue
                equity = protocol["equity"]
                previous_exit = None
                for trade in row["trades"]:
                    entry = datetime.fromisoformat(trade["entry_time_utc"])
                    exit_time = datetime.fromisoformat(trade["exit_time_utc"])
                    assert previous_exit is None or entry >= previous_exit
                    previous_exit = exit_time
                    assert entry <= exit_time
                    risk = abs(trade["entry_price"]-trade["sl_initial"])/info["trade_tick_size"]*info["trade_tick_value"]*trade["volume"]
                    budget = equity * min(cfg["risk_pct"], runtime["max_total_open_risk_pct"]) / 100
                    assert risk <= budget + 1e-7, (symbol, scenario, row["arm"], risk, budget)
                    assert cfg["min_lot"]-1e-9 <= trade["volume"] <= cfg["max_lot"]+1e-9
                    if trade["side"] == "BUY":
                        assert trade["sl_initial"] < trade["entry_price"] < trade["tp_initial"]
                        assert trade["exit_sl"] >= trade["sl_initial"]-1e-10
                    else:
                        assert trade["tp_initial"] < trade["entry_price"] < trade["sl_initial"]
                        assert trade["exit_sl"] <= trade["sl_initial"]+1e-10
                    max_utilization = max(max_utilization, risk / budget)
                    equity += trade["pnl_money"]
                    checked += 1
            records.append(dict(symbol=symbol, scenario=scenario, checked_trade_rows=checked,
                                maximum_authorized_stop_budget_utilization=max_utilization))
    with (STUDY / "risk_audit.json").open("x", encoding="utf-8") as stream:
        json.dump(dict(status="passed", records=records,
                       auditor_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       checks=["initial-stop risk within configured and portfolio budgets at reconstructed pre-entry equity",
                               "configured min/max volume", "directional initial protection", "exit stop never wider than initial",
                               "isolated single-position chronology"],
                       limitation="Saved initial/final stops only; not proof of every intratrade stop update, margin realism, gap-loss bounds or synchronized portfolio risk"), stream, indent=2)
    print("Passed independent saved-ledger risk and stop arithmetic audit")


if __name__ == "__main__":
    audit()
