"""Where Arches imposes a version, the project follows it.

Arches pins exact versions in its own `package.json` (the `arches` and
`arches-dev-dependencies` packages) and in its Python requirements. The rule
is generic: whatever Arches pins exactly and the project also declares must
equal Arches' pin, unless `DIVERGENCES` names it with a reason. Everything
Arches leaves open stays free.

The checks are functions of the parsed files, so the unit cases at the bottom
feed them modified copies.
"""

import copy
import importlib.metadata
import json
import re
import tomllib
import unittest
from pathlib import Path

import yaml
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]

ARCHES_PACKAGES = ("arches", "arches-dev-dependencies")
EXACT_VERSION = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")
ARCHES_REF = re.compile(r"#stable/(\d+\.\d+\.\d+)$")

# Names Arches pins exactly that the project declares at another version.
DIVERGENCES = {
    "vue": "Security fix: 3.5.44, same minor as Arches' 3.5.20 (b870ea7e).",
    "typescript": "The project type-checks with 5.6.2; arches-dev-dependencies "
    "pins 5.4.5 and keeps its own nested copy.",
    "webpack": "Dependabot keeps webpack current (5.110.x); "
    "arches-dev-dependencies keeps its own nested 5.105.4.",
    "webpack-dev-server": "Override 5.2.7 clears an advisory present in 5.2.5.",
    "@babel/core": "Override ^7.29.6 clears advisories present in 7.29.0.",
}

# (parent package, name) pairs whose nested copy is the parent's own pin, not
# a second copy of an Arches pin.
NESTED_ALLOWED = {
    ("arches-vue-components", "@primeuix/themes"): "pins 1.0.1 itself",
    ("arches_vue_components", "@primeuix/themes"): "pins 1.0.1 itself",
}


def load_project(root=ROOT):
    return {
        "lock": json.loads((root / "package-lock.json").read_text()),
        "package": json.loads((root / "package.json").read_text()),
        "uv": tomllib.loads((root / "uv.lock").read_text()),
        "pyproject": tomllib.loads((root / "pyproject.toml").read_text()),
        "dependabot": yaml.safe_load((root / ".github" / "dependabot.yml").read_text()),
    }


def arches_exact_pins(lock):
    """Name -> version for every exact pin of arches and arches-dev-dependencies."""
    pins = {}
    for package in ARCHES_PACKAGES:
        entry = lock["packages"][f"node_modules/{package}"]
        for section in ("dependencies", "devDependencies"):
            for name, spec in (entry.get(section) or {}).items():
                if EXACT_VERSION.match(spec):
                    pins[name] = spec
    return pins


def declared_specs(package):
    """Name -> spec of our dependencies, devDependencies and string overrides."""
    specs = {}
    for section in ("dependencies", "devDependencies", "overrides"):
        for key, spec in (package.get(section) or {}).items():
            if not isinstance(spec, str):
                continue
            name = ("@" + key[1:].split("@")[0]) if key[0] == "@" else key.split("@")[0]
            specs[name] = spec
    return specs


def pinned_by_arches(project):
    """The names Arches pins exactly that we declare, with both specs."""
    pins = arches_exact_pins(project["lock"])
    ours = declared_specs(project["package"])
    return {name: (ours[name], pins[name]) for name in pins if name in ours}


def spec_problems(project, divergences=DIVERGENCES):
    problems = []
    shared = pinned_by_arches(project)
    for name, (ours, theirs) in sorted(shared.items()):
        if name not in divergences and ours != theirs:
            problems.append(
                f"package.json declares {name} {ours!r} but Arches pins {theirs!r}: "
                f"set it to {theirs!r}, or add {name!r} to DIVERGENCES with a reason."
            )
    for name in sorted(divergences):
        if name not in shared:
            problems.append(
                f"DIVERGENCES names {name!r}, which Arches no longer pins exactly "
                "or the project no longer declares: remove the entry."
            )
        elif shared[name][0] == shared[name][1]:
            problems.append(
                f"DIVERGENCES names {name!r} but package.json now equals Arches' "
                f"pin {shared[name][1]!r}: remove the entry."
            )
    return problems


def nested_problems(project, divergences=DIVERGENCES):
    followed = {
        name for name, (ours, theirs) in pinned_by_arches(project).items()
    } - set(divergences)
    problems = []
    for path in project["lock"]["packages"]:
        if "/node_modules/" not in path:
            continue
        parent, name = path.rsplit("/node_modules/", 1)
        parent = parent.split("node_modules/")[-1]
        if name in followed and (parent, name) not in NESTED_ALLOWED:
            problems.append(
                f"{path} is a second installed copy of {name}, which Arches pins "
                "and the project follows: align the versions so npm keeps one."
            )
    return problems


