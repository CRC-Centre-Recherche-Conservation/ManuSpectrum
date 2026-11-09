"""The UFW assertions of verify.yml, fed with what `ufw status verbose` prints.

verify.yml runs `ufw status verbose` once (task "Read the UFW status") and
matches its lines with Ansible's `match` (re.match) and `search` (re.search)
tests. These tests evaluate the `that` conditions of verify.yml themselves, not
a copy of their regexes, with Jinja2 and those two Ansible tests, on samples of
that output: a change to a regex or to a count is checked against what UFW
really prints.
"""

import unittest

import jinja2
from ansible.plugins.test.core import match, search

from roles import ROLES_DIR, load_tasks

VERIFY = ROLES_DIR / "baseline" / "tasks" / "verify.yml"

SSH = "Assert UFW rate-limits SSH"
COUNT = "Assert UFW has no other inbound rule"
UFW_ASSERTIONS = (
    "Assert UFW is active with deny in and allow out",
    SSH,
    "Assert UFW allows HTTP",
    "Assert UFW allows HTTPS",
    COUNT,
)

# `ufw status verbose` on a host where apply mode set the SSH limit
# (community.general.ufw, rule limit, port 22, proto tcp: `ufw limit 22/tcp`).
APPLY_MODE = """\
Status: active
Logging: on (low)
Default: deny (incoming), allow (outgoing), disabled (routed)
New profiles: skip

To                         Action      From
--                         ------      ----
22/tcp                     LIMIT IN    Anywhere
80/tcp                     ALLOW IN    Anywhere
443/tcp                    ALLOW IN    Anywhere
22/tcp (v6)                LIMIT IN    Anywhere (v6)
80/tcp (v6)                ALLOW IN    Anywhere (v6)
443/tcp (v6)               ALLOW IN    Anywhere (v6)

"""

# The same host after `ufw limit OpenSSH` instead (issue #273): the verbose
# form prints the port of the application profile, then its name.
OPENSSH_PROFILE = """\
Status: active
Logging: on (low)
Default: deny (incoming), allow (outgoing), disabled (routed)
New profiles: skip

To                         Action      From
--                         ------      ----
22/tcp (OpenSSH)           LIMIT IN    Anywhere
80/tcp                     ALLOW IN    Anywhere
443/tcp                    ALLOW IN    Anywhere
22/tcp (OpenSSH (v6))      LIMIT IN    Anywhere (v6)
80/tcp (v6)                ALLOW IN    Anywhere (v6)
443/tcp (v6)               ALLOW IN    Anywhere (v6)

"""

# The To column of the SSH limit rule of each output, IPv4 then IPv6. The SSH
# and count assertions likewise hold one condition per family, IPv4 first.
SSH_RULES = {
    APPLY_MODE: ("22/tcp", "22/tcp (v6)"),
    OPENSSH_PROFILE: ("22/tcp (OpenSSH)", "22/tcp (OpenSSH (v6))"),
}


def environment():
    env = jinja2.Environment()
    env.tests["match"] = match
    env.tests["search"] = search
    return env


def verdicts(stdout):
    """{name: one bool per condition of its `that` list} for each UFW assertion.

    stdout_lines is built as the command module builds it: trailing newlines
    stripped, then split into lines.
    """
    tasks = {task["name"]: task for task in load_tasks(VERIFY)}
    env = environment()
    variables = {
        "baseline_ufw": {"rc": 0, "stdout_lines": stdout.rstrip("\r\n").splitlines()}
    }
    return {
        name: tuple(
            bool(env.compile_expression(condition)(**variables))
            for condition in tasks[name]["ansible.builtin.assert"]["that"]
        )
        for name in UFW_ASSERTIONS
    }


def failing(stdout):
    """The UFW assertions that fail: one of their conditions is false, as for assert."""
    return [name for name, results in verdicts(stdout).items() if not all(results)]


def to_column(line):
    """The To column of a line: ufw separates the columns by two spaces or more."""
    return line.split("  ")[0]


def without(stdout, to):
    """The output without the rule whose To column is `to`."""
    return "".join(
        line for line in stdout.splitlines(keepends=True) if to_column(line) != to
    )


