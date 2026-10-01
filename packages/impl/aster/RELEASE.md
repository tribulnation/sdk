# tribulnation-aster 0.4.1 release candidate

Perpetual funding payment history is available for a selected market and for the
whole perpetual exchange. Both paths read Aster's native `FUNDING_FEE` income with
inclusive bounds and paginated, retryable requests. SDK amounts are positive when
funding was paid and negative when received; exchange-wide rows include their native
market ID.

An authenticated mainnet read returned settled funding payments through both SDK
paths, with matching amounts and timestamps. Regression tests cover pagination
retries, both amount signs and exchange-wide market identity. The received sign is
verified by a deterministic test.

Other Market and Report behavior is unchanged from 0.4.0. Requires
tribulnation-sdk >=2.8.0 and typed-aster >=0.2.0.
