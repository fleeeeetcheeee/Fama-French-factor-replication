# Project 3 — Fama-French Factor Replication

**Tier:** 1 (Factor fluency) — first project of the tier
**Spec:** `ResearchToDo.md` → Part 3 → Tier 1 → Project 3
**Repo:** https://github.com/fleeeeetcheeee/Fama-French-factor-replication
**Status:** **Steps 1 and 2 complete; step 3's universe and book-equity layers built and verified
against live CRSP and Compustat.** 333 tests pass, 98% coverage. The reference layer reproduces
published HML and SMB to French's own 0.5 bp rounding floor; `universe/` screens a real CRSP
cross-section to within 1.3% of his published NYSE median across four decades; `construct/` holds
the 2x3 sort machinery plus book equity, NYSE breakpoints are now **derived** rather than borrowed
(median error −0.000% over 544 months), and book equity tracks his published BE/ME breakpoints at
1.08% mean absolute error over 1975–2024.

Along the way the book-equity work established something French does not document: **he stops adding
balance-sheet deferred taxes after fiscal 1992**, measured on his own published breakpoints with a
clean single minimum in the cutoff scan.

What remains of step 3 is the **formation join** — nothing yet connects book equity to the June
cross-section, so the sort machinery still has never run on real data. `qfactor/` is still empty.

