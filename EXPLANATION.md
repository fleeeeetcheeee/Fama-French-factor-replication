# What We Built and How It Works
### A Beginner-Friendly Explanation

---

## The Big Picture

When a fund manager says "our stock picks beat the market by 3% a year", the first question a
serious investor asks is: *was that skill, or did you just own cheap stocks and small companies?*
Cheap stocks and small companies have historically earned higher returns on their own, so a manager
who simply leans that way will look skilled without being so.

To answer the question you need yardsticks — return series that capture "what cheap stocks did",
"what small stocks did", and so on. The standard yardsticks were built by the economists Eugene
Fama and Kenneth French, and French publishes them free on his website. They are called
**factors**. Almost every piece of equity research is checked against them.

This project rebuilds those yardsticks from scratch — from the raw prices of every US stock since
the 1920s and the raw balance sheets of every company since the 1950s — and checks the rebuild
against French's published numbers. The target was a correlation above 0.99 with his value factor
(HML) over 1990–2020. The rebuild reaches **0.9954**.

Why rebuild something you can download? Because you cannot defend a number you cannot produce.
Rebuilding forces every hidden decision into the open — which stocks count, which accounting figure
is "book value", what happens when a company goes bankrupt mid-month — and each of those decisions
turns out to move the answer.

---

## What a Factor Actually Is

Take the value factor, **HML** ("High Minus Low"). Every June:

1. Rank all companies by **book-to-market**: the accounting value of the company (from its balance
   sheet) divided by what the stock market says it is worth. A high ratio means the market prices
   the company cheaply relative to its books — a "value" stock. A low ratio is a "growth" stock.
2. Also split companies into **small** and **big** by market value.
3. That gives six groups: small-growth, small-neutral, small-value, big-growth, big-neutral,
   big-value.
4. For the next twelve months, track the return of each group, weighting each company by its size.
5. HML each month = average of the two value groups − average of the two growth groups.

So HML answers: "this month, how much did cheap stocks beat expensive ones?" The other factors are
the same recipe with a different ranking: **SMB** (small minus big), **RMW** (profitable minus
unprofitable), **CMA** (companies that invest conservatively minus those that invest aggressively),
and **UMD** (recent winners minus recent losers, re-ranked every month).

---

## The Details That Decide Everything

The recipe above sounds simple. Each step hides a choice, and getting any of them wrong produces a
number that *looks* right — correlating 0.95 or 0.98 with the real thing — and isn't.

### "Small" is measured against the New York Stock Exchange only

The dividing lines between small and big, and between growth, neutral and value, are computed from
**NYSE companies only** and then applied to every company on NYSE, AMEX and NASDAQ. NASDAQ is full
of tiny companies; if they helped set the dividing line, "small" would mean "microscopic". The
code computes these lines itself and checks them against the ones French publishes: they agree to
within 0.5% on average over 544 months.

### Book value comes from last year, market value from December

A company's June ranking uses the balance sheet from the fiscal year that ended the *previous*
calendar year, divided by the stock market value at the end of the *previous December*. This
ensures the accounting numbers were actually public when the ranking was made — using this year's
balance sheet in June would mean using information investors did not have yet.

### "Book value" has a 30-year-old footnote

French defines book value as shareholders' equity, plus a tax-related balance sheet item called
deferred taxes, minus preferred stock. But after an accounting-rule change (FASB 109), he stopped
adding deferred taxes for fiscal years from 1993 on. His definitions page does not say so; his
change log does. This project first found the break by testing the formula against French's
published numbers year by year — and then found the change note. Applying the definition literally,
without the cutoff, drops the correlation from 0.995 to 0.975.

### Blank-check companies are not companies

During the 2020–2022 boom in SPACs ("special purpose acquisition companies" — shells that raise
money to buy a business later), hundreds of them listed on the NYSE as ordinary shares. Counting
them as real firms dragged the NYSE's "median company size" 18% below French's in 2022. Excluding
the industry code they are filed under reproduces French's firm counts almost exactly, across 98
years of his data.

### Bankrupt companies still count

When a company is delisted — bankrupt, merged, or kicked off the exchange — its last loss is
recorded in a separate file. If you ignore that file, failing companies simply vanish from your
portfolio with their final losses uncounted, which flatters exactly the cheap, distressed stocks
the value factor holds. The code adds those final returns back, including the two-thirds of
delistings whose last loss falls in a month *after* the stock's final regular price. (Measured at
the factor level, this turns out to matter less than a basis point a month — but it is the right
arithmetic, and the test suite now proves it.)

### Connecting prices to balance sheets

Stock prices (from CRSP) and balance sheets (from Compustat) come from two different databases
with two different ID systems. The official bridge between them is a separate subscription this
project does not have. Instead, companies are matched through **CUSIPs** — the nine-character IDs
printed on every security. Using every CUSIP any share class of a company ever had, and every
security Compustat records, links the large majority of companies — but not all, and the unmatched
ones skew small. This is the largest remaining source of difference from French.

