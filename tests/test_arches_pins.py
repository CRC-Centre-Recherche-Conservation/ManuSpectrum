"""Where Arches imposes a version, the project follows it.

Arches pins exact versions in its own `package.json` (`dependencies` for what
its runtime ships, `peerDependencies` for its build and test tooling; the
controlled lists and Vue components applications are bundled in the package)
and in its Python requirements. The rule
is generic: whatever Arches pins exactly and the project also declares must
equal Arches' pin, unless `DIVERGENCES` names it with a reason. Everything
Arches leaves open stays free.

The checks are functions of the parsed files, so the unit cases at the bottom
feed them modified copies. `ZoneFrameContractTests` pins by source snippet what
the annotation zone stamps rely on in Arches' IIIF viewer, leaflet-iiif and
Leaflet, and fails with what to re-check when an upgrade moves it. The Arches
sources are read from the Python package copy webpack builds from
(`arches.__file__`), leaflet-iiif and Leaflet from `node_modules`.
"""

import copy
import fnmatch
import hashlib
import importlib.metadata
import json
import re
import tomllib
import unittest
from pathlib import Path

import arches
import yaml
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]

ARCHES_PACKAGES = ("arches",)
ARCHES_APPLICATIONS = (
    "arches-controlled-lists",
    "arches-querysets",
    "arches_querysets",
    "arches-vue-components",
)
EXACT_VERSION = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")
ARCHES_REF = re.compile(
    r"#(?:stable/(?P<stable>\d+\.\d+\.\d+)"
    r"|v(?P<alpha>\d+\.\d+\.\d+)-alpha\.(?P<number>\d+))$"
)

# Names Arches pins exactly that the project declares at another version.
DIVERGENCES = {
    "vue": "Security fix: 3.5.44, same minor as Arches' 3.5.20 (b870ea7e).",
    "webpack-dev-server": "Override 5.2.7 clears an advisory present in 5.2.6.",
    "@babel/core": "Override ^7.29.6 clears advisories present in 7.29.0.",
}