The spec's done criterion **cannot be met as written on free data** — see
[The done criterion is unreachable as written](#the-done-criterion-is-unreachable-as-written).
Step 1 puts a *measured* number on it: a universe without small-cap stocks tops out at
**0.92** correlation with published HML, measured on French's own portfolios, so the bound is a
property of the data rather than of any implementation.

**WRDS access was approved on 2026-08-24 and is now connected and characterised.** CRSP and
Compustat annual are readable; **CRSP/Compustat Merged is not, and cannot be added**, so the
PERMNO↔GVKEY join is permanently a CUSIP match at 92.9% of firms / 96.1% of market equity. CRSP
history ends 2024-12-31 while French's published files are built from the 202606 vintage, so no
comparison can run past 2024-12. The spec's >0.99 criterion is reachable in principle on this data;
the linkage gap is now a *measured* component of the step-5 attribution rather than a caveat. The
free-data ceiling above stays valid regardless — it is measured on French's own published
portfolios, so it is a fact about the data, not a limitation of this project.

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
(pandas 3.0.5, numpy 2.5.2, scipy 1.18.0). Also checked that a fresh clone with no data still
runs green — 80 pass, 27 skip — since a suite that requires a download to pass is a suite nobody
else will ever see pass.

Committed as `ba41458` (scaffold) and `e9f3dc2` (reference layer), split along the dependency
boundary rather than by session, and pushed. Cloning the remote at the start rather than
`git init`-ing over it meant the two commits landed straight on top of its `Initial commit` with
no rebase — the reconciliation Project 02 needed did not arise here.

### 2026-08-24 — WRDS reconnaissance: CRSP and Compustat yes, the link table no

Written as work happened. Connected as `fjlee01` over `wrds-pgdata.wharton.upenn.edu:9737`;
221 libraries visible. No data pulled yet — everything below is bounded probing.

#### What the subscription actually covers

| | Verified by | Result |
|---|---|---|
| CRSP monthly/daily stock | `select` on `msf`, `dsf`, `msenames`, `msedelist` | **Full read access** |
| CRSP CIZ format | `select` on `msf_v2`, `stksecurityinfohist` | **Also present** — both formats available |
| Compustat annual | `select` on `funda` (949 cols), `company`, `security` | **Full read access** |
| **CRSP/Compustat Merged (CCM)** | `select` on `ccmxpf_lnkhist` | **DENIED** — `permission denied for schema crsp_a_ccm` |
| Compustat Point-in-Time | `pitfnda`, `pitfndq`, `snapshot_funda` | **Does not exist** here |
| OptionMetrics / TAQ | library list | **Sample libraries only** (`optionmsamp_us`, `taqsamp`) |

`list_libraries()` reported `crsp` and every `ccmxpf_*` table inside it, and all five are denied on
`select`. The `crsp` schema exposes *views* onto `crsp_a_ccm`, which is a separate subscription
line. Listing a table is not entitlement to read it, and the recon plan said so before this ran —
which is the only reason it was checked rather than assumed.

**Coverage.** `crsp.msf` runs 1925-12-31 → **2024-12-31** (5,153,763 rows) — an annual update, so
it ends 18 months before French's 2026-06 vintage. Any comparison window ends 2024-12, not 2026.
`comp.funda` runs 1950-06 → 2026-07. Every field the FF protocol needs is present in `funda`:
`seq/ceq/pstk/pstkl/pstkrv/txditc/txdb/itcb` for book equity, `revt/cogs/xsga/xint` for RMW,
`at` for CMA. Checked by name against the live table rather than assumed.

#### The missing link table is the one real problem

Without CCM there is no maintained PERMNO↔GVKEY mapping, and that join is what makes bottom-up
construction possible at all. Measured the pre-CCM fallback — an 8-character CUSIP match — against
the June-2020 CRSP universe (3,574 firms) and Compustat FY2019:

| Join key | Firms matched | By market-equity weight |
|---|---|---|
| `msenames.cusip` → `funda.cusip[:8]` | 3,260 / 3,574 = **91.2%** | **96.0%** |
| `msenames.ncusip` → `funda.cusip[:8]` | 2,921 / 3,574 = 81.7% | 94.2% |

The header CUSIP beats the historical one, which is initially backwards-looking but expected:
Compustat's `funda.cusip` is itself the *current* identifier, so matching it against CRSP's current
header CUSIP compares like with like. Matching it against `ncusip` asks a historical key to find a
current one and loses ~10% of firms. Worth stating plainly that this makes the link mildly
forward-looking, which is a limitation to declare rather than a bug to fix.

96% by weight and 91% by count is workable for a value-weighted factor but is **not** CCM. The
missing 9% is not random — it will be concentrated in the small, the delisted and the
recently-restructured, which is exactly the tail HML depends on. Requesting CCM from the
institution's WRDS representative is worth doing before accepting this; it is often an addable
subscription line.

#### The NYSE-median check found a real construction detail, and a real anomaly

Recomputed the NYSE median market equity from CRSP and compared it to French's published
`ME_Breakpoints` p50 — the single strongest available check, because agreement confirms the
universe screen, the sign handling on `prc` (negative when it is a bid/ask midpoint rather than a
trade) and the `shrout` thousands→millions conversion all at once, against an external reference.

**First attempt was off by −7.2%.** The cause is a documented FF detail: market equity is
aggregated to the **company** (`permco`), summing across share classes, not left per security
(`permno`). Fixing that moved 2000 from −5.50% to **−0.18%** and 2010 from −3.68% to **−0.35%**.

Sweeping the corrected version across decades:

| June of | French p50 ($m) | CRSP p50 ($m) | diff | French n | our n | Δn |
|---|---|---|---|---|---|---|
| 1980 | 200.7 | 200.4 | −0.15% | 1,419 | 1,426 | +7 |
| 1990 | 503.6 | 498.1 | −1.09% | 1,293 | 1,300 | +7 |
| 1995 | 682.8 | 678.0 | −0.70% | 1,644 | 1,644 | 0 |
| 2000 | 905.1 | 903.4 | −0.18% | 1,635 | 1,632 | −3 |
| 2005 | 1,786.2 | 1,785.6 | −0.03% | 1,440 | 1,440 | 0 |
| 2010 | 1,589.7 | 1,584.2 | −0.35% | 1,296 | 1,305 | +9 |
| 2015 | 2,736.9 | 2,709.4 | −1.01% | 1,321 | 1,337 | +16 |
| 2018 | 3,228.9 | 3,177.1 | −1.60% | 1,226 | 1,246 | +20 |
| 2020 | 2,584.1 | 2,433.4 | −5.83% | 1,173 | 1,208 | +35 |
| **2022** | 3,208.6 | 2,611.8 | **−18.60%** | 1,242 | 1,396 | **+154** |
| 2024 | 4,023.1 | 3,690.7 | −8.26% | 1,190 | 1,259 | +69 |

Two readings. **The screen is essentially correct for 1980–2015** — sub-1% on the median and
near-exact on firm counts, which is a strong signal that the CRSP-side universe logic is right.
**Something diverges sharply from ~2018 and peaks in 2022**, where we carry 154 NYSE names French
does not. The sign is informative: extra firms depressing the median means the surplus is small-cap.
The 2021–22 SPAC wave is the obvious candidate — hundreds of blank-cheque companies listed with
`shrcd` 10/11 and modest market caps — but that is a hypothesis, not a finding, and it is the first
thing step 2 has to resolve. Recorded now because a replication that quietly inherits this would
show a clean 1963–2015 result and an unexplained recent-decade drift.

#### Smaller findings

- **Delisting returns barely need imputing**: 193 of 29,106 delisting events have a null `dlret`,
  157 of them performance-related (codes 500, 520–584). Shumway's −30% convention therefore moves
  very little here — good, since it is the crudest assumption in the standard recipe.
- **No Compustat Point-in-Time.** So `funda` is restated data. Since French uses the same, this
  *helps* the replication and hurts any tradeable claim: matching him means inheriting his
  restatement lookahead. That belongs in the limitations section as a distinction, not a defect.
- **Extract is small.** 4,776,239 `msf` rows from 1962, 117,830 `msenames`, 591,346 `funda` rows —
  and only ~25 of `funda`'s 949 columns are needed. This is a few hundred MB of Parquet, so it is
  one bounded pull rather than a staged job.
- No OptionMetrics and no TAQ beyond sample libraries, which constrains Projects 5, 12 and 13 later.

**Nothing written to disk, no extract code yet** — deliberately, until the CCM question is settled,
because whether the link is CCM or CUSIP changes the shape of the universe module.

---

### 2026-08-25 — Universe screen resolved: the SPAC leak, and SIZ/CIZ equivalence

Closed open questions 4, 5 and 6. The headline: the post-2018 divergence was a real screen defect
in my code, not a French idiosyncrasy, and fixing it improves *every* year rather than trading
recent accuracy against historical.

**Question 5 — the ~150 extra NYSE names.** Diagnosed by elimination, cheapest test first.

1. *Not ETFs.* The first hypothesis was NYSE Arca leakage. A `shrcd` × `exchcd` cross-tab killed it
   outright: all 1,804 ETFs (`shrcd` 73) sit on `exchcd` 3/4/5, never on `exchcd` 1. The NYSE
   filter already excluded every one of them.
2. *Not a join or measurement bug.* Zero `(permno, date)` pairs had duplicate `msenames` rows
   (0 of 124,589). And market equity computed as `abs(prc) * shrout / 1000` matches CRSP's own
   `mthcap` field on **1,419 of 1,419** securities — exactly, not approximately. That eliminated the
   entire measurement path and left the universe as the only remaining suspect.
3. *The error shape was the clue.* Comparing the full percentile curve rather than just the median:
   June 2022 was −37% at p20 and −31% at p30 but only −4.8% at p5 and −6.2% at p95. An inverted-U.
   Extra tiny firms would push the error monotonically down toward the bottom tail; this said the
   surplus sat in the lower-middle of the distribution, around a few hundred million dollars.
4. *Dating it.* A monthly count series 2017–2024 against French's own counts: a stable +20 to +30
   through 2019, then a ramp beginning Q4 2020, peaking at **+164 in January 2022**, decaying to
   +70 by late 2024. French's own count barely moves across the whole period (1,193 → 1,233 →
   1,206). That profile — ramp, spike, slow unwind — is the SPAC cycle.
