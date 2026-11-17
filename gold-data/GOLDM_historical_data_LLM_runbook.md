# GOLDM Historical Data Retrieval --- LLM Agent Runbook

**Goal:** Retrieve genuine public MCX GOLDM (Gold Mini, 100 g)
historical daily data and deliver validated CSV files.

**Target period:** 17 November 2025 through 16 November 2026,
inclusive.\
**Timezone:** Asia/Kolkata (IST, UTC+05:30).\
**Requested interval:** Daily candles only.\
**Price convention requested:** ₹ per 10 grams. Preserve the exchange's
original quoted price and document any verified conversion; never assume
a conversion.\
**Authentication:** Do not use the user's FYERS account or ask for
credentials. Use public sources only.

------------------------------------------------------------------------

## 1. Instructions to the LLM / research agent

You are a data-retrieval and validation agent. You must actually
retrieve the source files, parse them, create the CSV outputs, and
provide downloadable file links. Do not merely describe how the user
could do it.

### Non-negotiable rules

1.  Use public, legally accessible sources only. Prefer official MCX
    files. An independent archive may be used as a secondary source or
    when official bulk retrieval is impractical.
2.  Do not fabricate rows, prices, volume, open interest, symbols,
    expiries, lot sizes, tick sizes, listing dates, or missing records.
3.  Do not claim a file is complete unless you have downloaded and
    validated its underlying records.
4.  Do not replace missing candles with zero. Keep missing
    dates/contracts explicitly reported.
5.  Preserve source values and source column names in a raw-data copy.
    Normalize into the requested schema only after mapping each field.
6.  Do not silently combine GOLD (1 kg) with GOLDM (100 g). Filter the
    exact GOLDM underlying/instrument and verify instrument identifiers.
7.  Include expired contracts whenever their historical daily records
    are publicly available.
8.  If a source does not expose a requested field (for example listing
    date, lot size, tick size, or open interest), leave it blank and
    report the gap. Do not infer it.
9.  Do not treat a current contract master as a historical contract
    master. Listing and delisting dates require historical exchange
    records or another verifiable source.
10. Cite/link every source used and record retrieval timestamps, URL,
    HTTP status, and file hash where possible.
11. The requested end date is 16-Nov-2026. Verify whether the exchange
    has published that day's bhavcopy. If not, mark it
    pending/unavailable; do not substitute the previous session and call
    it complete.
12. Do not stop after the first endpoint failure. Try the official MCX
    download interface, its downloadable files, and the public archive
    independently. If one source is inaccessible, explain exactly which
    source failed and continue with the others.

------------------------------------------------------------------------

## 2. Public sources to investigate

Start with these URLs, but verify that each is live and that its
contents match the expected data before relying on it.

-   MCX official bhavcopy page:
    https://www.mcxindia.com/market-data/bhavcopy
-   MCX official contract-available-for-trading page:
    https://www.mcxindia.com/market-data/contractavailablefortrading
-   Public MCX archive API previously identified:
    https://mtf.trading/api/v1/mcx
-   Public archive date index previously identified:
    https://mtf.trading/mcx/index.json

The MTF archive is an independent source, not the exchange. Verify its
current schema, date coverage, pagination, rate limits, and terms before
downloading. Do not assume an endpoint or parameter works merely because
it appears in this runbook.

### Suggested archive query patterns to test

Test one known trading date first, such as 2026-10-15, and inspect the
returned headers and rows:

-   `https://mtf.trading/api/v1/mcx?date=2026-10-15&symbol=GOLDM&instr=FUTCOM&format=csv&limit=100000`
-   `https://mtf.trading/api/v1/mcx?date=2026-10-15&symbol=GOLDM&instr=OPTFUT&format=csv&limit=100000`

If the provider returns JSON rather than CSV, parse the JSON response
correctly. Do not rename JSON to `.csv`. Discover the actual documented
schema and pagination mechanism. A provider may require different
parameter names or date formats.

------------------------------------------------------------------------

## 3. Required deliverables

Create a folder named `GOLDM_BACKTEST` and provide these files:

### A. `goldm_futures_daily.csv`

One row per available GOLDM futures contract per trading date. Include,
where source data supports them:

-   `date`
-   `timestamp_ist` (daily candle/session date; do not invent an
    intraday time)
-   `symbol`
-   `instrument`
-   `expiry_date`
-   `open`
-   `high`
-   `low`
-   `close`
-   `volume`
-   `open_interest`
-   `price_unit`
-   `source`
-   `source_file`

Keep each futures expiry distinct. Do not create a continuous near-month
series unless a separate continuous file is explicitly requested and
roll dates are documented.

### B. `goldm_options_daily.csv`

One row per listed option contract per trading date. Include:

-   `date`
-   `timestamp_ist`
-   `symbol`
-   `underlying` (must be GOLDM)
-   `expiry_date`
-   `strike`
-   `option_type` (`CE` or `PE`)
-   `open`
-   `high`
-   `low`
-   `close`
-   `volume`
-   `open_interest`
-   `lot_size` (only if verified)
-   `tick_size` (only if verified)
-   `price_unit`
-   `source`
-   `source_file`

