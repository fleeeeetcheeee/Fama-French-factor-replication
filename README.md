# Fama-French Factor Replication

Building SMB, HML, UMD, RMW and CMA from individual firm data — and measuring, precisely, how
close free data can get to Kenneth French's published series and why it falls short.

> **Status: in progress — 2 of 6 steps.** The reference layer is built and verified; bottom-up
> construction has not started. 107 tests, 96% coverage. This README will be rewritten around the
> full results when there are any. Reasoning is logged in [`LOG.md`](LOG.md).

## The result so far

**A Fama-French replication built on a large-cap universe cannot exceed 0.92 correlation with
published HML — and this is a property of the data, not of the implementation.**

Measured on French's *own* published portfolios, so no implementation can beat it. HML decomposes
into the average of two spreads, one per size half:

```
HML = ½[(SmallValue − SmallGrowth) + (BigValue − BigGrowth)]
```

An HML built without small caps is exactly the second term. Its correlation with the real factor
then follows in closed form from the two spread volatilities and their correlation ρ:

```
corr(B, ½(S+B)) = (σ_B + ρσ_S) / √(σ_S² + 2ρσ_Sσ_B + σ_B²)
```

| Truncation | Window | n | corr | analytic | TE (bps/mo) | ρ(small,big) |
|---|---|---|---|---|---|---|
| Big-only | full history | 1,200 | 0.9208 | 0.9208 | 160.5 | 0.664 |
| Big-only | spec 1990–2020 | 372 | 0.8827 | 0.8827 | 157.0 | 0.579 |
| Big-only | reachable 2010.07+ | 192 | 0.9173 | 0.9173 | 161.6 | 0.615 |
| Small-only | full history | 1,200 | 0.9030 | — | 160.5 | — |

The empirical and closed-form columns are computed by entirely different routes and agree to four
decimals, which is what makes the decomposition trustworthy rather than merely plausible.

Three readings worth taking:

- **0.92 is not a near miss.** Tracking error is ~160 bps/month against a factor whose own monthly
  σ is ~370 bps.
- **Neither size half is redundant** — dropping small costs about as much as dropping big
  (0.92 vs 0.90). HML is not a large-cap phenomenon that a large-cap universe would capture anyway.
- **The ceiling is set by ρ ≈ 0.58–0.66**, meaning small-cap and large-cap value spreads genuinely
  diverge. That is a fact about value investing, not about a data budget.

The factor *algebra* is separately verified exact: HML and SMB rebuilt from French's six
value-weighted portfolios match his published series to **0.5 bps**, the half-ulp of his own
2-decimal reporting.

## The question

Fama-French factors are the language of equity research: when a PM asks *"is your alpha just
value?"*, the answer is a regression against these series. Building them from scratch forces you
through the construction details — NYSE breakpoints, June formation on prior-December accounting,
the six-month reporting gap, value-weighting with monthly drift — that decide whether a factor is
the real one or a plausible-looking impostor.

## What this can and cannot establish

The spec's target is HML correlating >0.99 with French's published series over 1990–2020. **That
is not reachable on free data**, and the reason is data existence rather than difficulty: the only
free source of machine-readable US book equity is the SEC's Financial Statement Data Sets, which
begin at **2009q1**. The first June formation with genuinely-known book equity is therefore
June 2010. Three further gaps — universe breadth, missing delisted-firm price history, and the
book-equity definition — are documented with their measured sizes in [`LOG.md`](LOG.md).

So the deliverable is reshaped rather than softened. The interesting result here is not a
correlation number; it is the **decomposition of the gap** — how many basis points of tracking
error come from universe truncation, how many from the book-equity definition, how many from
survivorship, each isolated and measured rather than listed as a caveat. A replication that
reports 0.99 because it had CRSP demonstrates less than one that reports a lower number and can
account for every part of the difference.

## Method

1. ~~**Establish the ceiling first**~~ — **done**, above. Bounding the project from published data
   before writing construction code cost an afternoon and changed what the project is trying to
   prove.
2. **Sort machinery** — in progress. Breakpoint application, portfolio assignment, value-weighted
   returns with monthly drift between annual rebalances. Tested against synthetic cross-sections
   with hand-computable answers, because the sort is where a replication goes silently wrong: a
   `>=` for a `>`, or June market equity used for the BE/ME ratio where December is required.
3. **Universe assembly** from SEC EDGAR + free price sources.
4. **Bottom-up construction**, reported honestly.
5. **Gap attribution**, by ablation.
6. **q-factor extension** (Hou-Xue-Zhang 2015) and spanning tests against FF5 in both directions.

## Run it

```bash
python scripts/fetch_reference_data.py   # ~11 small files from French's library
python scripts/ceiling_analysis.py       # reproduces the table above
pytest                                   # 107 tests; skips cleanly without the data
```

NYSE breakpoints are taken from French's own published breakpoint files rather than derived —
deriving them needs a historical exchange-listing map, which is not free. This is a real limitation
and is treated as one: the breakpoints are borrowed, and they carry the current CRSP vintage's
restatements rather than what was known at the time.

## Data sources (all free)

- **Ken French's data library** — published factors, the 6 source portfolios with firm counts, and
  the NYSE breakpoint files.
- **global-q.org** — Hou-Xue-Zhang q-factors, for the extension's reference series.
- **SEC EDGAR Financial Statement Data Sets** — book equity and the accounting inputs, via
  Project 01's pipeline.
- **yfinance / Stooq** — prices.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate

# Reproducible: the exact versions this has been verified against
pip install -r requirements.lock && pip install -e . --no-deps

# Or, for development against current versions
pip install -e ".[dev]"

cp .env.example .env      # set SEC_USER_AGENT="Your Name your@email.com"
```

Verified against Python 3.13.9, pandas 3.0.5, numpy 2.5.2, scipy 1.18.0.

## Limitations

Stated here rather than buried, because they bound what any number in this repo can mean.

- **NYSE breakpoints are borrowed, not derived.** Deriving them needs a historical exchange-listing
  map per firm per date, which is not free. French's own breakpoint files are used instead. They
  also carry the *current* CRSP vintage's restatements ("created using the 202606 CRSP database"),
  so they embed information not known at the time — a mild lookahead.
- **No book equity before 2009.** The SEC's Financial Statement Data Sets begin at 2009q1, so the
  first June formation with genuinely-known book equity is June 2010. The spec's 1990–2020 window
  is not reachable on free data at all.
- **Delisted firms have no price history** from free sources, and value portfolios are
  disproportionately distressed firms. This biases the value leg upward. Inherited from Project 01,
  where it is that project's largest open item.
- **RMW and CMA cannot start before 1963** — French's OP and INV breakpoint files begin there,
  reflecting Compustat coverage.
- **Steps 3–6 are not built.** Everything above the "result so far" section is measured; everything
  below it is a plan.

## Relationship to the earlier projects

**Project 01** (point-in-time equity data pipeline) supplies fundamentals and prices. Consumed as
*data*, not imported — projects in this workspace do not depend on each other's packages.

**Project 02** (event-driven backtesting engine) already reproduces published HML *returns* to
0.5 bps, but from French's own portfolio series. That validated the backtester's accounting. It
says nothing about whether HML can be built from firm data, which is this project's subject.
