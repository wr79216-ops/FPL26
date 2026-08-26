# FPL Signal — Positional Recommendation Signals Plan

## Purpose

Improve the **Recommendations** page so each position is ranked with a clearer, more football-relevant evidence set. Users should be able to see both:

1. the weighted signals that affect the FPL Signal ranking; and
2. the supporting official FPL statistics that explain a player's current-season profile.

This plan deliberately does **not** treat every visible statistic as a ranking input. Several FPL statistics measure nearly the same thing (for example xG, xGI, goals, BPS, and bonus). Weighting all of them at once would double-count one type of performance and make the model less reliable.

The model remains a 0–100 position-relative ranking, not a predicted points total, probability, or guarantee of returns.

## Progress

| Phase | Status | Outcome |
|---|---|---|
| A — Field audit and metric dictionary | Complete (26 Aug 2026) | Active official FPL endpoint audit, schema scope, and source-controlled catalogue are recorded in [`POSITIONAL_RECOMMENDATION_SIGNALS_FIELD_AUDIT.md`](POSITIONAL_RECOMMENDATION_SIGNALS_FIELD_AUDIT.md). |
| B — Persist verified official statistics | Complete (26 Aug 2026) | Verified current and per-fixture fields are persisted with nullable migration-safe columns; tests cover populated and unavailable values. |
| C — Build transparent positional features | Not started | Awaiting Phase B. |
| D — Candidate model and score breakdown UI | Not started | Awaiting Phase C. |
| E — Backtest, calibration, and release gate | Not started | Awaiting candidate model. |
| F — Documentation and operations | Not started | Awaiting production decision. |

## Current baseline

The production model is `v1.1`. It already uses position-relative fixture, minutes, form, historical stability, value, and selected performance signals:

- GK: saves, bonus, fixture, minutes, form, history, value;
- DEF: attacking output, fixture, minutes, form, history, bonus, value;
- MID: xGI, fixture, form, minutes, points per match, history, value, ICT;
- FWD: xG, xGI, fixture, minutes, form, points per match, history, value.

The current official bootstrap refresh stores totals such as goals, assists, clean sheets, saves, bonus, BPS, influence, creativity, threat, ICT, xG, xA, xGI, minutes, price, ownership, and transfer activity. Per-player history is already available on demand from the official FPL `element-summary/{id}` endpoint.

Several requested statistics are not currently persisted by the app. Their exact availability and definitions must be audited against the active official FPL payload before they can be called production data.

## Product design

### Two layers of explanation

The Recommendations page will use two distinct layers.

| Layer | Purpose | Examples |
|---|---|---|
| **Weighted ranking signals** | Inputs which contribute to the 0–100 score, with documented weights. | xG / 90, xGC / 90, saves / 90, clean-sheet rate, defensive contribution / 90, discipline risk, minutes, fixture ease. |
| **Official season evidence** | Raw or per-90 context shown to the user. It does not automatically change the rank. | Goals, assists, BPS, bonus, goal conceded, yellow/red cards, penalties missed/saved, influence, creativity, threat, ICT. |

The interface must label the first layer as **“Used in ranking”** and the second as **“Official context”**. A tooltip on every metric must state whether it affects the score and how the value is calculated.

### Position-specific score breakdown

When a user selects a position, the score table and expandable player evidence should use the following profile. “Primary” means a candidate weighted signal; “context” means visible evidence unless Phase D approves it for weighting.

| Position | Primary ranking candidates | Official context shown |
|---|---|---|
| GK | xGC / 90 (lower is better), saves / 90, clean-sheet rate, minutes, fixture ease, bonus | Goals conceded, penalties saved, BPS, bonus, form, ICT, yellow/red cards |
| DEF | xGC / 90 (lower is better), clean-sheet rate, xGI / 90, defensive contribution / 90, minutes, fixture ease | Goals conceded, goals/assists, BPS, bonus, yellow/red cards, influence/creativity/threat/ICT |
| MID | xGI / 90, goals + assists involvement / 90, clean-sheet rate where meaningful, minutes, fixture ease, bonus/BPS profile | Goals, assists, BPS, bonus, yellow/red cards, influence/creativity/threat/ICT |
| FWD | xG / 90, xGI / 90, goal conversion rate with shrinkage, assists / 90, minutes, fixture ease, BPS/bonus profile | Goals, assists, BPS, bonus, yellow/red cards, influence/creativity/threat/ICT |

