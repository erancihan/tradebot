# Canaries — contestants that exist to test the *test*

These are not trading ideas and none of them is promotable. They are
instruments for deciding whether a scenario can measure skill at all, which is
the question both prior gauntlets got wrong for months.

A scenario is admitted to the library only if:

    oracle_topk  >>  {real candidates}  >  random_topk  >=  always_haven

Each canary fails the bracket in a different, diagnostic way:

- **`always_haven`** holds the defensive name and nothing else. If it *wins*
  anywhere, hiding is a free lunch in that scenario and the scenario is
  flattery — a defensive candidate would score well without timing anything.
- **`random_topk`** picks K names at random (seeded, so it is reproducible and
  prefix-stable). It must land mid-pack. If it beats a real momentum book on
  the mean, the scenario contains no learnable cross-sectional signal and any
  ranking over it is noise.
- **`oracle_topk`** cheats: it selects on *future* returns. It must win by a
  wide margin. If the oracle cannot win, there is no signal in the scenario to
  find and every verdict from it is meaningless.

The bracket is candidate-agnostic by construction. It asks "can this test
measure skill", never "did my favourite win" — which is why it cannot be used
to tune a scenario toward a result.

**These are deliberately excluded from ordinary runs.** `arena`'s loader
expands a directory with a non-recursive `glob("*.py")`, so `--algos ./algos`
does not pick them up and the baked-in field count of 12 is unaffected. Point
at them explicitly:

    tradebot arena run --algos ./algos ./algos/canaries --scenario scenarios/xs_bull_dispersion.yaml

`oracle_topk` uses look-ahead on purpose. It must never be promoted, never be
used as a baseline, and never appear in a season.
