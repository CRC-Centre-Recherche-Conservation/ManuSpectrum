# Runbook: Explorer

Alerts of the monitoring stack that point here. Each section has the same five parts. Commands run on the host from the repository checkout, as the service account. How alerts reach people, and how to open Grafana, is in `deploy/OBSERVABILITY.md`.

Not an alert: **403 and 429 on the Explorer APIs**. A refusal is not an incident, so no rule watches it; the panel « Explorer calls from outside the page » (dashboard Application, Guards) shows them.

- 403 with `"This endpoint serves the Analysis Explorer page only."` on `/{lang}/api/explorer/*` or `/api/spectrum-preview/*`: the request did not carry `Sec-Fetch-Site: same-origin` and `Sec-Fetch-Mode: cors`, which only the page's own `fetch()` sends (`views/explorer/guard.py`). A script, a pasted URL or another site gets this answer, with a link to the documented products. The metric `manuspectrum_explorer_ui_checks_total{outcome,reason}` counts them by reason. `EXPLORER_UI_ONLY` in `.env` is `enforce` (refuse), `observe` (answer and count) or `off` (no check); change it, then recreate `web`. A curl probe or a measurement script must send `-H 'Sec-Fetch-Site: same-origin' -H 'Sec-Fetch-Mode: cors'`.
- 429 from nginx on the same routes: one address spent the pace zone (`explorer`, 10 r/s, burst 40) or the hourly budget (`explorer_budget`: a bucket of 6000 refilled at 100 r/m, so about 6000 an hour and up to ~12000 in the first hour from a full bucket). Read them in the access log (`NGINX_LOG_HOST_DIR`, JSON): `status` 429 and a `uri` under `/api/explorer/` or `/api/spectrum-preview/`, grouped by client address, for example `jq -r 'select(.status==429 and (.uri|test("/api/(explorer|spectrum-preview)/"))) | .remote_addr' <access.log> | sort | uniq -c | sort -rn | head`. The two numbers are `rate=` in `deploy/compose/nginx/snippets/ratelimit.conf` and `burst=` in the `^/(en|fr)/api/explorer/` and `^/api/spectrum-preview/` locations of `edge-rules.conf` (keep burst = rate per minute x 60); `tests/test_edge_contract.py` pins them together. Reload nginx after a change.
- Before an event (a class, a workshop, a demonstration) where many people share one address, raise the budget: for 60 people browsing, set `rate=` to `300r/m` and `burst=` to `18000` in both places, reload nginx (`make -C deploy nginx-reload`), and put the values back afterwards. Update the two numbers in `tests/test_edge_contract.py` only if the change is kept.
- A browser that sends no Fetch Metadata (old or privacy-hardened) is answered when its `Referer` is a page of this site (metric reason `referer`); with no Referer either it gets the 403 above.

## ExplorerBundleBuildSlow

Severity: warning. The Explorer corpus rebuild is slow.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. Grafana through the SSH tunnel.

### Symptom

Changes to the data reach the Explorer late; worker memory rises during rebuilds.

### Diagnosis

Dashboard Application, row Explorer: build duration, bundle size, rows. Logs of `manuspectrum.explorer` give the duration and the number of analyses of each build.

### Remediation

Accept the delay during a large import. Otherwise give the workers more memory or lower the number of gunicorn workers; the lasting answer is the incremental projection (issue #101).

### Escalation

The technical lead, then the project lead for the budget of the projection.

## ExplorerBundleBuildVerySlow

Severity: critical. The Explorer corpus rebuild is very slow.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. Grafana through the SSH tunnel.

### Symptom

The Explorer shows stale data and workers risk running out of memory.

### Diagnosis

As for `ExplorerBundleBuildSlow`; check `ContainerMemoryNearLimit` and `WebMemoryNearLimit` at the same time.

### Remediation

Stop the import that causes it if any. Raise the memory limit of web and worker or reduce the workers, then plan the incremental projection (issue #101).

### Escalation

The technical lead, then the project lead for the budget of the projection.

## ExplorerRebuildFailing

Severity: warning. Background Explorer rebuilds fail.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

The Explorer keeps serving the previous corpus; new data does not appear.

### Diagnosis

`make -C deploy logs` for the `manuspectrum.explorer` errors of web (a database timeout, a memory error).

### Remediation

Fix the error shown. A request that needs the build runs it in the request and shows the error to its reader.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## ExplorerRebuildContinuous

Severity: info. The Explorer corpus is rebuilt all the time.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

Nothing visible; the corpus is rebuilt as soon as a rebuild ends because the data keeps changing.

### Diagnosis

Dashboard Application, row Explorer. A bulk import or a loop writing to the data tables keeps the change ledger moving.

### Remediation

None needed during an import. If no import runs, find the writer in the logs.

### Escalation

Mentioned in the monthly report; the technical lead if it persists.

## DataChangeLedgerNotPruned

Severity: warning. The data change ledger is not pruned.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

The ledger grows; the Explorer data version check slows down.

### Diagnosis

Check that beat and worker run (`make -C deploy status`) and the task `prune_data_changes` in the worker log.

### Remediation

Restart beat and worker. Run the prune task by hand through `make -C deploy manage`.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.
