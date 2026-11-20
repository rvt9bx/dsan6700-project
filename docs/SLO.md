# Service level objective

## The main route

People use Eenie Meenie Movies to get a recommendation: `POST /recommend` starts a job, and the page polls until the
job is done. What a person waits for is the **job**, so the SLO is about jobs, not about the `POST` (which answers in
milliseconds).

## The objective

> **Over any 28 days, 99% of recommendations complete within 5 seconds.**

| | |
|---|---|
| **Good** | A recommendation job that completed (status `completed`) within 5 seconds |
| **Bad** | A job that failed, a job that took longer than 5 seconds, or a `POST /recommend` the service refused with a 5xx (for example a 503 because too many jobs were running) |
| **Not counted** | 4xx answers: an invalid request (422), a body that was too large or not JSON (413, 415), or a client over its rate limit (429). Those are the caller's to fix, not failures of the service |
| **Target** | 99% good |
| **Window** | 28 days, rolling |
| **Error budget** | 1% of recommendations may be bad: at 200 recommendations a day, about 56 in 28 days |

**Why 5 seconds:** a job embeds up to six short descriptions with a small CPU model and runs one Qdrant search per
person, so a normal job should take about a second; the "Job duration" panel shows the real p50 and p95 on the
instance, and if p95 is near 5 seconds the threshold should be revisited. The frontend gives up after 60 seconds.
Five seconds leaves room for a slow moment and is still short enough that a person watching the loading screen would
not think the page is stuck.

**Why 99%:** this is a class project on one small instance with no on-call rotation. A restart or deploy loses the
jobs in progress, which costs a few bad recommendations each time; 99% leaves room for that while still catching a
real problem, such as Qdrant being down for an hour.

## How it is measured

The app exports these on `/metrics`, and Prometheus keeps 30 days of them:

- `movierec_recommend_job_duration_seconds` is a histogram of job durations with an `outcome` label (`completed` or
  `failed`). Its `le="5.0"` bucket counts jobs that took 5 seconds or less.
- `movierec_http_requests_total{endpoint="/recommend",method="POST",status=~"5.."}` counts refused submissions.

The share of good recommendations over 28 days, in PromQL:

```promql
sum(increase(movierec_recommend_job_duration_seconds_bucket{outcome="completed",le="5.0"}[28d]))
/
(
  sum(increase(movierec_recommend_job_duration_seconds_count[28d]))
  + (sum(increase(movierec_http_requests_total{endpoint="/recommend",method="POST",status=~"5.."}[28d])) or vector(0))
)
```

The top row of the Grafana dashboard shows this number ("Good recommendations"), the error budget left, and the
counts behind them, for whatever time range is selected; set the range to **Last 28 days** to see the SLO window.
`tests/test_limits.py` checks that the series the query relies on exist, so renaming them breaks a test.

**Limits of the measurement:**

- Counters live in the app's memory, so they restart at zero when the app restarts. Prometheus's `increase()`
  handles that, but jobs lost in a restart are never counted at all, so a deploy's cost is slightly undercounted.
- `increase()` cannot see the first value of a series that has just appeared, so with very little traffic the counts
  can be one short at first.
- With two copies of the app, each would export its own counters, and the `sum()` in the query adds them up, so the
  query keeps working.

## When the error budget runs out

1. Look at the "Jobs finished per second, by outcome" and "Job duration" panels to see whether jobs are failing or
   slow.
2. Find failed jobs in the logs: `jq 'select(.message == "Recommendation job failed")'` on `app.jsonl` gives each
   one's `request_id`, `job_id` and traceback.
3. Until the budget recovers, deploy only fixes for the problem, not new features.
4. If the cause was something that broke, write a postmortem in `docs/`.
