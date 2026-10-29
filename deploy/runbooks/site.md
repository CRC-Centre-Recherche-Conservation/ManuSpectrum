# Runbook: Site and application errors

Alerts of the monitoring stack that point here. Each section has the same five parts. Commands run on the host from the repository checkout, as the service account. How alerts reach people, and how to open Grafana, is in `deploy/OBSERVABILITY.md`.

## SiteDown

Severity: critical. The public site does not answer.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. Grafana through the SSH tunnel (see OBSERVABILITY.md).

### Symptom

Visitors get an error or nothing. The alert does not fire during the 15 minutes that follow a host reboot (the 04:50 reboot).

### Diagnosis

`make -C deploy status` shows which container is down or unhealthy. `make -C deploy logs` for nginx and web. `curl -sk https://localhost/healthz` from the host separates nginx and the network from the application. A certificate failure shows in the `CertificateExpiringSoon` and `CertificateExpiryCritical` alerts.

### Remediation

Start what is down with `make -C deploy up`. After a bad update, roll back to the previous image (README, update section). A full disk is the usual hidden cause: see `DiskAlmostFull`.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## NotReady

Severity: critical. The application reports it is not ready.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. Grafana through the SSH tunnel.

### Symptom

The site may answer /healthz but one dependency (PostgreSQL, Elasticsearch, Celery broker, a Redis, Cantaloupe) does not. Searches or logins fail.

### Diagnosis

In Grafana (or Prometheus), query `manuspectrum_readyz_component_up == 0` to name the component. `make -C deploy status` for the container, `make -C deploy logs` for its last lines.

### Remediation

Restart the failing dependency with `docker compose` through `make -C deploy up`. Elasticsearch red or unassigned shards: see the datastores runbook and the production README. A dependency that is up but unreachable points to the Compose network.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## CantaloupeDown

Severity: critical. The IIIF image server does not answer.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

Manuscript images and thumbnails do not load; the rest of the site works.

### Diagnosis

`make -C deploy status` for the cantaloupe container, `make -C deploy logs` for its Java errors (out of memory, unreadable source).

### Remediation

Restart it with `make -C deploy up`. An out-of-memory kill also shows in `ContainerOOMKilled`. If the source images come from the network filesystem, check `NfsUnavailable`.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## ErrorRateHigh

Severity: critical. More than 1 % of the requests fail with a 5xx.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. Grafana through the SSH tunnel.

### Symptom

Visitors or editors meet error pages.

### Diagnosis

The Application dashboard shows the failing views (`view` label). `make -C deploy logs` for the tracebacks of web; each log line carries a request id. A dependency problem shows as `NotReady`.

### Remediation

Fix or roll back the change that introduced the error. A saturated service shows in `WebSaturated`. A database or Elasticsearch outage: see the datastores runbook.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## SearchLatencyHigh

Severity: warning. The Explorer search is slow.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. Grafana through the SSH tunnel.

### Symptom

The Explorer takes seconds to answer a search.

### Diagnosis

Check `ExplorerBundleBuildSlow` (a rebuild of the corpus bundle), the CPU and memory panels of the Infrastructure dashboard, and PostgreSQL activity (`pg_stat_activity_count`).

### Remediation

Wait for a running rebuild to end. A host short of memory: see `MemoryPressure`. A slow query: read the top statements by `queryid` in the PostgreSQL panel.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## SearchExportSlow

Severity: warning. Search exports run for a long time in the web worker.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. Read access to the nginx access log directory (`NGINX_LOG_HOST_DIR` in `deploy/compose/.env`; `/data/manuspectrum/nginx-logs` when the value of `.env.example` is kept) and `python3` on the host. Root (`sudo`) for the firewall rule.

### Symptom

Three or more requests to `/{en,fr}/search/export_results` or `/{en,fr}/api/search/export_results` took more than 60 seconds in 64 hours. Arches decides between the immediate export and the Celery export from the `total` parameter sent by the client, so a visitor who sends `total=0` gets the export built in the request. nginx answers 504 after 120 s while the gunicorn thread keeps working until the build ends; the PostgreSQL `statement_timeout` (60 s) bounds each query, not the whole build. The route is open to visitors on purpose (`ADMIN.md`, « Search exports by visitors »).

The latency metric (`django_http_requests_latency_seconds_by_view_method`) counts a request that fails twice (django-prometheus records it in `process_exception` and again in `process_response`), so a burst of failing exports can raise the count faster than the number of requests. It is only visible in the metric, not in the log. The counters are per web container start (multiprocess directory): the first export of a route since the web container started is not counted by `increase`.

