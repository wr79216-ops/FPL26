# Historical Data Contract

## Source and scope

Completed-season aggregate CSV files are downloaded from the public [`vaastav/Fantasy-Premier-League`](https://github.com/vaastav/Fantasy-Premier-League) archive. The current configuration imports `2023-24`, `2024-25`, and `2025-26` from each season's `cleaned_players.csv`. Official current-season FPL remains the source of truth for active player IDs, teams, prices, status, ownership, fixtures, and current statistics.

The importer requires player name, position, minutes, total points, goals, assists, clean sheets, bonus, and price columns. Position aliases from older files are mapped explicitly (`AM` and `DM` to `MID`; `FW` to `FWD`). Invalid rows or missing required columns reject the entire import before the database transaction begins. Successful source files are archived under `data/historical/<season>/cleaned_players.csv`.

## Identity mapping

Names are transliterated for matching, lowercased, and stripped of punctuation. The original source name remains stored for audit.

- `MATCHED`: unique exact name and position, or a unique high-confidence candidate above 90% similarity with a four-point lead over the next candidate.
- `REVIEW`: a candidate from 80% similarity that is not above the high-confidence threshold, or a candidate with unresolved ambiguity.
- `UNMATCHED`: no candidate passes the review threshold.

Only `MATCHED` rows may influence scoring. Unique candidates above 90% are automatically promoted to `MATCHED`, covering harmless historical/current display-name differences. The verified exceptions in `config/historical_identity_overrides.yaml` are also promoted to `MATCHED` with the audit method `manual_confirmed_override`; these overrides unify a historical display name with the current official FPL player ID. Lower-confidence or ambiguous candidates remain visible in Data Status and are excluded until they are explicitly confirmed.

## Historical stability score

Only seasons with at least 450 minutes are eligible. For each matched current player:

1. Calculate season points per 90.
2. Weight seasons by recency: `1.0`, `0.6`, `0.36`, and so on.
3. Convert recency-weighted points per 90 to a position-relative percentile.
4. Calculate consistency as `100 - capped coefficient of variation × 100`.
5. Blend `80% output percentile + 20% consistency`.
6. Shrink the result toward neutral 50 using season coverage (full at two seasons) and minute coverage (full at 1,800 total minutes).

Players without an eligible safe match receive a neutral history input of 50. The position configuration assigns historical stability only 5% for MID/FWD and 10% for GK/DEF, so it cannot dominate the recommendation score.

## Snapshot auditability

Current-season refreshes persist one row per `(season, gameweek, player_id)` in `gameweek_snapshots`. Repeated refreshes update that natural key rather than adding duplicates. These snapshots preserve price, ownership, form, points, minutes, expected output, ICT, and capture time for future Phase 9 backtesting.
