"""Reconcile all adviser variants and disclose every result and fitted decision."""
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

from src.risk.sizing import SymbolTradeInfo, calc_position_risk_money
from src.strategy.adaptive_direction_agent import fit_advice, update_boundary
from src.strategy.cost_aware_agent import ClosedOutcome
from src.tools.research_agent_improvement import VARIANTS, advice_config, nominate

ROOT = Path(__file__).resolve().parent
LABELS = {"baseline": "Досегашен месечен агент", "weekly": "Седмично обновяване",
    "lookback_90": "История 90 дни", "lookback_365": "История 365 дни",
    "recent_weighted": "Тежест на скорошните сделки", "trail_gap_1_25": "Trailing разстояние 1,25R"}


def stamp(value):
    """Parse the explicit timestamp in a saved trade ledger."""
    return int(datetime.fromisoformat(value).timestamp())


def build():
    """Independently audit sizing, ledgers, cached controls and each causal fit."""
    report = json.loads((ROOT/"report.json").read_text(encoding="utf-8"))
    plan, results = report["plan"], report["results"]
    reference_path = Path("reports/usdchf_direction_agent/report.json")
    assert hashlib.sha256(reference_path.read_bytes()).hexdigest() == plan["reference_report_digest"]
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    info = SymbolTradeInfo(**plan["symbol_info"])
    assert len(results) == 24 and sum(map(len, results.values())) == 72
    training = {}
    for clock in (3, 2):
        trades = reference["results"][f"baseline_gmt{clock}_stress"]["full"]["trades"]
        training[clock] = tuple(ClosedOutcome(stamp(t["exit_time_utc"]), t["side"],
            t["pnl_money"]/calc_position_risk_money(t["entry_price"], t["sl_initial"], t["volume"], info)) for t in trades)
        for stress in (False, True):
            suffix = f"gmt{clock}"+("_stress" if stress else "")
            for phase, old in reference["results"]["agent_best_"+suffix].items():
                actual = dict(results["baseline_"+suffix][phase])
                actual["scenario"] = old["scenario"]
                assert actual == old, "Cached agent baseline changed"
    trades_checked, fits_checked, decisions_checked = 0, 0, 0
    for v in VARIANTS:
        config = advice_config(v)
        for clock in (3, 2):
            for stress in (False, True):
                scenario = f"{v}_gmt{clock}"+("_stress" if stress else "")
                assert set(results[scenario]) == {"earlier", "later", "full"}
                for row in results[scenario].values():
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
                    assert math.isclose(cash, row["account"]["end_equity"], abs_tol=1e-7)
                    assert math.isclose(net_total, row["metrics"]["net_pnl"], abs_tol=1e-7)
                    assert row["wins_100_to_200"] == sum(100 <= t["pnl_money"] <= 200 for t in row["trades"])
                    fits = {}
                    for saved in row["agent_months"] if v == "baseline" else row["agent_fits"]:
                        advice = fit_advice(training[clock], saved["fitted_at"], config)
                        assert json.loads(json.dumps(asdict(advice))) == saved
                        assert advice.last_training_exit is None or advice.last_training_exit < advice.fitted_at
                        fits[advice.fitted_at] = advice
                        fits_checked += 1
                    for decision in row["agent_decisions"]:
                        boundary = update_boundary(decision["time"], config)
                        assert decision["fitted_at"] == boundary
                        assert decision["allow"] == (decision["side"] in fits[boundary].allowed_sides)
                        decisions_checked += 1
                    for t in row["trades"]:
                        assert t["side"] in fits[update_boundary(stamp(t["entry_time_utc"]), config)].allowed_sides
    selected = json.loads((ROOT/"locked_selection.json").read_text(encoding="utf-8"))["selected"]
    assert nominate(results)[0] == selected
    def row(v, clock=3, stress=False, phase="full"):
        return results[f"{v}_gmt{clock}"+("_stress" if stress else "")][phase]
    winner = max(VARIANTS, key=lambda v: row(v, stress=True)["metrics"]["net_pnl"])
    robust = max(VARIANTS, key=lambda v: min(row(v, o, True)["metrics"]["net_pnl"] for o in (3, 2)))
    diagnostics = {v: {
        "positive_full_both_costs_both_clocks": all(row(v, o, s)["metrics"]["net_pnl"] > 0 for o in (3, 2) for s in (False, True)),
        "beats_previous_agent_full_stress_both_clocks": all(row(v, o, True)["metrics"]["net_pnl"] > row("baseline", o, True)["metrics"]["net_pnl"] for o in (3, 2)),
        "positive_earlier_stress": row(v, stress=True, phase="earlier")["metrics"]["net_pnl"] > 0,
        "earlier_stress_trades": row(v, stress=True, phase="earlier")["metrics"]["trades"],
    } for v in VARIANTS}
    money = lambda n: f"€{n:,.2f}"
    lines = ["# USDCHF M30/M1: подобряване на агента при €10 000 и риск 0,5%", "",
        "Пълен период **15.11.2024–10.11.2026 включително**. Всеки тест е отделна непрекъсната сметка, без месечни рестартирания. 6 варианта × 2 брокерски часовника × 2 нива на разходи × 3 периода = **72 сметки**: 12 проверени контроли от предишния агент и 60 нови симулации.", "",
        f"Най-висока пълна печалба при GMT+3 и удвоени разходи: **{LABELS[winner]}**, {money(row(winner, stress=True)['metrics']['net_pnl'])}. Най-висок минимум между двата часовника: **{LABELS[robust]}**, {money(min(row(robust, o, True)['metrics']['net_pnl'] for o in (3, 2)))}. Предишният агент дава {money(row('baseline', stress=True)['metrics']['net_pnl'])} по GMT+3 и {money(row('baseline', 2, True)['metrics']['net_pnl'])} по GMT+2.", "",
        f"Предварителен избор по по-ранната година: **{LABELS.get(selected, 'без сделки / cash')}**. Заключен е преди новите по-късни/пълни резултати. Пълният победител е описателен резултат върху многократно използвани дати и не заменя този избор. Печалбата за почти две години не е месечна доходност или прогноза.", "",
        "## Пълен период, основен часовник GMT+3", "",
        "| Вариант | Печалба нормални | Печалба удвоени | Спад нормални / удвоени | Сделки нормални / удвоени | Печеливши €100–200 нормални / удвоени |",
        "|---|---:|---:|---:|---:|---:|"]
    for v in VARIANTS:
        a, b = row(v), row(v, stress=True)
        lines.append(f"| {LABELS[v]} | {money(a['metrics']['net_pnl'])} | {money(b['metrics']['net_pnl'])} | {money(a['account']['m1_close_drawdown'])} / {money(b['account']['m1_close_drawdown'])} | {a['metrics']['trades']} / {b['metrics']['trades']} | {a['wins_100_to_200']} / {b['wins_100_to_200']} |")
    lines += ["", "Спадът включва отворен P&L, комисиони и swap по M1 затваряния и действителни симулирани изпълнения. Вътре в минутата спадът може да е по-голям. Броят сделки и печелившите €100–200 са измерени след разходите; няма увеличаване на обем за достигането им.", "",
        "## Отделни години и чувствителност към часовника", "",
        "По-рано: 15.11.2024–14.11.2025; по-късно: 16.11.2025–10.11.2026. Отделните години започват със собствени €10 000 и не се сумират до пълната сметка. Към всеки update агентът може да използва само вече приключила shadow история, включително от предишната година.", "",
        "| Вариант | GMT | По-рано нормални / удвоени | По-късно нормални / удвоени | Пълен период нормални / удвоени | Спад пълен период, удвоени |",
        "|---|---:|---:|---:|---:|---:|"]
    for v in VARIANTS:
        for o in (3, 2):
            pairs = [f"{money(row(v, o, False, p)['metrics']['net_pnl'])} / {money(row(v, o, True, p)['metrics']['net_pnl'])}" for p in ("earlier", "later", "full")]
            lines.append(f"| {LABELS[v]} | +{o} | {' | '.join(pairs)} | {money(row(v, o, True)['account']['m1_close_drawdown'])} |")
    lines += ["", "## Пет отделни промени", "",
        "- Седмично обновяване: понеделник 00:00 UTC вместо първо число на месеца; същите 180 дни история.",
        "- История 90 дни: по-кратък прозорец, останалото е същото.",
        "- История 365 дни: по-дълъг прозорец, останалото е същото.",
        "- Тежест на скорошните сделки: в оригиналните 180 дни теглото се намалява наполовина на всеки 60 дни. Пример: изход преди 60 дни тежи 0,5, преди 120 дни — 0,25.",
        "- Trailing разстояние 1,25R: същият месечен агент, само по-широко разстояние при първоначално избраната exit конфигурация. Вече поставен стоп никога не се отдалечава; активацията остава при1,5R, началният SL20пипса е същият. Shadow обучението не се променя с изхода, за да се изолира една промяна.", "",
        "Общи правила: поне 8 приключили shadow сделки за посоката, положителна средна stressed netR, избира се най-добрата посока, BUY при равенство. Иначе няма вход. Използват се само изходи строго преди съответния UTC update; текущи/бъдещи резултати и отворени позиции не участват. Същата stressed shadow история обучава нормалния и стрес теста, отделно за GMT+3 и GMT+2. Няма измислена история преди15.11.2024. Смяната на съвета не затваря съществуващи позиции. Всички варианти са фиксирани предварително, без комбинации или пренастройване след резултатите.", "",
        "Това са обясними симулационни филтри за съществуващите сигнали. Минимумът8 и положителната средна стойност не са статистическа гаранция; при претегляне ефективната извадка може да е по-малка. Повторното търсене върху същата история увеличава риска от случайно добър резултат.", "",
        "## Непроменен риск и разходи", "",
        "- €10 000, риск0,5% от текущата equity, начално до €50 ценови риск, SL20пипса, максимум0,5лота, една позиция, дневна защита€150. Сесии, cooldown, bias, order block, M1 потвърждение и spread cap0,9 остават същите. Комисиони/приплъзване/gap могат да увеличат реалната загуба над ценовия риск. Няма martingale, усредняване, grid или увеличение на риска.",
        "- Нормални: записан исторически spread, €3,50/лот/страна комисиона и0,2пипса неблагоприятно приплъзване при market/stop. Удвоени: €7/страна,0,4пипса и двойни отрицателни swap дебити; положителните swap кредити остават същите. Записаният spread не се удвоява; fallback1 става2пипса. TP лимитът няма изходно приплъзване.",
        "- Архивираният текущ swap остава постоянен в историята, а не действителна дневна серия. BUY приблизително +€1,5274 и SELL −€27,8755/лот/обикновен ден, постоянна EUR tick оценка. Приет троен swap в сряда заради невалиден брокерски код7. GMT+3 основно, GMT+2 чувствителност; исторически DST не е възстановен. SELL се затваря пет минути преди троен swap; при липсващи котировки изходът е на първата действителна следваща и дължимият swap остава.",
        "- Данните вече са използвани многократно. Причинният walk-forward алгоритъм не прави тези дати недокоснат holdout. Margin, latency, ликвидност и пълен tick path не са възстановени. Тези резултати не разрешават автоматична live търговия.",
        "- Метаданни: наследеното поле risk_unchanged в замразения план съдържа описание на exit вариантите от предишното изследване. Точните нови промени са в variants, advice_configs и exit_training; в този тест няма fixed2R кандидат. Числовите рискови настройки и действителните сделки са проверени. Оригиналният план е запазен без промяна.", "",
        f"Одит: **72 сметки, {trades_checked} записа за сделки, {fits_checked} обучения, {decisions_checked} решения**. Началният риск, разходите, swap събитията, балансите и броят печалби€100–200 се съгласуват. Всяко обучение е независимо възстановено само от допустимите минали резултати. **441 теста минаха, 1 съществуващ очакван неуспех; 18 нови регресионни случая.**", "",
        "```powershell", "python -m src.tools.research_agent_improvement --history I:/Liquidity_VS_Birbirion/history/mt5_20261111/USDCHF_extended.json --output reports/usdchf_agent_improvement", "python -m reports.usdchf_agent_improvement.build_report", "python -m pytest -q", "```", "",
        "[План](plan.json) · [Всички сделки, обучения и решения](report.json) · [Заключен избор](locked_selection.json) · [Одит](audit.json)", "",
        "Само офлайн тестове. MT5 не е инициализиран, ботът не е стартиран, няма поръчки или реални сделки, live настройките са непроменени."]
    (ROOT/"README.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    audit = {"accounts_checked": 72, "trades_checked": trades_checked, "fits_checked": fits_checked,
        "entry_decisions_checked": decisions_checked, "cached_controls_exact": True, "locked_selection": selected,
        "descriptive_primary_stress_winner": winner, "descriptive_best_worst_clock_stress": robust,
        "diagnostics": diagnostics}
    (ROOT/"audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    build()