---

## How Close Is Close?

| Factor | What it measures | Correlation with French, 1990–2020 |
|---|---|---|
| Mkt-RF | the stock market minus cash | 1.0000 |
| SMB | small minus big | 0.9981 |
| **HML** | **cheap minus expensive** | **0.9954** |
| RMW | profitable minus unprofitable | 0.9928 |
| CMA | conservative minus aggressive investment | 0.9923 |
| UMD | recent winners minus recent losers | 0.9997 |

A useful reference point: French rebuilt his own factors in 2025 when the price database changed
format. His new HML and his old HML correlate at **0.9991**. So even the author, using the same
companies, lands a little under 1.0 when the underlying data shifts — which is why 0.9954 should be
read against 0.9991, not against a perfect 1.

To find out *where* the remaining gap comes from, the project rebuilds HML several times, changing
one decision each time, and records how the correlation moves. That table is in the README.

---

## The Second Model: q-Factors

Fama and French are not the only yardstick. In 2015 Kewei Hou, Chen Xue and Lu Zhang proposed the
**q-factor model**, built from a different economic argument: companies invest more when their
cost of capital is low, so investment and profitability should explain returns. Its profitability
measure uses *quarterly* earnings, and only once they have been publicly announced — which requires
the actual announcement date of every earnings report.

The project builds those factors too and runs **spanning tests**: can one model explain the other's
factors? The answer matches the published research. The q-model's profitability factor earns about
0.4% a month that the Fama-French model cannot explain, while the q-model explains every
Fama-French factor, including momentum. The same conclusion comes out of French's and HXZ's
published numbers and out of the rebuilt ones.

---

## How the Code Is Organised

```
reference/   read the published files we compare against (French, global-q, Moody's)
universe/    turn raw CRSP prices into a clean monthly panel of real companies
construct/   book value, rankings, the June formation, portfolios, factors
qfactor/     the quarterly profitability and the q-factor sort
evaluate/    how close is close: correlations, regressions, the GRS test
pipeline.py  plugs the layers together
```

Every step that can be wrong in an interesting way is a function tested on a tiny, made-up market —
four or six companies — where the right answer can be worked out by hand. Then the whole thing is
checked against French's real published numbers.

---

## The Scripts

| Script | What it does |
|---|---|
| `fetch_reference_data.py` | download French's files, the Moody's book values and the q-factors |
| `extract_wrds.py` | pull CRSP and Compustat into local files (needs a WRDS subscription) |
| `build_factors.py` | build every factor and compare it with French |
| `attribution.py` | rebuild with one decision changed at a time |
| `validate_characteristics.py` | check book-to-market, profitability and investment against French's dividing lines |
| `build_qfactors.py` | build the q-factors and run the spanning tests |

---

## What This Does Not Claim

- **These are not trading results.** The balance-sheet database has been corrected after the fact,
  so some numbers used here were not exactly what investors saw at the time. French's factors share
  that property; matching him means inheriting it.
- **The early decades fit less well.** Before 1990 the balance-sheet database covers fewer
  companies, and the profitability and investment factors correlate around 0.97–0.98 with French's.
- **The q-factors start in 1972**, not 1967, because extending them earlier needs estimation steps
  that are not built.

---

## Quick Reference: Key Terms

| Term | Meaning |
|---|---|
| **Factor** | A return series capturing one systematic pattern (value, size, momentum...) used as a yardstick |
| **HML / SMB / RMW / CMA / UMD** | Value, size, profitability, investment and momentum factors |
| **Book-to-market** | Accounting value ÷ stock-market value; high means "cheap" |
| **Breakpoint** | The dividing line between groups (e.g. the NYSE median size) |
| **NYSE breakpoints** | Dividing lines computed from NYSE stocks only, then applied to all stocks |
| **Value-weighted** | Each stock counts in proportion to its market value |
| **CRSP** | The standard academic database of US stock prices and returns |
| **Compustat** | The standard database of company financial statements |
| **CUSIP** | A nine-character identifier for a security, used here to connect the two databases |
| **PERMNO / PERMCO / GVKEY** | CRSP's security ID, CRSP's company ID, Compustat's company ID |
| **Delisting return** | The final return of a stock that leaves the exchange, stored separately |
| **Deferred taxes** | A balance-sheet tax item French stopped adding to book value from fiscal 1993 |
| **Moody's book equity** | Hand-collected balance-sheet values for early decades, published by French |
| **SPAC / blank-check company** | A shell company listed to acquire a business later; excluded here |
| **Correlation** | How closely two series move together; 1.0 means in lockstep |
| **Tracking error** | The typical monthly size of the difference between two series |
| **Spanning test** | Asks whether one model's factors explain another's returns |
| **GRS test** | A joint test that several unexplained returns ("alphas") are all zero |
| **Vintage** | A particular release of a database; later releases include corrections |
