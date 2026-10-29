# Security policy

## Supported versions

Security fixes go into the latest release. The platform at
[manuspectrum.huma-num.fr](https://manuspectrum.huma-num.fr/) always runs a signed release.

| Version | Supported |
| --- | --- |
| latest `1.x` release | ✅ |
| older releases, release candidates (`-rc.N`) | ❌ |

## Reporting a vulnerability

Please **do not open a public issue, pull request or discussion**. Report it privately through GitHub:
[**Report a vulnerability**](https://github.com/CRC-Centre-Recherche-Conservation/ManuSpectrum/security/advisories/new)
(the « Security » tab of the repository). Only you and the maintainers see the report.

Include what you can of:

- the affected page, route or component, and the version (shown in the back-office menu);
- the steps to reproduce, and what an attacker gains;
- whether the problem needs an account, and which role.

## What happens next

ManuSpectrum is maintained by a small research team: we answer as soon as we can and keep you informed, but we cannot
commit to fixed delays.

1. **Triage.** We confirm the problem, assess its impact and agree on its severity with you, in the advisory.
2. **Private fix.** The fix is developed in a **temporary private fork** attached to the advisory (a GitHub security
   advisory feature), never on a public branch. If you wish to help, we add you as a collaborator on it; the
   fork is deleted once the advisory is published.
3. **Release.** The fix ships as a new signed version, whose tag is marked as a security release so the platform
   administrators install it promptly.
4. **Disclosure.** We publish the advisory once the fixed release is out, request a CVE when it applies, and credit you
   if you wish.

Please keep the details private until the advisory is published, test only against your own installation, never against
other people's data, and use no more access than you need to show the problem.

## Scope

- **In scope**: the code of this repository (the ManuSpectrum application and its deployment kit) and the platform it
  runs.
- **Arches**: a vulnerability in Arches core belongs to the Arches project; report it as their
  [security policy](https://github.com/archesproject/arches/security) describes. If you are unsure where a problem
  lies, report it here and we will route it.
- **Out of scope**: denial of service by volume, findings from automated scanners without a demonstrated impact, and
  the third-party services the platform links to.