# (parent package, name) pairs whose nested copy is the parent's own pin, not
# a second copy of an Arches pin.
NESTED_ALLOWED = {
    ("geojson-rbush", "@types/geojson"): "pins 7946.0.8 itself",
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
    """Name -> version for every exact pin of Arches' runtime and tooling."""
    pins = {}
    for package in ARCHES_PACKAGES:
        entry = lock["packages"][f"node_modules/{package}"]
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            for name, spec in (entry.get(section) or {}).items():
                if EXACT_VERSION.match(spec):
                    pins[name] = spec
    return pins


def declared_specs(package):
    """Name -> spec of our dependencies, devDependencies and string overrides.

    An override written `$name` only refers to the dependency of that name.
    """
    specs = {}
    for section in ("dependencies", "devDependencies", "overrides"):
        for key, spec in (package.get(section) or {}).items():
            if not isinstance(spec, str) or spec.startswith("$"):
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
    actual = {
        rule["dependency-name"]
        for rule in npm.get("ignore", [])
        if "update-types" not in rule
    }
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
    ignores = uv.get("ignore", [])
    problems = []
    rules = [r for r in ignores if r["dependency-name"] == "arches"]
    if not rules:
        problems.append("dependabot.yml uv `ignore` has no rule for `arches`.")
    elif any("update-types" in r for r in rules):
        problems.append(
            "dependabot.yml uv `ignore` for `arches` must cover every update "
            "type: drop its `update-types`."
        )
    for rule in ignores:
        caught = [
            name
            for name in ARCHES_APPLICATIONS
            if fnmatch.fnmatchcase(name, rule["dependency-name"])
        ]
        if caught:
            problems.append(
                f"dependabot.yml uv `ignore` {rule['dependency-name']!r} also "
                f"holds back {', '.join(caught)}: Arches applications stay free."
            )
    return problems


def ref_version(ref):
    """The uv.lock spelling of the Arches version a git ref names, or None.

    `#stable/8.2.0` is `8.2.0`; `#v8.2.0-alpha.25` is `8.2.0a25`.
    """
    match = ARCHES_REF.search(ref)
    if not match:
        return None
    if match.group("stable"):
        return match.group("stable")
    return f"{match.group('alpha')}a{match.group('number')}"


def expected_ref(version):
    match = re.fullmatch(r"(\d+\.\d+\.\d+)a(\d+)", version)
    if match:
        return f"#v{match.group(1)}-alpha.{match.group(2)}"
    return f"#stable/{version}"


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
            if ref_version(ref) != version:
                problems.append(
                    f"package.json {name} is {ref!r} but uv.lock has arches "
                    f"{version}: use `{expected_ref(version)}`."
                )
    lock_version = project["lock"]["packages"]["node_modules/arches"]["version"]
    release = re.match(r"\d+\.\d+\.\d+", version).group(0)
    if lock_version not in (version, release):
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

    def test_dependabot_uv_ignores_arches_core_only(self):
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
        project["package"]["dependencies"]["openvue"] = "^1.0.0"
        self.assertTrue(any("openvue" in p for p in spec_problems(project)))

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
        npm["ignore"] = [r for r in npm["ignore"] if r["dependency-name"] != "openvue"]
        problems = dependabot_problems(project)
        self.assertEqual(len(problems), 1)
        self.assertIn("openvue", problems[0])

    def test_an_extra_ignore_fails(self):
        project = self.project()
        npm = next(
            u
            for u in project["dependabot"]["updates"]
            if u["package-ecosystem"] == "npm"
        )
        npm["ignore"].append({"dependency-name": "papaparse"})
        self.assertTrue(any("papaparse" in p for p in dependabot_problems(project)))

    def test_an_ignore_limited_to_update_types_is_not_a_pin(self):
        project = self.project()
        npm = next(
            u
            for u in project["dependabot"]["updates"]
            if u["package-ecosystem"] == "npm"
        )
        npm["ignore"].append(
            {
                "dependency-name": "papaparse",
                "update-types": ["version-update:semver-major"],
            }
        )
        npm["ignore"] = [
            (
                {**r, "update-types": ["version-update:semver-major"]}
                if r["dependency-name"] == "openvue"
                else r
            )
            for r in npm["ignore"]
        ]
        problems = dependabot_problems(project)
        self.assertEqual(len(problems), 1)
        self.assertIn("openvue", problems[0])

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
        project["package"]["dependencies"][
            "arches"
        ] = "archesproject/arches#stable/8.1.4"
        self.assertTrue(any("8.1.4" in p for p in version_problems(project)))

    def test_an_alpha_ref_of_another_number_fails(self):
        project = self.project()
        project["uv"]["package"] = [
            {**p, "version": "8.2.0a25"} if p["name"] == "arches" else p
            for p in project["uv"]["package"]
        ]
        project["package"]["dependencies"][
            "arches"
        ] = "archesproject/arches#v8.2.0-alpha.24"
        self.assertTrue(any("alpha.25" in p for p in version_problems(project)))

    def test_a_pyproject_range_excluding_the_locked_arches_fails(self):
        project = self.project()
        deps = project["pyproject"]["project"]["dependencies"]
        deps[:] = ["arches>=8.0,<8.1" if d.startswith("arches==") else d for d in deps]
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

    def test_a_uv_ignore_glob_catching_an_arches_application_fails(self):
        project = self.project()
        uv = next(
            u
            for u in project["dependabot"]["updates"]
            if u["package-ecosystem"] == "uv"
        )
        uv["ignore"][0]["dependency-name"] = "arches*"
        self.assertTrue(
            any("arches-vue-components" in p for p in uv_ignore_problems(project))
        )

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


LEAFLET_IIIF = ROOT / "node_modules" / "leaflet-iiif" / "leaflet-iiif.js"
LEAFLET_SRC = ROOT / "node_modules" / "leaflet" / "dist" / "leaflet-src.js"
LEAFLET_IIIF_SHA256 = "3910f668c74903c81f9f2fd1a1cb40cd3151b54cfffe8144b5bfa560cf5cd8f3"
ARCHES_COMPONENTS = (
    Path(arches.__file__).parent / "app" / "media" / "js" / "views" / "components"
)
IIIF_VIEWER = ARCHES_COMPONENTS / "iiif-viewer.js"
IIIF_ANNOTATION = ARCHES_COMPONENTS / "iiif-annotation.js"
ANNOTATION_BLOCK_SHA256 = (
    "34233d3d6e9d11cf141c991d6ab9e12658d68d4c29b81e0bf110384a03bef5a1"
)

REVISIT = (
    "Zone stamps (`msUnit`, `msImageWidth`, `msImageHeight`, `msFrame`, "
    "manuspectrum/iiif/units.py and frames.py) rely on this: "
)


def squeeze(source):
    return re.sub(r"\s+", " ", source)


JS_TOKEN = re.compile(
    r"(?P<keep>\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`"
    r"|(?<=[=(,:!&|?;{}\[])\s*/(?![/*])(?:\\.|\[(?:\\.|[^\]\\\n])*\]|[^/\\\n\[])+/)"
    r"|/\*.*?\*/|//[^\n]*",
    re.S,
)


def strip_comments(source):
    """*source* without its JavaScript comments.

    String, template and regular expression literals are kept whole, so a `//`
    or `/*` inside one does not open a comment.
    """
    return JS_TOKEN.sub(lambda m: m.group("keep") or " ", source)


def bare(source):
    """*source* without any whitespace, so a reflow cannot break a snippet."""
    return re.sub(r"\s+", "", source)


def leaflet_iiif_problems(raw):
    """What the zone frame arithmetic relies on in leaflet-iiif's layer."""
    problems = []
    if hashlib.sha256(raw).hexdigest() != LEAFLET_IIIF_SHA256:
        problems.append(
            REVISIT + "leaflet-iiif.js changed: compare its `_getInfo` (how it sets "
            "`maxNativeZoom` from the info.json tile size and sizes) with "
            "`units.native_zoom` and `units.tile_width`, and re-check "
            "folio/page-layer.ts and folio/geometry.ts, then update "
            "LEAFLET_IIIF_SHA256."
        )
    source = bare(raw.decode())
    for needle in (
        "_this.x=data.width",
        "_this.y=data.height",
        "_this.maxNativeZoom=",
        "_this._infoPromise=",
        "_this._imageSizes=",
        "_getZoomForUrl",
        "_isValidTile",
    ):
        if needle not in source:
            problems.append(
                REVISIT + f"leaflet-iiif no longer has `{needle}`; the Data Lab "
                "reads these layer members (folio/page-layer.ts)."
            )
    return problems


LAYER_FACTORY = re.compile(
    r"\b(?:tileLayer\s*(?:\.\s*iiif\b|\[\s*(['\"])iiif\1\s*\])"
    r"|TileLayer\s*(?:\.\s*Iiif\b|\[\s*(['\"])Iiif\2\s*\]))"
    r"(?:\s*\.\s*(?:call|apply|bind)\b)?\s*\("
)
LAYER_OPTION = (
    r"(?:fitBounds|className)\s*:\s*(?:\"[^\"\n]*\"|'[^'\n]*'|`[^`]*`|[^,{}\"'`])+"
)
LAYER_ARGS = re.compile(
    rf"[^,(){{}}]+,\s*\{{\s*{LAYER_OPTION}(?:\s*,\s*{LAYER_OPTION})*\s*,?\s*\}}\s*\)"
)
UNIT_NAMES = r"(?:tileSize|zoomOffset|detectRetina|zoomReverse|maxNativeZoom)"
WRITE = r"\s*(?:\+\+|--|(?:\*\*|<<|>>>?|&&|\|\||\?\?|[-+*/%&|^])?=(?![=>]))"
UNIT_CHANGE = re.compile(
    rf"(?<=[{{,])\s*(?:{UNIT_NAMES}|(['\"]){UNIT_NAMES}\1"
    rf"|\[\s*(['\"]){UNIT_NAMES}\2\s*\])\s*:"
    rf"|(?<=[{{,])\s*{UNIT_NAMES}\s*[,}}]"
    rf"|\b(?:{UNIT_NAMES}|crs)\b['\"]?\]?{WRITE}"
    rf"|(?:\+\+|--)\s*[\w$.]*\b{UNIT_NAMES}\b"
    rf"|\boptions['\"]?\]?(?:\s*\[[^\]]*\])?{WRITE}"
    r"|\b(?:setOptions|mergeOptions)\s*\("
    r"|\.(?:extend|defaults)\s*\("
    r"|\bassign\s*\(\s*[\w$.\[\]'\"]*options"
)


def iiif_viewer_problems(source):
    """Arches builds its image layers with leaflet-iiif's defaults on CRS.Simple.

    Every way of building a leaflet-iiif layer (`L.tileLayer.iiif(`, its
    bracket and `.call` forms, `new L.TileLayer.Iiif(`) takes a URL and an
    object literal of `fitBounds` and `className` only; there are at least
    two. Outside comments, nothing sets a unit-moving option (`tileSize`,
    `zoomOffset`, `detectRetina`, `zoomReverse`, `maxNativeZoom`) as a key, a
    shorthand or a write, changes a layer's options after construction
    (`setOptions`, `mergeOptions`, any `.extend(` or `.defaults(`, `assign`
    into options, a write to `options` or one of its entries) or writes a
    `crs`. Reading these options, directly or through a member
    (`canvasLayer.options.maxNativeZoom`), is allowed.
    """
    problems = []
    source = strip_comments(source)
    calls = list(LAYER_FACTORY.finditer(source))
    if len(calls) < 2 or any(not LAYER_ARGS.match(source, c.end()) for c in calls):
        problems.append(
            REVISIT + "iiif-viewer.js no longer builds every layer with "
            "`L.tileLayer.iiif(url, {fitBounds, className})`; other options, a "
            "spread or options built elsewhere may move the unit: re-check how "
            "the layer is made."
        )
    moving = sorted({m.group(0).strip() for m in UNIT_CHANGE.finditer(source)})
    if moving:
        problems.append(
            REVISIT + f"iiif-viewer.js now writes or may write {moving}: options "
            "of a layer that move the unit, or the map's CRS, are set or changed "
            "there (a `.extend(`, `.defaults(` or `assign` call may write them)."
        )
    if bare("crs: L.CRS.Simple") not in bare(source):
        problems.append(
            REVISIT + "iiif-viewer.js no longer sets `crs: L.CRS.Simple` on the map."
        )
    return problems


def iiif_annotation_problems(source):
    """The card keeps each feature's id, canvas and Leaflet-written geometry.

    `frames.stamp_collection` matches a saved feature to its stored stamp by
    id, `properties.canvas` and the geometry rounded as Leaflet writes it.
    """
    problems = []
    source = bare(strip_comments(source))
    start = source.find("this.updateTiles")
    end = source.find("updateDrawFeatures();", start) + len("updateDrawFeatures();")
    if (
        start < 0
        or hashlib.sha256(source[start:end].encode()).hexdigest()
        != ANNOTATION_BLOCK_SHA256
    ):
        problems.append(
            REVISIT + "iiif-annotation.js `this.updateTiles … updateDrawFeatures();` "
            "changed: check each feature still keeps its id and `properties.canvas`, "
            "its geometry as Leaflet wrote it (6 decimals) and its stamp, and that "
            "features are written as loaded; then update ANNOTATION_BLOCK_SHA256."
        )
    for snippet in (
        "features.push(feature);",
        "features:features}",
        "self.tile.data[id].features(features);",
        "drawFeatures(drawFeatures().concat(featureCollection.features));",
        "feature.properties.nodeId = id;",
        "feature.id=uuid.generate();",
        "canvas:self.canvas(),",
        "drawFeature.properties=Object.assign(drawFeature.properties,styleProperties);",
        "drawFeature.geometry = layer.toGeoJSON().geometry;",
    ):
        if bare(snippet) not in source:
            problems.append(
                REVISIT + f"iiif-annotation.js no longer contains `{snippet}`: "
                "check a save still returns each feature with its id, "
                "`properties.canvas`, stamp and 6-decimal geometry."
            )
    if (
        source.count("uuid.generate") != 1
        or len(re.findall(r"\.id=(?!=)", source)) != 1
    ):
        problems.append(
            REVISIT + "iiif-annotation.js assigns a feature id elsewhere than on "
            "draw (or no longer on draw); an id given on load would re-stamp "
            "every zone with the live frame."
        )
    return problems


def leaflet_rounding_problems(source):
    """Leaflet 1.6 `toGeoJSON` rounds to 6 decimals, as `frames.leaflet_round`."""
    source = bare(source)
    needles = (
        "precision=typeofprecision==='number'?precision:6;",
        "varpow=Math.pow(10,(digits===undefined?6:digits));"
        "returnMath.round(num*pow)/pow;",
    )
    return [
        REVISIT + f"leaflet-src.js no longer contains `{n}`: compare with "
        "`frames.leaflet_round` (geometry equality, `same_geometry`)."
        for n in needles
        if bare(n) not in source
    ]


class ZoneFrameContractTests(unittest.TestCase):
    def test_leaflet_iiif_layer_is_the_one_the_frames_are_computed_for(self):
        problems = leaflet_iiif_problems(LEAFLET_IIIF.read_bytes())
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_arches_viewer_layers_take_only_default_unit_options(self):
        problems = iiif_viewer_problems(IIIF_VIEWER.read_text())
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_arches_annotation_card_returns_id_canvas_and_geometry(self):
        problems = iiif_annotation_problems(IIIF_ANNOTATION.read_text())
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_arches_annotation_datatype_accepts_stamped_features(self):
        from arches.app.datatypes.datatypes import AnnotationDataType

        collection = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": "0b0d0f3e-0b8a-4a39-9a63-0c4d5f5a1a11",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
                    },
                    "properties": {
                        "msUnit": 32,
                        "msImageWidth": 4000,
                        "msImageHeight": 3000,
                        "msFrame": "read",
                    },
                }
            ],
        }
        self.assertEqual(AnnotationDataType().validate(collection), [])
        self.assertEqual(
            AnnotationDataType().transform_value_for_tile(json.dumps(collection)),
            collection,
        )

    def test_leaflet_rounds_geometry_to_six_decimals(self):
        problems = leaflet_rounding_problems(LEAFLET_SRC.read_text())
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_leaflet_iiif_changes_name_what_to_recheck(self):
        raw = LEAFLET_IIIF.read_bytes()
        problems = leaflet_iiif_problems(raw + b"\n// edit")
        self.assertEqual(len(problems), 1)
        self.assertIn("_getInfo", problems[0])
        for old, needle in (
            (b"_this.x = ", "_this.x=data.width"),
            (b"_this._imageSizes = ", "_this._imageSizes="),
        ):
            self.assertIn(old, raw)
            problems = leaflet_iiif_problems(raw.replace(old, b"_this.zz = "))
            self.assertEqual(len(problems), 2, problems)
            self.assertIn(needle, problems[1])

    def test_viewer_changes_that_move_the_unit_fail(self):
        viewer = IIIF_VIEWER.read_text()
        first_call = re.compile(r"L\.tileLayer\.iiif\(layerInfoUrl, \{.*?\}\)", re.S)
        cases = {
            "tileSize option": (
                "fitBounds: false,",
                "fitBounds: false, tileSize: 512,",
            ),
            "zoomOffset option": (
                "fitBounds: false,",
                "fitBounds: false, zoomOffset: 1,",
            ),
            "detectRetina option": (
                "fitBounds: false,",
                "fitBounds: false, detectRetina: true,",
            ),
            "zoomReverse option": (
                "fitBounds: false,",
                "fitBounds: false, zoomReverse: true,",
            ),
            "spread": ("fitBounds: false,", "...layerDefaults, fitBounds: false,"),
            "shorthand": ("fitBounds: false,", "fitBounds: false, tileSize,"),
            "call removed": ("L.tileLayer.iiif(", "x("),
            "options after construction": (
                "});\n\n                    canvasLayer.on",
                "}); canvasLayer.options.zoomOffset = 1; canvasLayer.on",
            ),
            "crs": ("crs: L.CRS.Simple", "crs: L.CRS.EPSG3857"),
        }
        for name, (old, new) in cases.items():
            self.assertIn(old, viewer, name)
            self.assertTrue(iiif_viewer_problems(viewer.replace(old, new)), name)
        self.assertTrue(
            iiif_viewer_problems(
                first_call.sub("L.tileLayer.iiif(layerInfoUrl, opts)", viewer, count=1)
            ),
            "options in a variable",
        )
        push = "layers.push(canvasLayer);"
        self.assertIn(push, viewer)
        for name, code in {
            "tileSize key": "const o = {tileSize: 512};",
            "zoomOffset key": "const o = {zoomOffset: 1};",
            "detectRetina key": "const o = {detectRetina: true};",
            "zoomReverse write": "zoomReverse = true;",
            "maxNativeZoom write": "canvasLayer.maxNativeZoom = 3;",
            "maxNativeZoom write by key": "canvasLayer['maxNativeZoom'] = 3;",
            "shorthand key": "const o = {tileSize};",
            "quoted key": "const o = {'detectRetina': true};",
            "computed key": "const o = {['zoomOffset']: 1};",
            "compound write": "canvasLayer.options.zoomOffset += 1;",
            "postfix increment": "canvasLayer.options.zoomOffset++;",
            "prefix increment": "++canvasLayer.options.zoomOffset;",
            "bracket write": "canvasLayer.options['zoomOffset'] = 1;",
            "entry write": "for (var k in params.o) canvasLayer.options[k] = params.o[k];",
            "options replaced": "canvasLayer.options = params.o;",
            "options replaced by key": "canvasLayer['options'] = params.o;",
            "setOptions": "L.setOptions(canvasLayer, params.o);",
            "mergeOptions": "L.TileLayer.Iiif.mergeOptions(params.o);",
            "extend a class": "const B = L.TileLayer.Iiif.extend({options: params.o});",
            "L.extend": "L.extend(canvasLayer.options, params.o);",
            "L.Util.extend": "L.Util.extend(canvasLayer.options, params.o);",
            "$.extend": "$.extend(canvasLayer.options, params.o);",
            "_.extend": "_.extend(canvasLayer.options, params.o);",
            "_.defaults": "_.defaults(canvasLayer.options, params.o);",
            "assign into options": "Object.assign(canvasLayer.options, params.o);",
            "assign into bracket options": (
                "Object.assign(canvasLayer['options'], params.o);"
            ),
            "crs write": "map.options.crs = L.CRS.EPSG3857;",
            "crs bracket write": "map.options['crs'] = L.CRS.EPSG3857;",
            "write between strings holding comment marks": (
                "var g = 'image/*'; canvasLayer.options.zoomOffset = 1; var h = 'a*/b';"
            ),
            "write between double-quoted strings holding comment marks": (
                'var g = "image/*"; canvasLayer.options.zoomOffset = 1; var h = "a*/b";'
            ),
            "write between template literals holding comment marks": (
                "var g = `image/*`; canvasLayer.options.zoomOffset = 1; var h = `a*/b`;"
            ),
            "write after a double-quoted string holding a line comment mark": (
                'var u = "http://x"; canvasLayer.options.zoomOffset = 1;'
            ),
            "write after a template literal holding a line comment mark": (
                "var u = `http://${h}`; canvasLayer.options.zoomOffset = 1;"
            ),
            "write after a regex holding a quote": (
                "var r = /'/; var u = '//'; canvasLayer.options.zoomOffset = 1;"
            ),
        }.items():
            self.assertTrue(
                iiif_viewer_problems(viewer.replace(push, code + push)), name
            )

    def test_every_way_to_build_the_layer_takes_allowed_keys_only(self):
        viewer = IIIF_VIEWER.read_text()
        first_call = re.compile(r"L\.tileLayer\.iiif\(layerInfoUrl, \{.*?\}\)", re.S)
        for name, source in {
            "spread": viewer.replace(
                "fitBounds: false,", "...layerDefaults, fitBounds: false,", 1
            ),
            "variable": first_call.sub(
                "L.tileLayer.iiif(layerInfoUrl, opts)", viewer, count=1
            ),
            "another key": viewer.replace(
                "fitBounds: false,", "fitBounds: false, setMaxBounds: true,", 1
            ),
            "spread after an allowed key": viewer.replace(
                'className: "iiif-layer-primary"',
                'className: "iiif-layer-primary", ...layerDefaults',
            ),
            "space before the parenthesis": viewer + "\nx = L.tileLayer.iiif (u, o);",
            "reflowed member": viewer + "\nx = L.tileLayer\n    .iiif(u, o);",
            "bracket member": viewer + "\nx = L.tileLayer['iiif'](u, o);",
            "class": viewer + "\nx = new L.TileLayer.Iiif(u, o);",
            "class bracket member": viewer + "\nx = new L.TileLayer['Iiif'](u, o);",
            "call": viewer + "\nx = L.tileLayer.iiif.call(L, u, {fitBounds: false});",
        }.items():
            self.assertIsNone(UNIT_CHANGE.search(strip_comments(source)), name)
            self.assertTrue(iiif_viewer_problems(source), name)
        for name, code in {
            "class with allowed keys": "new L.TileLayer.Iiif(u, {fitBounds: false});",
            "bracket member with allowed keys": "L.tileLayer['iiif'](u, {className: c});",
        }.items():
            self.assertEqual(iiif_viewer_problems(viewer + "\nx = " + code), [], name)

    def test_viewer_changes_that_leave_the_unit_alone_pass(self):
        viewer = IIIF_VIEWER.read_text()
        push = "layers.push(canvasLayer);"
        for name, source in {
            "reflowed options": viewer.replace(
                "fitBounds: false,", "fitBounds:false,", 1
            ).replace("{\n                        fitBounds", "{ fitBounds", 1),
            "className from a template literal": viewer.replace(
                'className: "iiif-layer-primary"', "className: `iiif-layer-${side}`"
            ),
            "className from a variable": viewer.replace(
                'className: "iiif-layer-primary"', "className: self.layerClass"
            ),
        }.items():
            self.assertEqual(iiif_viewer_problems(source), [], name)
        for name, code in {
            "comment naming tileSize": "// leaflet-iiif reads tileSize\n",
            "Math.min read": "var z = Math.min(canvasLayer.options.maxNativeZoom, 3);",
            "ternary read": "var z = c ? canvasLayer.options.maxNativeZoom : 0;",
            "object literal read": "var o = {z: canvasLayer.options.maxNativeZoom};",
            "bracket read": "var z = canvasLayer.options['maxNativeZoom'];",
            "comparison": "if (canvasLayer.maxNativeZoom === 3) {}",
            "crs read": "var c = map.options.crs;",
            "arrow parameter": "var f = maxNativeZoom => maxNativeZoom * 2;",
        }.items():
            self.assertEqual(
                iiif_viewer_problems(viewer.replace(push, code + push)), [], name
            )

    def test_unit_options_in_comments_are_not_writes(self):
        viewer = IIIF_VIEWER.read_text()
        push = "layers.push(canvasLayer);"
        for comment in (
            "// options: {tileSize: 256}\n",
            "/* canvasLayer.options.zoomOffset = 1; */",
        ):
            self.assertTrue(UNIT_CHANGE.search(comment), comment)
            self.assertEqual(
                iiif_viewer_problems(viewer.replace(push, comment + push)), [], comment
            )

    def test_annotation_changes_that_lose_id_canvas_or_geometry_fail(self):
        annotation = IIIF_ANNOTATION.read_text()
        for old, new in (
            ("features.push(feature);", ""),
            ("drawFeature.geometry = layer.toGeoJSON().geometry;", ""),
            ("feature.properties.nodeId = id;", ""),
            ("canvas: self.canvas(),", ""),
            ("features: features", "features: features.map(fn)"),
            ("self.tile.data[id].features(features);", ""),
            ("feature.id = uuid.generate();", ""),
            (
                "feature.properties.nodeId = id;",
                "feature.properties.nodeId = id; feature.id = uuid.generate();",
            ),
            (
                "var features = [];",
                "var features = [];\n            var strip = function(f) { return f; };",
            ),
            (
                "if (ko.isObservable(self.tile.data[id])) {",
                "features = features.map(strip);\n            "
                "if (ko.isObservable(self.tile.data[id])) {",
            ),
            (
                "this.card.triggerUpdate = updateDrawFeatures;",
                "feature.id = uuid.generate(); "
                "this.card.triggerUpdate = updateDrawFeatures;",
            ),
            (
                "this.card.triggerUpdate = updateDrawFeatures;",
                "feature.id = makeId(); this.card.triggerUpdate = updateDrawFeatures;",
            ),
            (
                "this.card.triggerUpdate = updateDrawFeatures;",
                "feature['id'] = uuid.generate(); "
                "this.card.triggerUpdate = updateDrawFeatures;",
            ),
        ):
            self.assertIn(old, annotation)
            self.assertTrue(
                iiif_annotation_problems(annotation.replace(old, new)), (old, new)
            )
        style = re.sub(
            r"Object\.assign\(\s*drawFeature\.properties,", "assign2(", annotation
        )
        self.assertTrue(iiif_annotation_problems(style))

    def test_a_reflowed_or_commented_annotation_card_passes(self):
        annotation = IIIF_ANNOTATION.read_text()
        trigger = "this.card.triggerUpdate = updateDrawFeatures;"
        for name, source in {
            "reflowed": annotation.replace("\n", "\n  "),
            "comment in the pinned block": annotation.replace(
                "features.push(feature);", "features.push(feature); // kept whole\n"
            ),
            "commented id assignment": annotation.replace(
                trigger, "/* feature.id = uuid.generate(); */ " + trigger
            ),
        }.items():
            self.assertNotEqual(source, annotation, name)
            self.assertEqual(iiif_annotation_problems(source), [], name)

    def test_leaflet_rounding_changes_fail(self):
        leaflet = LEAFLET_SRC.read_text()
        self.assertTrue(leaflet_rounding_problems(leaflet.replace(": 6;", ": 5;")))
