from .base import IJobSource, JobQuery, SourceResult
from .http_sources import ArbeitnowJobSource, RemotiveJobSource
from .mock import MockJobSource
from .registry import AggregatedJobSearch, JobSourceRegistry, deduplicate_jobs
from .unavailable import UnavailableJobSource

__all__ = [
    "IJobSource",
    "JobQuery",
    "SourceResult",
    "MockJobSource",
    "RemotiveJobSource",
    "ArbeitnowJobSource",
    "UnavailableJobSource",
    "JobSourceRegistry",
    "AggregatedJobSearch",
    "deduplicate_jobs",
]
