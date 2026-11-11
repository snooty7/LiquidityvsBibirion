# Initial USDCHF M30 diagnostic: 90-day training

Configured M5 confirmation was restored before replay. The corrected baseline produced 64 out-of-sample trades, EUR +18.06 net, PF 1.060, and realized drawdown EUR 76.32.

Eight hypotheses were registered before training. None met the fixed-selection sample requirement in six of nine development training windows. Every selected test replay therefore used the baseline; no alternative candidate test outcome was inspected in this diagnostic. No candidate was promoted.

The follow-up study extends training to 365 days using additional older broker history. It preserves the eight hypotheses, test dates, risk, minimum sample count, cost model, selection rule, and promotion gates. The purpose is to address insufficient training samples without lowering the sample requirement.
