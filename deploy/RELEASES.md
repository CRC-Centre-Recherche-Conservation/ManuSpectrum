# Releases

The application image is built, proven, published and signed by GitHub
Actions. A host never builds it: it pulls a digest and checks the signature
before running it (`scripts/release-verify.sh`, used by the update command of
PP-10b).

Image: `ghcr.io/crc-centre-recherche-conservation/manuspectrum`. Tags:
`sha-<40 hex commit>` (staging) and `vX.Y.Z[-rc.N]` (release). The signed
object is the digest, never a tag.

## The chain

| Step | Workflow | What it proves |
| --- | --- | --- |
| Build | `staging.yml`, on push to `main` | The image builds from scratch, with the day's Debian security updates, and carries the label `org.opencontainers.image.revision` = the commit |
| Proof | `stack-proof.yml`, called by `staging.yml` | On that exact image: probe, the whole Compose stack, observability, mails, `down`/`up`, Docker restart, static swap, backup / loss / restore |
| Publish | `staging.yml` | The image that passed is pushed as `sha-<commit>` and its build provenance is attested (workflow `staging.yml`, branch of the run); its digest is in the job summary |
| Guard | `release.yml`, on a `v*` tag | A ruleset protects the `v*` tags (the job fails otherwise); final tags sit on the first-parent line of `main`, release candidates on the integration branch named for their version (`dev/X.Y.Z`, `dev/X.Y.x` or `dev/X.x.x`), no other tag name is accepted; the tag's `X.Y.Z` must equal `APP_VERSION` in `manuspectrum/settings.py` at the tagged commit (`release-version-guard.sh`) |
| Promote | `release.yml` | The provenance of the `sha-<commit>` digest is verified (`gh attestation verify`: signer workflow `staging.yml`, branch `main` for a final tag, the integration branch the guard found for a candidate), then the digest gets the tag name; the digest is compared before and after. No `sha-<commit>` image means `staging.yml` did not publish the commit: the job fails and says so. An image built on the integration branch is therefore never released as final |
| Scan | `release.yml` | Trivy (HIGH and CRITICAL with a fix) blocks; accepted findings and their expiry are in `.trivyignore` |
| Sign | `release.yml` | The job first checks that a digest carrying only `staging.yml`'s provenance fails `cosign verify`; then the digest is signed with cosign, keyless (GitHub OIDC); then the SBOM attestation is attached to it in GHCR (made by the same workflow identity, which cosign v3 accepts as a signature, so it comes last) |
| Verify | `release.yml` | `scripts/release-verify.sh`, the policy a host runs, accepts the release and refuses a `sha-*` reference, a signature of another tag and (for a candidate) the `prod` policy |
| Release | `release.yml` | The GitHub Release is created (pre-release for a candidate) or edited if it exists |

`deploy-lint.yml` runs the same `stack-proof.yml` on pull requests, with the
image built from the buildkit cache of the pull request and its base branch.
Pushes to the integration branch only warm that cache (`staging.yml`,
`warm-cache`); a manual run of `staging.yml` on it publishes a `sha-<commit>`
image too.

## Branches

`main` holds what is released; feature branches start from the integration
branch and merge into it. An integration branch is named
`dev/<major>.<minor>.<patch>` where minor and patch are a number or `x`
(`^dev/[0-9]+\.([0-9]+|x)\.([0-9]+|x)$`): `dev/1.x.x` carries a whole major
line, `dev/1.0.0` one release. A release candidate `vX.Y.Z-rc.N` must be an
ancestor of an integration branch whose name matches its version: `dev/X.Y.Z`,
else `dev/X.Y.x`, else `dev/X.x.x` (the first one that exists on `origin` and
holds the commit). `release-ref-guard.sh` prints that branch after the commit,
and `release.yml` verifies the provenance against `refs/heads/<that branch>`.
A plain `dev` branch, or a `dev/` branch of another version, is refused. Final
tags stay on the first-parent line of `main`. `staging.yml` runs on every
`dev/**` push (cache warm-up) and by hand on one (`workflow_dispatch`).
`.github/dependabot.yml` needs a literal branch: its `target-branch` values
name the current integration branch.

## Cut a release