5. *Naming them.* Bucketing the June-2022 screen by each PERMNO's first appearance in `msf`: 295
   firms first listed in 2020 or later, median ME $445m against $3,666m for everything else, and
   127 of them carrying SIC **6799**. The names settle it — `KINGSWOOD ACQUISITION CORP`,
   `PARABELLUM ACQUISITION CORP`, `G & P ACQUISITION CORP`, and so on down the list.

An earlier check for SIC `677x` had returned zero and briefly pointed away from SPACs. That was my
error: CRSP files blank-check companies under **6799** ("Investors, NEC"), not 6770.

**The fix, and why it is defensible.** French documents his screen as "all NYSE stocks that have a
CRSP share code of 10 or 11 and have good shares and price data. We exclude closed end funds and
REITs." In CRSP's coding those two exclusions are already implied by `shrcd` 10/11 — REITs are
`shrcd` 18 and closed-end funds are 44/48, both visible in the cross-tab and both already out. So
his stated screen equals mine, and the difference has to be in what counts as a firm. Excluding
SIC 6799 — economically the same category of blank-check investment vehicle French names — is what
reproduces his universe:

| June | French n | base n | ex-6799 n | median gap, base → ex-6799 |
|---|---|---|---|---|
| 1990 | 1,293 | 1,300 | 1,293 | −1.09% → **−0.42%** |
| 2000 | 1,635 | 1,632 | 1,625 | −0.18% → **−0.21%** |
| 2010 | 1,296 | 1,305 | 1,300 | −0.35% → **−0.11%** |
| 2015 | 1,321 | 1,337 | 1,322 | −1.01% → **+0.06%** |
| 2018 | 1,226 | 1,246 | 1,230 | −1.60% → **−0.32%** |
| 2020 | 1,173 | 1,208 | 1,188 | −5.83% → **−2.71%** |
| 2022 | 1,242 | 1,396 | 1,251 | −18.60% → **−1.30%** |
| 2024 | 1,190 | 1,259 | 1,210 | −8.26% → **−1.24%** |

It is not a patch tuned to 2022. Pre-2010 there are only 6–7 such firms in the whole NYSE
cross-section, so the screen is nearly inert historically — and it still *improves* 1990, 2015 and
2018. Verified across the full distribution, not just the median: worst-percentile error in June
2022 falls from 37.25% to **2.92%**, and 2015's whole curve is within 1.02%.

Recorded honestly: French does not publish "exclude SIC 6799" anywhere. The screen is inferred from
matching his counts and his stated intent, not from documentation. If his actual mechanism is a
CRSP vintage reclassification of SPACs — his files are built from the 202606 database, mine ends
2024-12 — the observable result is the same but the reasoning would differ.

**Residual, not chased.** June 2024 still runs −8.3% at p5 while the rest of its curve is within
3.6%. Small-cap restatement and delisting backfill between CRSP vintages is the likely cause and it
sits in the part of the distribution least able to move a value-weighted factor. Noted, not fixed.

**Question 6 — SIZ or CIZ.** Answered empirically rather than by preference. Rebuilding the same
June-2022 cross-section through CIZ (`msf_v2` + `stksecurityinfohist`, screening
`sharetype='NS'`, `securitytype='EQTY'`, `securitysubtype='COM'`, `usincflg='Y'`,
`issuertype in ('ACOR','CORP')`, `primaryexch='N'`, `conditionaltype='RW'`,
`tradingstatusflg='A'`) gives 1,419 permnos / 1,400 permcos against SIZ's 1,415 / 1,396 — and an
**identical median to one decimal place** ($2,611.8m under both).

So the format choice does not matter for the universe, which is the useful finding: **build on SIZ**
for fidelity to the published recipe and to keep the Shumway delisting adjustment explicit in our
own code rather than pre-folded into CIZ's return field, with this equivalence kept as a test.

Worth noting CIZ does *not* solve question 5 for free: all 124 SIC-6799 names inside the CIZ screen
classify as `CORP`/`COM`/`NS`/`RW`, indistinguishable from ordinary common stock. There is no
structural field for blank-check status in either format.

**Question 4 — CCM.** Confirmed unavailable and not obtainable; `crsp_a_ccm` stays denied. The
CUSIP fallback is now permanent architecture rather than a stopgap. Measured the improvement from
matching against *every* historical CUSIP a PERMNO ever carried, rather than only its current one
(June 2020, all exchanges, 3,549 securities, $30.7T):

| link key | firms | by ME |
|---|---|---|
| current `cusip` | 92.2% | 96.1% |
| `ncusip` alone | 81.9% | 94.2% |
| union of all historical | **92.9%** | **96.1%** |

The union buys +0.7pp of firms and nothing at all by market equity, so the misses are structural —
firms genuinely absent from Compustat — rather than a CUSIP-vintage artifact. Unmatched names have
a median ME of $122m against $724m for matched ones, confirming the gap concentrates in small caps.
That fixes the fallback's ceiling at roughly **93% of firms / 96% of market equity**, and linkage
becomes a measured component of the step-5 gap attribution rather than an unquantified caveat.

### 2026-08-25 — The blank-check screen, promoted from inferred to measured

The SIC 6799 exclusion was adopted on eight June cross-sections and recorded as *inferred*, because
French publishes no such rule. That was the weakest link in the universe layer, so it was tested
properly before anything was built on top of it.

**Scored on every month French publishes** — 866 of them, 1926-07 to 2024-12, against his
`ME_Breakpoints` median and firm count — and scored *against alternatives*, since a screen that
works is worth less than a screen that works better than the other candidates:

