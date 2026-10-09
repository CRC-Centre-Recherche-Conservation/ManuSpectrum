"""Links of the deployment documents resolve, and OBSERVABILITY.md names what exists."""

import re
import unittest
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[2]
RULES = DEPLOY / "compose" / "observability" / "prometheus" / "rules"
RUNBOOK_URL = re.compile(
    r"https://github\.com/CRC-Centre-Recherche-Conservation/ManuSpectrum/blob/main/"
    r"(deploy/runbooks/[a-z]+\.md)(?:#([\w-]+))?"
)
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")


def slug(heading):
    """GitHub's anchor for a heading: lower case, punctuation dropped, spaces to hyphens."""
    text = re.sub(r"[`*]", "", heading.strip().lower())
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def anchors(path):
    found, in_fence = set(), False
    for line in path.read_text().splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
        elif not in_fence and line.startswith("#"):
            found.add(slug(line.lstrip("#")))
    return found


def documents():
    return sorted(DEPLOY.glob("*.md")) + sorted((DEPLOY / "runbooks").glob("*.md"))


class DocumentLinkTests(unittest.TestCase):
    def test_relative_links_and_anchors_resolve(self):
        problems = []
        for document in documents():
            in_fence = False
            for line in document.read_text().splitlines():
                if line.startswith("```"):
                    in_fence = not in_fence
                if in_fence:
                    continue
                for target in LINK.findall(line):
                    if re.match(r"[a-z]+:", target):
                        continue
                    name, _, anchor = target.partition("#")
                    path = (document.parent / name).resolve() if name else document
                    if not path.exists():
                        problems.append(f"{document.name}: {target} (no file)")
                    elif (
                        anchor and path.suffix == ".md" and anchor not in anchors(path)
                    ):
                        problems.append(f"{document.name}: {target} (no anchor)")
        self.assertEqual(problems, [])

    def test_every_runbook_url_of_the_rules_resolves(self):
        problems, seen = [], 0
        for rules in sorted(RULES.glob("*.yml")):
            for url in RUNBOOK_URL.finditer(rules.read_text()):
                seen += 1
                path = DEPLOY.parent / url.group(1)
                if not path.exists():
                    problems.append(f"{rules.name}: {url.group(0)} (no file)")
                elif url.group(2) and url.group(2) not in anchors(path):
                    problems.append(f"{rules.name}: {url.group(0)} (no anchor)")
        self.assertGreater(seen, 40)
        self.assertEqual(problems, [])


class ObservabilityDocTests(unittest.TestCase):
    def setUp(self):
        self.text = (DEPLOY / "OBSERVABILITY.md").read_text()

    def test_names_every_rule_file_and_runbook(self):
        for rules in RULES.glob("*.yml"):
            with self.subTest(area=rules.stem):
                self.assertIn(f"runbooks/{rules.stem}.md", self.text)

    def test_names_every_monitoring_make_target(self):
        makefile = (DEPLOY / "Makefile").read_text()
        targets = re.findall(
            r"(?m)^((?:monitoring-init|observability-on|observability-off|"
            r"alert-[a-z]+|alerts|silence|monthly-report|report-test|"
            r"container-metrics|disk-usage)):",
            makefile,
        )
        self.assertGreaterEqual(len(targets), 10)
        for target in targets:
            with self.subTest(target=target):
                self.assertIn(f"`{target}`", self.text)

    def test_names_every_mail_category(self):
        for category in (
            "Alert",
            "Heartbeat",
            "Report",
            "Contact",
            "Account",
            "System",
        ):
            with self.subTest(category=category):
                self.assertIn(f"| {category} |", self.text)

    def test_readme_lists_the_systemd_units_and_targets(self):
        readme = (DEPLOY / "README.md").read_text()
        for word in ("OBSERVABILITY.md", "runbooks/", "alert-recipients", "disk-usage"):
            with self.subTest(word=word):
                self.assertIn(word, readme)


if __name__ == "__main__":
    unittest.main()
