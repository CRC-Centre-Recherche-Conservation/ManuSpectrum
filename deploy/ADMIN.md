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

1. In the admin, Users, "Add user": a user name and the **e-mail address**, no password
   (leave the password fields empty or unusable). Save. Give the groups the person needs.
2. In the Users list, tick the account, choose the action **Send invitation (account with
   no password)**. The person receives a mail `[ManuSpectrum][Account] Your ManuSpectrum
   account` (English, then French) with a personal link, valid for a limited time.
   An account that is inactive, has no e-mail or already has a password is skipped with a
   message. A failed send is reported and counted (`AccountMailFailures`): fix the relay
   (`runbooks/application.md`), then send a new invitation.
3. The person opens the link, reads and accepts the terms of use (a required checkbox;
   the acceptance is stored with its date and the version of the terms), chooses a
   password (12 characters or more, upper and lower case, a digit and a symbol; common
   or similar passwords are refused), then sets up two-factor authentication with an
   authenticator application at `/<lang>/account/two-factor`.
4. An invitation never activated shows in the monthly report (below) after three months.

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
  opens the admin, User profiles, ticks the profile and chooses **Reset two-factor
  authentication (superuser)** (only superusers can). The action clears the secret and mails
  the person a personal link (`account/two-factor/reset/...`, valid 24 hours, single use):
  they type their password, scan the new QR code, confirm one code and are signed in. A
  wrong password counts as a failed sign-in (lockout). **Send the two-factor enrolment link
  (superuser)** mails the link again to the selected profiles that hold no secret (lost
  mail, expired link). An account without an address or inactive gets no mail: the action
  says so.
- **New `SECRET_KEY`.** Every stored secret becomes unreadable (`SECRETS.md`). In User
  profiles, select all profiles with a secret and run **Reset two-factor authentication
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
  (GDPR art. 12-14, transparency). Send one mail by hand from the shared project mailbox, with
  the active accounts in blind copy (export the addresses from the admin user list), saying what
  changes and linking the page. Note the date and the change in the register below.

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
