"""Benchmark-column method classification (PRD §7.2 point 10, §5.6).

The benchmark column is mapped to the `dnbp_benchmark` field by header text
via the synonym registry in headers.py. This module answers the separate
question of *which formula* produced it, from that same header text — the
07-08 file's plain "Do Not Buy Price" is the legacy Gayan fixed-cost method;
the 12-08 file's "...Using % method instructed by the financier" is the
newer financier-margin method. If a file ever carries a benchmark header
this can't classify, the value is still stored (never dropped) tagged
UNKNOWN — this system never guesses a method, and never falls back from one
method to the other.
"""

from domain.ingestion.headers import normalise
from domain.ingestion.types import BenchmarkMethod


def classify_benchmark_header(header_text: object) -> BenchmarkMethod:
    text = normalise(header_text)
    if "financier" in text or "%" in str(header_text):
        return BenchmarkMethod.FINANCIER_MARGIN
    if "do not buy price" in text:
        return BenchmarkMethod.GAYAN_FIXED_COST
    return BenchmarkMethod.UNKNOWN
