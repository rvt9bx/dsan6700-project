"""Prometheus metrics, served at GET /metrics.

Labels are only ever route templates, methods, status codes and outcomes, never a job
id or anything a user typed, so the number of series stays small and nothing private
is exported.
"""

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "movierec_http_requests_total",
    "HTTP requests, by route, method and status code",
    ["endpoint", "method", "status"],
)
HTTP_REQUEST_SECONDS = Histogram(
    "movierec_http_request_duration_seconds",
    "Time to answer an HTTP request",
    ["endpoint", "method"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

JOBS = Counter(
    "movierec_recommend_jobs_total",
    "Recommendation jobs that finished, by outcome (completed or failed)",
    ["outcome"],
)
JOB_SECONDS = Histogram(
    "movierec_recommend_job_duration_seconds",
    "Time for a recommendation job: embedding the descriptions, searching and ranking",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
JOBS_IN_FLIGHT = Gauge(
    "movierec_recommend_jobs_in_flight",
    "Recommendation jobs pending or running now",
)
EMPTY_RETRIEVALS = Counter(
    "movierec_recommend_empty_results_total",
    "Completed jobs whose search found no movies",
)
TOP_SCORE = Histogram(
    "movierec_recommend_top_score",
    "Group score of the top pick (cosine similarity, higher is a closer match)",
    buckets=(0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)
QUERIES_PER_JOB = Histogram(
    "movierec_recommend_queries_per_job",
    "Descriptions embedded per job: one per person in the group",
    buckets=(1, 2, 3, 4, 5, 6),
)
