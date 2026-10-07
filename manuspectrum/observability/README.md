# Observability

Logs, health probes and Prometheus metrics of ManuSpectrum. Nothing here collects or
stores anything: Prometheus, Alertmanager and Grafana are deployed separately (PP-6).

## Logs

| Environment | Format |
| --- | --- |
| Development (`settings.py`) | Unchanged: Arches' text logs. `LOGGING` is not touched. |
| Image (`settings_docker.py`) | One JSON object per line on stdout. `MS_LOG_FORMAT=text` gives `time level logger [request_id] message` for a terminal. |

Fields of a JSON line: `timestamp` (UTC, ISO 8601), `level`, `logger`, `message`,
`service` (`manuspectrum`), `environment` (`DEPLOY_ENVIRONMENT`), `version`, `hostname`,
`request_id`, `trace_id` (empty until tracing exists), then the record's `extra` fields.

Levels: root at WARNING; `django`, `arches`, `manuspectrum` and `celery` at INFO;
`django.request` at WARNING. No file, no `mail_admins`.

Redaction happens in the formatter, whatever the logger: values of keys naming a password,
token, cookie, session, CSRF value, API key or credential; in text, `Authorization` values,
IIIF tokens (`msiiif1.`), bare `Bearer` tokens, JSON `access_token`/`refresh_token` values, `password=`/`code=`/`key=`/`sig=`-style query values, URL credentials and e-mail
addresses (non-string `extra` values are stringified first). Do not log personal data on the strength of it: redaction is the net, not the rule.

Reading them:

```bash
docker compose logs --no-log-prefix web | jq -c 'select(.level=="ERROR")'
docker compose logs --no-log-prefix web | jq -R 'fromjson?'   # gunicorn's own lines are text
```

## Request id

`RequestIdMiddleware` (first in `MIDDLEWARE`) accepts the caller's `X-Request-ID` when it is
8 to 128 characters of `[A-Za-z0-9._-]` starting alphanumeric, otherwise generates one, and
echoes it in the response. It lives in `context.request_id_var`; `RequestIdFilter` puts it on
every log record.

- Celery: `before_task_publish` copies it into the message header `ms_request_id`;
  `task_prerun` binds it in the worker.
- A thread you start does not inherit it: run its body under
  `bound_request_id(current_request_id())`.
- A streamed body logs after the middleware returned and carries no id.

## Health

- `/healthz`: liveness. No dependency; the Compose healthcheck.
- `/readyz`: readiness. PostgreSQL, Elasticsearch, the Celery broker, both Redis instances
  and Cantaloupe, probed concurrently. 200 when all are `up`, else 503; JSON with `status`
  and, per component, `up` (with `seconds`), `down` (with the exception class only) or
  `timeout` (logged as a WARNING by component name). Probes run on daemon threads; a process
  runs one evaluation at a time and a concurrent call reuses its result if it ended less
  than 2 s ago. Bounded by `READYZ_TIMEOUT` (2 s); `READYZ_REDIS_URLS` and `READYZ_CANTALOUPE`
  choose the components. Each probe sets `manuspectrum_readyz_component_up`.

To add a component: write `probe_<name>(timeout)` in `health.py`, add it to `components()`,
add its name to `metrics.READYZ_COMPONENTS`.

Both live below the language boundary of `urls.py` (`/en/readyz` is 404).

## Metrics

- Web: `/metrics`. Worker: `worker:9808/metrics` (`MS_CELERY_METRICS_PORT`, not published).
- Internal only: a request carrying `X-Forwarded-For` (relayed by nginx) gets a bodyless 404;
  nginx also denies the path (PP-3).
- Multiprocess: `PROMETHEUS_MULTIPROC_DIR` (`/run/prometheus`, a tmpfs) holds one file set per
  process; the entrypoint empties it before the server starts. When a process dies,
  gunicorn's `child_exit` / Celery's `worker_process_shutdown` call
  `multiproc.archive_dead_process(pid, path)`: its counter, histogram and summary files are
  added into `counter_archive.db`, `histogram_archive.db` and `summary_archive.db`, its
  `gauge_mostrecent` file keeps the newest value in `gauge_mostrecent_archive.db`, its
  `gauge_live*` files are dropped (as `mark_process_dead` does) and the pid's files are
  deleted, under an `flock`. Totals never fall and the directory holds one file per type
  plus the live processes' files, however many workers were recycled. No other gauge mode
  exists in the project (`metrics.gauge()` refuses them); one added would be left as
  prometheus_client leaves it.
