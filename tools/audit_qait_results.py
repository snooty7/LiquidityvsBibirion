"""Independent stdlib audit of saved adaptive ledgers; no trading-code imports."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def audit(history_path: Path, reports: list[Path], output: Path) -> dict:
    """Recompute net money from fills and metadata, equity, costs and volume steps."""
    history = json.loads(history_path.read_text(encoding="utf-8-sig"))
    count = 0
    ledgers = 0
    inputs = []
    for path in reports:
        document = json.loads(path.read_text(encoding="utf-8"))
        pairs = {}
        for row in document["comparisons"]:
            if row["status"] != "complete":
                continue
            trades = row["trades"]
            assert math.isclose(sum(trade["pnl_money"] for trade in trades),
                                row["result"]["ending_equity"]-row["result"]["initial_equity"], abs_tol=1e-6)
            for trade in trades:
                info = history["symbols"][trade["symbol"]]["symbol_info"]
                move = (trade["exit_price"]-trade["entry_price"])*(1 if trade["side"] == "BUY" else -1)
                expected = move/info["trade_tick_size"]*info["trade_tick_value"]*trade["volume"]-trade["commission_cost_money"]
                assert math.isclose(expected, trade["pnl_money"], abs_tol=1e-8)
                all_costs = sum(trade[name] for name in ("spread_cost_money", "commission_cost_money", "slippage_cost_money"))
                assert math.isclose(trade["gross_pnl_money"]-all_costs, trade["pnl_money"], abs_tol=1e-8)
                assert math.isclose(trade["volume"]/info["volume_step"], round(trade["volume"]/info["volume_step"]), abs_tol=1e-8)
                assert info["volume_min"] <= trade["volume"] <= info["volume_max"]
                count += 1
            pairs.setdefault((row["fold"], row["phase"]), {})[row["arm"]] = trades
            ledgers += 1
        for pair in pairs.values():
            assert pair["adaptive"] == pair["adaptive_shadow"]
        inputs.append(dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    result = dict(status="passed", audited_trade_rows=count, audited_ledgers=ledgers,
                  checks=["fill-price net P&L", "gross/cost reconciliation", "ending equity", "volume step/min/max", "shadow ledger identity"],
                  reports=inputs, auditor_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  limitation="Audit verifies ledger arithmetic, not tick realism, portfolio simulation or profitability")
    if output.exists():
        raise ValueError("Audit output must not already exist")
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--reports", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.history, args.reports, args.output)))