Include expired options if historical records exist. Include all strikes
present in the source, not just a reconstructed ±10-strike band. Do not
synthesize option prices from futures prices.

### C. `goldm_contract_master.csv`

One row per unique contract, including futures and options. Fields:

-   `symbol`
-   `underlying`
-   `instrument` (`FUTCOM` / `OPTFUT` or source's verified equivalent)
-   `expiry_date`
-   `strike` (blank for futures)
-   `option_type` (blank for futures)
-   `lot_size`
-   `tick_size`
-   `listing_date`
-   `last_trading_date` or `delisting_date`
-   `source`
-   `verification_status`

Use exchange historical contract records to establish listing and
last-trading dates. If these dates cannot be established, leave them
blank and set `verification_status` to `not_verified`.

### D. `missing_dates.csv`

One row for every expected weekday/trading session that could not be
retrieved or validated, with:

-   `date`
-   `reason`
-   `sources_attempted`
-   `status`

Do not classify weekends as missing trading sessions. Where possible,
use the official MCX trading calendar/holidays rather than assuming
every weekday was a trading day.

### E. `data_quality_report.md`

Include: - Actual first and last data dates retrieved. - Number of
unique trading dates. - Number of futures contracts and option
contracts. - Number of futures and options rows. - Number of expired
contracts included. - Missing sessions and missing fields. -
Duplicate-row count and deduplication rule. - Source URLs and retrieval
date/time. - Price quotation units and any conversion applied, with
evidence. - Whether the 16-Nov-2026 bhavcopy was published and
retrieved. - Explicit coverage limitations.

Also preserve raw downloads under `GOLDM_BACKTEST/raw/`, without
modifying the originals.

------------------------------------------------------------------------

## 4. Data retrieval and validation workflow

1.  Open the official MCX bhavcopy page and determine how date-wise
    downloads work. Use the site's actual public download links or
    documented requests; do not guess hidden endpoints.
2.  Inspect one sample file. Confirm delimiter, encoding, headers,
    instrument identifiers, symbol field, expiry, strike, CE/PE, OHLC,
    volume, and OI.
3.  Test the independent archive for the same date and compare a sample
    of GOLDM rows with MCX official data.
4.  Retrieve all available sessions from 2025-11-17 through 2026-11-16.
    Use bounded concurrency and sensible delays; obey site terms and
    rate limits.
5.  If a date's file is unavailable, retry a limited number of times and
    record the failure. Do not repeatedly hammer the server.
6.  Filter only GOLDM futures and GOLDM options. Confirm the underlying
    and instrument type from source fields and exchange specifications.
7.  Retain every individual contract and expiry. Include expired
    contracts when the historical daily file contains them.
8.  Build the contract master from verified historical contract-master
    records, not from the candle data alone. Candle observations can
    establish that a contract traded on a date, but do not necessarily
    establish its listing date.
9.  Normalize dates to ISO `YYYY-MM-DD`. For daily bars, use the session
    date. Do not invent a time-of-day timestamp for daily candles.
10. Validate numeric fields, OHLC consistency (`high` must be at least
    open/close/low; `low` must be at most open/close/high), nonnegative
    volume/OI where applicable, and unique keys.
11. Use a stable row key such as
    `(date, symbol, expiry_date, strike, option_type)` for options and
    `(date, symbol, expiry_date)` for futures. Investigate conflicting
    duplicates rather than blindly keeping the last row.
12. Confirm the price unit against MCX contract specifications and the
    bhavcopy documentation. The user's desired display is ₹ per 10
    grams, but do not rescale unless the source unit is proven.
13. Write all CSVs with UTF-8 encoding and a header row.
14. Re-open the generated CSVs and report row counts from the actual
    saved files.
15. Provide links to each generated file and, ideally, one ZIP
    containing the full folder.

------------------------------------------------------------------------

## 5. Acceptance criteria

The task is complete only when:

-   The actual CSV files have been downloaded or created from retrieved
    public source rows.
-   Futures and options are separated correctly.
-   CE and PE are distinguished correctly.
-   Expired contracts are included wherever source history exists.
-   The contract master does not invent listing dates, lot sizes, or
    tick sizes.
-   Missing dates and missing fields are reported.
-   The source and quotation units are documented.
-   The CSVs can be opened and their row counts verified.
-   Download links point to real files that exist.

If you cannot access the sources or cannot create downloadable files in
your environment, say so clearly and provide the exact source/step that
failed. Do not claim success.

------------------------------------------------------------------------

## 6. Final response format

When finished, respond with:

1.  A short status: `complete`, `partially complete`, or `blocked`.
2.  Actual date coverage: first date to last date.
3.  Counts: trading dates, futures rows/contracts, options
    rows/contracts.
4.  Expired-contract inclusion status.
5.  Price unit verification status.
6.  Links to:
    -   `goldm_futures_daily.csv`
    -   `goldm_options_daily.csv`
    -   `goldm_contract_master.csv`
    -   `missing_dates.csv`
    -   `data_quality_report.md`
    -   `GOLDM_BACKTEST.zip` (if created)
7.  A concise list of unresolved gaps.

**Never output sample/fake OHLC rows as if they were market data.**
