# Security policy

## Supported versions

Security fixes go into the latest release. The platform at
[manuspectrum.huma-num.fr](https://manuspectrum.huma-num.fr/) always runs a signed release.

| Version | Supported |
| --- | --- |
| latest `1.x` release | ✅ |
| older releases, release candidates (`-rc.N`) | ❌ |

## Reporting a vulnerability

Please **do not open a public issue**. Report it privately through GitHub:
[**Report a vulnerability**](https://github.com/CRC-Centre-Recherche-Conservation/ManuSpectrum/security/advisories/new)
(the « Security » tab of the repository).

Include what you can of:

- the affected page, route or component, and the version (shown in the back-office menu);
- the steps to reproduce, and what an attacker gains;
- whether the problem needs an account, and which role.

We acknowledge a report within five working days, keep you informed while we work on it, and credit you in the
advisory if you wish. A fix is released as a new signed version; its tag is marked as a security release, which
shortens the time the platform administrators have to install it.

## Scope

- **In scope**: the code of this repository (the ManuSpectrum application and its deployment kit) and the platform it
  runs.
- **Arches**: a vulnerability in Arches core belongs to the Arches project; report it as their
  [security policy](https://github.com/archesproject/arches/security) describes. If you are unsure where a problem
  lies, report it here and we will route it.
- **Out of scope**: denial of service by volume, findings from automated scanners without a demonstrated impact, and
  the third-party services the platform links to.

Please test only against your own installation, never against other people's data, and give us reasonable time to
fix a problem before you disclose it.
