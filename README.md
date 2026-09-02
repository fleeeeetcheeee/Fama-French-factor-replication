# Fama-French Factor Replication

Building SMB, HML, UMD, RMW and CMA from individual firm data — and decomposing, in basis points,
every source of difference from Kenneth French's published series.

> **Status: in progress.** Steps 1 and 2 are complete; step 3's universe and book-equity layers are
> verified against live CRSP and Compustat. The sort machinery is written but has not yet run on
> real data — the join between book equity and the June cross-section is the last missing piece.
> 333 tests, 98% coverage. This README will be rewritten around the full results when there are any.
> Reasoning is logged in [`LOG.md`](LOG.md).

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

## A finding, on the way to the factor

**Fama-French book equity stops adding balance-sheet deferred taxes after fiscal 1992, and the
published definition does not say so.**

The definition — "stockholders' equity, plus balance sheet deferred taxes and investment tax credit
(if available), minus the book value of preferred stock" — carries no date qualifier, and neither
does French's variable-definitions page. His published NYSE BE/ME breakpoints do. Scored against
every percentile he publishes:

| book equity definition | formation 1963–1993 | formation 1994–2024 |
|---|---|---|
| `SE + DT − PS` (always add, as stated) | 3.42% | 8.69% |
| `SE − PS` (never add) | 10.64% | 0.96% |
| DT through FY1992, none after | **3.42%** | **0.96%** |

It is a step, not a drift — 1.05% for formation 1993 against 9.91% for 1994 under "always add" —
and scanning the cutoff year gives a clean single minimum at fiscal 1992 (1.12%, against 1.55% and
1.56% either side).

**The cutoff is measured. The reason for it is inferred.** SFAS 109 takes effect for fiscal years
beginning after 15 December 1992, so the first affected year end for a calendar-year filer is
December 1993 — exactly where the break lands. Suggestive, not proof: a change in what Compustat's
`txditc` means would produce the same observable, and the two are not separable with this data. The
distinction is kept in the code and in the log rather than resolved by assertion.

With the cutoff applied, book equity tracks the published breakpoints at **1.08% mean absolute
error over 1975–2024** with a −0.22% median bias. The residual decomposes by data availability
rather than by era: 0.6–1.6% in 2016–2024 where the CUSIP match rate is 97–98%, and 4–13% in
1963–1971 where Compustat covers 55–78% of NYSE and French is using hand-collected Moody's book
equity that cannot be bought at any price.

## The question

Fama-French factors are the language of equity research: when a PM asks *"is your alpha just
value?"*, the answer is a regression against these series. Building them from scratch forces you
through the construction details — NYSE breakpoints, June formation on prior-December accounting,
the six-month reporting gap, value-weighting with monthly drift — that decide whether a factor is
the real one or a plausible-looking impostor.

## What this can and cannot establish

The spec's target is HML correlating >0.99 with French's published series over 1990–2020. With CRSP
and Compustat that is reachable in principle, and the interesting question moves from *whether* to
*by how much, and from what*.

One gap is permanent and worth naming up front. CRSP/Compustat Merged — the curated, date-aware
link between CRSP's PERMNO and Compustat's GVKEY — is not in this subscription and cannot be added.
The join therefore falls back to matching 8-character CUSIPs, which reaches **92.9% of firms and
96.1% of market equity**. The residual is structural rather than a CUSIP-vintage artifact: matching
against every historical CUSIP a security ever carried buys only 0.7pp more firms and nothing at
all by weight. Unmatched names have a median market equity of $122m against $724m for matched ones,
so the gap is a small-cap gap — precisely where a value factor carries risk.

That is treated as a measurable quantity rather than a caveat. Linkage gets its own interface in
the code so its cost can be isolated by ablation in step 5, alongside universe truncation, the
book-equity definition, and survivorship. **The deliverable is the decomposition**: how many basis
points of tracking error come from each source, isolated and measured. A replication that reports
0.99 demonstrates less than one that reports a number and can account for every part of the
difference.

CRSP history also ends 2024-12-31 while French's published files are built from the 202606 vintage,
so no comparison here can run past 2024-12, and his numbers carry 18 further months of restatement
that are not visible to us.

## Method

