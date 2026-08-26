# Positional Recommendation Signals — Phase A Field Audit

**Audited:** 26 August 2026  
**Source:** Official Fantasy Premier League API  
**Endpoints sampled:**

- `https://fantasy.premierleague.com/api/bootstrap-static/`
- `https://fantasy.premierleague.com/api/element-summary/1/`

This audit records endpoint shape and field types observed from the active official FPL API. It is a data contract for the next implementation phase, not a statement that every field already affects the FPL Signal ranking.

## Result

All requested core statistics are supplied by the official FPL payload in both the current-season player response and the per-fixture player-history response:

- defensive contribution;
- xG, xA, xGI, and xGC;
- clean sheets and goals conceded;
- penalties saved and missed;
- yellow and red cards;
- saves, BPS, bonus;
- influence, creativity, threat, and ICT;
- goals, assists, minutes, and starts.

The active `bootstrap-static` player object also exposes the following ready-made current-season rates: `expected_goals_conceded_per_90`, `goals_conceded_per_90`, `clean_sheets_per_90`, `saves_per_90`, and `defensive_contribution_per_90`. FPL Signal will calculate its own rates from the persisted totals where practical, so the model has one consistent calculation path across current and per-fixture data.

## Observed types

The sampled payload used numeric JSON values for counts and string-encoded decimal values for expected-stat and ICT-family values.

| Field family | `bootstrap-static` type | `element-summary` history type | Handling |
|---|---:|---:|---|
| Minutes, starts, goals, assists, clean sheets, goals conceded, saves, BPS, bonus, cards, penalties, defensive contribution | number | number | Parse as integer. |
| xG, xA, xGI, xGC | string decimal | string decimal | Parse using the existing strict numeric transformer. |
| Influence, creativity, threat, ICT | string decimal | string decimal | Parse using the existing strict numeric transformer. |
| Current `*_per_90` rates | number | not supplied as per-90 fields | Do not persist as the canonical source; calculate consistently from totals and minutes. |

`0` in either endpoint is an official zero. Missing keys must be represented as unavailable rather than silently converted to zero.

## Verified field matrix

| User-facing metric | Official field(s) | Endpoint coverage | Position relevance | Proposed Phase B persistence | Initial ranking status |
|---|---|---|---|---|---|
| xGC | `expected_goals_conceded` | Current + per fixture | GK, DEF | Current + history | Candidate only |
| Goals conceded | `goals_conceded` | Current + per fixture | GK, DEF | Current + history | Context; candidate only after validation |
| Clean sheets | `clean_sheets` | Current + per fixture | GK, DEF; context for MID/FWD | Current + history | Candidate only |
| Saves | `saves` | Current + per fixture | GK | Already current + history | Production GK input |
| Penalties saved | `penalties_saved` | Current + per fixture | GK | Current + history | Context initially |
| Penalties missed | `penalties_missed` | Current + per fixture | MID, FWD | Current + history | Context initially |
| Defensive contribution | `defensive_contribution` | Current + per fixture | DEF, GK context | Current + history | Candidate only |
| Goals | `goals_scored` | Current + per fixture | MID, FWD; DEF context | Already current + history | Context; avoid duplicating xG/xGI |
| Assists | `assists` | Current + per fixture | MID, FWD; DEF context | Already current + history | Context; avoid duplicating xGI |
| xG | `expected_goals` | Current + per fixture | FWD, MID | Already current + history | Production FWD input |
| xA | `expected_assists` | Current + per fixture | MID, DEF | Already current + history | Context initially |
| xGI | `expected_goal_involvements` | Current + per fixture | MID, FWD, DEF | Already current + history | Production MID/FWD input |
| Goal conversion | derived: `goals_scored / expected_goals` | Derived | FWD, MID | No raw column; feature only | Candidate only with shrinkage |
| Yellow cards | `yellow_cards` | Current + per fixture | All | Current + history | Context; discipline candidate |
| Red cards | `red_cards` | Current + per fixture | All | Current + history | Context; availability remains authoritative |
| BPS | `bps` | Current + per fixture | All | Already current + history | Context; correlated with bonus |
| Bonus | `bonus` | Current + per fixture | All | Already current + history | Production GK/DEF input; context elsewhere |
| Influence | `influence` | Current + per fixture | All | Already current + history | Context; part of ICT family |
| Creativity | `creativity` | Current + per fixture | All | Already current + history | Context; part of ICT family |
| Threat | `threat` | Current + per fixture | All | Already current + history | Context; part of ICT family |
| ICT index | `ict_index` | Current + per fixture | All | Already current + history | Production MID input; composite context elsewhere |
| Minutes / starts | `minutes`, `starts` | Current + per fixture | All | Already current + history | Production minutes input |

## Schema decision for Phase B

Add these verified raw totals to both current-stat and per-fixture-history storage:

```text
goals_conceded
penalties_saved
penalties_missed
yellow_cards
red_cards
defensive_contribution
```

The following are already persisted and require no schema change: minutes, starts, goals, assists, clean sheets, saves, BPS, bonus, influence, creativity, threat, ICT, xG, xA, and xGI. Per-fixture xGC is already stored as `xgc`.

**Phase C prerequisite correction (26 Aug 2026):** the current-season snapshot did not yet persist `expected_goals_conceded`, despite the official field being audited. Schema v9 adds it as a nullable current-stat field. This gives xGC / 90 a current-season source without changing historical `xgc` handling.

No derived rate is stored as a source-of-truth column. Phase C will calculate rates from persisted totals and minutes. This prevents a current-season rate from using a definition different from the player-history rate.

## Missingness and safety rules

1. A transformer must distinguish a missing optional FPL field from a present numeric zero.
2. The first schema release may use a nullable column for an optional field, or a separate availability marker. It must not backfill historical unknowns with `0`.
3. Existing database rows pre-migration must display as **Not available until refreshed**, not as a real zero.
4. FPL status (`d`, `i`, `s`, and similar) remains the only production availability authority. Red cards may contribute to future discipline context but must not replace availability status.
5. Goal conversion remains withheld from production scoring until it passes its own low-xG and low-minutes tests.

## Phase A deliverables completed

- Verified active official endpoint field coverage and observed JSON types.
- Created [`config/recommendation_metrics.yaml`](../config/recommendation_metrics.yaml) as the source-controlled metric dictionary.
- Confirmed the Phase B schema scope above.
- Preserved production model `v1.1`: no recommendation weights or UI ranking behaviour changed in this phase.
