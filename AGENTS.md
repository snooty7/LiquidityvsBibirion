# AGENTS.md

## Project summary
This repository contains a Python-based MetaTrader 5 trading bot focused on liquidity-driven setups.
Primary deployment target is Windows with MetaTrader 5 terminal installed locally.

## Core constraints
- Language: Python 3.11+
- Broker interface: MetaTrader5 Python package
- Primary assets: EUR/USD environment and USD-quoted instruments
- Main strategy family: liquidity sweeps, displacement, confirmation, structure-based execution
- Risk-first architecture is mandatory

## Non-negotiable rules
- Never add martingale
- Never add averaging down
- Never add grid logic unless explicitly requested
- Never move stop-loss further away to save a trade
- Always size positions from risk, not from arbitrary lot size
- Preserve modular boundaries: strategy, risk, execution, services
- Prefer configuration-driven behavior
- Keep logs and decisions explainable
- Backtests and live logic must share the same signal definitions where possible

## Strategy philosophy
We are not chasing random breakouts.
We want:
1. Bias / directional context
2. Liquidity map
3. Sweep event
4. Confirmation / displacement
5. Structure-based stop
6. Risk-based sizing
7. Controlled exits

## Coding preferences
- Keep functions small and testable
- Use dataclasses where appropriate
- Add docstrings on public methods
- Do not silently swallow exceptions
- Prefer explicit names over short names
- Do not introduce dependencies unless needed

## Testing priorities
- Risk sizing correctness
- Daily loss guard
- Stop distance validation
- Session filtering
- Liquidity signal logic

## Expected next steps for Codex
1. Read config files first
2. Improve RiskManager before adding more strategy complexity
3. Keep MT5 execution adapter isolated from signal logic
4. Add backtest harness after live-safe guards are stable