| variant | median \|err\| | p95 \|err\| | worst \|err\| | worst count diff |
|---|---|---|---|---|
| base, no exclusion | 0.17% | 4.12% | 23.63% | 171 |
| **ex SIC 6799** | **0.08%** | **1.28%** | **3.96%** | **27** |
| ex SIC 6770 | 0.17% | 4.12% | 23.63% | 171 |
| ex SIC 6770 + 6799 | 0.08% | 1.28% | 3.96% | 27 |
| ex SIC 67xx (all holding/investment) | 0.50% | 4.10% | 6.93% | 101 |
| ex company name containing "ACQUISITION" | 0.17% | 2.89% | 17.15% | 120 |

Four things this establishes that the June sample could not:

1. **6799 is the whole effect.** Adding 6770 changes nothing — the two rows are identical to the
   digit. CRSP does not use 6770 for these entities, which is why the original `677x` check came
   back empty and briefly pointed away from SPACs.
2. **It is not overfitted to 2022.** Median absolute error over 866 months is 0.08%, and the
   1920s–1980s decades run at 0.00–0.11% median error with a worst *count* difference of 2 firms.
   Sixty years of near-exact agreement is not something a patch tuned to one year produces.
3. **Broadening it is worse.** Excluding all of SIC 67xx overshoots — median count difference −18,
   median error up to 0.50% — so the boundary is at 6799 specifically, not at "investment-like".
4. **SIC beats the name heuristic.** Matching "ACQUISITION" in the company name is materially worse
   (worst error 17.15% against 3.96%), so the classification is doing real work that a string match
   does not replicate.

**Status change:** the *screen* is now a measured result, selected against alternatives on the full
published history. The *mechanism* remains unknown and is still labelled inferred — French may be
excluding these through a CRSP vintage reclassification rather than an SIC filter, and both produce
the same observable. That distinction is kept in `config.py` and the README because it is the part
that could still be wrong.

**Residual, logged rather than chased.** The 2020s decade retains a median error of −1.77% and a
median count difference of +14 firms; the worst single month is 2022-03 at −3.96% with 23 extra
firms. Every one of the twelve worst months falls in 2020–2024 and every one is negative, so this
is a systematic small-firm surplus in the recent period, not noise. It is an order of magnitude
smaller than the 18.6% it replaced. Two candidate explanations — further blank-check entities under
other SIC codes, and CRSP vintage differences against French's 202606 build — and no evidence
distinguishing them, so neither is claimed. Carried as open question 9.

### 2026-08-25 — Universe layer built and verified against live CRSP

`ffrep/universe/` exists now: four modules, 183 tests total (96% coverage, and 100% on all three
logic modules), with 18 integration tests running against the live database.

    wrds_source.py   queries only, no judgement          64% (network-only)
    screen.py        which securities are a firm         100%
    delisting.py     Shumway's -30%                      100%
    linker.py        PERMNO -> GVKEY and its cost        100%

**The layering rule is Project 01's, deliberately.** Extraction may not transform; transformation
may not reach the network. Every decision that could be wrong in an interesting way is a pure
DataFrame function testable against a hand-built cross-section, and `wrds_source.py` is left
carrying as little judgement as possible because it can only ever be integration-tested. Its 64%
coverage is the network paths and is expected to stay that way.

**Tests are hand-computable by design.** `10 dollars x 1,000 thousand shares = $10m` is checkable
in your head; a fixture of realistic-looking noise is not. The failure mode this layer guards
against is not a crash but a plausible wrong answer, and only a case whose correct output you
already know can catch one. Same reasoning as Project 02's synthetic cross-sections.

**Two orderings that are load-bearing**, both covered by a named test:

* The share screen must run *before* company aggregation. Aggregating first would fold a SPAC's
  market equity into a legitimate company's total and then never look at its SIC again —
  `test_screen_runs_before_aggregation`.
* PERMCO ties break on the lower PERMNO. An arbitrary rule is fine; a *nondeterministic* one makes
  the whole build irreproducible, which is the same reasoning as Project 02's event-queue sequence
  counter — `test_ties_break_deterministically_on_lower_permno`.

**`CcmLinker` raises instead of falling back.** It would have been easy to make it silently
degrade to CUSIP. It doesn't: if CCM access ever appears, the failure should be loud and at the
seam rather than a quiet difference in results six steps downstream.

**Found while writing the tests: SIZ and CIZ disagree about ~20 firms' SIC codes.** `msf_v2.siccd`
is the *current* header classification; `msenames.siccd` travels with the name record and is
point-in-time. After the blank-check exclusion the two formats give 1,276 vs 1,255 NYSE companies
and medians 2.4% apart, where before the exclusion they agreed to one decimal place. This is an
additional argument for SIZ that question 6 did not anticipate: its SIC is the value that was true
at the time, and applying today's industry code to a 1990 cross-section is the same class of
lookahead that Project 01 exists to prevent. The integration test asserts the 5%/30-firm envelope
and documents the reason rather than tuning the tolerance until it passed.

**Acceptance, on live data rather than claimed:** the NYSE median tracks French's published value
within 5% at every June from 1990 to 2022, the firm count within 30, and the full percentile curve
for June 2022 within 6% at p10 through p90. Two tests assert that the corrections *matter* —
that removing the blank-check exclusion moves 2022 by more than 10%, and that company aggregation
moves June-2000 closer to French — so a regression that quietly drops either one fails rather than
passing with a worse number.

WRDS tests are opt-in behind `FFREP_WRDS_TESTS=1` plus `WRDS_USERNAME`, and skip when credentials
are absent, so a fresh clone with no subscription still runs green.

### 2026-08-25 — Step 2: sort machinery, and breakpoints promoted from borrowed to derived

`ffrep/construct/` exists. 266 tests, 97% coverage, all three construct modules at 100%.

    sorts.py        characteristics and 2x3 bucket assignment
    portfolios.py   value-weighted returns with weights that drift on retx
    factors.py      six portfolios into SMB and HML

**Breakpoints can be derived.** This was the README's largest standing
limitation and it is now a choice rather than a constraint. Comparing breakpoints computed from our
screened CRSP universe against French's published `ME_Breakpoints`, over **544 months and every
percentile he reports** — 10,336 (month, percentile) pairs:

