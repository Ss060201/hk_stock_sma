# Phase 8 Formula Evidence Report

## 1. Executive Summary

- Formula decision: `FORMULA_SUPPORTED_BUT_NOT_CONFIRMED`
- Production change: `NO CHANGE`
- Production logic changed in Phase 8: `No`
- Key reason: the project has strong supporting evidence for `Volume / ShareBase × 100`, but still has `0/11` directly observed same-observation AASTOCKS TOR rows.

## 2. Evidence Collected

- Phase 5 established a time-aligned 11-stock benchmark with same-session AASTOCKS `Volume`, `ShareIssued`, and explicit timestamps.
- Phase 6 showed Yahoo same-date volume is extremely close to AASTOCKS same-date volume and identified `2577` and `9678` as share-base outliers.
- Phase 7 showed the public AASTOCKS frontend object still exposes timestamped `Volume` and `ShareIssued` but `TurnoverRate` remains `N/A`.
- Supporting AASTOCKS definition: "Turnover Rate measures the trading volume to the total issued shares in a period of time."
- Supporting definition source: https://www.aastocks.com/en/stocks/quote/quick-quote.aspx?symbol=06681

## 3. Same-Observation TOR Availability

- Total rows: `11`
- Observed TOR rows: `0`
- Same-observation TOR rows: `0`
- Tier 1: `0`
- Tier 2: `0`
- Tier 3: `0`
- Final bounded search result: `same_observation_tor_unavailable = true`
- Search note: The bounded final investigation did not find any legitimate public AASTOCKS representation that exposed a directly attributable same-observation displayed TOR. The frontend object continued to expose timestamped Volume and ShareIssued but TurnoverRate remained N/A.

## 4. Formula Sensitivity

- For most benchmark rows, `TOR_share_issued`, `TOR_yahoo`, and `TOR_aastocks` are almost identical because Yahoo `sharesOutstanding` and same-session AASTOCKS `ShareIssued` are nearly the same.
- The two material sensitivity cases are `2577` and `9678`.

| Ticker | Timestamp | TOR ShareIssued | TOR Yahoo | TOR AASTOCKS | TOR Official | Key Sensitivity |
|---|---|---:|---:|---:|---:|---|
| 0005 | 2026-08-07 16:08:24 | 0.068383 | 0.068524 | 0.068383 |  | No material sensitivity. |
| 1672 | 2026-08-07 16:08:23 | 0.165307 | 0.165307 | 0.165307 |  | No material sensitivity. |
| 2726 | 2026-08-07 16:08:24 | 0.190296 | 0.190290 | 0.190296 |  | No material sensitivity. |
| 6681 | 2026-08-07 16:08:20 | 1.471493 | 1.471496 | 1.471493 |  | Yahoo vs AASTOCKS differs by only 0.00015%. |
| 9678 | 2026-08-07 16:08:21 | 3.962093 | 4.215143 | 3.962093 | 3.962103 | Yahoo vs AASTOCKS differs by 6.39%; official vs AASTOCKS differs by 0.00026%. |
| 1879 | 2026-08-07 16:08:22 | 0.236584 | 0.236582 | 0.236584 |  | No material sensitivity. |
| 3317 | 2026-08-07 16:08:24 | 1.621844 | 1.621853 | 1.621844 |  | No material sensitivity. |
| 2432 | 2026-08-07 16:08:19 | 1.243957 | 1.243961 | 1.243957 |  | No material sensitivity. |
| 2577 | 2026-08-07 16:08:23 | 0.903308 | 1.545867 | 0.903308 | 0.887790 | Yahoo vs AASTOCKS differs by 71.13%; official vs AASTOCKS differs by 1.72%. |
| 6082 | 2026-08-07 16:08:21 | 1.349037 | 1.349042 | 1.349037 |  | No material sensitivity. |
| 2655 | 2026-08-07 16:08:24 | 0.340824 | 0.340825 | 0.340824 |  | No material sensitivity. |

## 5. Outlier Analysis

- `2577`: `SHARE_BASE_OUTLIER`. Share-base difference vs Yahoo: `-41.566280%`; volume difference vs Yahoo: `0.070161%`.
- `9678`: `SHARE_BASE_OUTLIER`. Share-base difference vs Yahoo: `-6.003363%`; volume difference vs Yahoo: `0.005595%`.
- `6681`: `TIMESTAMP_MISMATCH`. Share-base difference vs Yahoo: `-0.000147%`; volume difference vs Yahoo: `0.010007%`.
- `0005`: `NO_MATERIAL_OUTLIER`. Share-base difference vs Yahoo: `-0.205723%`; volume difference vs Yahoo: `0.003404%`.
- `2726`: `NO_MATERIAL_OUTLIER`. Share-base difference vs Yahoo: `0.003053%`; volume difference vs Yahoo: `0.022095%`.
- `2577`: unresolved official post-conversion explanation remains in place; no production override is justified from Phase 8 evidence alone.
- `9678`: official post-placement H-share evidence remains strong and explains the Yahoo lag; still no production metadata change is made in Phase 8.
- `6681`: same-session share base and volume remain aligned, so the legacy discrepancy is best explained by timestamp mismatch rather than denominator failure.

## 6. Formula Decision

- Decision: `FORMULA_SUPPORTED_BUT_NOT_CONFIRMED`
- Why this is not `FORMULA_CONFIRMED`: the project still has no directly observed same-observation AASTOCKS TOR sample, so the required direct validation threshold is not met.
- Why this is not `FORMULA_NOT_SUPPORTED`: no reliable observed TOR evidence materially contradicts the formula, and the remaining discrepancies are explainable by timestamp mismatch or known share-base outliers.
- Why this is not `INSUFFICIENT_EVIDENCE`: AASTOCKS provides a supporting turnover-rate definition, same-session `Volume` and `ShareIssued` are available for all 11 rows, Yahoo volume is closely aligned, and independent evidence does not contradict the working formula.

## 7. Production Recommendation

- `MORE RESEARCH REQUIRED`
- Rationale: the formula is supported enough to remain the working production direction, but not directly confirmed enough to justify claiming it as proven.

## 8. Phase 9 Recommendation

- Smallest next research step: obtain at least 5 directly observed same-observation AASTOCKS TOR rows from a legitimate Tier 1–3 source, or conclude that such evidence is not publicly obtainable and freeze the formula status at supported-but-not-confirmed.
- If the project stops formula research, the next practical focus should move to metadata coverage, official share-base maintenance, benchmark expansion, and production-quality monitoring for outlier tickers.

