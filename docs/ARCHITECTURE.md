# Core Architecture

Phase F extends the strict boundaries between current official FPL ingestion, historical enrichment, persisted data, feature calculation, explainable recommendations, time-safe model evaluation, non-binding decision support, and policy-gated external enrichment.

```text
Streamlit UI
    ↓ receives presentation-ready data only
Application services
    ↓ orchestrate use cases
Domain contracts
    ↓ stable source-independent records
Repositories                 FPLClient
    ↓ SQLAlchemy              ↓ HTTP + validation + cache
SQLite                       Official FPL JSON
                                 ↓
                            Raw JSON store

Provider registry → policy/status only → optional adapter after access approval
```

## Layer responsibilities

### `src/ui`

Renders pages and controls. It must not import `requests`, create HTTP clients, open SQLAlchemy sessions, or depend on official FPL JSON field names.

### `src/services`

Coordinates application use cases and exposes compact status/results to the UI. Services are the composition boundary between infrastructure and presentation.

### `src/domain`

Contains typed, source-independent contracts for teams, players, fixtures, current stats, gameweek snapshots, gameweek history, historical player-seasons, identity mappings, historical scores, recommendation scores, backtest outcomes, predictions, and run summaries. API transformation must produce these records before database loading.

### `src/api`

`FPLClient` is the sole current official FPL HTTP gateway. `HistoricalDataClient` is isolated to configured completed-season CSV files and applies timeout, retry, season validation, and required-column validation before service-level row parsing.

Public squad import also passes through `FPLClient`. Manager metadata and picks use a short memory cache but deliberately bypass the raw archive and database.

### `src/providers`

Defines the adapter protocol and fail-closed registry for optional external enrichment. The registry reads capabilities and governance state without creating a client or making a network request. No provider may become ready without an allowed access mode, recorded Terms/licence review, an implemented adapter, and official-player identity validation.

### `src/database`

Owns the SQLAlchemy models, SQLite connection, transactional sessions, schema checks, and idempotent repository writes. UI code must never import this layer directly.

### `src/data`

Contains raw persistence and legacy sample fixtures used only by tests. Runtime MVP pages no longer load sample player or fixture data.

## Database schema

Schema version `10` contains:

- `schema_metadata`
- `teams`
- `players`
- `fixtures`
- `player_current_stats`
- `gameweek_snapshots`
- `player_gameweek_history`
- `player_history_sync`
- `historical_player_seasons`
- `historical_identity_mappings`
- `player_historical_scores`
- `recommendation_scores`
- `backtest_player_gameweeks`
- `backtest_fixtures`
- `backtest_predictions`
- `backtest_runs`

Primary or composite keys reflect the natural identity of each record so repeated ingestion can be implemented as an idempotent upsert. `gameweek_snapshots` has a uniqueness guard on `(season, gameweek, player_id)`; a repeat refresh updates the same snapshot instead of duplicating it. Historical player rows are unique by `(source, season, source_player_key)`. `player_history_sync` records the latest checked season/gameweek even when an element-summary response contains no match history, preventing repeated requests on Streamlit reruns. Backtest outcomes are unique by `(season, player_id, fixture_id)`, predictions by `(season, as_of_gameweek, horizon, model_version, player_id)`, and aggregate runs by `(season, horizon, model_version)`.

## Migration strategy

The application records its expected integer schema version in `schema_metadata`. Startup applies only registered forward migrations and rejects databases newer than the application supports. The v1 → v2 migration creates `gameweek_snapshots` and backfills it from existing `player_current_stats`; v2 → v3 adds the durable player-history sync cache; v3 → v4 adds official goalkeeper saves to current stats; v4 → v5 adds historical player-season, identity mapping, and stability-score tables; v5 → v6 adds the four backtest tables; v6 → v7 adds official transfer-in activity; v7 → v8 adds nullable official defensive, penalty, and discipline totals to current and per-fixture history; v8 → v9 adds nullable current-season xGC; v9 → v10 adds nullable positional candidate fields to `backtest_player_gameweeks`. After a migration, Data Status instructs the operator to refresh official FPL data. Downgrade is not supported; rollback uses a model/configuration commit and an explicit backup restore when data recovery is required.

## Raw data layout

```text
data/raw/
└── YYYY-MM-DD/
    └── HHMMSS_microsecondsZ/
        └── source_name.json
```

Every response is timestamped in UTC and stored in a new run directory. Raw data is excluded from Git and exists for debugging, audit, and reproducibility.

## Official endpoint contracts and positional signals

`FPLClient` is the fail-closed boundary for `bootstrap-static`. It validates the required
top-level collections and the core player fields used by ETL/ranking before caching or archiving
the response. Contract tests intentionally reject a player payload with a missing core field so
an upstream rename cannot become a default zero in the score. Positional fields such as xGC,
penalties, cards, and defensive contribution are optional: when FPL does not supply one, the
nullable database value and UI label remain **Not supplied**.

Current-season recommendations use official FPL JSON. Backtesting uses validated completed-season
CSV snapshots and is never mixed into the current-season refresh. `candidate-v1.3-positional` is
evaluated per position and remains experimental; only `production-v1.1` is the live model until
the documented coverage/regression gates and activation approval pass.