| | value |
|---|---|
| median error | **−0.000%** |
| mean absolute error | 0.508% |
| 95th percentile absolute error | 2.042% |
| within 1% | 85.7% of pairs |
| within 2% | 94.7% of pairs |
| size breakpoint (p50) alone | 0.389% mean absolute error, 89.0% within 1% |

Error is smallest in the middle of the distribution (0.33–0.42% mean absolute from p50 to p70) and
largest in the small tail (1.08% at p5), which is the expected shape — the bottom percentiles sit
where the firm density is highest and a handful of universe differences move the value most.

**The interpolation convention was measured, not assumed.** The first implementation used linear
interpolation because it is the numpy default, which is exactly the kind of unexamined choice this
project is supposed to avoid. Scoring all five numpy conventions against French over **1960–1989** —
chosen because CRSP data that old cannot plausibly have been restated, so vintage differences
cannot confound the comparison:

| method | median error | mean \|error\| | within 0.5% |
|---|---|---|---|
| **lower** | **0.0000%** | **0.2240%** | **85.0%** |
| nearest | 0.0049% | 0.2458% | 83.2% |
| linear | 0.0886% | 0.2774% | 83.2% |
| midpoint | 0.1076% | 0.3094% | 80.8% |
| higher | 0.1943% | 0.3971% | 72.2% |

`lower` is unbiased to four decimal places where every alternative is not, and its median absolute
difference from French is **$0.0048m — inside the $0.005m half-ulp of his own two-decimal
reporting**, so for half of all pairs the two agree as closely as his published precision can
express. Switched the default and pinned it in `config.py` with the table.

It also makes the bucket edges coherent rather than arbitrary: `lower` returns an actual firm's
market equity, and that firm belongs in the bucket at or below the breakpoint — which is precisely
the inclusive-lower-edge rule the sort uses. Two conventions that were independently chosen turn
out to be the same convention, which is weak evidence that both are right.

**The drift asymmetry, stated as a number.** Weights drift on `retx` (ex-dividend) because market
capitalisation grows by price appreciation only; returns accrue on `ret` because the holder
receives the dividend. Using `ret` for both is the natural mistake and it compounds across a
twelve-month holding period, progressively overweighting high-dividend firms — and dividend yield
correlates with value, so the error lands disproportionately on HML. `test_drift_uses_retx_not_ret`
constructs a case where the correct answer is 0.05 and the wrong convention gives 0.0545, so the
distinction is proven to matter rather than merely asserted.

**A docstring that overstated the code, found by re-reading it.** `portfolios.py` claimed "a firm
whose return is missing has its weight dropped from that month forward". The implementation
actually treats the two kinds of missing differently: missing `retx` ends the position permanently
(there is no defensible weight to carry), while missing `ret` only excludes the firm from that
month. Both are defensible; conflating them in prose is not. Corrected, and both behaviours pinned
by `TestMissingKindsAreDistinct`.

**WRDS connection retry.** The server intermittently refuses the first connection of a session —
seen twice. The `wrds` package responds by falling back to an interactive `input()` prompt, which
under a script raises `EOFError` from inside the library and killed a 30-minute validation run.
`connect()` now retries and treats `EOFError` as what it actually is: this library's way of
reporting a failed handshake, not real end-of-input. Six tests cover it against a fake module, and
`wrds_source.py` coverage went 64% → 86% as a result.

#### What is verified, and what is not

Distinguishing these is the point, so they are separated explicitly.

**Verified against an external reference:** the universe screen, the derived breakpoints, the
interpolation convention, and the market-equity computation. All measured against French's
published files or CRSP's own `mthcap` field, over decades rather than sample points.

**Verified only against hand computation:** the 2x3 bucket assignment, the drift arithmetic, the
factor algebra, and the missing-data semantics. These are correct implementations of what they are
documented to do, on cross-sections small enough to check by eye. That is a weaker claim than the
above — it establishes internal consistency, not agreement with French.

**Not verified at all, and not yet verifiable:**

* **The construct layer has never run on real data.** BE/ME needs the Compustat extract, which has
  not been pulled. Every construct test uses synthetic input. Implemented is not verified.
* **The inclusive-lower-edge bucket convention** is coherent with the measured `lower` quantile
  method but has never been checked against French's own portfolio assignments. With continuous
  data exact ties are near-measure-zero, so the empirical cost is expected to be negligible — but
  "expected" is the operative word.
* **The `retx` drift convention** is proven to differ from the alternative and matches the
  documented Fama-French method, but has not been validated against French's published portfolio
  *returns*. That is step 4's job and is the first real test of this layer.

**Inherited residual.** Derived breakpoints carry open question 9 forward: the 2020s decade shows
1.90% mean absolute error against 0.21–0.37% for the 1960s–1980s, tracking the same unexplained
+14-firm surplus. Deriving breakpoints does not fix it and was never going to.

### 2026-08-26 — Book equity, and a cutoff French does not document

**Written retroactively on 2026-09-02.** The code and its validation run landed on 2026-08-26 and
the entry was never written; what follows is reconstructed from the working tree, the validation
script and the measured numbers pinned in `config.py` and the module docstring. The dead ends are
therefore thinner here than in the entries above, which is exactly the cost the append-as-you-go
rule exists to avoid.

`ffrep/construct/book_equity.py` exists: BE, operating profitability and investment from Compustat
annual. 100 new tests (55 unit, 34 live-Compustat integration, 11 for the widened extract queries),
bringing the suite to **333 passing / 57 skipped, 98% coverage**, `book_equity.py` at 100%.

#### The definition is three nested hierarchies in one English sentence

Davis, Fama and French (2000) state it as prose; as code it is::

    BE = SE + DT - PS
    SE = SEQ, else CEQ + PSTK, else AT - LT
    PS = PSTKRV, else PSTKL, else PSTK
    DT = TXDITC

