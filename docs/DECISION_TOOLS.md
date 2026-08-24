# Decision Tools Contract

## Purpose

Phase 10 turns the persisted official FPL ranking into practical decision support. It provides a Transfer Finder and Captain Shortlist, but never presents either result as an automatic instruction.

## Transfer Finder

The user chooses a player to transfer out, an available bank budget, and a 1/3/5/8-gameweek horizon. A replacement is eligible only when it:

- has the same FPL position;
- is marked `Available` by the official FPL cache;
- costs no more than the outgoing player's price plus the entered bank; and
- has a higher recommendation score than the outgoing player.

Eligible replacements are ordered by projected gain, then recommendation score and expected-output score. Every option exposes its price, recommendation score, projected-points proxy, trade-off, and model reasons.

## Captain Shortlist

The shortlist normally uses available outfield players. It falls back to all available players only if no outfield player exists.

- **Safe:** prioritises minutes security, final recommendation score, and fixtures.
- **Balanced:** balances final recommendation score, expected output, and fixtures.
- **Differential:** prioritises expected output and fixtures among players below 10% ownership; it falls back to the standard pool when no low-owned player is available.

The service selects distinct players for the three roles when enough candidates exist.

## Projected-points proxy

The app deliberately does not present a calibrated FPL-points forecast. Instead, it uses an inspectable proxy:

```text
confidence-adjusted PPM
× official fixture count in the selected horizon
× (0.60 + fixture score / 125)
```

Confidence shrinks a player's current points per match toward the average PPM of their FPL position. A fixture score of 50 is neutral and produces a multiplier of 1.00. A team with no listed official fixture in the horizon correctly receives a zero proxy.

**Projected gain** is simply replacement proxy minus outgoing-player proxy. It is useful for comparing two alternatives under the same assumptions, not for guaranteeing points.

## Decision confidence and trade-offs

Decision confidence is a 0–100 signal summary, not a probability. It blends final recommendation score (45%), minutes security (30%), fixture ease (15%), and current `Available` status (10%).

Every transfer and captain option also lists:

- next fixture and fixture score;
- xGI per 90;
- minutes-security score;
- current FPL price;
- ownership; and
- the two strongest configured model reasons.

## Current limitations

The **Decision Tools** page itself does not import a personal FPL squad. **Advanced Planner** can optionally load one public official squad and validate a wildcard draft's total budget, position quotas, and club limit, but neither page models free transfers, transfer hits, chips, purchase-price selling rules, price changes, or final deadline/news updates. Users must confirm these constraints and use their own judgement before making a move.
