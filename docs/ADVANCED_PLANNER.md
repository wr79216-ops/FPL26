# Phase 11 Advanced Planner and Enrichment Governance

## Outcome

Phase 11 adds advanced official-data planning without silently activating an external data source. The application now provides:

- a separate, fail-closed external-provider boundary;
- an internal custom fixture-difficulty comparison;
- public official FPL squad import for the active gameweek;
- a constraint-aware 15-player wildcard draft and same-position change list.

Official FPL remains authoritative for player IDs, positions, clubs, status, prices, ownership, points, fixtures, and FPL squad composition.

## External provider policy

Providers are declared in `config/external_providers.yaml`. Loading the registry performs no network request. A provider can only report `Ready` when all of the following are true:

1. it is explicitly enabled;
2. its access mode is `licensed_api` or `user_supplied_export`;
3. Terms/licence review is recorded;
4. an adapter is implemented;
5. enrichment remains keyed to validated official FPL player IDs.

FotMob is currently `Disabled`. The application does not scrape FotMob or use its data. Its possible capabilities—lineups, availability context, match events, and rotation context—remain documented future options pending an allowed access route and identity-validation workflow.

## Custom fixture difficulty

Every upcoming fixture retains the official 1–5 FDR. The internal comparison also calculates a continuous 1–5 difficulty:

```text
custom FDR = 60% official FDR
           + 40% opponent-strength difficulty
           + venue adjustment
```

Opponent strength is scaled across the current official team-strength range. Home receives `-0.25` difficulty and away receives `+0.25`, with the result capped to 1–5. The continuous value is converted to a 0–100 ease score using interpolation between the official FDR score anchors and the same 1/3/5/8-GW recency weights.

Recommendation Engine v1.1 still uses official FDR. Custom difficulty is displayed as a comparison signal until it has been backtested across multiple seasons.

## Public squad import

The user supplies a numeric public FPL manager ID. The application reads official `entry/{id}/` and `entry/{id}/event/{gw}/picks/` responses for the currently cached gameweek. It validates all 15 player IDs against the current official ranking cache.

Imported manager and picks data:

- requires no login, password, or session cookie;
- is cached briefly in memory;
- is not written to the raw JSON archive or SQLite;
- is kept only in the active Streamlit session.

After a successful import, the squad is rendered in a formation-first pitch layout. It groups the official active picks into GK/DEF/MID/FWD rows, derives the visible formation (for example `3-4-3`), separates the bench, and displays official captain/vice-captain flags plus gameweek points/rank when the response provides them. Each player card also displays the official `event_points` value for the imported gameweek. Player cards use the current official club name and a local colour accent only; no club badge or third-party kit image is fetched.

## Wildcard optimizer

The planner searches a broad set of high-scoring and low-cost candidates with a deterministic beam-search heuristic. Every returned draft enforces:

- exactly 2 GK, 5 DEF, 5 MID, and 3 FWD;
- no more than three players from one club;
- available official player status;
- total cached current price within the selected budget;
- a legal starting XI formation with 1 GK, 3–5 DEF, 2–5 MID, and 1–3 FWD.

Captain and vice-captain are selected from the starting XI using recommendation, expected-output, and minutes signals. If a squad was imported, outgoing and incoming players are paired by position for an auditable wildcard comparison.

The result is a heuristic decision aid, not proof of a globally unique mathematical optimum. It does not execute transfers or model purchase-price selling rules, transfer hits, free transfers, chips, price changes, or late team news. The final draft must be checked in official FPL before use.