Measured how often each fallback actually fires, on this subscription's 443,461 firm-years carrying
any balance-sheet data (1950–2026):

| SE branch | share | | PS branch | share |
|---|---|---|---|---|
| `SEQ` | 95.79% | | `PSTKRV` | 99.19% |
| `CEQ + PSTK` | 0.74% | | `PSTKL` | 0.12% |
| `AT − LT` | 2.57% | | `PSTK` | 0.51% |
| unavailable | 0.89% | | unavailable | 0.19% |

At those rates the hierarchies look like defensive padding, and that reading is wrong. In the 1950s
`seq` is missing on **98.7%** of rows, so `AT − LT` carries essentially the whole decade; by 1970
`seq` is missing on 3.3%. Dropping the hierarchy would not degrade the early sample, it would
delete it. Worth having measured rather than assumed, because the cheap version of this module —
`seq + txditc - pstkrv` — is indistinguishable from the correct one on a recent cross-section.

#### The finding: French stops adding deferred taxes after fiscal 1992, and says so nowhere

His definition carries no date qualifier and his variable-definitions page states none. His
published `BE-ME_Breakpoints` do. Scored against every percentile he publishes, split at the break:

| book equity definition | formation 1963–1993 | formation 1994–2024 |
|---|---|---|
| `SE + DT − PS` (always add, as stated) | 3.42% | 8.69% |
| `SE − PS` (never add) | 10.64% | 0.96% |
| DT through FY1992, none after | **3.42%** | **0.96%** |

It is a step, not a drift: mean absolute error runs 1.05% for formation 1993 and 9.91% for 1994
under "always add", and 10.08% then 0.61% under "never add". Scanning the cutoff over FY1988–FY1998
gives a clean single minimum:

| cutoff FY | 1989 | 1990 | 1991 | **1992** | 1993 | 1994 | 1995 |
|---|---|---|---|---|---|---|---|
| mean \|err\| | 2.39% | 2.03% | 1.55% | **1.12%** | 1.56% | 1.99% | 2.44% |

**The cutoff is measured; the reason for it is inferred.** SFAS 109 was issued February 1992 and
takes effect for fiscal years beginning after 15 December 1992 — the first affected fiscal year end
for a calendar-year filer is December 1993, which is exactly where the break lands. That is
suggestive and it is not proof. The alternative — that Compustat's `txditc` changed meaning rather
than French's use of it — is not separable with the data here. The fit does rule out the trivial
version of that alternative: if `txditc` were simply absent after 1992 the two definitions would
coincide, and they differ by 8pp.

Recorded the same way as the SIC 6799 screen, and for the same reason: the *observable* is
established on decades of published data, the *mechanism* is a hypothesis, and conflating the two
is how a replication acquires a confident wrong story. Both live in `config.py` next to the
constant they justify, so the next reader meets the evidence before the number.

Searched for prior art before claiming it: nothing states this cutoff. It is the kind of thing that
is presumably folk knowledge inside shops that do this for a living, and it is not written down
where a free search finds it.

#### With the cutoff in, the residual is linkage rather than accounting

Shipped definition against the published NYSE BE/ME breakpoints, 1975–2024: **1.08% mean absolute
error, −0.22% median bias.** The error decomposes by data availability, not by year:

* **2016–2024**, where the CUSIP match rate is 97–98%: 0.6–1.6%.
* **1963–1971**, where Compustat covers 55–78% of NYSE and French is using hand-collected Moody's
  book equity that is not purchasable at any price: 4–13%.

So the remaining gap sits where the *inputs* are missing, which is the shape you want — it says the
formula is right and the panel is short, rather than the reverse. Pre-1975 is reported by the script
but excluded from the summary for that reason.

Two independent checks beyond the percentiles, both of which the formula could fail while leaving
the percentiles intact:

* **The BE ≤ 0 count.** French publishes it separately. Percentiles are computed from positive
  values only, so a systematic sign error would move this count and nothing else. Asserted within 12
  firms.
* **The firm-count shortfall.** We are always *short* of French, never over, and the shortfall is
  bounded at 80 NYSE firms. Stated as a shortfall rather than a tolerance so it cannot be misread as
  agreement — it is the CUSIP linkage's cost showing up in a second place, consistent with the
  92.9%/96.1% measured in the universe layer.

#### The year label, settled empirically rather than assumed

A `BE-ME_Breakpoints` row is stamped with the **formation year t**, not the accounting year *t−1*.
Getting this backwards shifts every breakpoint by one year and still produces a full, plausible
table — no crash, no missing data, just a silently wrong answer, which is the failure mode this
whole project is organised against. Tested both readings: the formation-year reading wins by an
order of magnitude, and the medians settle it outright — our accounting-year-1976 median BE/ME
equals French's 1977 row to three decimals. Pinned by `TestYearLabel`.

#### Three smaller decisions, each of which was a fork

* **`datadate.year`, not Compustat's `fyear`.** They disagree on 13.3% of rows — every fiscal year
  ending January through May, which Compustat labels with the *previous* calendar year. French's
  rule is "the fiscal year ending in calendar year t−1", which is the year of the end date. Using
  `fyear` would match a May-1990 fiscal year to a June-1990 formation: one month after the fiscal
  year closed and months before the annual report existed. That is lookahead of exactly the kind
  Project 01 exists to prevent, and it would have been invisible in the output.
* **Empty records are dropped *before* the one-record-per-year selection.** 16.1% of `INDL`/`STD`
  rows carry no balance-sheet data at all. A blank row with a later `datadate` would otherwise win
  the "last fiscal year end in the calendar year" tie-break and displace a populated one, turning a
  usable firm-year into a missing one for reasons nothing downstream would surface. Checked whether
  they are financial-format filers hiding under the wrong `indfmt`: only 32 of 85,112 have a
  populated `FS` row at the same gvkey and date, so they are placeholders, not a coverage gap.
