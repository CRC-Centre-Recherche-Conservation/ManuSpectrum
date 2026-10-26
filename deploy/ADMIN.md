# Administration

Day-to-day tasks of the administrators of a running ManuSpectrum. This page covers
accounts, restrictions (embargoes), abandoned workflows and the draft register of
processing; PP-9 completes it with the rest of the operating procedures. Commands
run on the host from the repository checkout, as the service account; "the admin" is
the Django administration (`/<lang>/admin/`), which only staff and superusers reach.

## Accounts

There is no self-signup (`POST /<lang>/auth/signup` answers 404). An account exists
because an administrator created it. People ask for one through the contact page
(reason "Request an account"), which opens a pre-filled mail; nothing is stored.

### Create an account and invite the person

1. In the admin, Users, "Add user": user name, **e-mail address** (required, unique), first and
   last name and the groups the person needs. There is no password field: the account is
   created with an unusable password. Leave **Send the invitation now** ticked (the default)
   and save: the person receives a mail `[ManuSpectrum][Account] Your ManuSpectrum
   account` (English, then French) with a personal link, valid for a limited time. Staff and
   superuser rights are set on the change page afterwards.
2. To send the invitation again (lost mail, expired link), or when the box was unticked: in
   the Users list, tick the account and choose **Send invitation (account with no
   password)**. An account that is inactive, has no e-mail or already has a password is
   skipped with a message. A failed send is reported and counted (`AccountMailFailures`):
   fix the relay (`runbooks/application.md`), then send a new invitation.
3. The person opens the link, reads and accepts the terms of use (a required checkbox;
   the acceptance is stored with its date and the version of the terms), chooses a
   password (12 characters or more, upper and lower case, a digit and a symbol; common
   or similar passwords are refused), then sets up two-factor authentication with an
   authenticator application at `/<lang>/account/two-factor`.
4. An invitation never activated shows in the monthly report (below) after three months.
5. Advise editors not to switch on the spell checker (SCAYT) of the rich-text editor: it sends the typed text to a third party (WebSpellChecker); the browser's own spell checker does not.

### Two-factor authentication

- TOTP, with any authenticator application. Enrolment is self-service at
  `/<lang>/account/two-factor`.
- Rollout order (`README.md`, "Upgrading"): deploy with `FORCE_TWO_FACTOR_AUTHENTICATION=false`
  in `.env`, the administrators enrol, then set `true` and recreate `web`. With `true`, a
  sign-in without a second factor is refused by Arches, and the project middleware keeps any
  signed-in account that has no secret on `account/two-factor` (page navigations are
  redirected there, every other request is refused with 403), so a newly invited person
  enrols right after activating and nobody uses the site without a second factor. An
  account that existed before the switch and never enrolled cannot sign in: select it and run **Send the two-factor
  enrolment link (superuser)** (below), which mails it the enrolment link (**Reset** skips
  accounts that hold no secret).
- **Lost phone.** After checking the person's identity by another channel, a superuser
  opens the admin, Users, ticks the account and chooses **Reset two-factor
  authentication (superuser)** (only superusers can; the same actions are on the Arches profile
  pages, reached from the link on the User page). The list shows the **Two-factor
  authentication** column and filter, the User page an « Account » section. The action clears the secret and mails
  the person a personal link (`account/two-factor/reset/...`, valid 24 hours, single use):
  they type their password, scan the new QR code, confirm one code and are signed in. A
  wrong password counts as a failed sign-in (lockout). **Send the two-factor enrolment link
  (superuser)** mails the link again to the selected accounts that hold no secret (lost
  mail, expired link). An account without an address or inactive gets no mail: the action
  says so.
- **New `SECRET_KEY`.** Every stored secret becomes unreadable (`SECRETS.md`). In the Users
  list, use the filter **By two-factor authentication** → **Enrolled**, select all and run **Reset two-factor authentication
  (superuser)**: every person gets their link. Rotate when the working hours allow, since
  those who do not follow their link stay locked out until they do (re-send it as needed).