def dependabot_problems(project, divergences=DIVERGENCES):
    expected = set(pinned_by_arches(project)) - set(divergences)
    npm = next(
        u for u in project["dependabot"]["updates"] if u["package-ecosystem"] == "npm"
    )
    actual = {rule["dependency-name"] for rule in npm.get("ignore", [])}
    problems = []
    if expected - actual:
        problems.append(
            "dependabot.yml npm `ignore` lacks the packages Arches pins exactly: "
            f"add {sorted(expected - actual)}."
        )
    if actual - expected:
        problems.append(
            "dependabot.yml npm `ignore` lists packages Arches does not pin "
            f"exactly (or that diverge on purpose): remove {sorted(actual - expected)}."
        )
    return problems


def uv_ignore_problems(project):
    uv = next(
        u for u in project["dependabot"]["updates"] if u["package-ecosystem"] == "uv"
    )
    rules = [r for r in uv.get("ignore", []) if r["dependency-name"] == "arches*"]
    if not rules:
        return ["dependabot.yml uv `ignore` has no rule for `arches*`."]
    if any("update-types" in r for r in rules):
        return [
            "dependabot.yml uv `ignore` for `arches*` must cover every update "
            "type: drop its `update-types`."
        ]
    return []


def version_problems(project):
    uv_versions = [
        p["version"] for p in project["uv"]["package"] if p["name"] == "arches"
    ]
    if len(uv_versions) != 1:
        return ["uv.lock must hold exactly one `arches` package."]
    version = uv_versions[0]
    problems = []
    package = project["package"]
    for section in ("dependencies", "devDependencies"):
        for name in ARCHES_PACKAGES:
            ref = (package.get(section) or {}).get(name)
            if ref is None:
                continue
            match = ARCHES_REF.search(ref)
            if not match or match.group(1) != version:
                problems.append(
                    f"package.json {name} is {ref!r} but uv.lock has arches "
                    f"{version}: use `#stable/{version}`."
                )
    lock_version = project["lock"]["packages"]["node_modules/arches"]["version"]
    if lock_version != version:
        problems.append(
            f"package-lock.json has arches {lock_version}, uv.lock {version}."
        )
    requirement = next(
        Requirement(r)
        for r in project["pyproject"]["project"]["dependencies"]
        if canonicalize_name(Requirement(r).name) == "arches"
    )
    if not requirement.specifier.contains(version, prereleases=True):
        problems.append(
            f"pyproject.toml requires arches{requirement.specifier} but uv.lock "
            f"resolves {version}."
        )
    return problems


def pyproject_requirements(pyproject):
    sections = [pyproject["project"].get("dependencies", [])]
    sections += pyproject["project"].get("optional-dependencies", {}).values()
    sections += pyproject.get("dependency-groups", {}).values()
    return [Requirement(r) for group in sections for r in group if isinstance(r, str)]


def python_pin_problems(pyproject, arches_requires):
    arches_names = {canonicalize_name(Requirement(r).name) for r in arches_requires}
    problems = []
    for requirement in pyproject_requirements(pyproject):
        name = canonicalize_name(requirement.name)
        if name in arches_names and any(
            s.operator in ("==", "===") for s in requirement.specifier
        ):
            problems.append(
                f"pyproject.toml pins {requirement} with `==` but Arches requires "
                f"{name}: use a range inside Arches' so the resolver can follow it."
            )
    return problems


def arches_requires():
    return [
        r for r in importlib.metadata.requires("arches") or [] if "extra ==" not in r
    ]


class ArchesPinsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = load_project()

    def assertNoProblems(self, problems):
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_exact_arches_pins_are_followed(self):
        self.assertNoProblems(spec_problems(self.project))

    def test_one_installed_copy_of_each_followed_pin(self):
        self.assertNoProblems(nested_problems(self.project))

    def test_dependabot_npm_ignore_is_the_pins_arches_imposes(self):
        self.assertNoProblems(dependabot_problems(self.project))

    def test_dependabot_uv_ignores_every_arches_update(self):
        self.assertNoProblems(uv_ignore_problems(self.project))

    def test_arches_version_agrees_across_files(self):
        self.assertNoProblems(version_problems(self.project))

    def test_pyproject_does_not_pin_what_arches_requires(self):
        self.assertNoProblems(
            python_pin_problems(self.project["pyproject"], arches_requires())
        )


