"""Sources module for NQ Cockpit.

Handles external free market data sources (CBOE, yfinance, FRED, CFTC, etc.)
with health checking, timeouts, retry with exponential backoff, and caching.
"""