def with_rules(stdout, *rules):
    """The output with extra (To, Action, From) rules, in ufw's column layout."""
    added = "".join(f"\n{to:<26} {action:<12}{source}" for to, action, source in rules)
    return stdout.rstrip("\n") + added + "\n\n"


class UfwStatusVerboseTests(unittest.TestCase):
    def test_the_assertions_read_ufw_status_verbose(self):
        tasks = {task["name"]: task for task in load_tasks(VERIFY)}
        read = tasks["Read the UFW status"]
        self.assertEqual(read["ansible.builtin.command"], "ufw status verbose")
        self.assertEqual(read["register"], "baseline_ufw")
        for name in (SSH, COUNT):
            self.assertEqual(len(tasks[name]["ansible.builtin.assert"]["that"]), 2)

    def test_the_rule_apply_mode_sets_passes(self):
        self.assertEqual(failing(APPLY_MODE), [])

    def test_the_openssh_profile_passes_as_the_verbose_form_prints_it(self):
        self.assertEqual(failing(OPENSSH_PROFILE), [])

    def test_ssh_needs_its_limit_rule_in_each_ip_family(self):
        for stdout, (v4, v6) in SSH_RULES.items():
            for missing, families in ((v4, (False, True)), (v6, (True, False))):
                with self.subTest(missing=missing):
                    results = verdicts(without(stdout, missing))
                    self.assertEqual(results[SSH], families)
                    self.assertEqual(results[COUNT], families)

    def test_an_allow_rule_on_ssh_is_not_a_limit(self):
        for stdout, ssh_rules in SSH_RULES.items():
            allowed = "".join(
                (
                    line.replace("LIMIT IN", "ALLOW IN")
                    if to_column(line) in ssh_rules
                    else line
                )
                for line in stdout.splitlines(keepends=True)
            )
            with self.subTest(rule=ssh_rules[0]):
                self.assertEqual(failing(allowed), [SSH])

    def test_both_ssh_rules_at_once_are_one_too_many_in_each_family(self):
        both = with_rules(
            APPLY_MODE,
            ("22/tcp (OpenSSH)", "LIMIT IN", "Anywhere"),
            ("22/tcp (OpenSSH (v6))", "LIMIT IN", "Anywhere (v6)"),
        )
        results = verdicts(both)
        self.assertEqual(results[SSH], (False, False))
        self.assertEqual(results[COUNT], (False, False))
        self.assertEqual(failing(both), [SSH, COUNT])

    def test_an_extra_inbound_rule_fails_the_count_of_its_ip_family(self):
        ipv4_over, ipv6_over = (False, True), (True, False)
        extras = {
            ("8080/tcp", "ALLOW IN", "Anywhere"): ipv4_over,
            ("8080/tcp (v6)", "ALLOW IN", "Anywhere (v6)"): ipv6_over,
            ("5432/tcp", "DENY IN", "Anywhere"): ipv4_over,
            ("80,443/tcp (Nginx Full)", "ALLOW IN", "Anywhere"): ipv4_over,
            ("80,443/tcp (Nginx Full (v6))", "ALLOW IN", "Anywhere (v6)"): ipv6_over,
        }
        for stdout, (v4, _) in SSH_RULES.items():
            self.assertEqual(verdicts(stdout)[COUNT], (True, True))
            for extra, families in extras.items():
                with self.subTest(ssh=v4, extra=extra[0]):
                    results = verdicts(with_rules(stdout, extra))
                    self.assertEqual(results[COUNT], families)
                    self.assertEqual(failing(with_rules(stdout, extra)), [COUNT])

    def test_the_fail_message_names_the_command_and_both_forms(self):
        tasks = {task["name"]: task for task in load_tasks(VERIFY)}
        message = tasks[SSH]["ansible.builtin.assert"]["fail_msg"]
        for needle in (
            "ufw status verbose",
            "22/tcp (v6)",
            "22/tcp (OpenSSH (v6))",
            "ufw limit 22/tcp",
            "ufw limit OpenSSH",
        ):
            self.assertIn(needle, message)


if __name__ == "__main__":
    unittest.main()