- An OAuth2 application with the password grant signs a user in at `o/token/` with a password
  alone, whatever `FORCE_TWO_FACTOR_AUTHENTICATION` says. System check `manuspectrum.W004`
  (run by `migrate`) warns when one exists; add "no OAuth2 application with the password
  grant" to the production checklist.
- Arches' own 2FA settings and reset routes are refused at the edge; enrolment and resets go
  through the project pages above, and no mail comes from Arches' routes.
- The secrets are encrypted with `SECRET_KEY`: a new key makes everyone re-enrol
  (`SECRETS.md`).

### Unlock a locked account

Five failed sign-ins lock one account from one address for 15 minutes; the account stays
usable from another address. A user usually just waits. To unlock at once:

```bash
make -C deploy manage ARGS="axes_reset_username <username>"
```

or delete the row in the admin, "Access attempts". `LoginLockouts` warns above five locks in
an hour (`runbooks/application.md`).

### Terms of use

The terms are `manuspectrum/templates/views/pages/terms.htm` and their French catalogue
entries. Changing them:

1. Edit the English template and the French entries (`makemessages`, translate, `compilemessages`;
   `CLAUDE.md`, "Internationalization").
2. `tests/test_about_pages.TermsDigestTests` fails until `TERMS_DIGEST` in
   `manuspectrum/accounts/terms.py` is updated.
3. A change of substance: bump `TERMS_VERSION` too. Every signed-in user is then sent to
   the acceptance page at the next sign-in. A typo fix: update `TERMS_DIGEST` only, nobody is
   asked again.

The admin lists each acceptance (user, version, date) under "Terms acceptances". No mail is
sent when the terms change: acceptance at the next sign-in is the record, and someone who does
not sign in again does not use the service under the new terms.

### Privacy policy

The privacy policy (`manuspectrum/templates/views/pages/privacy.htm`) is information, not
something users accept: the processing rests on the public-interest mission, not on consent.
Changing it:

- Wording, a clarification, a corrected address: edit the page and its French entries, nothing
  else.
- A change of substance (a new purpose, a new recipient, a new third-party service, a transfer
  outside the European Union, a longer retention): the people concerned are told actively
  (GDPR art. 12-14, transparency). The application sends nothing itself: the administrator
  writes one mail from the shared project mailbox, with every active account in blind copy.
  Note the date and the change in the register below.

To get the addresses (superusers only, nothing to install):

1. Sign in, open the Django administration, then **Users**.
2. Tick the box at the top of the list to select the users of the page, then click
   **Select all N users** to take every page.
3. In the **Action** menu choose **Copy the e-mail addresses**, then click **Go**.
4. The page shows how many addresses it holds and, below, how many selected users were left
   out (inactive, no e-mail address, anonymised). Click **Copy**.
5. In the shared project mailbox, write a new message and paste the addresses in the **Bcc**
   field, never in To or Cc (the recipients must not see one another). Put the project
   address in To.
6. Paste the message below, adapt it, send it.

Message to adapt:

```text
Subject: ManuSpectrum: our privacy policy changes

Hello,

On <date>, the privacy policy of ManuSpectrum changes: <what changes, in one or two
sentences>. This takes effect from <date>.

The full text is at https://<site>/en/about/privacy. For any question, write to
<contact address>.

The ManuSpectrum team

---

Objet : ManuSpectrum : notre politique de confidentialité change

Bonjour,

Le <date>, la politique de confidentialité de ManuSpectrum change : <ce qui change, en une
ou deux phrases>. Elle s'applique à partir du <date>.

Le texte complet est sur https://<site>/fr/about/privacy. Pour toute question, écrivez à
<adresse de contact>.

L'équipe ManuSpectrum
```

### Inactive accounts

