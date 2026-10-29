# Contributing to ManuSpectrum

Thank you for helping! ManuSpectrum is a research platform maintained by a small team at the Centre de Recherche sur la
Conservation (CRC). Bug reports, ideas, documentation fixes and code are all welcome.

## Before you start

- **Questions and ideas**: open an issue with the matching template. For a larger change, describe it in an issue first,
  so we can agree on the approach before you write code.
- **Security problems**: never in a public issue. Follow [`SECURITY.md`](SECURITY.md).
- **Models and vocabularies** (graphs, controlled lists) live in the
  [data package](https://github.com/CRC-Centre-Recherche-Conservation/manuspectrum-pkg): changes to them go there.
- Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md).

## Branches and pull requests

- `dev` is the integration branch: start your branch from it and open your pull request against it.
- `main` holds what is released; it only receives merges from `dev`.
- Keep one topic per pull request, and fill in the pull request template: summary, what changed, how you verified it,
  follow-ups, and the issue it closes.
- CI runs on every pull request: tests on Python 3.11, 3.12 and 3.13, frontend tests, Black, Prettier, ESLint,
  TypeScript, missing migrations, line endings, secret scanning, and a coverage gate (a pull request may not lower the
  Python or frontend coverage of `dev`). Changes to `deploy/` also run the whole stack in containers.

## Development set-up

See [Getting started](README.md#-getting-started-development) in the README. Install the git hooks once per clone:

```bash
pre-commit install
```

They run Black, Prettier, ESLint, the TypeScript check and a secret scan on each commit.

## How we write code

- **Stay inside Arches.** Use an Arches extension point (datatype, function, widget, plugin, search component, ETL
  module) or its Python and JavaScript APIs when one exists. A copy of an Arches core file is a last resort: it names
  the core file, the Arches version and the exact difference in its header.
- **Permissions go through Arches' permission framework**, never around it. A payload that depends on the reader is
  never cached under a shared key.
- **New interface**: Vue 3 + TypeScript where Arches allows it; Knockout only where Arches requires it.
- **Bilingual**: every user-facing string exists in English and French (Django `gettext`, `{% trans %}`, `$gettext()`
  in Vue). Run `makemessages` from inside `manuspectrum/` (the folder holding `locale/`).
- **Tests come with the change**, and a test that must fail without the change is checked against the old code first.
  Run one Django test module per process:

  ```bash
  python manage.py test tests.<module> --settings=tests.test_settings --noinput
  npx vitest run <spec> --coverage.enabled=false
  ```

- **Comments document the code**, for a reader who was not in the review: constraints in docstrings, short inline
  comments for a local gotcha only.
- **Performance claims** come with a before/after measurement, not an estimate.

## Commits

- One commit per logical change, written as `type(scope): imperative summary`, with `type` among `feat`, `fix`,
  `perf`, `chore`, `docs`, `test`.
- Code, comments, commit messages and documentation are in English.
- Never commit a secret, a production value or research data. The secret scan blocks most mistakes; a leaked secret is
  rotated, not just removed.

## Licence

ManuSpectrum is published under the [GNU AGPL-3.0](LICENSE). By contributing, you agree that your contribution is
published under the same licence.