1. ~~**Establish the ceiling first**~~ — **done**, above. Bounding the project from published data
   before writing construction code cost an afternoon and changed what the project is trying to
   prove.
2. ~~**Sort machinery**~~ — **done**, and hand-verified. Breakpoint application, portfolio
   assignment, value-weighted returns with drift between annual rebalances. Tested against
   synthetic cross-sections with hand-computable answers, because the sort is where a replication
   goes silently wrong: a `>=` for a `>`, or June market equity used for the BE/ME ratio where
   December is required. Two conventions were *measured* rather than assumed — the percentile
   interpolation method and the weight-drift return — and both are described below.
3. **Universe assembly** from CRSP + Compustat — **screen and book equity built and verified; the
   join between them is not**. The screen reproduces French's published NYSE cross-section to within
   1.3% on the median and 9 firms in June 2022, across four decades; two corrections were each worth
   several percent and neither was obvious, and both are described below. Book equity reproduces his
   published BE/ME breakpoints at 1.08% mean absolute error over 1975–2024, which is where the
   deferred-tax cutoff above came from. What does not yet exist is the formation join — book equity
   against the June and December cross-sections — so the sort machinery still has no real input.
4. **Bottom-up construction**, reported honestly.
5. **Gap attribution**, by ablation.
6. **q-factor extension** (Hou-Xue-Zhang 2015) and spanning tests against FF5 in both directions.

## Run it

```bash
python scripts/fetch_reference_data.py   # ~11 small files from French's library
python scripts/ceiling_analysis.py       # reproduces the ceiling table above
pytest                                   # 333 tests; skips cleanly without data or WRDS

# with a WRDS subscription
export WRDS_USERNAME=<user>              # password comes from ~/.pgpass
python scripts/validate_book_equity.py   # reproduces the deferred-tax table above, ~5 min
FFREP_WRDS_TESTS=1 pytest tests/integration/   # universe screen and book equity vs CRSP
```

The WRDS tests are the interesting ones, and both suites are built the same way: they assert
agreement with files **we did not produce**. `test_universe_wrds.py` checks the CRSP universe screen
against French's published NYSE breakpoints — median, firm count, and the full percentile curve — at
six June cross-sections from 1990 to 2022. `test_book_equity_wrds.py` checks the assembled
book-equity definition against his published BE/ME breakpoints at seven formation years spanning
1990–2024, and pins the deferred-tax cutoff from both sides: before the break, adding deferred taxes
must beat omitting them by 3×; after it, the reverse.

Several tests assert that the corrections **matter**, so a regression that quietly drops the
blank-check exclusion, the company-level aggregation or the deferred-tax cutoff fails rather than
passing with a worse number.

## Data sources

- **CRSP monthly stock files** (via WRDS) — prices, shares outstanding, share codes, exchange
  codes, delisting returns. History to 2024-12-31.
- **Compustat annual fundamentals** (via WRDS) — book equity, operating profitability, investment.
- **Ken French's data library** (free) — published factors, the 6 source portfolios with firm
  counts, and the NYSE breakpoint files, used as the validation reference.
- **global-q.org** (free) — Hou-Xue-Zhang q-factors, for the extension's reference series.

WRDS data cannot be redistributed, so `data/` is gitignored throughout and only derived factor
series are versioned. Everything in the reference layer is free and public, and the reference tests
run without a subscription.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate

# Reproducible: the exact versions this has been verified against
pip install -r requirements.lock && pip install -e . --no-deps

# Or, for development against current versions
pip install -e ".[dev]"

cp .env.example .env      # set SEC_USER_AGENT="Your Name your@email.com"