* **A missing cutoff raises rather than defaulting.** `deferred_taxes` needs `datadate` to apply the
  cutoff and raises `KeyError` without it. A silently un-applied cutoff is an 8-percentage-point
  error that leaves no trace in the output — the same reasoning as Project 02's refusal to skip a
  same-timestamp order.

Two conventions the published sentence does not settle are exposed as keyword arguments rather than
hardcoded, so step 5 can ablate them instead of arguing about them: reconstructing `TXDITC` from
`TXDB + ITCB` when the combined field is missing (9.7% of non-blank rows, of which 22,147 have a
component), and treating all-missing preferred stock as zero (824 firm-years, 0.19%).

#### A pandas trap worth the line it costs

Compustat's total-assets field is named `at`, which collides with `DataFrame.at`, the scalar
indexer. `frame.at` silently returns the indexer rather than the column and fails later with an
unrelated-looking `AttributeError`. Every access in the module is `frame["at"]`.

#### Extract changes this required

`fetch_fundamentals` takes an optional window now — the validation wants all 528,573 firm-years back
to 1950, because comparing against breakpoints French publishes from 1926 on a bounded window would
be answering an easier question. `fetch_nyse_month_ends` is new: June and December cross-sections
over all of CRSP, exchange filtered in SQL. 318,114 security-months against roughly 1.9m for every
month, which is the difference between a whole-history validation that runs interactively and one
that does not.

#### What this does and does not establish

**Verified against an external reference:** the book-equity formula, the deferred-tax cutoff, the
year label, and the BE ≤ 0 count — all against French's published breakpoint files, over five
decades.

**Implemented and hand-tested only:** operating profitability and investment. `validate_book_equity.py`
scores both against `OP_Breakpoints` and `INV_Breakpoints` in percentage points, but **the numbers
were not recorded and no integration test asserts them.** BE/ME got the full treatment and RMW/CMA's
inputs did not. That is an honest gap, not a claim, and it is carried as open item 9 — it costs one
script run to close.

**Still not verified:** the sort machinery downstream of this. BE now exists on real data, so the
blocker named in the step-2 entry is gone — but nothing has yet joined book equity to the June
cross-section and produced a portfolio. That join is the last missing piece of step 3.

## Open questions

1. ~~**WRDS / CRSP / Compustat access — requested, approval pending.**~~ **Approved 2026-08-24.**
   The account exists. What is *not* yet known, and is now the highest-information unknown:

   - **Which products the subscription covers.** CRSP, Compustat and the CCM link table are all
     required; an institution may subscribe to some and not others.
   - **Which CRSP format is served** — legacy SIZ (`crsp.msf` / `msenames` / `msedelist`) or the
     newer CIZ (`crsp.msf_v2` / `stksecurityinfohist`). CIZ folds delisting returns into the
     return field and replaces the `shrcd`/`exchcd` screens with share-type flags, so the extract
     code differs materially between them.
   - **Whether Compustat Point-in-Time is included.** Standard `comp.funda` is *restated*, so
     replicating French faithfully means inheriting his restatement lookahead. Worth knowing which
     side of that line the project is on.

   **All three answered by the 2026-08-24 reconnaissance above:** CRSP yes (both SIZ and CIZ,
   through 2024-12), Compustat yes, **CCM link table no**, Point-in-Time no.

   Sequencing steps 1–2 first proved correct: step 1's result is measured on French's published
   portfolios, so it survives the answer intact rather than being invalidated by it.

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

4. ~~**Can CCM access be added?**~~ **Closed 2026-08-25 — no.** `crsp_a_ccm` is not in the
   subscription and will not be added. The PERMNO↔GVKEY join is permanently an 8-character CUSIP
   match, measured at 92.9% of firms / 96.1% of market equity against every historical CUSIP.
   Consequence for the design: linkage is a first-class, *measured* gap component in step 5, and the
   extract layer gets a `Linker` seam so the assumption is isolated and testable rather than
   diffused through the construction code.

5. ~~**Why do ~150 extra NYSE names appear from 2018 onward?**~~ **Closed 2026-08-25.** A screen
   defect in my code: CRSP tags blank-check/SPAC entities with SIC 6799 and `shrcd` 11, so they pass
   an ordinary-common-shares filter. Excluding SIC 6799 reproduces French's counts to within 9 firms
   in 2022 and improves every historical year. See the 2026-08-25 entry.

6. ~~**Which CRSP format to build on, SIZ or CIZ?**~~ **Closed 2026-08-25 — SIZ.** The two were
   verified to produce an identical NYSE median for June 2022, so the choice is free on the merits
   and goes to fidelity with the published recipe plus an explicit Shumway adjustment. The CIZ
   equivalence is kept as a regression test.

9. **What drives the residual +14 NYSE firms in the 2020s?** After the blank-check exclusion the
   median error is −1.77% for the 2020s decade against ≤0.11% for 1926–1989, and all twelve worst
   months are 2020–2024 and all negative. Systematic, small, and unexplained. Candidates: more
   blank-check entities under other SIC codes, or CRSP vintage differences against French's 202606
   build. No evidence separates them; do not guess in code.

7. **Does the SIC 6799 screen belong at the universe layer or the sort layer?** It changes the
   breakpoint universe, so it must apply before breakpoints are computed. Open only as a question of
   where it lives in the code, not whether it applies.

10. **Why does French stop adding deferred taxes after fiscal 1992?** The cutoff itself is measured
    and settled — FY1992, a clean single minimum, 8pp of error either side of it. The *mechanism* is
    not. SFAS 109 takes effect for fiscal years beginning after 15 December 1992, which is exactly
    where the break lands, but a change in what Compustat's `txditc` means would produce the same
    observable and the two are not separable with the data here. Same epistemic status as the SIC
    6799 screen, and recorded the same way. Do not let the SFAS 109 story harden into a claim.

