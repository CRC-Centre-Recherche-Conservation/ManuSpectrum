"""Contracts of the release workflows: what each one may do, parsed from the YAML."""

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github" / "workflows"
IMAGE_NAME = "ghcr.io/crc-centre-recherche-conservation/manuspectrum"
USES = re.compile(r"^(?P<action>[\w.-]+/[\w./-]+)@(?P<ref>\S+)$")
USER_CONTROLLED = re.compile(
    r"\$\{\{\s*github\.(event\.|head_ref|ref_name|ref\b|actor)", re.IGNORECASE
)


def load(name):
    return yaml.safe_load((WORKFLOWS / name).read_text())


def triggers(workflow):
    # PyYAML reads the bare key `on` as the boolean True.
    return workflow.get("on", workflow.get(True))


def steps(job):
    return job.get("steps", [])


def project_workflows():
    return sorted(p for p in WORKFLOWS.glob("*.yml") if p.name != "main.yml")


class PinningTests(unittest.TestCase):
    def test_every_action_is_pinned_by_full_sha(self):
        problems = []
        for path in project_workflows():
            text = path.read_text()
            workflow = yaml.safe_load(text)
            jobs = workflow["jobs"].values()
            for job in jobs:
                uses = [job["uses"]] if "uses" in job else []
                uses += [s["uses"] for s in steps(job) if "uses" in s]
                for ref in uses:
                    if ref.startswith("./"):
                        continue
                    match = USES.match(ref)
                    if not match or not re.fullmatch(r"[0-9a-f]{40}", match["ref"]):
                        problems.append(f"{path.name}: {ref}")
            for line in text.splitlines():
                if re.search(r"uses: \S+@[0-9a-f]{40}\s*$", line):
                    problems.append(f"{path.name}: no version comment: {line.strip()}")
        self.assertEqual(problems, [])

    def test_no_user_controlled_value_inside_run(self):
        problems = []
        for path in project_workflows():
            for name, job in yaml.safe_load(path.read_text())["jobs"].items():
                for step in steps(job):
                    if USER_CONTROLLED.search(step.get("run", "")):
                        problems.append(f"{path.name}:{name}: {step.get('name')}")
        self.assertEqual(problems, [])

    def test_every_release_workflow_declares_top_level_permissions(self):
        for name in ("stack-proof.yml", "staging.yml", "release.yml"):
            path = WORKFLOWS / name
            if not path.exists():
                continue
            workflow = load(name)
            self.assertIn("permissions", workflow, name)
            self.assertNotIn("write", str(workflow["permissions"]), name)


class StackProofTests(unittest.TestCase):
    def test_deploy_lint_calls_the_shared_stack_proof(self):
        job = load("deploy-lint.yml")["jobs"]["image"]
        self.assertEqual(job["uses"], "./.github/workflows/stack-proof.yml")
        self.assertEqual(job["with"]["git-sha"], "${{ github.sha }}")
        self.assertNotIn("steps", job)

    def test_stack_proof_is_reusable_and_labels_the_revision(self):
        workflow = load("stack-proof.yml")
        call = triggers(workflow)["workflow_call"]
        self.assertIn("git-sha", call["inputs"])
        self.assertIn("image-artifact", call["inputs"])
        text = (WORKFLOWS / "stack-proof.yml").read_text()
        self.assertIn("GIT_SHA=", text)
        self.assertIn("probe-image.sh", text)

    def test_trivy_runs_on_the_image_that_was_loaded_or_built(self):
        stack = steps(load("stack-proof.yml")["jobs"]["image"])
        ids = [s.get("id") for s in stack]
        trivy = stack[ids.index("trivy")]
        loader = stack[[s.get("name") for s in stack].index("Docker load")]
        self.assertEqual(loader["id"], "docker-load")
        self.assertIn("steps.docker-load.outcome == 'success'", trivy["if"])
        self.assertIn("steps.build.outcome == 'success'", trivy["if"])
        self.assertNotIn("steps.load.", trivy["if"])

    def test_the_dockerfile_labels_the_revision(self):
        text = (ROOT / "deploy" / "docker" / "Dockerfile").read_text()
        self.assertRegex(text, r"(?m)^ARG GIT_SHA=")
        self.assertIn('org.opencontainers.image.revision="${GIT_SHA}"', text)


