# Phase 9 Backtesting and Model Calibration

## Decision

Candidate `v1.2` is **promising but not promoted**. It beats `production-v1.1` on MAE, Spearman rank correlation, and Top-10 hit rate at every tested horizon, but the comparison covers only the 2025–26 season and cannot reconstruct historical injury or availability status. Production therefore remains `v1.1`.

## Scope and source

- Season: 2025–26 Premier League.
- Source: public historical CSVs from the [Vaastav Fantasy Premier League repository](https://github.com/vaastav/Fantasy-Premier-League).
- Grain: one player-fixture-gameweek outcome plus one fixture record.
- Horizons: next 1, 3, and 5 gameweeks.
- Models: `production-v1.1` and `candidate-v1.2` from `config/backtest_models.yaml`.
- Loaded data: 29,747 unique player-fixture rows and 380 fixtures.
- Evaluation: 6 aggregate runs and 153,072 persisted player-cutoff predictions.

The source contained 29,757 player-fixture rows. Ten repeated natural keys had byte-equivalent row values and were removed. A repeated key with conflicting values rejects the import rather than selecting a row silently.

## Time-safe protocol

For every cutoff gameweek N, feature values are built only from rows at or before N. Recommendation scores and ranks are frozen before points from N+1 through N+h are joined as outcomes.

The following controls prevent known leakage paths:

- Rolling form, minutes, bonus, ICT, expected output, and price use observations through the cutoff only.
- Fixture ease is reconstructed from opponents' league points per match earned through the cutoff; final-season FDR is not used.
- Cross-season history uses seasons strictly earlier than the target season.
- The same eligible players and future window are used for baseline and candidate at each cutoff.
- Stored prediction keys include season, cutoff, horizon, model version, and player.

## Metric definitions

- **MAE percentile (lower is better):** mean absolute difference between the 0–100 recommendation score and the player's future-points percentile among players in the same position.
- **Spearman (higher is better):** mean cutoff-level rank correlation between recommendation score and actual future points.
- **Top-10 hit rate (higher is better):** mean percentage overlap between the ten highest predicted players and ten highest actual scorers at each cutoff.
- **Average actual points Top 10 (higher is better):** mean future-window points produced by the ten highest predicted players.

MAE here measures score calibration against a position-relative target; it is not an error in raw FPL points. Spearman and Top-10 metrics assess ordering and shortlist usefulness, not causal prediction.

## Results

| Horizon | Model | Cutoffs | Predictions | MAE ↓ | Spearman ↑ | Top-10 hit ↑ | Avg actual pts Top 10 ↑ |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 GW | production-v1.1 | 35 | 27,102 | 17.645 | 0.586 | 8.57% | 4.27 |
| 1 GW | candidate-v1.2 | 35 | 27,102 | 17.070 | 0.622 | 9.14% | 4.20 |
| 3 GW | production-v1.1 | 33 | 25,424 | 18.320 | 0.652 | 10.00% | 11.34 |
| 3 GW | candidate-v1.2 | 33 | 25,424 | 17.648 | 0.695 | 10.61% | 11.22 |
| 5 GW | production-v1.1 | 31 | 24,010 | 18.418 | 0.672 | 10.32% | 18.50 |
| 5 GW | candidate-v1.2 | 31 | 24,010 | 17.722 | 0.716 | 11.94% | 18.76 |

Candidate v1.2 improves MAE by 0.576–0.696 points, Spearman by 0.036–0.044, and Top-10 hit rate by 0.57–1.62 percentage points. Average realized points among its predicted Top 10 is 0.07 lower at 1 GW and 0.12 lower at 3 GW, then 0.26 higher at 5 GW. This mixed secondary metric reinforces the conservative hold decision.

## Quality and reproducibility checks

- Required CSV columns, numeric values, seasons, positions, and fixture-team references are validated before persistence.
- Ten exact source duplicates were identified and safely deduplicated; no conflicting duplicate was accepted.
- Prediction natural keys have zero duplicates after the run.
- Candidate v1.2 at the 5-GW horizon was independently recomputed from stored predictions: MAE `17.7216`, Top-10 hit `11.94%`, and average Top-10 points `18.761`, matching the stored aggregate values after rounding.
- Rerunning the workflow replaces the same season/horizon/model result rather than accumulating duplicate runs.

Overall data status: **share with caveats**. The stored calculations and keys are internally consistent, but the available evidence is insufficient for production promotion.

## Limitations and next validation

- Only one season is evaluated; candidate selection and evaluation are not yet separated across independent seasons.
- Historical injury and availability states are unavailable, so the availability multiplier is neutral.
- Official FPL form is approximated with rolling five-gameweek points.
- Fixture ease is reconstructed and is not an archive of the official historical FDR snapshot.
- Early-season cutoffs have less evidence, although evaluation begins at GW3.

Before promoting v1.2, rerun the same protocol on at least one additional independent season. If reliable sources become available, add historical availability and archived FDR, then compare position- and horizon-specific calibration without changing the evaluation set.