## Official refresh flow

```text
Data Status: Refresh official FPL data
    ↓
FPLIngestionService clears response cache for this manual run
    ↓
FPLClient fetches bootstrap-static and fixtures
    ↓
RawDataStore persists each validated JSON response
    ↓
Transform layer validates and creates domain records
    ↓
One SQLite transaction upserts teams → players → fixtures → current stats → gameweek snapshots
    ↓
RefreshStatusStore records success or retains the previous successful status on failure
```

## Fixture analytics flow

```text
Fixtures page
    ↓
FixtureAnalyticsService reads teams, players, and unstarted fixtures from SQLite
    ↓
Official FDR (1–5) is converted into fixture ease (100–10)
    ↓
Nearest fixtures receive the largest horizon weight (1, 3, 5, or 8)
    ↓
Live team fixture matrix and per-team fixture score
```

## On-demand player detail flow

```text
Player Detail: Load official gameweek history
    ↓
PlayerAnalyticsService checks player_history_sync for the current season/GW
    ↓ cache miss only
FPLClient fetches element-summary/{player_id} with four-hour memory cache
    ↓
Transform layer validates history and idempotently upserts player_gameweek_history
    ↓
Feature engine calculates rolling 3/5/10 form, PPM, xG/xA/xGI per 90, value,
minutes security, availability penalty, and minimum-minutes confidence adjustment
    ↓
Player Detail renders raw metrics, adjusted metrics, source period, and history rows
```

## Recommendation Engine V1 flow

```text
Official players + latest current stats + horizon fixture scores
    ↓
Raw signals: form, expected output, minutes, history, value, bonus, ICT, saves, ownership
    ↓
Tie-aware percentile normalization within GK / DEF / MID / FWD
    ↓
Minimum-minutes confidence shrinkage + official availability penalty
    ↓
Position weights loaded from scoring.yaml
    ↓
Persist every component in recommendation_scores with model/GW/horizon/time
    ↓
Dashboard, Players, Recommendations, and Compare consume one cached result set
```

## Historical enrichment flow

```text
Data Status: Import historical seasons
    ↓
HistoricalDataClient downloads configured completed-season cleaned_players.csv files
    ↓
Required columns, row types, season labels, positions, prices, and duplicate identities are validated
    ↓
Source CSV is archived locally and player-season rows are idempotently upserted
    ↓
Normalized exact/fuzzy identity matching → MATCHED / REVIEW / UNMATCHED
    ↓ MATCHED with at least 450 minutes only
Recency-weighted points/90 + cross-season consistency + evidence shrinkage toward neutral 50
    ↓
Persist player_historical_scores; Recommendation Engine v1.1 uses it at 5–10% weight
```

## Backtesting and calibration flow

```text
Backtesting: Import & rerun 2025-26 backtests
    ↓
HistoricalDataClient downloads merged gameweeks, fixtures, and teams CSVs
    ↓
Required columns, row types, positions, and player-fixture identities are validated
    ↓ exact duplicate source rows only
Deduplicate safely; reject conflicting duplicate identities
    ↓
Persist backtest_player_gameweeks and backtest_fixtures idempotently
    ↓ for every cutoff GW N and horizon 1 / 3 / 5
Build form, minutes, expected output, historical, value, and fixture features using data through N only
    ↓
Freeze production-v1.1 and candidate-v1.3-positional scores/ranks
    ↓
Join actual points from GW N+1 through N+h
    ↓
Persist backtest_predictions and aggregate MAE, Spearman, Top-10 hit rate, and Top-10 actual points
    ↓
Backtesting UI compares versions and exposes one exact cutoff for audit
```

Fixture ease in the backtest is reconstructed from opponent league points earned only through each cutoff. It never reads the final-season difficulty snapshot. Historical cross-season stability uses seasons strictly before the backtest season. See `docs/BACKTESTING.md` for metric definitions and known limitations.

## Operations, refresh, and rollback

Data Status exposes schema version, source freshness, endpoint-contract readiness, and the
positional candidate gate. After a Railway deployment that includes a migration, allow startup
to finish, then run **Refresh official FPL data**. Run the historical import/backtest again when
the candidate report needs new coverage. If the official endpoint fails validation, the refresh
is rejected and the last known-good snapshot remains available. Model rollback and the
forward-only database policy are recorded in `docs/MODEL_CHANGELOG.md`.

## Decision-support flow

```text
Decision Tools: selected horizon, player out, and bank budget
    ↓
RecommendationEngineService reads cached official rankings
FixtureAnalyticsService reads listed official fixtures
    ↓
Transfer Finder: same position + available + affordable + higher score
Captain Shortlist: Safe / Balanced / Differential role weighting
    ↓
Confidence-adjusted PPM × fixture count × fixture multiplier
    ↓
Render projected-points proxy, projected gain, confidence, and visible trade-offs
```

Decision tools do not write a new model score or claim guaranteed FPL points. Advanced Planner may import a public squad in memory and validate wildcard budget, position quotas, and club limits, but neither service executes transfers or models free transfers, chips, selling-price history, price changes, or late team news. See `docs/DECISION_TOOLS.md` and `docs/ADVANCED_PLANNER.md` for the exact rules.
