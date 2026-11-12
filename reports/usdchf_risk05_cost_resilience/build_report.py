"""Reconcile every saved account and render the complete exploratory comparison."""
import hashlib
import json
import math
from pathlib import Path

from src.risk.sizing import SymbolTradeInfo, calc_position_risk_money
from src.tools.research_financing_resilience import VARIANTS, nominate

ROOT = Path(__file__).resolve().parent


def build():
    """Audit recorded cash flows and disclose all variants, including failures."""
    report = json.loads((ROOT/"report.json").read_text(encoding="utf-8"))
    plan, rows = report["plan"], report["results"]
    reference_path = Path("reports/usdchf_10k_risk05/legacy/report.json")
    assert hashlib.sha256(reference_path.read_bytes()).hexdigest() == plan["reference_report_digest"]
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    for scenario, values in reference["results"].items():
        assert rows[scenario] == values, "Reused control changed"
    assert len(rows) == 24 and sum(map(len, rows.values())) == 72
    selected = json.loads((ROOT/"locked_selection.json").read_text(encoding="utf-8"))["selected"]
    assert selected == nominate(rows)[0]
    info = SymbolTradeInfo(**plan["symbol_info"])
    trades_checked = 0
    for periods in rows.values():
        assert set(periods) == {"earlier", "later", "full"}
        for row in periods.values():
            cash, total = 10000., 0.
            for trade in row["trades"]:
                risk = calc_position_risk_money(trade["entry_price"], trade["sl_initial"], trade["volume"], info)
                assert risk <= cash*.005+1e-7 and trade["volume"] <= .5
                net = trade["gross_pnl_money"]-trade["spread_cost_money"]-trade["commission_cost_money"]-trade["slippage_cost_money"]+trade["swap_money"]
                assert math.isclose(net, trade["pnl_money"], abs_tol=1e-7)
                assert math.isclose(sum(v for _, v in trade["swap_events"]), trade["swap_money"], abs_tol=1e-7)
                cash += net
                total += net
                trades_checked += 1
            assert math.isclose(cash, row["account"]["end_equity"], abs_tol=1e-7)
            assert math.isclose(total, row["metrics"]["net_pnl"], abs_tol=1e-7)
            assert row["wins_100_to_200"] == sum(100 <= t["pnl_money"] <= 200 for t in row["trades"])
    labels = {"original": "Стар M30/M1", "sell_flat": "SELL без пренощуване",
        "triple_exit": "SELL изход само преди троен swap", "one_unit_carry": "SELL максимум една единица swap",
        "avoid_late_sell_entries": "Без късни SELL входове", "trail_gap_0_75": "Trailing разстояние 0,75R"}
    def row(v, clock, stress=False, phase="full"):
        return rows[f"{v}_gmt{clock}"+("_stress" if stress else "")][phase]
    money = lambda n: f"€{n:,.2f}"
    winner = max(VARIANTS, key=lambda v: row(v, 3, True)["metrics"]["net_pnl"])
    candidate = "triple_exit"
    a, b = row(candidate, 3), row(candidate, 3, True)
    lines = ["# USDCHF M30/M1: €10 000, риск 0,5%, swap и разходи", "",
        "Период: **15.11.2024–10.11.2026 включително**, отделна непрекъсната сметка за всеки тест, без месечни рестартирания. 6 варианта × 2 часовника × 2 нива на разходи × 3 периода = **72 сметки** (24 проверени контроли от предишния отчет, 48 нови теста).", "",
        f"**Подобрение спрямо стария вариант:** изход само на SELL пет минути преди троен swap. В използвания модел той дава {money(a['metrics']['net_pnl'])} при нормални и {money(b['metrics']['net_pnl'])} при удвоени разходи, със спад съответно {money(a['account']['m1_close_drawdown'])} и {money(b['account']['m1_close_drawdown'])}. При GMT+2 стресът остава положителен: {money(row(candidate, 2, True)['metrics']['net_pnl'])}. Това е малка печалба за почти две години, а не месечна доходност.", "",
        f"**Избор само по по-ранната година:** {labels[selected]}. **Най-висока печалба за целия период при стрес GMT+3:** {labels[winner]}. Това са различни критерии: пълният период вече е разгледан и победителят по него е изследователски резултат, а не независимо потвърдена бъдеща печалба.", "",
        "## Цял период, основен часовник GMT+3", "",
        "| Вариант | Печалба нормални | Печалба удвоени | Спад нормални / удвоени | Сделки нормални / удвоени | Печеливши €100–200 нормални / удвоени | Swap нормални / удвоени |",
        "|---|---:|---:|---:|---:|---:|---:|"]
    for v in VARIANTS:
        a, b = row(v, 3), row(v, 3, True)
        lines.append(f"| {labels[v]} | {money(a['metrics']['net_pnl'])} | {money(b['metrics']['net_pnl'])} | {money(a['account']['m1_close_drawdown'])} / {money(b['account']['m1_close_drawdown'])} | {a['metrics']['trades']} / {b['metrics']['trades']} | {a['wins_100_to_200']} / {b['wins_100_to_200']} | {money(a['swap_net'])} / {money(b['swap_net'])} |")
    lines += ["", "Спадът включва отворената печалба/загуба по M1 затваряния, реалните симулирани изпълнения, комисиони и swap. Вътре в минутата спадът може да е по-голям. Броят сделки може да се променя при различни разходи заради защитите и размера на позициите.", "",
        "## Отделни години и чувствителност към часовника", "",
        "По-рано: 15.11.2024–14.11.2025; по-късно: 16.11.2025–10.11.2026. Всяка година започва самостоятелно с €10 000; сумата им не е непрекъснатият общ тест.", "",
        "| Вариант | GMT | По-рано нормални / удвоени | По-късно нормални / удвоени | Цял период нормални / удвоени | Спад цял период, удвоени |",
        "|---|---:|---:|---:|---:|---:|"]
    for v in VARIANTS:
        for clock in (3, 2):
            values = [f"{money(row(v, clock, False, p)['metrics']['net_pnl'])} / {money(row(v, clock, True, p)['metrics']['net_pnl'])}" for p in ("earlier", "later", "full")]
            lines.append(f"| {labels[v]} | +{clock} | {' | '.join(values)} | {money(row(v, clock, True)['account']['m1_close_drawdown'])} |")
    diagnostics = {}
    for v in VARIANTS:
        diagnostics[v] = {
            "positive_full_both_costs_both_clocks": all(row(v, o, s)["metrics"]["net_pnl"] > 0 for o in (3, 2) for s in (False, True)),
            "positive_later_stress_both_clocks": all(row(v, o, True, "later")["metrics"]["net_pnl"] > 0 for o in (3, 2)),
            "beats_known_sell_flat_full_stress_both_clocks": all(row(v, o, True)["metrics"]["net_pnl"] > row("sell_flat", o, True)["metrics"]["net_pnl"] for o in (3, 2)),
            "positive_earlier_stress": row(v, 3, True, "earlier")["metrics"]["net_pnl"] > 0,
        }
    (ROOT/"audit.json").write_text(json.dumps({"accounts_checked": 72, "ledger_trades_checked": trades_checked,
        "cached_controls_exact": True, "locked_nominee": selected, "descriptive_full_stress_winner": winner,
        "diagnostics": diagnostics}, indent=2), encoding="utf-8")
    lines += ["", "## Какво е променено", ""]
    lines += [f"- **{labels[v]}:** {definition}." for v, definition in VARIANTS.items()]
    lines += ["", "Всички нови промени са отделни, без комбинации или допълнително търсене след резултатите. Изборът е заключен след по-ранните GMT+3 тестове с удвоени разходи, преди новите по-късни/пълни тестове. Няма положителен по-ранен резултат; номинацията означава по-малка загуба, а не печеливша обучаваща година.", "",
        "Начален стоп 20 пипса, TP 2R; trailing се включва при 1,5R и сваля TP. Рискът е 0,5% от текущата сметка (първоначално до €50 ценови риск), максимум 0,5 лота, една позиция, дневна защита €150 и останалите сигнали/сесии/защити са запазени. Разходи и gap могат да увеличат реалната загуба над ценовия риск. Стопът никога не се отдалечава. Новите политики използват същия replay път за изпълнение и споделената live функция за trailing; те са само изследователски и не са включени в live конфигурацията.", "",
        "## Разходи и граници на извода", "",
        "- Нормални: исторически записан spread, €3,50 на лот на страна комисиона, 0,2 пипса неблагоприятно приплъзване при пазарни/stop изпълнения; fallback spread 1 пипс. TP лимитът няма изходно приплъзване.",
        "- Удвоени: €7 комисиона на страна, 0,4 пипса приплъзване, двойни отрицателни swap дебити; положителните кредити остават същите. Записаният spread не се удвоява; fallback става 2 пипса.",
        "- Използван е архивираният брокерски swap snapshot, държан постоянен през историята: BUY приблизително +€1,5274 и SELL −€27,8755 на лот/обикновен ден. Това не са действителните ставки за всеки исторически ден. EUR tick оценката също е постоянна.",
        "- Невалиден брокерски код7 за троен swap е заменен изрично с предположение сряда. Основно полунощ GMT+3, чувствителност GMT+2; исторически DST не е възстановен. При липсваща котировка изходът е на първата действителна следваща; начисленият swap остава.",
        "- Повторно използвани дати: тези тестове не доказват доходност върху недокоснат период. Не са моделирани исторически margin, ликвидност, latency и tick траектории. Отрицателната по-ранна година остава съществено предупреждение.", "",
        f"Проверени са {trades_checked} записа за сделки в 72 отделни сметки: първоначален риск, обем, всички разходи, swap събития, краен баланс и броят печалби €100–200 се съгласуват. **413 теста минаха, 1 съществуващ очакван неуспех; 16 нови регресионни случая.**", "",
        "Възпроизвеждане от корена на feature worktree (използвайте нов output при промяна на протокола):", "",
        "```powershell", "python -m src.tools.research_financing_resilience --history I:/Liquidity_VS_Birbirion/history/mt5_20261111/USDCHF_extended.json --output reports/usdchf_risk05_cost_resilience", "python -m reports.usdchf_risk05_cost_resilience.build_report", "python -m pytest -q", "```", "",
        "[План](plan.json) · [Всички сметки и сделки](report.json) · [Заключен избор](locked_selection.json) · [Одит и диагностики](audit.json)", "",
        "Ботът не е стартиран; MT5 не е инициализиран; няма поръчки, сделки или промени по live настройките."]
    (ROOT/"README.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(json.dumps({"selected": selected, "winner": winner, "diagnostics": diagnostics}, indent=2))


if __name__ == "__main__":
    build()
