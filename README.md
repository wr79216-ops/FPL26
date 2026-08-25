# FPL Signal

A local-first Fantasy Premier League decision-support application combining official FPL data, fixture analysis, transparent recommendation scoring, historical enrichment, and time-safe backtesting.

## Project status

Phase 11 is complete for the official-data MVP. In addition to transparent transfer/captain support, the app now provides custom fixture-difficulty comparison, public official squad import, and a constraint-aware wildcard planner. External providers remain fail-closed; FotMob is documented but disabled until an allowed access route and identity validation are available. The production model remains v1.1 until a candidate is validated across more than one season.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Then open the local Streamlit URL shown in the terminal.

## Tests

```bash
PYTHONPATH=. pytest
```

## Structure

```text
app.py                 Streamlit entry point
config/                Application and scoring configuration
data/                  Local SQLite database and raw snapshots (not committed)
src/data/               Raw persistence, refresh status, and legacy sample-data fixtures
src/api/                Sole HTTP gateway and response cache
src/database/           SQLAlchemy schema, sessions, and repositories
src/domain/             Stable records shared between layers
src/services/           Application orchestration boundary
src/features/           Pure, unit-tested analytical calculations
src/providers/          Policy-gated external enrichment contracts
src/ui/                 Theme, reusable components, and page renderers
src/utils/              Shared runtime utilities
tests/                 Automated tests
logs/                  Local runtime logs (not committed)
```

## Official application data

All application pages now read official FPL data persisted in SQLite. The deterministic sample provider remains only as a frontend-test fixture and is no longer loaded by `app.py`.

## Refresh official FPL data

Open **Data Status** in the local app and select **Refresh official FPL data**. The application fetches the official public FPL endpoints, writes raw JSON snapshots under `data/raw/`, validates and loads teams, players, fixtures, current player stats, and idempotent gameweek snapshots into SQLite, then records the most recent successful refresh. If a later refresh fails, the app retains and reports the last successful dataset.

## Player history and features

Open **Player Detail**, choose an official FPL player, and select **Load official gameweek history**. The first request for a player/gameweek stores the validated `element-summary` history; repeated loads use the persistent cache. Features display their source period, raw value, confidence-adjusted value, sample minutes, and availability effect. The current minimum sample is 270 minutes and can be changed in `config/scoring.yaml`.

## Recommendation Engine V1

The engine calculates all players for fixture horizons 1, 3, 5, and 8. Raw form, fixture ease, minutes, expected output, historical stability, value, bonus, ICT, saves, and ownership signals are normalized as percentiles within each position where appropriate. Small-sample performance signals are shrunk toward neutral according to confidence, and the official availability status applies a final penalty. The UI shows the strongest weighted reasons for every ranking rather than only the final number.

## Historical data and identity matching

Open **Data Status** and select **Import historical seasons** to download the configured completed-season CSVs, validate every row, archive the source files under `data/historical/`, and perform an idempotent import. Identity outcomes are `MATCHED`, `REVIEW`, or `UNMATCHED`; only `MATCHED` rows with at least 450 minutes contribute to scoring. Ambiguous candidates remain visible in the Data Status review queue and are excluded from the model.

The exact source, validation contract, matching thresholds, and stability formula are documented in [docs/HISTORICAL_DATA.md](docs/HISTORICAL_DATA.md). Unique identity candidates above 90% confidence are automatically marked `MATCHED`; the verified mappings in `config/historical_identity_overrides.yaml` are also treated as `MATCHED`; lower-confidence or ambiguous candidates remain in `REVIEW`.

## Backtesting and calibration

Open **Backtesting** to compare production v1.1 with candidate v1.2, choose a 1/3/5-GW evaluation horizon, and inspect persisted rankings at an exact gameweek cutoff. Select **Import & rerun 2025-26 backtests** to download the validated gameweek, fixture, and team CSVs, archive them locally, and rebuild all six evaluations. Features are frozen at GW N before outcomes from GW N+1 through N+h are joined.

The metric definitions, leakage controls, quality checks, exact results, and conservative model decision are documented in [docs/BACKTESTING.md](docs/BACKTESTING.md).

## Advanced planner and external enrichment

The app header includes a live countdown to the next official FPL deadline, using the latest official bootstrap snapshot and the visitor's local timezone. Open **Advanced Planner** to compare official and internal fixture ease, optionally import a public FPL squad by manager ID, and build a legal 15-player wildcard draft within a selected budget. An imported squad appears in a formation-first pitch layout with the official Starting XI, bench, captain/vice-captain, team gameweek points/rank, and the latest official gameweek points on each player card; no third-party kit imagery is used. Imported public squad data remains session-only and is not archived. The optimizer enforces position quotas and the maximum-three-per-club rule, then proposes same-position changes when a squad is available.

External providers are configured separately and fail closed. FotMob is currently disabled; no scraping or automatic enrichment is performed. The formula, provider policy, privacy behavior, optimizer constraints, and limitations are documented in [docs/ADVANCED_PLANNER.md](docs/ADVANCED_PLANNER.md).

## Decision tools

Open **Decision Tools** to compare an outgoing player with affordable, available same-position upgrades and review projected gain for the selected horizon. The Captain Shortlist provides distinct Safe, Balanced, and Differential profiles whenever the current data permits. Projected points are deliberately labelled as a signal-adjusted proxy, not a guaranteed forecast: confidence-adjusted PPM × official fixture count × fixture multiplier. This page does not import a squad; Advanced Planner separately validates wildcard budget, positions, and club limits. Free transfers, chips, selling-price history, price changes, and late team news are not modelled.

The full decision rules and limitations are documented in [docs/DECISION_TOOLS.md](docs/DECISION_TOOLS.md).

## Using the MVP

1. Open **Data Status** and refresh the official FPL cache.
2. Use **Player Finder** to search a player/team or filter a position (for example MID), budget, ownership, minutes, and horizon. Enable **Differentials only** for ownership below 10%.
3. Open **Recommendations** for the transparent component-score breakdown, or **Player Detail** to load cached official match history and see points, minutes, and xGI trends.
4. Use **Compare** with one shared fixture horizon to inspect the trade-off between two players.
5. Open **Decision Tools** to evaluate transfer and captain options with transparent trade-offs.
6. Open **Backtesting** to inspect model performance and a stored player-level prediction audit.
7. Open **Advanced Planner** for custom fixture comparison, optional public squad import, and a wildcard draft.

Every headline/column with an info tooltip has a short definition. **Data Status** shows whether the cache is fresh and which official data rows are missing; player history is deliberately fetched on demand and is therefore reported separately.

## Architecture

Layer responsibilities, schema versioning, and raw-data conventions are documented in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Tech stack, scope, and limitations

For a user-facing explanation of the technology stack, data sources, model meaning, feature coverage, history scope, privacy behavior, and known limitations, see [docs/TECHSTACK_AND_SCOPE.md](docs/TECHSTACK_AND_SCOPE.md).

## Data-source policy

Official FPL endpoints will be the source of truth for FPL-specific fields such as price, ownership, points, and fixtures. Any third-party source, including FotMob, is a future enrichment layer only and must be used through an allowed access method.