class CheckBehaviourTests(unittest.TestCase):
    """Each check fails on a modified copy of the real files."""

    @classmethod
    def setUpClass(cls):
        cls.real = load_project()

    def project(self):
        return copy.deepcopy(self.real)

    def test_a_mismatched_pin_fails(self):
        project = self.project()
        project["package"]["dependencies"]["leaflet"] = "1.9.4"
        problems = spec_problems(project)
        self.assertEqual(len(problems), 1)
        self.assertIn("leaflet", problems[0])
        self.assertIn("1.6.0", problems[0])

    def test_a_range_over_an_exact_pin_fails(self):
        project = self.project()
        project["package"]["dependencies"]["primevue"] = "^4.3.7"
        self.assertTrue(any("primevue" in p for p in spec_problems(project)))

    def test_a_stale_divergence_fails(self):
        project = self.project()
        project["package"]["overrides"]["vue"] = "3.5.20"
        problems = spec_problems(project)
        self.assertEqual(len(problems), 1)
        self.assertIn("remove the entry", problems[0])

    def test_a_divergence_on_an_unpinned_name_fails(self):
        problems = spec_problems(self.project(), {**DIVERGENCES, "left-pad": "x"})
        self.assertTrue(any("left-pad" in p for p in problems))

    def test_a_missing_ignore_fails(self):
        project = self.project()
        npm = next(
            u
            for u in project["dependabot"]["updates"]
            if u["package-ecosystem"] == "npm"
        )
        npm["ignore"] = [r for r in npm["ignore"] if r["dependency-name"] != "primevue"]
        problems = dependabot_problems(project)
        self.assertEqual(len(problems), 1)
        self.assertIn("primevue", problems[0])

    def test_an_extra_ignore_fails(self):
        project = self.project()
        npm = next(
            u
            for u in project["dependabot"]["updates"]
            if u["package-ecosystem"] == "npm"
        )
        npm["ignore"].append({"dependency-name": "pinia"})
        self.assertTrue(any("pinia" in p for p in dependabot_problems(project)))

    def test_a_nested_second_copy_fails(self):
        project = self.project()
        project["lock"]["packages"]["node_modules/foo/node_modules/leaflet"] = {
            "version": "1.9.4"
        }
        self.assertTrue(
            any("foo/node_modules/leaflet" in p for p in nested_problems(project))
        )

    def test_a_nested_copy_of_a_divergence_is_allowed(self):
        project = self.project()
        project["lock"]["packages"]["node_modules/foo/node_modules/vue"] = {
            "version": "3.5.20"
        }
        self.assertEqual(nested_problems(project), [])

    def test_an_arches_version_mismatch_fails(self):
        project = self.project()
        project["package"]["devDependencies"][
            "arches-dev-dependencies"
        ] = "archesproject/arches-dev-dependencies#stable/8.1.4"
        self.assertTrue(any("8.1.4" in p for p in version_problems(project)))

    def test_a_pyproject_range_excluding_the_locked_arches_fails(self):
        project = self.project()
        deps = project["pyproject"]["project"]["dependencies"]
        deps[:] = ["arches>=8.0,<8.1" if d.startswith("arches>=") else d for d in deps]
        self.assertTrue(
            any("pyproject.toml requires" in p for p in version_problems(project))
        )

    def test_a_uv_ignore_limited_to_some_update_types_fails(self):
        project = self.project()
        uv = next(
            u
            for u in project["dependabot"]["updates"]
            if u["package-ecosystem"] == "uv"
        )
        uv["ignore"][0]["update-types"] = ["version-update:semver-major"]
        self.assertNotEqual(uv_ignore_problems(project), [])

    def test_a_pyproject_pin_of_an_arches_requirement_fails(self):
        pyproject = copy.deepcopy(self.real["pyproject"])
        pyproject["project"]["dependencies"].append("celery==5.5.0")
        problems = python_pin_problems(pyproject, ["Celery==5.5.0"])
        self.assertEqual(len(problems), 1)
        self.assertIn("celery", problems[0])

    def test_a_pin_of_a_name_arches_does_not_require_passes(self):
        self.assertEqual(
            python_pin_problems(self.real["pyproject"], ["celery==5.5.0"]), []
        )
