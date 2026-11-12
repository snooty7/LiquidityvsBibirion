"""Audit all directional/agent accounts and render every outcome without selection bias."""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from src.risk.sizing import SymbolTradeInfo, calc_position_risk_money
from src.strategy.cost_aware_agent import ClosedOutcome, fit_month, month_start
from src.tools.research_direction_agent import VARIANTS, nominate

ROOT = Path(__file__).resolve().parent
LABELS = {"baseline": "Досегашен изход преди троен swap", "buy_only": "Само BUY",
    "sell_only": "Само SELL", "fixed_2r": "Фиксирана цел 2R без trailing",
    "agent_positive": "Агент: положителни посоки", "agent_best": "Агент: най-добра посока"}


def stamp(value):
    """Parse the explicit UTC timestamps saved in every trade ledger."""
    return int(datetime.fromisoformat(value).timestamp())


def build():
    """Reconcile risk/cost/cash and independently reconstruct all monthly advice."""
    report = json.loads((ROOT/"report.json").read_text(encoding="utf-8"))
    plan, results = report["plan"], report["results"]
    reference_path = Path("reports/usdchf_risk05_cost_resilience/report.json")
    assert hashlib.sha256(reference_path.read_bytes()).hexdigest() == plan["reference_report_digest"]
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    info = SymbolTradeInfo(**plan["symbol_info"])
    assert len(results) == 24 and sum(map(len, results.values())) == 72
    training = {}
    for clock in (3, 2):
        trades = reference["results"][f"triple_exit_gmt{clock}_stress"]["full"]["trades"]
        training[clock] = tuple(ClosedOutcome(stamp(t["exit_time_utc"]), t["side"],
            t["pnl_money"]/calc_position_risk_money(t["entry_price"], t["sl_initial"], t["volume"], info)) for t in trades)
        for stress in (False, True):
            suffix = f"gmt{clock}"+("_stress" if stress else "")
            for phase, old in reference["results"]["triple_exit_"+suffix].items():
                actual = dict(results["baseline_"+suffix][phase])
                actual["scenario"] = old["scenario"]
                assert actual == old, "Cached baseline changed"
    trades_checked, fits_checked, decisions_checked = 0, 0, 0
    for scenario, periods in results.items():
        assert set(periods) == {"earlier", "later", "full"}
        clock = 3 if "_gmt3" in scenario else 2
        for row in periods.values():
            cash, net_total = 10000., 0.
            for t in row["trades"]:
                risk = calc_position_risk_money(t["entry_price"], t["sl_initial"], t["volume"], info)
                assert risk <= cash*.005+1e-7 and t["volume"] <= .5
                net = t["gross_pnl_money"]-t["spread_cost_money"]-t["commission_cost_money"]-t["slippage_cost_money"]+t["swap_money"]
                assert math.isclose(net, t["pnl_money"], abs_tol=1e-7)
                assert math.isclose(sum(amount for _, amount in t["swap_events"]), t["swap_money"], abs_tol=1e-7)
                cash += net
                net_total += net
                trades_checked += 1
                if scenario.startswith("buy_only"):
                    assert t["side"] == "BUY"
                if scenario.startswith("sell_only"):
                    assert t["side"] == "SELL"
                if scenario.startswith("fixed_2r"):
                    assert t["exit_sl"] == t["sl_initial"] and t["exit_tp"] == t["tp_initial"]
            assert math.isclose(cash, row["account"]["end_equity"], abs_tol=1e-7)
            assert math.isclose(net_total, row["metrics"]["net_pnl"], abs_tol=1e-7)
            assert row["wins_100_to_200"] == sum(100 <= t["pnl_money"] <= 200 for t in row["trades"])
            if scenario.startswith("agent_"):
                months = {}
                for saved in row["agent_months"]:
                    advice = fit_month(training[clock], saved["fitted_at"], best_only=scenario.startswith("agent_best"))
                    assert json.loads(json.dumps(asdict(advice))) == saved
                    assert advice.last_training_exit is None or advice.last_training_exit < advice.fitted_at
                    months[advice.fitted_at] = advice
                    fits_checked += 1
                for decision in row["agent_decisions"]:
                    boundary = month_start(decision["time"])
                    assert decision["fitted_at"] == boundary
                    assert decision["allow"] == (decision["side"] in months[boundary].allowed_sides)
                    decisions_checked += 1
                for t in row["trades"]:
                    assert t["side"] in months[month_start(stamp(t["entry_time_utc"]))].allowed_sides
    selected = json.loads((ROOT/"locked_selection.json").read_text(encoding="utf-8"))["selected"]
    assert nominate(results)[0] == selected
    def row(v, clock=3, stress=False, phase="full"):
        return results[f"{v}_gmt{clock}"+("_stress" if stress else "")][phase]
    winner = max(VARIANTS, key=lambda v: row(v, stress=True)["metrics"]["net_pnl"])
    robust = max(VARIANTS, key=lambda v: min(row(v, o, True)["metrics"]["net_pnl"] for o in (3, 2)))
    diagnostics = {v: {
        "positive_full_both_costs_both_clocks": all(row(v, o, s)["metrics"]["net_pnl"] > 0 for o in (3, 2) for s in (False, True)),
        "beats_reference_full_stress_both_clocks": all(row(v, o, True)["metrics"]["net_pnl"] > row("baseline", o, True)["metrics"]["net_pnl"] for o in (3, 2)),
        "positive_earlier_stress": row(v, stress=True, phase="earlier")["metrics"]["net_pnl"] > 0,
        "earlier_stress_trades": row(v, stress=True, phase="earlier")["metrics"]["trades"],
    } for v in VARIANTS}
    money = lambda n: f"€{n:,.2f}"
    lines = ["# USDCHF: посоки, изходи и месечен агент — €10 000 / риск 0,5%", "",
        "Период **15.11.2024–10.11.2026 включително**. 72 независими сметки: 12 точно проверени контроли от предишното изследване и 60 нови теста. Всяка сметка се движи непрекъснато в собствения си период, без месечни рестартирания; позициите не се затварят автоматично при месечна смяна на съвета.", "",
        f"Най-висока пълна печалба при GMT+3 и удвоени разходи: **{LABELS[winner]}**, {money(row(winner, stress=True)['metrics']['net_pnl'])}. Най-висок от по-ниските резултати между двата часовника: **{LABELS[robust]}**, минимум {money(min(row(robust, o, True)['metrics']['net_pnl'] for o in (3, 2)))}. Това са описателни сравнения върху вече използвани дати.", "",
        f"Изборът по по-ранната година с удвоени разходи е **{LABELS.get(selected, 'без сделки / cash')}**. Заключен е преди новите по-късни и пълни резултати. Пълният победител не заменя този избор; положителната пълна печалба сама по себе си не потвърждава надеждна бъдеща стратегия.", "",
        "## Цял период, GMT+3, след всички моделирани разходи", "",
        "| Вариант | Нормални печалба | Удвоени печалба | Спад нормални / удвоени | Сделки нормални / удвоени | Печеливши €100–200 нормални / удвоени |",
        "|---|---:|---:|---:|---:|---:|"]
    for v in VARIANTS:
        a, b = row(v), row(v, stress=True)
        lines.append(f"| {LABELS[v]} | {money(a['metrics']['net_pnl'])} | {money(b['metrics']['net_pnl'])} | {money(a['account']['m1_close_drawdown'])} / {money(b['account']['m1_close_drawdown'])} | {a['metrics']['trades']} / {b['metrics']['trades']} | {a['wins_100_to_200']} / {b['wins_100_to_200']} |")
    lines += ["", "Спадът е по equity при M1 затваряния и действителни симулирани изпълнения, с отворен P&L, комисиони и swap. Вътреминутният спад може да бъде по-голям. €100–200 е отчетен резултат от печеливши сделки, а не обещание или повод за увеличение на риска.", "",
        "## По-рано, по-късно и втори брокерски часовник", "",
        "По-рано: 15.11.2024–14.11.2025. По-късно: 16.11.2025–10.11.2026. Всяка година започва с отделни €10 000 и не се сумира до непрекъснатия пълен тест. Агентът в по-късния тест може да ползва приключила по-ранна shadow история, защото тя вече е известна към съответния месец.", "",
        "| Вариант | GMT | По-рано нормални / удвоени | По-късно нормални / удвоени | Цял период нормални / удвоени | Спад цял период удвоени |",
        "|---|---:|---:|---:|---:|---:|"]
    for v in VARIANTS:
        for o in (3, 2):
            pairs = [f"{money(row(v, o, False, p)['metrics']['net_pnl'])} / {money(row(v, o, True, p)['metrics']['net_pnl'])}" for p in ("earlier", "later", "full")]
            lines.append(f"| {LABELS[v]} | +{o} | {' | '.join(pairs)} | {money(row(v, o, True)['account']['m1_close_drawdown'])} |")
    lines += ["", "## Как работи агентът", "",
        "Това е детерминистичен съветник за посоката, без връзка с брокер и без инструмент за изпращане на поръчки. Той филтрира съществуващите M30/M1 входове; не измисля нови сигнали. На първо число UTC оценява само shadow сделките, приключили строго преди този момент през предходните 180 дни. За всяка посока изчислява средната нетна печалба в единици първоначален ценови риск, със spread, двойни комисиони/приплъзване и отрицателен swap. Трябват поне 8 приключили сделки и положителна средна стойност. Това е малка извадка и изследователска евристика, а не статистическа гаранция.", "",
        "Единият вариант допуска всички положителни посоки, другият — само най-добрата (BUY при равенство). При недостатъчни данни/неположителни стойности остава извън пазара. Началният период няма измислена предварителна история. Същите stressed labels обучават нормалния и стрес теста, с отделна shadow история за всеки часовник. Отворена сделка следва първоначалните стоп/изходи дори при смяна на месечния съвет. Shadow стратегията е фиксирана от предишни изследвания; този избор и повторното използване на историята ограничават независимостта на проверката.", "",
        "### Месечни решения: основен часовник и удвоени разходи", "",
        "| Месец | BUY брой / средно netR | SELL брой / средно netR | Положителни посоки | Най-добра посока |",
        "|---|---:|---:|---|---|"]
    positive = {m["fitted_at"]: m for m in row("agent_positive", stress=True)["agent_months"]}
    best = {m["fitted_at"]: m for m in row("agent_best", stress=True)["agent_months"]}
    for boundary in sorted(set(positive)|set(best)):
        m = positive.get(boundary) or best[boundary]
        format_side = lambda i: f"{m['counts'][i]} / " + (f"{m['mean_net_r'][i]:.3f}" if m['mean_net_r'][i] is not None else "—")
        allow = lambda source: (', '.join(source[boundary]['allowed_sides']) or "без входове") if boundary in source else "няма оценка"
        lines.append(f"| {datetime.fromtimestamp(boundary, timezone.utc).strftime('%Y-%m')} | {format_side(0)} | {format_side(1)} | {allow(positive)} | {allow(best)} |")
    monthly = {}
    for v in VARIANTS:
        values = {}
        for t in row(v, stress=True)["trades"]:
            key = t["exit_time_utc"][:7]
            values[key] = values.get(key, 0)+t["pnl_money"]
        monthly[v] = values
    (ROOT/"monthly_closed_pnl.json").write_text(json.dumps(monthly, indent=2), encoding="utf-8")
    lines += ["", "Липсващи месеци в таблицата нямат опит за вход. Месечните приключени печалби са в [monthly_closed_pnl.json](monthly_closed_pnl.json); те се групират по изход и не са equity доходност за месеца.", "",
        "## Непроменен риск и ограничения", "",
        "- €10 000, риск 0,5% от текущата equity, начално до €50 ценови риск, стоп 20 пипса, максимум 0,5 лота и една позиция. Оригиналните сесии, cooldown, bias, order block, M1 потвърждение, spread cap0,9 и дневна защита €150 остават включени. Разходи и gaps могат да увеличат реалната загуба над ценовия риск. Няма увеличаване на обем, martingale, усредняване или отдалечаване на стоп.",
        "- Контролът използва trailing при1,5R с разстояние1R и SELL изход пет минути преди троен swap. Само fixed2R изключва trailing и запазва първоначалния TP2R/SL; рискът и сигналите са същите. BUY-only и SELL-only се преиграват изцяло със собствен капацитет и equity, без изтриване на загубили сделки от готов журнал.",
        "- Нормални разходи: записан исторически spread, €3,50/лот/страна комисиона, 0,2 пипса неблагоприятно market/stop приплъзване. Стрес: €7/страна, 0,4 пипса и двойни отрицателни swap дебити; кредитите остават същите. Записаният spread не се удвоява; fallback1 става2 пипса. TP лимитът няма изходно приплъзване.",
        "- Архивираният текущ swap е постоянен през историята, не е действителна историческа дневна серия. BUY приблизително +€1,5274, SELL −€27,8755/лот/обикновен ден. Постоянна EUR tick оценка. Изрично предположение троен swap в сряда заради невалиден брокерски код7. GMT+3 основно и GMT+2 чувствителност, без възстановен исторически DST. Липсващи котировки водят до първия действителен по-късен изход и дължимото финансиране остава.",
        "- Историята вече е използвана многократно. Месечният алгоритъм е причинен в симулацията, но резултатите не са недокосната бъдеща проверка. Няма симулиран пълен tick path, исторически margin, latency или изчерпана ликвидност. По-висока печалба в тест не означава безопасна автоматична търговия.", "",
        f"Одит: **72 сметки, {trades_checked} записа за сделки, {fits_checked} месечни модела и {decisions_checked} решения**. Риск, разходи, swap, баланс и target-band броене са съгласувани; всеки модел е независимо възстановен само от допустимите минали labels. **423 теста минаха, 1 съществуващ очакван неуспех; 10 нови регресионни случая.**", "",
        "```powershell", "python -m src.tools.research_direction_agent --history I:/Liquidity_VS_Birbirion/history/mt5_20261111/USDCHF_extended.json --output reports/usdchf_direction_agent", "python -m reports.usdchf_direction_agent.build_report", "python -m pytest -q", "```", "",
        "[План](plan.json) · [Всички резултати и решения](report.json) · [Заключен избор](locked_selection.json) · [Одит](audit.json)", "",
        "Само офлайн тестове. MT5 не е инициализиран, ботът не е стартиран, няма поръчки/реални сделки и live настройките не са променени."]
    (ROOT/"README.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    audit = {"accounts_checked": 72, "trades_checked": trades_checked, "monthly_fits_checked": fits_checked,
        "entry_decisions_checked": decisions_checked, "cached_controls_exact": True,
        "earlier_locked_selection": selected, "descriptive_primary_stress_winner": winner,
        "descriptive_best_worst_clock_stress": robust, "diagnostics": diagnostics}
    (ROOT/"audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    build()