def write_jobs(workflow, scope):
    return sorted(
        name
        for name, job in workflow["jobs"].items()
        if scope in (job.get("permissions") or {})
        and job["permissions"][scope] == "write"
    )


class LockfileTests(unittest.TestCase):
    @staticmethod
    def filter_script():
        changes = load("deploy-lint.yml")["jobs"]["changes"]
        return next(s["run"] for s in steps(changes) if s.get("id") == "filter")

    def triggers(self, changed):
        """Run the filter's patterns on a changed-file list; return the outputs."""
        script = self.filter_script().replace(
            'files="$(git diff --name-only "$BASE_SHA...$HEAD_SHA")"',
            'files="$CHANGED"',
        )
        out = Path(tempfile.mkdtemp()) / "output"
        result = subprocess.run(
            ["bash", "-c", script],
            env={
                "PATH": os.environ["PATH"],
                "EVENT_NAME": "pull_request",
                "CHANGED": changed,
                "GITHUB_OUTPUT": str(out),
            },
            check=True,
        )
        self.assertEqual(result.returncode, 0)
        try:
            return dict(line.split("=") for line in out.read_text().split())
        finally:
            out.unlink()
            out.parent.rmdir()

    def test_pyproject_alone_only_runs_the_lock_check(self):
        got = self.triggers("pyproject.toml")
        self.assertEqual(got["image"], "false")
        self.assertEqual(got["lockfile"], "true")
        self.assertEqual(got["stack"], "false")

    def test_the_lock_file_does_not_run_the_stack_job(self):
        self.assertEqual(self.triggers("uv.lock")["stack"], "false")

    def test_files_read_by_the_compose_tests_run_the_stack_job_only(self):
        for path in (
            "manuspectrum/urls.py",
            "manuspectrum/settings.py",
            "manuspectrum/observability/metrics.py",
            "deploy/BACKUP.md",
            "deploy/RELEASES.md",
            "deploy/SECRETS.md",
            "deploy/ACCEPTANCE.md",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.triggers(path)["stack"], "true")
        for path in ("deploy/BACKUP.md", "deploy/RELEASES.md"):
            with self.subTest(path=path):
                self.assertEqual(self.triggers(path)["image"], "false")

    def test_build_context_config_files_build_the_image(self):
        for path in (
            "tsconfig.json",
            ".babelrc",
            ".browserslistrc",
            "eslint.config.mjs",
            ".prettierrc",
            ".stylelintrc.json",
            "gettext.config.js",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.triggers(path)["image"], "true")

    def test_an_unrelated_file_triggers_no_lock_check(self):
        self.assertEqual(self.triggers("README.md")["lockfile"], "false")

    def test_the_lockfile_job_uses_the_dockerfiles_uv_image(self):
        jobs = load("deploy-lint.yml")["jobs"]
        job = jobs["lockfile"]
        self.assertEqual(job["needs"], "changes")
        self.assertEqual(job["if"], "needs.changes.outputs.lockfile == 'true'")
        self.assertIn("timeout-minutes", job)
        run = "\n".join(s.get("run", "") for s in steps(job))
        self.assertIn("lock --check", run)
        self.assertIn("deploy/docker/Dockerfile", run)
        self.assertIn("ARG UV_IMAGE=", (ROOT / "deploy/docker/Dockerfile").read_text())
        checkout = next(s for s in steps(job) if "checkout" in s.get("uses", ""))
        self.assertIs(checkout["with"]["persist-credentials"], False)
        self.assertIn("lockfile", jobs["conclusion"]["needs"])


class ReleaseScanTests(unittest.TestCase):
    def test_the_trivy_action_keeps_no_cache(self):
        scan = steps(load("release.yml")["jobs"]["scan"])
        trivy = next(s for s in scan if "trivy-action" in s.get("uses", ""))
        self.assertEqual(str(trivy["with"]["cache"]).lower(), "false")


class DependabotTests(unittest.TestCase):
    @staticmethod
    def updates():
        path = ROOT / ".github" / "dependabot.yml"
        return yaml.safe_load(path.read_text())["updates"]

    def test_python_updates_go_through_uv_and_every_entry_targets_dev(self):
        updates = self.updates()
        ecosystems = [u["package-ecosystem"] for u in updates]
        self.assertIn("uv", ecosystems)
        self.assertNotIn("pip", ecosystems)
        self.assertIn("docker-compose", ecosystems)
        for update in updates:
            self.assertEqual(update["target-branch"], "dev", update["directory"])

    def test_npm_groups_minor_and_patch(self):
        npm = next(u for u in self.updates() if u["package-ecosystem"] == "npm")
        group = next(iter(npm["groups"].values()))
        self.assertEqual(sorted(group["update-types"]), ["minor", "patch"])


