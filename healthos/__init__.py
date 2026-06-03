"""HealthOS — personal health data aggregator.

Pulls Whoop, Garmin, and Eight Sleep into a single Postgres database, serves a
dashboard API, runs nightly syncs + behavioral inference, and exposes an MCP
server so Claude can answer natural-language questions about health trends.
"""

__version__ = "0.1.0"