# WRDS (optional; the reference layer and all unit tests run without it)
pip install --no-deps -r requirements-wrds.lock   # --no-deps is required, see the file
#   1. put your credentials in ~/.pgpass, mode 0600:
#        wrds-pgdata.wharton.upenn.edu:9737:wrds:<username>:<password>
#   2. export WRDS_USERNAME=<username>
#   3. FFREP_WRDS_TESTS=1 pytest tests/integration/test_universe_wrds.py
```

Verified against Python 3.13.9, pandas 3.0.5, numpy 2.5.2, scipy 1.18.0.

## Limitations

Stated here rather than buried, because they bound what any number in this repo can mean.

- **No CRSP/Compustat Merged link table.** Not in the subscription, and not obtainable. The
  PERMNO↔GVKEY join is an 8-character CUSIP match covering 92.9% of firms and 96.1% of market
  equity, and the missing names skew small. This is the largest single limitation and it is
  permanent; step 5 measures what it costs rather than assuming it is negligible.
- **The blank-check exclusion is measured, but its mechanism is inferred.** CRSP tags SPACs with
  share code 11, so they pass an ordinary-common-shares filter; through 2021–22 that put up to 164
  excess names into the NYSE cross-section and dragged the June-2022 median 18.6% below French's.
  Excluding SIC 6799 is validated on all **866 months** French publishes — median absolute error
  0.08% against 0.17% unscreened — and beats every alternative tested (6770 does nothing, 67xx
  overshoots, name-matching is worse). What is *not* established is why: French publishes no such
  rule, and a CRSP vintage reclassification would produce the same observable. A residual +14 firms
  and −1.77% median error persists through the 2020s and is unexplained.
- **CRSP ends 2024-12-31**, French's files are built from the 202606 vintage. Comparisons stop at
  2024-12, and a residual of roughly 8% at the 5th percentile in June 2024 is consistent with
  small-cap restatement between vintages. Noted, not chased.
- **~~NYSE breakpoints are borrowed, not derived.~~ Retired.** They are now derived from our own
  screened CRSP universe. Validated against French's published files over **544 months and every
  percentile he reports**: median error −0.000%, mean absolute error 0.51%, 85.7% of pairs within
  1%. The percentile convention was selected by scoring all five numpy methods against him over
  1960–1989 — `lower` is unbiased where `linear` carries a +0.09% median error. His files are
  retained as the validation reference, which is the right role for them.
- **The deferred-tax cutoff is measured; its mechanism is inferred.** FY1992 is where the data puts
  the break, with 8 percentage points of error either side of it and a single clean minimum in the
  cutoff scan. *Why* he does it is not established — SFAS 109's effective date coincides exactly,
  but a change in what Compustat's `txditc` means is observationally equivalent and this data cannot
  separate them. Treated as an open question rather than a conclusion.
- **Operating profitability and investment are implemented but their agreement with French is
  unrecorded.** `validate_book_equity.py` scores both against his published `OP_Breakpoints` and
  `INV_Breakpoints`, but no number is captured and no test asserts a bound. RMW's and CMA's sort
  variables therefore sit at a weaker standard of evidence than BE/ME, and that gap is named rather
  than papered over.
- **Delisting returns are implemented but not yet exercised** on a full panel. The Shumway (1997)
  −30% convention is applied to performance-related delistings with a missing return; 193 of 29,106
  delisting events in this subscription qualify.
- **The sort machinery has never run on real data.** Book equity now exists on real Compustat, so
  the blocker is no longer the data — it is that nothing yet joins book equity to the June and
  December CRSP cross-sections. Every construct test still uses synthetic input, and the arithmetic
  is verified against hand computation only. Internal consistency is a weaker claim than the
  breakpoint, universe and book-equity results, which are verified against French. Implemented is
  not verified.
- **The full monthly CRSP panel has not been pulled.** The annual June/December cross-sections have
  (318,114 security-months, all of CRSP), but the ~4.8M monthly rows that step 4 needs for returns
  between rebalances have not.
- **Steps 4, 5 and 6 are not built.** Everything in the two results sections above is measured;
  everything after them is a plan.

## Relationship to the earlier projects

**Project 01** (point-in-time equity data pipeline) is no longer the fundamentals source — CRSP and
Compustat replace it, and with them the 2009q1 EDGAR floor and the missing delisted-price problem
both disappear. Its point-in-time discipline still governs the design here: `msenames` is joined on
`namedt`/`nameendt` so a security's share code, exchange and SIC are the values that were true at
the time, not today's.

**Project 02** (event-driven backtesting engine) already reproduces published HML *returns* to
0.5 bps, but from French's own portfolio series. That validated the backtester's accounting. It
says nothing about whether HML can be built from firm data, which is this project's subject.