class StagingTests(unittest.TestCase):
    def setUp(self):
        self.workflow = load("staging.yml")
        self.text = (WORKFLOWS / "staging.yml").read_text()

    def test_build_image_is_replaced(self):
        self.assertFalse((WORKFLOWS / "build-image.yml").exists())

    def test_triggers(self):
        on = triggers(self.workflow)
        self.assertEqual(sorted(on["push"]["branches"]), ["dev", "main"])
        self.assertIn("workflow_dispatch", on)
        self.assertNotIn("tags", on["push"])

    def test_only_the_publish_job_writes(self):
        for scope in ("packages", "id-token", "attestations"):
            self.assertEqual(write_jobs(self.workflow, scope), ["publish"], scope)
        self.assertEqual(write_jobs(self.workflow, "contents"), [])

    def test_publish_attests_the_pushed_digest(self):
        publish = steps(self.workflow["jobs"]["publish"])
        names = [s.get("uses", "").split("@")[0] for s in publish]
        self.assertIn("actions/attest-build-provenance", names)
        attest = publish[names.index("actions/attest-build-provenance")]
        self.assertEqual(
            attest["with"]["subject-digest"], "${{ steps.push.outputs.digest }}"
        )
        self.assertIs(attest["with"]["push-to-registry"], True)
        self.assertGreater(
            names.index("actions/attest-build-provenance"),
            [s.get("id") for s in publish].index("push"),
        )

    def test_main_and_manual_runs_are_never_cancelled_nor_replaced_in_the_queue(self):
        concurrency = self.workflow["concurrency"]
        group = concurrency["group"]
        self.assertIn("refs/heads/main", group)
        self.assertIn("workflow_dispatch", group)
        self.assertIn("github.run_id", group)
        cancel = str(concurrency["cancel-in-progress"])
        self.assertIn("github.event_name == 'push'", cancel)
        self.assertIn("github.ref != 'refs/heads/main'", cancel)

    def test_publish_writes_the_commit_and_digest_to_the_summary(self):
        run = [
            s["run"]
            for s in steps(self.workflow["jobs"]["publish"])
            if s.get("id") == "push"
        ][0]
        self.assertIn("GITHUB_STEP_SUMMARY", run)
        self.assertIn("Commit:", run)
        self.assertIn("$GITHUB_SHA", run)
        self.assertIn("Digest:", run)

    def test_the_image_archive_is_uploaded_with_a_light_compression(self):
        upload = [
            s
            for s in steps(self.workflow["jobs"]["build"])
            if "upload-artifact" in s.get("uses", "")
        ][0]
        self.assertIn(upload["with"]["compression-level"], (0, 1))

    def test_the_pushed_tag_is_the_commit_and_never_latest(self):
        self.assertIn("sha-$GITHUB_SHA", self.text)
        self.assertNotIn("latest", self.text.replace("latest-", ""))
        self.assertIn(IMAGE_NAME, self.text)

    def test_the_published_image_is_the_proven_one(self):
        jobs = self.workflow["jobs"]
        self.assertEqual(jobs["proof"]["uses"], "./.github/workflows/stack-proof.yml")
        self.assertIn("build", jobs["proof"]["needs"])
        self.assertIn("proof", jobs["publish"]["needs"])
        self.assertEqual(
            jobs["proof"]["with"]["image-artifact"],
            jobs["publish"]["steps"][0]["with"]["name"],
        )
        self.assertNotIn("build-push-action", str(jobs["publish"]))

    def test_publish_exposes_the_digest(self):
        self.assertIn("digest", self.workflow["jobs"]["publish"]["outputs"])


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.workflow = load("release.yml")
        self.jobs = self.workflow["jobs"]
        self.text = (WORKFLOWS / "release.yml").read_text()

    def test_only_a_version_tag_starts_it(self):
        on = triggers(self.workflow)
        self.assertEqual(on, {"push": {"tags": ["v*"]}})

    def test_one_run_per_tag_and_none_is_cancelled(self):
        concurrency = self.workflow["concurrency"]
        self.assertIn("github.ref", concurrency["group"])
        self.assertIs(concurrency["cancel-in-progress"], False)

    def test_write_scopes_are_held_by_the_jobs_that_need_them(self):
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        self.assertEqual(write_jobs(self.workflow, "contents"), ["release"])
        self.assertEqual(write_jobs(self.workflow, "packages"), ["promote", "sign"])
        self.assertEqual(write_jobs(self.workflow, "id-token"), ["sign"])
        self.assertEqual(write_jobs(self.workflow, "attestations"), ["sign"])
        self.assertEqual(self.jobs["promote"]["permissions"]["attestations"], "read")

    def test_every_job_but_the_guard_says_what_it_needs(self):
        for name, job in self.jobs.items():
            self.assertIn("permissions", job, name)

    def test_the_chain_cannot_skip_a_stage(self):
        needs = {
            name: (
                set([job["needs"]] if isinstance(job["needs"], str) else job["needs"])
                if "needs" in job
                else set()
            )
            for name, job in self.jobs.items()
        }
        self.assertIn("guard", needs["promote"])
        self.assertIn("promote", needs["scan"])
        self.assertTrue({"promote", "scan"} <= needs["sign"])
        self.assertTrue({"promote", "sign"} <= needs["verify"])
        self.assertIn("verify", needs["release"])

    def test_it_never_builds(self):
        self.assertNotIn("build-push-action", self.text)
        self.assertNotRegex(self.text, r"docker build(?!x)")
        self.assertNotIn("latest", self.text.replace("latest-", ""))

    def test_the_guard_runs_on_the_full_history(self):
        checkout = steps(self.jobs["guard"])[0]
        self.assertEqual(checkout["with"]["fetch-depth"], 0)
        self.assertIn("release-ref-guard.sh", self.text)

    def test_a_missing_staging_image_names_staging_yml(self):
        promote = "\n".join(s.get("run", "") for s in steps(self.jobs["promote"]))
        self.assertIn("staging.yml", promote)
        self.assertIn("image-retag.sh", promote)
        self.assertNotIn("imagetools create", promote)
        self.assertIn("image-digest.sh", promote)

    def test_the_promoted_digest_is_compared_with_the_tested_one(self):
        promote = "\n".join(s.get("run", "") for s in steps(self.jobs["promote"]))
        self.assertRegex(promote, r'\[ "\$promoted" != "\$digest" \]')

    def test_the_scan_blocks(self):
        scan = "\n".join(s.get("run", "") for s in steps(self.jobs["scan"]))
        self.assertIn("trivy-report.sh", scan)
        self.assertIn("--fail", scan)
        trivy = [
            s for s in steps(self.jobs["scan"]) if "trivy-action" in s.get("uses", "")
        ]
        self.assertEqual(trivy[0]["with"]["exit-code"], "0")
        self.assertEqual(trivy[0]["with"]["severity"], "HIGH,CRITICAL")

    def test_the_signed_object_is_the_digest(self):
        text = "\n".join(s.get("run", "") for s in steps(self.jobs["sign"]))
        self.assertRegex(text, r'cosign sign --yes "\$IMAGE_NAME@\$DIGEST"')
        uses = " ".join(s.get("uses", "") for s in steps(self.jobs["sign"]))
        self.assertNotIn("attest-build-provenance", self.text)
        self.assertIn("actions/attest@", uses)
        self.assertIn("anchore/sbom-action", uses)

    def test_provenance_is_not_a_signature_is_proved_before_any_attestation_of_this_workflow(
        self,
    ):
        sign = steps(self.jobs["sign"])
        names = [s.get("name", "") for s in sign]
        proof = names.index("Provenance is not a signature")
        self.assertIn("cosign verify", sign[proof]["run"])
        self.assertIn("exit 1", sign[proof]["run"])
        self.assertLess(proof, names.index("Sign the digest (keyless)"))
        self.assertLess(
            names.index("Sign the digest (keyless)"),
            names.index("Software bill of materials"),
        )
        self.assertLess(
            names.index("Software bill of materials"),
            names.index("Attach the bill of materials"),
        )
        installer = next(
            i for i, s in enumerate(sign) if "cosign-installer" in s.get("uses", "")
        )
        self.assertLess(installer, proof)

    def test_the_guard_checks_the_tag_version_against_app_version(self):
        run = "\n".join(s.get("run", "") for s in steps(self.jobs["guard"]))
        self.assertIn('release-version-guard.sh "$TAG" "$commit"', run)
        self.assertLess(
            run.index("release-ref-guard.sh"), run.index("release-version-guard.sh")
        )

    def test_promote_verifies_the_staging_attestation_before_tagging(self):
        run = [
            s["run"]
            for s in steps(self.jobs["promote"])
            if "image-retag.sh" in s.get("run", "")
        ][0]
        self.assertLess(run.index("gh attestation verify"), run.index("image-retag.sh"))
        for part in (
            "--signer-workflow",
            "workflows/staging.yml",
            "--source-ref",
            '--source-digest "$COMMIT"',
            "refs/heads/main",
            "refs/heads/dev",
            "oci://$IMAGE_NAME@$digest",
        ):
            self.assertIn(part, run)

    def test_the_guard_checks_the_tag_ruleset_before_the_branch_rules(self):
        guard = steps(self.jobs["guard"])
        runs = [s.get("run", "") for s in guard]
        ruleset = next(i for i, r in enumerate(runs) if "release-ruleset-check.sh" in r)
        branch = next(i for i, r in enumerate(runs) if "release-ref-guard.sh" in r)
        self.assertLess(ruleset, branch)
        self.assertEqual(self.jobs["guard"]["permissions"], {"contents": "read"})

    def test_there_is_no_manual_trigger(self):
        self.assertNotIn("workflow_dispatch", str(triggers(self.workflow)))

    def test_verify_runs_the_servers_policy_and_its_refusals(self):
        run = "\n".join(s.get("run", "") for s in steps(self.jobs["verify"]))
        self.assertIn("release-verify.sh", run)
        self.assertIn("--policy prod", run)
        self.assertIn("--policy rc", run)
        self.assertIn("sha-", run)
        self.assertIn("v0.0.0", run)

    def test_the_release_is_created_or_edited_never_duplicated(self):
        run = "\n".join(s.get("run", "") for s in steps(self.jobs["release"]))
        self.assertIn("gh release view", run)
        self.assertIn("gh release edit", run)
        self.assertIn("gh release create", run)
        self.assertIn("--prerelease", run)

    def test_cosign_is_pinned_in_the_installer_and_the_policy_script(self):
        installer = [
            s
            for s in steps(self.jobs["sign"])
            if "cosign-installer" in s.get("uses", "")
        ][0]
        version = installer["with"]["cosign-release"]
        self.assertRegex(version, r"^v\d+\.\d+\.\d+$")
        script = (ROOT / "deploy" / "scripts" / "release-verify.sh").read_text()
        self.assertIn(f"cosign:{version}@sha256:", script)


