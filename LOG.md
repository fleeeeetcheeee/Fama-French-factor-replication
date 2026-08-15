# Project 3 — Fama-French Factor Replication

**Tier:** 1 (Factor fluency) — first project of the tier
**Spec:** `ResearchToDo.md` → Part 3 → Tier 1 → Project 3
**Repo:** https://github.com/fleeeeetcheeee/Fama-French-factor-replication
**Status:** **Steps 1 and 2 of 6 in progress; step 1 complete.** 107 tests pass, 96% coverage.
The reference-data layer is built and verified against the real files, and the factor algebra
reproduces published HML and SMB to French's own 0.5 bp rounding floor.

The spec's done criterion **cannot be met as written on free data** — see
[The done criterion is unreachable as written](#the-done-criterion-is-unreachable-as-written).
Step 1 now puts a *measured* number on it: a universe without small-cap stocks tops out at
**0.92** correlation with published HML, measured on French's own portfolios, so the bound is a
property of the data rather than of any implementation. WRDS access is pending; steps 1–2 were
chosen because they are invariant to that answer.

---

## Goal

Construct SMB, HML, UMD, RMW and CMA from individual firm data — 2×3 sorts on size ×
book-to-market with NYSE breakpoints, formed each June on prior-December accounting data — and
reproduce Kenneth French's published factor returns. Then extend to the Hou-Xue-Zhang (2015)
q-factor model and run spanning tests in both directions.

**Done criterion (from the spec):** *"Monthly returns of your HML factor correlate with French's
published HML at >0.99 over at least the 1990–2020 period."*

---

## Build log

### 2026-08-15 — Setup and feasibility analysis

Written as work happened. Nothing committed.

#### Repository setup

Cloned the pre-existing GitHub repo (`2461c42 Initial commit`, holding a `LICENSE` and a one-line
`README.md` stub created through the web UI) directly into
`TierOne/Project03-FamaFrenchFactorReplication/`.

Deliberately a `clone` rather than Project 02's `git init` + `git remote add`. That sequence gave
Project 02 a local history unrelated to the remote's and cost a rebase to reconcile without
discarding the remote's initial commit. Cloning starts from the remote's history and the problem
does not arise. First tier folder outside `TierZero`, so `TierOne/` was created here.

**Package named `ffrep`.** `tierzero` (Project 01) names a tier rather than a project and would
collide the moment two of these are installed together; `evbt` (Project 02) is taken. Checked
against PyPI to avoid a shared-venv collision: `famafrench` is taken (an existing factor-
construction library — importing the wrong one silently would be a genuinely confusing failure),
`factorlab` and `pyfactor` are taken, `ffrep` is free.

#### The done criterion is unreachable as written

This was checked before writing any code, because the answer determines the shape of the project.
The criterion requires HML over **at least 1990–2020**. On free data the series **cannot begin
before July 2010**, and the reason is not difficulty — the source data does not exist.

The binding chain:

1. HML formed in June of year *t* needs book equity from the fiscal year ending in calendar year
   *t−1*, and market equity at the end of December *t−1*.
2. The only free source of machine-readable US book equity is the SEC's Financial Statement Data
   Sets, which **begin at 2009q1**. Verified during Project 01: `2008q1` → 404, `2009q1` → 200.
   EDGAR holds filings back to the mid-1990s, but as unstructured text — the XBRL mandate phased
   in from 2009.
3. A fiscal year ending December 2009 is filed in Q1 2010 and lands in the 2010q1 dataset. The
   first formation with genuinely-known book equity is therefore **June 2010**, and the first
   return month is **July 2010**.

Overlap with the required window: **126 of 366 months**, all of them after 2010. The first twenty
years of the criterion's window are not reachable by any amount of work on free data.

Three further gaps, each independently large:

**Universe.** French's HML spans every NYSE/AMEX/NASDAQ ordinary common share on CRSP — roughly
3,000–5,000 names. Project 01's store is the S&P 500, ~500 large caps. This is not a matter of
degree for HML specifically: with NYSE breakpoints, French's own `ME_Breakpoints` file puts the
**NYSE median market equity at $5,139m as of 2026-06**, and the S&P 500 is a large-cap index whose
constituents sit overwhelmingly above that. The `SmallValue` and `SmallGrowth` legs would be
near-empty and HML would degenerate into `BigValue − BigGrowth`. How near-empty is measurable
rather than assumed — see step 1 of the plan.

**Delisted price history.** Project 01's open item 2: yfinance serves no history at all for
delisted tickers (10 of 40 in its smoke run). This is worse for HML than for most factors, because
value portfolios are disproportionately distressed firms and distressed firms delist
disproportionately. Omitting them biases the value leg upward. Shumway (1997) is the standard
reference on the size of this effect.

**Book equity definition.** Fama-French book equity is
`stockholders' equity + balance-sheet deferred taxes and investment tax credit − book value of
preferred stock`. Project 01's parser applies a 34-tag whitelist (`CORE_TAGS`); querying its store
confirms the only equity-related tag present is `StockholdersEquity` (83,925 facts in 2026q1) —
no deferred taxes, no preferred stock. Getting FF's actual definition requires extending that
whitelist in Project 01 and re-parsing.

**Conclusion.** >0.99 over 1990–2020 needs CRSP + Compustat. There is no free substitute and no
clever workaround. Recorded here rather than discovered three weeks in.

#### What *is* free, and it is more than expected

The single largest technical blocker dissolved on inspection. French publishes his **NYSE
breakpoints** as free downloads, so reproducing them from a historical exchange-listing map — which
is not free and which Project 01 does not store — is unnecessary. Verified by downloading and
inspecting both:

| File | Shape | Verified content |
|---|---|---|
| `ME_Breakpoints_CSV.zip` | monthly, `YYYYMM, count, p5 … p100` in $m | 192512 – 202606; 2026-06 median $5,139m, 1,085 NYSE firms |
| `BE-ME_Breakpoints_CSV.zip` | **annual**, `YYYY, n(BE≤0), n(BE>0), p5 … p100` | 1926 – 2026; 2026 30th pct 0.261, 70th 0.710 |

Also free and confirmed present on the library index: `OP_Breakpoints`, `INV_Breakpoints`,
`Prior_2-12_Breakpoints`, `F-F_Research_Data_5_Factors_2x3`, `F-F_Momentum_Factor`,
`6_Portfolios_ME_OP_2x3`, `6_Portfolios_ME_INV_2x3`, and `Portfolios_Formed_on_BE-ME`. The
Hou-Xue-Zhang q-factors are free at global-q.org.

**The breakpoint files do not match Project 02's French parser.** That parser locates tables by a
`,`-leading header row; the breakpoint files have no such header — `ME_Breakpoints` goes straight
from a one-line preamble into data rows. So the breakpoint reader is new code, not reuse. Noting
it now because assuming reuse and discovering this mid-build is exactly the kind of avoidable cost
Project 02 recorded twice.

**One honesty caveat on using French's breakpoints.** They are built from the *current* CRSP
vintage ("created using the 202606 CRSP database"), so they embed restatements not known at the
time. The effect is small but it is a mild lookahead, and it means the breakpoints are borrowed
rather than independently derived. Both belong in the limitations section, not in a footnote.

#### Planned approach

Staged so that each step has a verifiable answer before the next depends on it — the same
machinery/data split that made Project 02's done criterion interpretable.

**Step 1 — Establish the ceiling before building anything.** Using French's *published* series
only, compute how well `BigValue − BigGrowth` (an HML with no small leg, which is what an
S&P-500-sized universe forces) tracks true HML. That number is the upper bound on any
large-cap-only replication, is obtainable in an afternoon from data already confirmed downloadable,
and is worth knowing before writing a line of construction code. Repeat for the reachable window
(2010-07 onward) versus the full history, since the criterion's window and the reachable window
differ.

**Step 2 — Sort machinery, tested against known answers.** Breakpoint application, portfolio
assignment, value-weighted returns with monthly weight drift between annual rebalances, factor
assembly. Tested on synthetic cross-sections whose portfolio memberships and returns are
hand-computable — the sort is where a replication silently goes wrong (a `>=` for a `>`, June ME
used for the BE/ME ratio where December ME is required), and those errors produce plausible
series, not crashes.

**Step 3 — Universe assembly.** Widen beyond the S&P 500 using the SEC's ~10,000-entry
CIK↔ticker map, and extend Project 01's `CORE_TAGS` for the book-equity components. Investigate
Stooq for delisted price history — the spec names it as a free source and it is the only candidate
for closing Project 01's open item 2.

**Step 4 — Bottom-up construction and the honest number.** Run it, report the correlation.

**Step 5 — Attribute the gap, quantitatively.** This is the actual research contribution and the
reason the project survives not hitting 0.99. Each cause gets isolated and measured rather than
listed: universe truncation (step 1's ceiling, plus firm counts against French's published counts
per portfolio — he publishes them, so coverage is directly measurable without any returns),
book-equity definition (ablate `SE` against `SE + DT − PS`), missing delisted names, and borrowed
versus derived breakpoints.

**Step 6 — q-factor extension and spanning tests.** ME, I/A and ROE per Hou-Xue-Zhang (2015);
spanning regressions in both directions against FF5, with a hand-rolled GRS test. Following
Project 02's precedent of writing the statistics out in numpy rather than importing statsmodels,
since the portfolio standard requires deriving them on a whiteboard.

#### Scaffold built

`pyproject.toml` (hatchling, `src/` layout, Python ≥3.11), `.gitignore` carried over from Project
02, package skeleton `reference/ universe/ construct/ qfactor/ evaluate/`, and `config.py`.

`config.py` follows Project 01's rule that one module owns every path, URL and constant. Here that
matters more than usual: the Fama-French protocol is a stack of specific and arbitrary-looking
choices — 30th/70th percentiles, June formation, December accounting market equity, a six-month
reporting gap, positive-book-equity screening — and each one changes the answer. `FORMATION_MONTH`,
`BEME_MARKET_EQUITY_MONTH` and `SIZE_MARKET_EQUITY_MONTH` are separate named constants specifically
because collapsing the last two is a real and silent error: the BE/ME ratio uses **December** *t−1*
market equity while the size sort and the value weights use **June** *t*.

**Verified:** `python -m venv`, `pip install -e ".[dev]"` clean, `ffrep.config` imports, derived
paths resolve, and `require_real_user_agent()` raises on the empty default.

### 2026-08-15 — Reference layer, and step 1: the ceiling is 0.92

Written as work happened, same session. Direction confirmed: WRDS approval is **pending**, so the
work done here is deliberately the part that is invariant to the answer — French's published data
and the factor algebra are the same reference set whether the firm-level data comes from CRSP or
from EDGAR.

#### What was built

`reference/library.py` (download, bytes verbatim, atomic `.tmp`-then-rename — same ingestion
discipline as Projects 01 and 02), `reference/parser.py` (the stacked-table CSV layout),
`reference/breakpoints.py` (the NYSE breakpoint files), `evaluate/regression.py` (OLS with
Newey-West, and the GRS test), `evaluate/ceiling.py` (step 1), plus two scripts.

`parser.py` is **vendored** from Project 02's `evbt/data/french.py` rather than imported —
projects here do not depend on each other's packages — and extended with firm counts, the
OP/INV portfolio name maps, a strict `find_table`, and SMB.

#### The parsers caught an error I had already made by hand

Writing the earlier LOG entry I read the 2026 BE/ME row off the raw file and recorded the 70th
percentile as 0.640. It is **0.710**; 0.640 is p65. I had miscounted by one column — which is
precisely the failure mode `breakpoints.py` warns about in its own docstring, committed by hand
within an hour of writing the warning. The parser is right and the LOG entry has been corrected.
Recorded rather than quietly fixed because it is direct evidence for why that module refuses to
identify count columns by reading the header, and instead derives them by subtraction from the
fixed 20-wide percentile block.

#### Verification of the reference layer

The factor algebra reproduces French's published series from his own portfolios:

| | n | max abs diff |
|---|---|---|
| HML from the 6 value-weighted portfolios | 1,200 | **0.5000 bps** |
| SMB from the 6 value-weighted portfolios | 1,200 | **0.5000 bps** |

0.5 bp is the half-ulp of French's 2-decimal reporting — the same floor Project 02 landed on
independently, reached here by a different route. `test_error_sits_exactly_on_french_rounding_not_
merely_under_it` asserts the max lands *on* the floor rather than merely under it, because an
accounting error would produce a messy bound, not the data's own precision limit.

Both tests initially failed at `0.5000000000000837` — float64 noise 8e-14 above the bound. Fixed
by making the *comparison* robust rather than loosening the bound to whatever passed; the epsilon
is 1e-9 bps, a billion times smaller than one basis point.

**Mutation-tested the highest-risk logic.** The ME breakpoint file has one leading count column
and the BE-ME file has two, with no usable header to distinguish them; guessing wrong shifts every
percentile silently and yields a complete, well-formed, entirely wrong table. Replacing the
subtraction with a hardcoded `n_counts = 1` — the realistic version of this error — fails **7
tests**, including both percentile-position assertions. Source restored and verified byte-identical.

#### Step 1 — the ceiling, from published data only

HML decomposes into the average of two spreads, one per size half:

```
HML = ½[(SmallValue − SmallGrowth) + (BigValue − BigGrowth)] = ½[small spread + big spread]
```

so an HML built without small caps *is* the big-spread term, and its correlation with the real
factor follows in closed form from the two volatilities and their correlation ρ:

```
corr(B, ½(S+B)) = (σ_B + ρσ_S) / sqrt(σ_S² + 2ρσ_Sσ_B + σ_B²)
```

**Result — measured on French's own portfolios, so this bounds the data, not the code:**

| truncation | window | n | corr | analytic | TE (bps/mo) | ρ(small,big) |
|---|---|---|---|---|---|---|
| HML, big-only | full history | 1,200 | 0.9208 | 0.9208 | 160.5 | 0.664 |
| HML, big-only | spec 1990–2020 | 372 | **0.8827** | 0.8827 | 157.0 | 0.579 |
| HML, big-only | free-data 2010.07+ | 192 | **0.9173** | 0.9173 | 161.6 | 0.615 |
| HML, small-only | full history | 1,200 | 0.9030 | — | 160.5 | — |
| HML, small-only | free-data 2010.07+ | 192 | 0.8779 | — | 161.7 | — |

The empirical and analytic columns agree to four decimals on all three windows. They are computed
by completely different routes — one correlates the realised series, the other evaluates the
formula from σ and ρ — so the agreement is evidence the decomposition is right rather than a
tautology, and it is asserted in the test suite.

**Three things this settles.**

1. **0.99 is unreachable on a large-cap universe, by a wide margin.** 0.92 is not a near miss —
   the tracking error is ~160 bps a month against a factor whose own monthly σ is ~370 bps. And
   because it is measured on French's portfolios, no amount of downstream care improves it.
2. **Neither size half is redundant.** Dropping small costs about as much as dropping big
   (0.92 vs 0.90). That kills the hopeful reading that HML is mostly a large-cap phenomenon which
   a large-cap universe would capture anyway.
3. **The ceiling is set by ρ, which is a property of the market.** ρ ≈ 0.58–0.66 means the
   small-cap and large-cap value spreads genuinely diverge. This is a fact about value investing,
   not about anyone's data budget — which makes it worth reporting in its own right rather than
   only as an excuse.

The 1990–2020 window is the *worst* of the three (0.8827, ρ = 0.579) — so the spec's own window is
where universe truncation hurts most, and the reachable window is slightly kinder.

#### Also verified against the real files

- `6_Portfolios_2x3` contains ten stacked tables; all located structurally.
- Small portfolios hold more *firms* than big ones in every month since 2015 — the cross-section
  lost to a large-cap universe is the majority of it by count.
- ME percentiles are monotone across all 1,207 monthly rows (the strongest available check that no
  column shift occurred anywhere in the file).
- OP and INV breakpoints begin **1963**, a second and harder start-date constraint on RMW and CMA.
- The 3-factor and 5-factor SMB series are **different** (corr 0.95+, max abs diff > 1e-4) — the
  5-factor version averages the small-minus-big spread across all three 2×3 sorts. Same name,
  different series; pinned so it cannot be silently conflated.

#### Not done

global-q.org timed out on the fetch (120 s). Only the q-factor extension needs it, which is step 6,
so the script warns and continues rather than failing the whole download. The URL also carries a
`2024` in its filename and may simply have moved — to be checked when step 6 starts.

**Verification: 107 tests, 96% coverage.** Dependencies pinned in `requirements.lock`
(pandas 3.0.5, numpy 2.5.2, scipy 1.18.0).

---

## Open questions

1. **WRDS / CRSP / Compustat access — requested, approval pending (as of 2026-08-15).** The
   highest-information unknown: it changes the project's shape rather than its schedule. With it,
   the spec's criterion becomes achievable as written and steps 3 and 5 mostly disappear. The spec
   itself flags WRDS as "a huge advantage" for this project. Work is being sequenced so that
   nothing done before the answer arrives is wasted either way — hence steps 1–2 first.
2. **Revised done criterion, pending the above.** Now informed by step 1's measured ceiling rather
   than guessed at. Proposed:
   - **Universe breadth is the binding constraint, not care.** With a broad free universe
     (several thousand names, not the S&P 500's ~500), the target is HML correlation **>0.95 over
     2010-07 – 2026-06**. Restricted to a large-cap universe the ceiling is **0.917** and the
     target must be stated against that, not against 0.99.
   - Exact reproduction of the factor *algebra* from French's published portfolios — **already met**
     at 0.5 bps.
   - The residual gap decomposed into named, separately measured causes.
   - q-factor extension with spanning tests both directions.
3. **Does Project 01's full bootstrap need to run first?** Its store currently holds one EDGAR
   quarter (2026q1) and 30 tickers — a smoke run, not a dataset. Project 03 needs 2009q1–present
   fundamentals and a universe two orders of magnitude wider. That bootstrap is Project 01's open
   item 10 and is a prerequisite here regardless of which criterion is adopted. Deferred until
   step 3, per the sequencing decision above.

## Status against the done criterion

| Requirement | State |
|---|---|
| Published reference series downloaded and parsed | **Done, verified** — 11 French files, all 5 breakpoint shapes |
| Factor algebra reproduces published HML/SMB | **Done, verified** — 0.5 bps, French's own rounding floor |
| Ceiling on a truncated universe established (step 1) | **Done** — 0.92 big-only; analytic and empirical agree |
| 2×3 size × BE/ME sorts, NYSE breakpoints (step 2) | In progress |
| June formation on prior-December accounting | Not started |
| SMB, HML, UMD, RMW, CMA constructed bottom-up | Not started |
| Correlation with French's published factors > 0.99 | **Unreachable as specified.** Ceiling measured at 0.917 (large-cap) — see step 1 |
| q-factor model + spanning tests | Not started (GRS test implemented and tested) |

## Open items

1. **Decide the data question (open question 1) before step 3.** Steps 1 and 2 are invariant to it.
   Step 1 is now complete and its result holds under either answer, since it is measured on
   French's published portfolios.
2. **Project 01's `CORE_TAGS` needs extending** for deferred taxes and preferred stock, followed by
   a re-parse. That is a change in Project 01's repo consumed as data here — projects in this
   workspace do not import from each other. Only bites if WRDS is unavailable.
3. **Project 01's full bootstrap is a hard prerequisite** for step 3 and has never been run (its
   open item 10).
4. **global-q.org fetch times out.** Needed only for step 6. The URL carries a `2024` in its
   filename and may have moved; check when that step starts.
5. **`evaluate/regression.py` is at 93%** — the uncovered lines are `OLSResult.summary()` and one
   GRS branch. Cosmetic, but `summary()` is the path a human reads results through, so it should
   not stay untested.
6. **Nothing committed.** The whole project is uncommitted in the working tree.