Definitions:

- **xGC / 90** = official expected goals conceded ÷ minutes × 90, lower is better. It is primarily relevant to GK/DEF.
- **Clean-sheet rate** = clean sheets ÷ eligible appearances or starts. The eligibility definition must be displayed.
- **Defensive contribution / 90** = official FPL `defensive_contribution` if verified in the active payload, divided by minutes × 90. It must not be inferred from an unrelated provider.
- **Goal conversion rate** = goals ÷ xG. It must be shrinkage-adjusted toward a neutral prior and never shown as a reliable finishing signal at very low xG/minutes.
- **Discipline risk** = a lower-is-better signal derived from yellow/red-card totals or rates. It is a negative adjustment only; a suspension/availability status continues to use the existing availability penalty.
- **Bonus/BPS profile** = bonus points and BPS are related. The initial weighted model may use only one combined component; both remain visible as separate official context.

## Data contract and source policy

### Source of truth

1. **Official FPL `bootstrap-static`** is the source for current-season player totals and availability.
2. **Official FPL `element-summary/{player_id}`** is the source for per-fixture history after the user requests a player detail or a controlled batch sync.
3. **Official FPL `event/{gameweek}/live`** may be used for completed gameweek validation only.
4. No scraping, inferred card data, or unlicensed third-party stat feeds will be used to fill missing official fields.

### Field audit before schema changes

Phase A must record the exact current-payload field name, data type, unit, and missing-value behavior for:

- `expected_goals_conceded`, `goals_conceded`, `clean_sheets`, `saves`;
- `penalties_saved`, `penalties_missed`;
- `yellow_cards`, `red_cards`;
- `defensive_contribution` and any related official defensive fields;
- `goals_scored`, `assists`, `bonus`, `bps`;
- `influence`, `creativity`, `threat`, `ict_index`;
- `expected_goals`, `expected_assists`, `expected_goal_involvements`, `minutes`, `starts`.

If a field is absent from either active FPL endpoint, the application will show **“Not supplied by official FPL data”** rather than a guessed zero or a fabricated value. `0` is valid only when FPL explicitly returns zero.

### Persistence and freshness

- Current-season totals are updated only during the existing official FPL refresh.
- Per-fixture history remains on-demand initially, with cache/sync metadata showing the gameweek and timestamp used.
- New current-stat columns require a forward SQLite migration and default only for old snapshots; the interface must state that a refresh is needed to populate the new field.
- New per-fixture columns require forward migrations and idempotent upserts keyed by player, season, gameweek, and fixture.

## Model rules

### Normalisation and small samples

- Every weighted metric is normalized within the same FPL position before combining scores.
- Rate signals use `per 90` where that is meaningful; raw totals remain explanatory context.
- Small-sample metrics shrink to neutral using the existing minutes-confidence method. Conversion rate requires a stronger shrinkage rule because xG can be near zero.
- Lower-is-better metrics (xGC, goals conceded, discipline risk) are inverted before percentile ranking.
- Missing data is never silently treated as strong performance. A missing weighted feature receives a documented neutral fallback only if that fallback is approved in configuration.

### Correlation safeguards

The first release must not weight all of the following together at full strength:

- xG, goals, xGI, and assists;
- BPS and bonus;
- clean sheets, goals conceded, and xGC;
- influence/creativity/threat and ICT (ICT is a composite of the other three).

One representative metric should power each scoring concept; the others stay visible in official context. This keeps score contributions understandable and makes backtesting meaningful.

### Config-driven weights

New weights live in `config/scoring.yaml`, not in UI code. Each position's weights must sum to `1.0` and have a user-facing label/tooltip. The model version must change only after the candidate passes validation, for example from `v1.1` to `v1.2`.

## Implementation phases

### Phase A — Field audit and metric dictionary