The monthly report (`OBSERVABILITY.md`) has an "Comptes inactifs" section: the active accounts
(not `anonymous`) with no sign-in for 12 months, and those that never signed in 3 months after
they were created (an invitation never activated counts there), with user name, last sign-in
or "jamais", and creation date. At 12 months nothing is done automatically: deactivating an
account is a decision of the project owner, taken by hand in the admin (untick "Active").
Deactivating an account (the user's page, or any save that turns "Active" off) mails the
user at once (`[ManuSpectrum][Account] Your account has been deactivated`, English then
French, only when the account has an e-mail address): the deactivation date, a link to the
contact page (`?reason=reactivation`) to ask for a reactivation, and the date the account
will be anonymised unless it is reactivated and used. That date is the end of the retention
period below, or 30 days after the deactivation when the account is already inside the notice
window (the deactivation mail is then its anonymisation notice). A superuser is told the
administrators decide instead. A bulk change by SQL or `QuerySet.update()` sends nothing;
the anonymisation itself sends no deactivation mail. Reactivating sends nothing.

At 24 months without a sign-in (`ACCOUNT_RETENTION_MONTHS`; a never-used account counts from
its creation) an account is **anonymised** by the daily pass (04:30 Europe/Paris), after one
notice mailed 30 days before (`ACCOUNT_RETENTION_NOTICE_DAYS`). A sign-in after the notice
cancels it. Anonymising never deletes: first and last name and e-mail are cleared, the user
name becomes `former-user-<id>`, the password is unusable, the two-factor secret and phone
are cleared, the account is deactivated, its sessions and sign-in records are removed, and in
the edit history the e-mail is erased while the name stays as contribution credit; the admin history
(`django_admin_log`) of the user object shows the new `former-user-<id>` name.
Permissions, groups, accepted terms and Person resources stay. The `ms_account_retention`
ledger keeps the user id and the dates, no personal data.

Superusers are warned and listed once in the administrators' summary (`ALERT_EMAILS`), and
are never anonymised by the pass: the decision is human. The monthly report counts the
accounts anonymised in the month.

- **Dry run.** `make -C deploy manage ARGS="anonymise_inactive_accounts"` lists, by user id,
  the notices and anonymisations the pass would make and writes and sends nothing; `--apply`
  runs the pass.
- Alerts: `AccountRetentionFailures`, `AccountRetentionStale`.

## Restrictions (embargoes)

A restriction is an Arches permission; the **Embargo** record in the admin carries its end
date and its history. Restrictions are temporary by construction: 12 months at most (`EMBARGO_MAX_MONTHS`)
unless an administrator records an exception (below).

- **Restricting.** In the resource's permission manager (Arches), set **No Access** for the
  user `anonymous` or the group Guest; the same setting for any other user or group is not a
  restriction here. The Embargo row is created as soon as the permissions are saved; its date
  is then set in the admin, under Embargoes.
- **Date.** The daily pass (06:00 Europe/Paris) records every restriction it finds without an
  Embargo row and dates it at the detection day plus 12 months (events `detected`, then
  `dated` by nobody); open Embargoes in the admin and edit "Ends on" (the last day of the
  restriction) to shorten it. It is lifted the day after at 06:00. A row restored or
  migrated with the database keeps its dates; one already past its end is lifted at the
  next pass with the usual mail. After moving data between hosts without the `ms_embargo`
  table, the first pass therefore dates every restriction it finds at its own detection day
  + 12 months: review the list and shorten what must end sooner.
  Notices go to the resource creator and the user who set the restriction at 30 and 7 days
  before and on the day it becomes public, with a summary to `ALERT_EMAILS`.
- **No end date.** An exception only a superuser can record (clear "Ends on"; it is logged as
  `undated`). Such a restriction is never lifted automatically. The list filter "End date",
  value "No end date", shows them and the monthly report counts them.
- **Extend.** Administrators only, in the admin: edit "Ends on", or tick embargoes and choose
  "Extend the end date by 3, 6 or 12 months". Beyond the maximum duration only a superuser can
  set the date. Each change is recorded: who, when, from and to.
- **History.** Open the embargo: the inline "events" list every change, and "Notices sent"
  the notices already mailed.
- **Rehearsal / by hand.** `make -C deploy manage ARGS="release_expired_embargoes"` lists what
  the pass would do (dry run); `--apply` runs it as the beat task does.
- Alerts: `EmbargoLiftFailures`, `EmbargoOverdue`, `EmbargoPassStale` (`runbooks/application.md`,
  `runbooks/celery.md`). `release_expired_embargoes --as-of YYYY-MM-DD` runs the pass as if it
  were 06:00 Paris that day (rehearsal: an end date cannot be set in the past). `--as-of` with
  `--apply` (here and in `anonymise_inactive_accounts`) is refused when `DEPLOY_ENVIRONMENT` is
  `production`; the dry run stays allowed.

## Search exports by visitors

The search page offers an export of the results. Arches 8.1.5 (`views/search.py`,
`export_results`) decides between the immediate export and the Celery export from the
`total` query parameter sent by the client. A visitor without an account who sends
`total=0`, or none, therefore gets an export of every resource they may read, built in
the web worker: on the rehearsal VM a full `tilecsv` export ran about two minutes, nginx
answered 504 at 120 s and the gunicorn thread worked on until the build ended. The
project accepts this and does not override the Arches route. The setting
`RESTRICT_CELERY_EXPORT_FOR_ANONYMOUS_USER = True` only refuses the Celery path to a
visitor; it does not stop the immediate one.

Who may call it. `export_results` is behind `@group_required("Resource Exporter")`
(`views/search.py`), and the `anonymous` user is a member of that group (Arches
migration `8010_export_permissions` added every user to it). The project keeps this on
purpose: visitors may export small searches. If abuse ever requires it, removing
`anonymous` from the « Resource Exporter » group in the Django admin closes the route
for visitors (Arches' own mechanism, reversible by adding the user back). Signed-in
curators are unaffected as long as they stay in the group.

The API route `api_export_results` (`views/api/search.py`) has no group check, always
builds in the request and answers GeoJSON only when the total is within the limit.
nginx refuses it without a Django session cookie, but a forged cookie passes: that is a
filter against robots, not a barrier.

What bounds it:

- nginx allows one export at a time per address (`limit_conn export_conn 1`) and six per
  minute (`limit_req zone=search_export`) on `/{en,fr}/search/export_results` and
  `/{en,fr}/api/search/export_results`.
- PostgreSQL stops any statement of the web service after 60 s (`PG_STATEMENT_TIMEOUT_MS`).
- The bound is per address, not global: N addresses hold N gunicorn threads for the
  length of a build, and the service has 5 workers x 4 threads = 20. Beyond that the
  other requests queue.

The alert `SearchExportSlow` (warning, `runbooks/site.md`) fires when three or more
exports took more than 60 seconds within 64 hours. The runbook shows how to find the
addresses in the access log and how to block one at the host firewall.

The real fix is a server-side count in Arches that routes large exports to Celery whatever
the client sends. It is not done here: no upstream issue is opened and the core route is
not overridden.

## Very linked resources

Arches loads every relation of a resource at once in three places: the related resources
graph of the search, « load all » in a report's related resources, and the related
resources summary of the report API (new-style reports, the workflow summary step). With
Arches' default of 10,000, a resource with about 1,650 relations froze the browser tab on
the graph: its layout and search grow with the square of the number of relations.

`RELATED_RESOURCES_EXPORT_LIMIT` in `.env` caps those three lists (1000 by default). Beyond
the cap Arches keeps that many relations, in no guaranteed order, and says nothing. The
paginated related resources of a report (15 per page) still show every relation; search
exports and ETL modules never read this value. To change it, edit `.env` and run
`make -C deploy up` (web reads it at start); a value that is not a whole number above 0
stops web from starting.

## Explorer APIs: page only

The Analysis Explorer's internal APIs (`/{lang}/api/explorer/*` except `export`, `series.csv`,
`events.csv`, `events.geojson` and the manifest, and `/api/spectrum-preview/*`) serve the
Explorer page, not other programs. `EXPLORER_UI_ONLY` in `.env` has three modes:

- `enforce` (the default of the deployment): a request that is not the page's own `fetch()`
  (`Sec-Fetch-Site: same-origin` and `Sec-Fetch-Mode: cors`) gets a 403 with a link to « Reuse
  the data » (`/{lang}/about/data`). A browser sending no Fetch Metadata is answered when its
  `Referer` is a page of this site.
- `observe`: answered, and counted as `observed` in `manuspectrum_explorer_ui_checks_total`.
- `off`: no check, no count.

Any other value stops web from starting. Change it in `.env`, then `make -C deploy up`. The
per-address request budget and how to raise it before an event are in
`deploy/runbooks/explorer.md`.

## Abandoned workflows

An open workflow run with no activity for 90 days (`WORKFLOW_CLEANUP_AFTER_DAYS`) is cleaned
daily at 03:30 Europe/Paris, after two notices at 21 and 7 days before. Only what the run
created and nothing else touches (still a draft, unmodified elsewhere, unlinked) is deleted;
completed workflows are never touched.

- **Ledger.** The admin, "Workflow cleanups": last activity, notices sent, cleaned on,
  resources deleted and kept. No user is stored in it.
- **Dry run.** `make -C deploy manage ARGS="prune_workflow_history"` lists the runs that would
  be noticed and cleaned and the resources it would delete and keep, and writes and sends
  nothing. `--apply` runs the pass; `--workflow <id>` restricts it to one run.
- **After a long outage or a restore.** A run found already past its delay gets both notices
  (21 and 7 days) the same day and is cleaned 7 days later. Before the beat schedule is enabled
  again (after a restore, a move to a new host, or a stack stopped for weeks), run the dry run,
  read who would be warned and what would be cleaned, and tell those people beforehand or delay
  the first pass.
- Alerts: `WorkflowCleanupFailures`, `WorkflowCleanupStale`.

## Draft register of processing

A draft for the CNRS data protection officer to complete and validate; the controller is the
CNRS (legal notice, `/<lang>/about/legal`).

| Processing | Data | Purpose | Retention |
| --- | --- | --- | --- |
| Accounts | User name, e-mail, name, password hash (Argon2), groups, two-factor secret (encrypted), acceptance of the terms with its version and date | Give access to describe and edit analyses | Until 24 months without sign-in (`ACCOUNT_RETENTION_MONTHS`), then anonymised after a notice 30 days before; never deleted. Superusers are never anonymised automatically |
| Login records | Sign-in successes and failures with the user name, address and time (django-axes tables) | Security, lockout | 6 months in the database (`LOGIN_RECORDS_RETENTION_DAYS`), then at most 6 months more in the monthly backups |
| Edit log | Who changed which resource and when (Arches `edit_log`) | Scientific traceability | With the data; the e-mail of a contributor is erased when the account is anonymised, the name stays as credit |
| Person resources | Names and affiliations of people in the scientific records | Attribution of data | With the data |
| Mails | Invitations and notices (embargo, workflow) to the people concerned; summaries to `ALERT_EMAILS` | Service notices, no unsubscribe link | Not stored by ManuSpectrum (the relay keeps its own logs) |
| Backups | The whole database, media and secrets, encrypted (restic) | Recovery | 7 daily, 4 weekly, 6 monthly (`BACKUP.md`) |
| Server logs | Access log without query string | Operation | 30 days |

Rights are exercised at `CONTACT_EMAIL`. Erasures since a backup are replayed before reopening a
restored stack (`BACKUP.md`, "Personal data").
