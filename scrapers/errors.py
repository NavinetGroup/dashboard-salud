# -*- coding: utf-8 -*-
"""Shared failure signal for scrapers.

Contract for every scraper's run(base_dir):
  - returns normally  → the source is up to date (new data written, or nothing
                        new published yet — that is not a failure);
  - raises ScrapeError → the source could not be refreshed and needs attention.

pipeline/runner.py turns raised errors into a non-zero exit code, so the cron
wrapper can alert instead of reporting "Pipeline OK".
"""


class ScrapeError(RuntimeError):
    """A scraper could not refresh its source."""