### Diagnosis

Find the addresses and the durations in the access log, rotated files included (`access.log`, then `access.log-<date>` and compressed `.gz` files; `zcat -f` reads both). The query string is not logged; the status 504 and `request_time` identify the long ones:

```bash
DIR=/data/manuspectrum/nginx-logs   # NGINX_LOG_HOST_DIR of deploy/compose/.env
zcat -f "$DIR"/access.log* | python3 -c '
import json, re, sys
for line in sys.stdin:
    try:
        r = json.loads(line)
    except ValueError:
        continue
    if "search/export" in r.get("uri", "") and r.get("request_time", 0) > 60:
        print(r["time"], r["remote_addr"], r["status"], r["request_time"], sep="\t")
'
```

The log has no user field, and signed-in curators repeat large exports too: compare the addresses with the networks your curators use before blocking. Dashboard Application: web memory and saturation (`WebSaturated`) during the same hours.

### Remediation

The bounds already in place are `limit_req zone=search_export` (6 per minute), `limit_conn export_conn 1` (one export at a time per address) and the 60 s `statement_timeout`. They are per address: N addresses hold N of the 20 gunicorn threads (5 workers x 4 threads).

Block an abusive address on the host firewall, not in the versioned nginx files. Docker publishes the nginx ports through its own iptables rules, which `ufw` does not see; rules in the `DOCKER-USER` chain are evaluated first and survive a `git` update of the repository:

```bash
sudo iptables  -I DOCKER-USER -s 203.0.113.7 -j DROP          # an IPv4 address
sudo ip6tables -I DOCKER-USER -s 2001:db8:1234:5678::/64 -j DROP   # an IPv6 prefix (/64: one subscriber)
sudo iptables  -L DOCKER-USER -n --line-numbers                # list (ip6tables for IPv6)
sudo iptables  -D DOCKER-USER -s 203.0.113.7 -j DROP          # remove
sudo ip6tables -D DOCKER-USER -s 2001:db8:1234:5678::/64 -j DROP   # remove the IPv6 prefix
```

Block the `/64` for IPv6: a single subscriber owns the whole prefix. The IPv6 rule only applies when Docker runs IPv6 with ip6tables on the nginx network: if the log shows the bridge gateway address instead of IPv6 clients, `docker-proxy` answers them and `DOCKER-USER` cannot single them out. With nftables, put the same drop in a table hooked on `forward` before Docker's. These rules do not survive a reboot. Do not save the whole ruleset (`netfilter-persistent save` would also restore Docker's own chains, with stale container addresses, before Docker starts): re-run the `-I` lines after a reboot while the abuse lasts, and remove them when it stops. The addresses above are documentation examples. Closing the route for every visitor is the other switch: remove `anonymous` from the « Resource Exporter » group (`ADMIN.md`). The lasting fix is a server-side count in Arches (the Celery path decided by the server, not by `total`), which belongs upstream.

### Escalation

The technical lead.

## WriteRequestsFailing

Severity: warning. At least three write requests (POST, PUT or DELETE) answered a server error in the last 30 minutes. Severity is warning on purpose: the site is up and the failures are few, which `ErrorRateHigh` (critical) does not see; a curator's input may be lost, so it is read the same working day.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. Grafana through the SSH tunnel (dashboard Activity, panel "Failing writes (5xx) by view").

### Symptom

A curator reports that a save, an import step or a deletion failed with an error page, or no one has noticed yet.

### Diagnosis

The panel "Failing writes (5xx) by view" gives the `view` of the failing requests (`tile`, `plugins`, `workflow_history`, `biblissima-create-resource`, ...). Read the web log for that period (`make -C deploy logs`, lines at ERROR with the request id). A database, Elasticsearch or Redis outage shows in `NotReady` or in the datastore alerts. The first error of a view that never failed counts too (the rule adds the series created within the window to the increase of the older ones); the panel counts it the same way. Limits: a series is counted as new only if its target was scraped (`up`) 30 minutes earlier, so a Prometheus started less than 30 minutes ago misses first errors of new series until then; a scrape gap never raises the alert on its own.

### Remediation

Fix the cause the log names. Tell the curators whose save failed to repeat it and check the record afterwards: a write that died halfway can leave a resource without its cards.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.
