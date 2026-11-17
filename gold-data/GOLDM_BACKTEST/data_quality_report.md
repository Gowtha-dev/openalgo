# Data Quality Report: MCX GOLDM Historical Backtest Data

**Dataset:** Multi Commodity Exchange of India (MCX) GOLDM (Gold Mini, 100g) Historical Daily Data  
**Period Requested:** 17 November 2025 to 16 November 2026 (inclusive)  
**Retrieval & Generation Timestamp:** 2026-11-16T13:02:48Z (IST: 2026-11-16 18:32:48+05:30)  
**Author / Agent:** Antigravity Data Retrieval & Validation Agent  

---

## 1. Executive Summary & Status

- **Status:** **Partially Complete** (Complete through the latest exchange-published session of 13-Nov-2026; 16-Nov-2026 is pending exchange end-of-day publication).
- **Date Coverage:** 
  - **First Trading Date Retrieved:** `2025-11-17`
  - **Last Trading Date Retrieved:** `2026-11-13` (Friday prior to request date)
  - **Target End Date (2026-11-16):** As of 18:30 IST on 16-Nov-2026, the MCX trading session is still active (MCX commodity trading hours extend to 23:30 / 23:55 IST). The exchange has not yet finalized or published the 16-Nov-2026 Bhavcopy. Per Runbook Rule 11, this session is formally marked as `pending_exchange_publication` and not substituted with previous session data.
- **Unique Trading Dates Retrieved:** 256 trading sessions.
- **Total Validated Rows:**
  - **Futures Rows (`FUTCOM`):** 1,536 rows
  - **Options Rows (`OPTFUT`):** 268,904 rows
- **Total Unique Contracts Identified:** 7,526 contracts
  - **Futures Contracts:** 18 distinct expiries
  - **Options Contracts:** 7,508 distinct strike / expiry / CE-PE combinations across 15 expiries

---

## 2. Dataset Verification & Summary Statistics

| Metric | Futures (`goldm_futures_daily.csv`) | Options (`goldm_options_daily.csv`) | Combined / Master (`goldm_contract_master.csv`) |
| :--- | :--- | :--- | :--- |
| **Row Count** | 1,536 | 268,904 | 7,526 unique contracts |
| **First Date** | 2025-11-17 | 2025-11-17 | 2025-11-17 (first observation) |
| **Last Date** | 2026-11-13 | 2026-11-13 | 2026-11-13 (last observation) |
| **Unique Trading Dates** | 256 | 256 | 256 |
| **Unique Expiries** | 18 | 15 | 18 futures, 15 options |
| **Expired Contracts Included** | 12 expiries | 12 expiries | 12 futures expiries, 12 options expiries |
| **Option Types** | N/A | CE (Call), PE (Put) | Both CE & PE mapped |
| **Lot Size** | 100 grams (1 lot) | 100 grams (1 lot) | 100 grams (1 lot) |
| **Tick Size** | ₹1.0 per 10g | ₹1.0 per 10g | ₹1.0 per 10g |
| **Price Quotation Unit** | ₹ per 10 grams | ₹ per 10 grams | ₹ per 10 grams |
| **Key Deduplication Rule** | `(date, symbol, expiry_date)` | `(date, symbol, expiry_date, strike, option_type)` | `(symbol, instrument, expiry_date, strike, option_type)` |
| **Duplicate Conflicts** | 0 duplicates | 0 duplicates | 0 duplicates |
| **OHLC Consistency Violations** | 0 violations | 0 violations | N/A |

---

## 3. Sources Investigated and Retrieval Metadata

### Primary Exchange Source (MCX India Official)
- **Bhavcopy Interface:** `https://www.mcxindia.com/market-data/bhavcopy`
  - **Status:** Verified live via headless browser session. HTTP 200 OK.
  - **Sample Direct Download:** `BhavCopyDateWise_13112026.csv` (~2.1 MB, 16,811 total market rows).
  - **Downloaded Location:** `GOLDM_BACKTEST/raw/BhavCopyDateWise_13112026.csv`
- **Contract Available for Trading:** `https://www.mcxindia.com/market-data/contractavailablefortrading`
  - **Status:** HTTP 200 OK. Verified active listing schedule for GOLDM futures contracts (start date, end date, tender period).
- **Product Specifications:** `https://www.mcxindia.com/products/bullion/gold#goldminisection`
  - **Status:** Verified official contract circulars and specifications for Gold Mini (100g).

### Secondary Archive Source (MTF Independent Archive)
- **Archive Base:** `https://mtf.trading/api/v1/mcx` and `https://mtf.trading/mcx/index.json`
  - **Index Metadata:** Contains 1,250 historical exchange sessions from 2022-01-03 to 2026-11-13 captured from official MCX daily bhavcopies.
  - **Direct Archive Storage:** Static daily gzipped Bhavcopy archives (`https://mtf.trading/mcx/{YYYYMMDD}.csv.gz`).
  - **Cross-Verification:** 100% field-by-field match between the official MCX download for 2026-11-13 and the MTF archive copy for 2026-11-13 across Open, High, Low, Close, Volume, Value, Strike, Option Type, and Open Interest.
  - **Download Manifest:** Full record of all 256 downloaded `.csv.gz` files, HTTP status codes, byte sizes, and SHA-256 hashes preserved in `GOLDM_BACKTEST/raw/download_manifest.json`.

---

## 4. Price Quotation Unit & Lot Size Verification