class RequiredChecksTests(unittest.TestCase):
    """The checks RELEASES.md tells to require are jobs that run on every pull request."""

    @staticmethod
    def documented():
        text = (ROOT / "deploy" / "RELEASES.md").read_text()
        match = re.search(
            r"^- When branch protection requires status checks, (.+?)(?=\n- |\n\n)",
            text,
            re.S | re.M,
        )
        assert match, "RELEASES.md no longer names the required checks"
        return re.findall(r"`([\w-]+)`", match[1].split("The jobs of")[0])

    def test_the_documented_checks_are_jobs_of_workflows_without_a_paths_filter(self):
        runs_everywhere = set()
        for path in project_workflows():
            workflow = yaml.safe_load(path.read_text())
            pull = triggers(workflow) or {}
            if not isinstance(pull, dict) or "pull_request" not in pull:
                continue
            filters = pull["pull_request"] or {}
            if "paths" in filters or "paths-ignore" in filters:
                continue
            runs_everywhere |= set(workflow["jobs"])
        named = self.documented()
        self.assertEqual(sorted(named), ["conclusion", "gitleaks"])
        self.assertEqual([c for c in named if c not in runs_everywhere], [])

    def test_the_tag_checklist_repeats_the_required_checks(self):
        text = (ROOT / "deploy" / "RELEASES.md").read_text()
        checklist = text.split("## Before pushing a tag (checklist)")[1]
        for check in self.documented():
            self.assertIn(f"`{check}`", checklist)


if __name__ == "__main__":
    unittest.main()