11. **Does the formation join belong in `construct/` or at a seam of its own?** It has to reach
    across the layer boundary — CRSP June and December cross-sections from `universe/`, book equity
    from `construct/`, the CUSIP linker between them — and the layering rule says extraction may not
    transform. The join is pure transformation over frames both layers already produced, so
    `construct/formation.py` is the presumption, but the alternative is a thin `pipeline/` that owns
    cross-layer assembly and keeps `construct/` free of universe concepts.

## Status against the done criterion

| Requirement | State |
|---|---|
| Published reference series downloaded and parsed | **Done, verified** — 11 French files, all 5 breakpoint shapes |
| Factor algebra reproduces published HML/SMB | **Done, verified** — 0.5 bps, French's own rounding floor |
| Ceiling on a truncated universe established (step 1) | **Done** — 0.92 big-only; analytic and empirical agree |
| CRSP universe screen reproduces French's NYSE cross-section | **Done, verified** — within 1.3% of the published median and 9 firms in 2022; 18 live-CRSP tests |
| PERMNO↔GVKEY linkage | **Done, measured** — CUSIP fallback at 92.9% of firms / 96.1% of ME; CCM unavailable |
| Delisting returns (Shumway 1997) | **Implemented, unit-tested** — not yet exercised on a full panel |
| 2×3 size × BE/ME sorts, NYSE breakpoints (step 2) | **Implemented, hand-verified** — 100% covered; never run on real data |
| NYSE breakpoints derived rather than borrowed | **Done, verified** — median error −0.000% over 544 months and every published percentile |
| Quantile convention matched to French | **Done, measured** — `lower`, selected against 4 alternatives on 1960–1989 |
| Book equity from Compustat (SE + DT − PS) | **Done, verified** — 1.08% mean abs error vs published BE/ME breakpoints, 1975–2024 |
| Deferred-tax cutoff matched to French | **Done, measured** — FY1992, single minimum; undocumented by him |
| Operating profitability and investment | **Implemented, hand-tested** — scored by the script but the numbers are unrecorded and unasserted |
| June formation on prior-December accounting | **Partially** — `for_formation_year` selects the records; nothing joins them to the June cross-section |
| SMB, HML, UMD, RMW, CMA constructed bottom-up | Not started |
| Correlation with French's published factors > 0.99 | **Unreachable as specified.** Ceiling measured at 0.917 (large-cap) — see step 1 |
| q-factor model + spanning tests | Not started (GRS test implemented and tested) |

## Open items

1. ~~**Decide the data question (open question 1) before step 3.**~~ **Answered 2026-08-24** —
   WRDS approved. Replaced by a narrower prerequisite: confirm subscription coverage and CRSP
   format before writing any extract layer.
2. ~~**Project 01's `CORE_TAGS` needs extending**~~ **Closed 2026-08-25 — moot for this project.**
   `comp.funda` is confirmed readable with all 949 columns, and supplies `TXDITC` and the
   `PSTKRV`/`PSTKL`/`PSTK` hierarchy directly; `FUNDA_FIELDS` in `wrds_source.py` pulls them. It
   remains a genuine gap in Project 01's own repo, where it is that project's open item.
3. ~~**Project 01's full bootstrap is a hard prerequisite**~~ **Closed 2026-08-25 — moot for this
   project.** CRSP replaces it as the price source, which also removes the delisted-price gap
   Project 01 could not close (yfinance serves no history for delisted tickers). It remains
   Project 01's own open item 10.
4. **global-q.org fetch times out.** Needed only for step 6. The URL carries a `2024` in its
   filename and may have moved; check when that step starts.
5. **`evaluate/regression.py` is at 93%** — the uncovered lines are `OLSResult.summary()` and one
   GRS branch. Cosmetic, but `summary()` is the path a human reads results through, so it should
   not stay untested.
6. ~~**Nothing committed.**~~ **Closed 2026-08-15.** Committed in layers on top of the remote's
   `2461c42 Initial commit`: scaffold, reference layer + step 1, universe layer, blank-check screen,
   sort machinery, WRDS retry, derived breakpoints, and book equity. Everything through
   `ced1c6f` is pushed to `origin/main`; the book-equity commit is local and awaiting a push.

7. **The universe layer has never been run over the full *monthly* history.** Partially closed on
   2026-08-26: `fetch_nyse_month_ends` pulled June and December cross-sections over all of CRSP
   (318,114 security-months) and `fetch_fundamentals` pulled all 528,573 Compustat firm-years, so
   the extract path is exercised at scale for the annual sorts. What is still unpulled is the
   **full monthly** panel — roughly 4.8M `msf` rows — which step 4 needs for the twelve monthly
   returns between rebalances and which no test has touched. Same distinction Project 01 draws:
   implemented is not verified.

8. ~~**Derive NYSE breakpoints rather than borrowing French's.**~~ **Closed 2026-08-25.** Done and
   validated over 544 months and every published percentile; median error −0.000%. His files are
   retained as the validation reference, which is the right role for them, and the README's
   borrowed-breakpoints limitation is retired.

9. **OP and INV are scored but their numbers are not recorded.** `validate_book_equity.py` compares
   both against `OP_Breakpoints` and `INV_Breakpoints` in percentage points and prints a per-decade
   table; nothing captures the output and no integration test asserts a bound, so RMW's and CMA's
   sort variables sit at a weaker standard of evidence than BE/ME. One script run closes it, and it
   should be closed before step 6 builds on them.

10. **The formation join does not exist.** `for_formation_year` picks the right accounting records
    and `FormationInputs` names the three series a formation needs (`me_june`, `me_december`,
    `book_equity`), but nothing constructs one from CRSP and Compustat. This is the single piece
    standing between the current tree and step 4's first bottom-up HML series. See open question 11
    for where it should live.

11. **The full monthly CRSP extract has not been pulled.** Step 4 needs it and it is the one
    remaining large pull — a few hundred MB of Parquet into the gitignored `data/processed/`.