- `manuspectrum_metrics_dir_bytes` (mostrecent gauge, updated on each archive) is the space
  the directory occupies. Alert when it exceeds 70 % of the tmpfs (`size=64m` of web and
  worker, so 45 MB) for 10 minutes: live files alone should stay a few MB.
- A one-off process started with `docker compose exec web python ...` would write its own
  files there and be summed into `/metrics`: run it with `env -u PROMETHEUS_MULTIPROC_DIR`,
  or through `make -C deploy manage`.

Metrics (`metrics.py`, a counter is exposed with the `_total` suffix):

- Web: `manuspectrum_inflight_requests`, `manuspectrum_log_records`,
  `manuspectrum_readyz_component_up`
- Memos, IIIF, access: `manuspectrum_memo_lookups`, `manuspectrum_iiif_answers`,
  `manuspectrum_iiif_auth_tokens`, `manuspectrum_read_refusals`, `manuspectrum_auth_logins`,
  `manuspectrum_spectrum_previews`
- Explorer: `manuspectrum_explorer_bundle_build_seconds`, `manuspectrum_explorer_bundle_bytes`,
  `manuspectrum_explorer_bundle_rows`, `manuspectrum_explorer_bundle_builds`,
  `manuspectrum_explorer_stale_served`, `manuspectrum_explorer_rebuild_failures`,
  `manuspectrum_explorer_export_bytes`
- Biblissima: `manuspectrum_biblissima_upstream_requests`,
  `manuspectrum_biblissima_upstream_latency_seconds`, `manuspectrum_biblissima_slot_timeouts`,
  `manuspectrum_biblissima_inflight`, `manuspectrum_biblissima_cache`,
  `manuspectrum_biblissima_suggest_prefix`, `manuspectrum_upstream_budget_spent`,
  `manuspectrum_biblissima_created_items`
- Outbound fetches: `manuspectrum_outbound_fetches`, `manuspectrum_outbound_fetch_seconds`,
  `manuspectrum_ssrf_rejections`
- Celery: `manuspectrum_celery_tasks`, `manuspectrum_celery_task_seconds`,
  `manuspectrum_index_resources`, `manuspectrum_data_change_rows`,
  `manuspectrum_data_change_pruned_timestamp_seconds` (both also set when the worker starts,
  the start time standing for the last prune until the daily one records its own)

django-prometheus adds the HTTP request metrics (`django_http_*`).

## Adding a metric

- Declare it in `metrics.py` only, named `manuspectrum_<what>` with its unit (`_seconds`,
  `_bytes`); Counter, Gauge or Histogram only (Info, Enum and Summary quantiles do not
  aggregate across processes).
- A Gauge goes through `gauge(..., mode="livesum" | "mostrecent")`.
- Labels come from `ALLOWED_LABELS`; values come from a closed vocabulary through `bounded()`
  or a helper (`language_label`, `memo_label`, `task_label`, ...), an unknown value becoming
  `other`. Never an id, a user, a URL, a path or a string a client sent.
- Test it where the code increments it, with `tests/observability_helpers.delta`;
  `tests/test_observability_metrics.py` enforces the naming and label rules.
- Say which alert or dashboard panel reads it in the pull request.

## Development

Everything is inert unless `settings_local.py` opts in: `METRICS_ENABLED = True` and
`READYZ_ENABLED = True` (otherwise `/metrics` and `/readyz` answer 404). Request metrics
(`django_http_*`) also need `django_prometheus.middleware.PrometheusBeforeMiddleware` first
and `PrometheusAfterMiddleware` last in `MIDDLEWARE`. The request id middleware and the
metric increments run everywhere: a response header and in-memory counters.