1. Merge into the integration branch (`dev/<line>`, e.g. `dev/1.x.x`). To
   publish its tip as `sha-<commit>` before a merge to `main`, run
   `staging.yml` by hand on that branch and wait for it to finish. Until
   `staging.yml` exists on the default branch (`main`), the « Run workflow »
   button is absent: once the push run of the merge has registered the
   workflow, use

   ```bash
   gh workflow run staging.yml --ref dev/<line>
   ```

   Tag exactly the commit the run published: the job summary of `publish`
   shows its commit and digest. A manual run is never cancelled by a later push.
2. Test candidate: set `APP_VERSION` in `manuspectrum/settings.py` to the
   version being released (`0.1.0`, no `v`, no prerelease), merge it, then tag
   the commit and push the tag. `release.yml` refuses a tag whose `X.Y.Z`
   differs from `APP_VERSION`.

   ```bash
   git tag -s v0.1.0-rc.1 <commit>
   git push origin v0.1.0-rc.1
   ```

3. Final release: merge to `main`, wait for `staging.yml` on `main` to
   finish, then tag that commit `v0.1.0` and push it.

   A release that fixes a security problem says so in its signed tag, as a
   trailer in the last paragraph of the message:

   ```bash
   git tag -s v0.1.1 -m v0.1.1 -m 'Security-Fix: yes' <commit>
   ```

   The release watch of a host reads the trailer (`Security-Fix: yes`, on an
   annotated tag). Its effect is on the host only: the « ready to install » mail
   gets « (security fix) » in its subject and a line in its body, and the
   `ReleasePendingTooLong` alert fires after 14 days instead of 30 while the
   release waits. Nothing is installed by it.
4. Follow `release.yml`. A failure before the `sign` job leaves no signature.
   `release.yml` has no manual trigger. Once the cause is outside the commit
   (a registry outage, a scan that needs a newer database), use « Re-run jobs »
   on the run of the tag, within 30 days: it runs the `release.yml` and the
   `.trivyignore` of the tagged commit, promotes and signs the same digest
   again and edits the existing Release. A cause inside the commit (a workflow
   fix, a `.trivyignore` entry) needs a new tag: a failed final release is
   fixed by the next patch tag, never by moving the tag.

A tag that is not `vX.Y.Z` or `vX.Y.Z-rc.N`, a final tag outside the
first-parent line of `main` and a candidate outside the integration branch are
refused by the `guard` job before anything is pushed. Never move or delete a
pushed tag: a signature names the tag, and the repository ruleset forbids it.

## On the host

A host follows one channel, set by `env_release_channel` in the Ansible
inventory (`RELEASE_CHANNEL` in `.env`): `prod` offers final tags
(`vX.Y.Z`) only, `rc` also offers release candidates (`vX.Y.Z-rc.N`). A rehearsal
host uses `rc`, production uses `prod`.

- **The watch** (`manuspectrum-watch.timer`, hourly) fetches the tags, picks the
  highest one the channel allows that is newer than the running version, and
  checks it: the registry digest, the signature and revision
  (`scripts/release-verify.sh`, with the channel policy) and whether Ansible
  must run first. It then marks the release as *armed* and mails
  `ALERT_EMAILS` once. It installs nothing and never moves the checkout (it
  fetches with `--prune-tags`: a tag that moved on the origin is refused by git,
  a local tag the origin lacks is dropped). With `--prune-tags`, a tag deleted
  and created again on the origin between two fetches is accepted as new; the
  armed-commit pin of the engine and `release-verify` still refuse anything the
  release workflow did not sign for that tag, and deleting a release tag is an
  incident. A tag
  whose image or signature is not published yet is waited for six hours before
  it counts as a failure (`ReleaseVerificationFailed`).
- **The update** is started by an operator, now or at a scheduled time, with
  `sudo manuspectrum-update`. It installs the armed release only, after a
  backup, and rolls back on its own when the application does not become ready.
- A host holds no registry credential: the package is public and pulled
  anonymously (`SECRETS.md`).