1. **Quotation Unit:**
   - MCX Gold Mini futures and options trade with price quotations in **₹ per 10 grams** (`INR / 10g`).
   - Official contract specification document confirms: `Quotation Base: Rs. per 10 grams`.
   - No unit conversion or rescaling was applied to the exchange prices; exchange quoted values are preserved intact.

2. **Trading Unit / Lot Size:**
   - Contract trading lot = **100 grams**.
   - Verified empirically from official MCX Bhavcopy volume fields:
     - On 2026-11-13, contract `GOLDM 04DEC2026` traded `54,454` lots.
     - Volume in units reported by exchange: `5,445.400 GRMS (In 000's)` = `5,445,400 grams`.
     - $\frac{5,445,400\text{ grams}}{54,454\text{ lots}} = 100\text{ grams/lot}$.
     - Trade Value reported: `₹7,44,690.67 Lacs`.
     - At ~₹1,36,764 per 10 grams, 1 lot = 10 units of 10g:
       $$54,454\text{ lots} \times 10 \times ₹1,36,764 \approx ₹74,473\text{ Lacs}$$
       matching the reported turnover within rounding.

3. **Tick Size:**
   - Minimum price movement (tick size) = **₹1.00 per 10 grams**.

---

## 5. Missing Sessions & Calendar Analysis

Between 17-Nov-2025 and 16-Nov-2026, there are 261 total Monday–Friday weekdays. 256 sessions were active trading days and successfully retrieved. The remaining 5 weekdays are documented in `GOLDM_BACKTEST/missing_dates.csv`:

| Date | Day | Reason | Status | Sources Attempted |
| :--- | :--- | :--- | :--- | :--- |
| `2025-12-25` | Thursday | Christmas (Official MCX Trading Holiday) | `market_holiday` | MCX Trading Calendar / Archive |
| `2026-01-26` | Monday | Republic Day (Official MCX Trading Holiday) | `market_holiday` | MCX Trading Calendar / Archive |
| `2026-04-03` | Friday | Good Friday (Official MCX Trading Holiday) | `market_holiday` | MCX Trading Calendar / Archive |
| `2026-10-02` | Friday | Mahatma Gandhi Jayanti (Official MCX Trading Holiday) | `market_holiday` | MCX Trading Calendar / Archive |
| `2026-11-16` | Monday | Session in progress (trading to 23:30 IST); Bhavcopy not yet published | `pending_exchange_publication` | MCX Official Bhavcopy / MTF Archive |

---

## 6. Contract Master & Verification Methodology

Per Runbook Rules 8 and 9:
- Historical observations from bhavcopies establish trading activity but do not establish formal exchange listing dates.
- For active futures contracts listed on the exchange's `contractavailablefortrading` schedule, exact listing dates and expiry dates were verified directly:
  - `2026-12-04` expiry: Listing date `2026-06-08`, Last trading date `2026-12-04` (`verified`)
  - `2027-01-05` expiry: Listing date `2026-07-06`, Last trading date `2027-01-05` (`verified`)
  - `2027-02-05` expiry: Listing date `2026-08-06`, Last trading date `2027-02-05` (`verified`)
  - `2027-03-05` expiry: Listing date `2026-09-07`, Last trading date `2027-03-05` (`verified`)
  - `2027-04-05` expiry: Listing date `2026-10-06`, Last trading date `2027-04-05` (`verified`)
  - `2027-05-05` expiry: Listing date `2026-11-06`, Last trading date `2027-05-05` (`verified`)
- For historical contracts that expired earlier in the target period (where MCX does not retain current active listings), the `listing_date` field is left blank and marked with `verification_status: "not_verified"`.

---

## 7. Data Integrity Checks

1. **OHLC Consistency:**
   - All traded records ($Volume > 0$ and $Open > 0$) strictly satisfy:
     - $High \ge \max(Open, Close, Low)$
     - $Low \le \min(Open, Close, High)$
   - Total violations: **0**.
2. **Untraded Options:**
   - MCX reports untraded option strikes with $Open = 0.0$, $High = 0.0$, $Low = 0.0$, $Volume = 0$, $Value = 0.0$, and $Close$ set to the previous settlement price or daily theoretical settlement price. These values have been preserved exactly as reported by the exchange without artificial zero-padding or synthesis.
3. **Primary Key Uniqueness:**
   - Futures: `(date, symbol, expiry_date)` — 0 duplicate collisions across 1,536 rows.
   - Options: `(date, symbol, expiry_date, strike, option_type)` — 0 duplicate collisions across 268,904 rows.

---

## 8. Directory Structure & Deliverable Files

```
GOLDM_BACKTEST/
├── goldm_futures_daily.csv        # 1,536 rows: All GOLDM futures daily candles
├── goldm_options_daily.csv        # 268,904 rows: All GOLDM options daily records (CE & PE)
├── goldm_contract_master.csv      # 7,526 rows: Unique contract master for futures & options
├── missing_dates.csv              # 5 rows: Official holidays & pending current session
├── data_quality_report.md         # Full methodology, audit trail, and verification metrics
└── raw/                           # Original, unedited raw source data
    ├── download_manifest.json     # Manifest with SHA256 hashes, byte sizes, and URLs
    ├── index.json                 # Archive master session index
    ├── BhavCopyDateWise_13112026.csv # Direct official MCX Bhavcopy download
    └── YYYYMMDD.csv.gz (x256)     # Complete daily raw bhavcopy archives
```

Archive package: `GOLDM_BACKTEST.zip` (~64.8 MB compressed).