1. Capture a representative active `bootstrap-static` response and multiple `element-summary` responses through the existing FPL client.
2. Produce a checked field matrix: endpoint, field, type, unit, position relevance, whether it is a raw total/rate, and whether FPL supplies it consistently.
3. Add a metric dictionary in code/config with short tooltip copy and a `used_in_ranking` flag.
4. Decide the Phase B schema only from verified fields; mark unavailable requested fields as deferred.

**Exit criteria:** field contract is documented and test fixtures represent both a populated field and a missing/not-supplied field.

### Phase B — Persist verified official statistics

1. Extend `CurrentPlayerStatsRecord`, `CurrentPlayerStatsModel`, transform, repository upsert, and SQLite migration for verified current-season totals.
2. Extend `GameweekHistoryRecord` and `GameweekHistoryModel` only for fields actually supplied per fixture by `element-summary`.
3. Keep existing refresh atomic and preserve last known good data when an FPL request fails.
4. Add transform, migration, idempotent-upsert, and missing-value tests.

**Exit criteria:** an official refresh persists the verified fields, previous databases migrate forward safely, and the UI can distinguish zero from unavailable.

### Phase C — Build transparent positional features

1. Create a dedicated feature builder for position-aware metrics and rates.
2. Calculate xGC / 90, saves / 90, clean-sheet rate, defensive contribution / 90, attacking rates, discipline risk, and shrinkage-adjusted conversion rate where source data permits.
3. Return both raw values and normalized score values with explicit direction (`higher_is_better`).
4. Add edge-case tests for zero minutes, zero xG, missing fields, goalkeeper appearances, and red-card/suspension status.

**Exit criteria:** all features are deterministic, bounded, and explainable without changing the production rank.

### Phase D — Candidate model and score breakdown UI

1. Add candidate weights to a separate experimental config or candidate model version.
2. Update `RecommendationRow` and score-breakdown data so the UI can show per-metric contribution, not only grouped component scores.
3. In Recommendations, display:
   - a compact **Used in ranking** table tailored to GK/DEF/MID/FWD;
   - an expandable **Official season evidence** table;
   - hover tooltips that explain formula, direction, source, freshness, and whether the metric affects ranking.
4. Keep score breakdown readable on mobile by showing primary columns first and moving supporting evidence into an expander.

**Exit criteria:** selecting each position shows the agreed profile, every visible number has a definition, and score changes can be traced to weighted contributions.

### Phase E — Backtest, calibration, and release gate

1. Backtest the candidate against a completed season with leakage-safe gameweek cutoffs.
2. Compare it against production `v1.1` using rank correlation, MAE, top-10 hit rate, and top-10 points.
3. Evaluate each position separately; do not promote a change which improves one group while materially degrading another without an explicit decision.
4. Check metric coverage, missingness, and sensitivity to early-season small samples.
5. Promote only if the candidate meets documented quantitative gates and no data-quality warning remains.

**Exit criteria:** candidate results, limitations, and promotion decision are visible in Backtesting/Data Status; otherwise the candidate remains experimental and production stays on `v1.1`.

### Phase F — Documentation and operations

1. Update `docs/TECHSTACK_AND_SCOPE.md`, `docs/ARCHITECTURE.md`, and in-app Data Status with the verified source and limitations.
2. Add a refresh note after deployment whenever a schema migration adds official fields.
3. Record model-version changelog and rollback path.
4. Monitor official endpoint shape changes with validation tests so a removed field cannot silently distort rankings.

## Non-goals for the first release

- Predicting exact future points, goals, clean sheets, cards, or penalty events.
- Claiming a player will take the next penalty/set piece.
- Inventing defensive-contribution data if the current official FPL payload does not expose it.
- Replacing the official FPL availability/status logic.
- Automatically changing users' squads or executing FPL transfers.

## Acceptance criteria

- A user selecting GK, DEF, MID, or FWD sees a position-specific score explanation aligned with this document.
- Every metric has a short hover definition and an explicit “used in ranking” status.
- Official source, snapshot freshness, and unavailable fields are communicated clearly.
- Ranking metrics are config-driven, normalized within position, and tested for missing/small-sample behavior.
- Production model changes only after leakage-safe backtesting and an explicit versioned release decision.