The operator's steps, the schedule, the refusals and what to do after a
rollback are in [ADMIN.md](ADMIN.md#updating-the-application); the alerts are in
[runbooks/release.md](runbooks/release.md).

## Verify an image by hand

From any machine with Docker and a clone that holds the tag (or with `--commit`):

```bash
git fetch --tags
digest="$(docker buildx imagetools inspect --raw ghcr.io/crc-centre-recherche-conservation/manuspectrum:v0.1.0-rc.1 | sha256sum | cut -d' ' -f1)"
bash deploy/scripts/release-verify.sh --policy rc \
  "ghcr.io/crc-centre-recherche-conservation/manuspectrum@sha256:$digest" v0.1.0-rc.1
```

It prints the commit when the image is accepted. The policies are `prod`
(final tags only) and `rc` (final or candidate tags). The check is, in this
order: the reference is a digest; with `--repo-dir <clone>` under the `prod`
policy, the tag's commit in that clone (tags and `origin/main` fetched) is on
the first-parent line of `origin/main`; the cosign signature carries the identity
`https://github.com/CRC-Centre-Recherche-Conservation/ManuSpectrum/.github/workflows/release.yml@refs/tags/<tag>`,
the issuer `https://token.actions.githubusercontent.com`, the trigger `push`
and the workflow commit; after the pull, the revision label equals the commit
of the tag. cosign runs from an image pinned by digest inside the script. The
host update command passes `--repo-dir` with the clone it fetched.

While the package is private, `DOCKER_CONFIG_DIR` names a directory holding
the `config.json` of `docker login` (cosign reads it from a container). That
file must hold plain `auths` entries only: a `credsStore` or `credHelpers`
key points at a helper that does not exist inside the cosign container, and
the login is then ignored. Once the package is public, no login is needed.

The attestations are read with the GitHub CLI:

```bash
gh attestation verify oci://ghcr.io/crc-centre-recherche-conservation/manuspectrum@sha256:<digest> \
  --repo CRC-Centre-Recherche-Conservation/ManuSpectrum
```

## Retention

`sha-<commit>` images accumulate, one per merge to `main`. Version tags are
kept. Untagged manifests (the attestations and signatures of an image) belong
to the digest they describe: never delete them by hand. Prune old `sha-*`
versions of the package by age in the GitHub package settings, keeping every
digest that a version tag points to.

## Prerequisites: repository settings

These live in the repository settings, not in the code. They are set before
the first tag is pushed; the chain relies on all of them.

- A tag ruleset on `refs/tags/v*` (enforcement active) with the rules
  `creation`, `update` and `deletion`, bypass limited to administrators.
  `release.yml` fails in its `guard` job when no active ruleset like this
  exists, or when the workflow token could bypass it
  (`current_user_can_bypass` must be `never`; `scripts/release-ruleset-check.sh`).
  The bypass list itself (administrators only, never the Actions app nor the
  Write role) is not readable by the token: it is checked by hand.
- The default workflow token permission is `read` (each workflow widens it per
  job).
- `main` and the integration branch are protected against force-push.
- When branch protection requires status checks, require `conclusion` (the
  job that gathers the workflows of `deploy-lint.yml`) and `gitleaks` (the job
  of `secret-scan.yml`). Both workflows run on every pull request, with no
  `paths:` filter, so the checks are never missing. The jobs of
  `stack-proof.yml` are called workflows with generated names.
- The GHCR package is made public after its first push, so a host can pull it
  without credentials.

## Before pushing a tag (checklist)

1. Ruleset: it includes exactly `refs/tags/v*`, carries `creation`, `update`
   and `deletion`, and its bypass list is administrators only and holds the
   person who tags.
2. `main` and the integration branch are protected (no force-push), and the
   required checks are `conclusion` and `gitleaks`.
3. The default workflow token permission is `read`.
4. Merge, then wait for the warm-cache run on the integration branch (and, for
   a final release, for `staging.yml` on `main`).
5. `gh workflow run staging.yml --ref dev/<line>`; note the
   commit and digest of the job summary.
6. Dry run:

   ```bash
   gh attestation verify oci://ghcr.io/crc-centre-recherche-conservation/manuspectrum@sha256:<digest> \
     --repo CRC-Centre-Recherche-Conservation/ManuSpectrum \
     --signer-workflow CRC-Centre-Recherche-Conservation/ManuSpectrum/.github/workflows/staging.yml \
     --source-ref refs/heads/dev/<line> --source-digest <commit>
   ```

7. Signed tag on that commit, push it, watch `release.yml`: the step
   « Provenance is not a signature » must pass, then verify the image by
   hand (« Verify an image by hand »).
8. After the first push, make the GHCR package public.
9. Migrations: a release with long migrations says how long its readiness
   takes (in the tag message and the release notes), and the operator raises
   `RELEASE_READY_WAIT_SECONDS` in `.env` (default 600, at most 1800: the
   engine refuses a larger value) before installing it. The engine rolls back
   when `/readyz` does not answer within that wait, which would interrupt a
   migration still running; the rollback never restores the data. A
   migration that cannot fit in 1800 seconds is run by hand beforehand.
