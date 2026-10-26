"""Static rules the roles must keep, read from their YAML."""

import unittest

import json
import re
import shlex

import yaml

from roles import ROLES_DIR, all_tasks, flatten, load_tasks, module_of, role_tasks

READ_ONLY_MODULES = {
    "assert",
    "command",
    "shell",
    "stat",
    "setup",
    "wait_for",
    "debug",
    "fail",
}


class PreflightTests(unittest.TestCase):
    def test_preflight_changes_nothing(self):
        tasks = role_tasks("preflight")
        self.assertGreater(len(tasks), 8, "preflight has no assertions yet")
        for _, task in tasks:
            module = module_of(task)
            self.assertIn(module, READ_ONLY_MODULES, task["name"])
            if module in ("command", "shell"):
                self.assertIs(task.get("changed_when"), False, task["name"])
                self.assertIs(task.get("check_mode"), False, task["name"])

    def test_every_assertion_says_what_to_do(self):
        for _, task in role_tasks("preflight"):
            if module_of(task) == "assert":
                self.assertIn("fail_msg", task["ansible.builtin.assert"], task["name"])


def strings(value):
    """Every string of a nested YAML value."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def handlers(role):
    path = ROLES_DIR / role / "handlers" / "main.yml"
    return list(flatten(yaml.safe_load(path.read_text(encoding="utf-8"))))


class BaselineApplyTests(unittest.TestCase):
    def apply_tasks(self):
        tasks = load_tasks(ROLES_DIR / "baseline" / "tasks" / "apply.yml")
        self.assertGreater(len(tasks), 10, "apply.yml is not written yet")
        return tasks

    def test_apply_never_restarts_sshd(self):
        for task in self.apply_tasks() + handlers("baseline"):
            module = module_of(task)
            if module in ("service", "systemd", "systemd_service"):
                args = task[next(k for k in task if k.endswith(module))]
                if str(args.get("name", "")) in ("ssh", "sshd", "ssh.service"):
                    self.assertNotEqual(args.get("state"), "restarted", task["name"])
        reload_handlers = [h for h in handlers("baseline") if h.get("listen") == "reload sshd"]
        self.assertGreaterEqual(len(reload_handlers), 2)
        first = reload_handlers[0]
        self.assertEqual(module_of(first), "command")
        self.assertIn("sshd -t", first["ansible.builtin.command"])

    def test_docker_suite_is_never_guessed(self):
        tasks = self.apply_tasks()
        for task in tasks:
            body = {k: v for k, v in task.items() if k not in ("name", "fail_msg")}
            if module_of(task) == "assert":
                body["ansible.builtin.assert"] = {
                    k: v
                    for k, v in task["ansible.builtin.assert"].items()
                    if k != "fail_msg"
                }
            for text in strings(body):
                self.assertNotIn("noble", text, task["name"])
        for template in (ROLES_DIR / "baseline" / "templates").glob("*"):
            self.assertNotIn("noble", template.read_text(encoding="utf-8"), template.name)

    def test_the_suite_probe_comes_before_any_change(self):
        tasks = self.apply_tasks()
        probe = tasks[0]
        self.assertEqual(module_of(probe), "uri")
        self.assertIn("docker_apt_codename", probe["ansible.builtin.uri"]["url"])
        self.assertIs(probe.get("check_mode"), False)
        follow_up = tasks[1]
        self.assertEqual(module_of(follow_up), "assert")
        self.assertIn("docker_apt_codename", follow_up["ansible.builtin.assert"]["fail_msg"])


class HostRoleTests(unittest.TestCase):
    def test_daemon_json_holds_the_logging_and_restart_policy(self):
        text = (ROLES_DIR / "host" / "templates" / "daemon.json.j2").read_text(encoding="utf-8")
        self.assertNotIn("{{", text, "daemon.json is static: a variable would need a render test")
        config = json.loads(text)
        self.assertEqual(config["log-driver"], "json-file")
        self.assertEqual(config["log-opts"], {"max-size": "10m", "max-file": "5"})
        self.assertIs(config["live-restore"], True)
        self.assertIs(config["no-new-privileges"], True)

    def test_daemon_json_is_validated_before_it_replaces_the_old_one(self):
        copies = [
            t
            for t in role_tasks("host")
            if module_of(t[1]) in ("template", "copy")
            and t[1][f"ansible.builtin.{module_of(t[1])}"]["dest"] == "/etc/docker/daemon.json"
        ]
        self.assertEqual(len(copies), 1)
        args = copies[0][1][f"ansible.builtin.{module_of(copies[0][1])}"]
        self.assertEqual(args["validate"], "dockerd --validate --config-file %s")
        self.assertEqual(copies[0][1]["notify"], "restart docker")

    def test_docker_restarts_only_from_a_handler_that_warns_first(self):
        for _, task in role_tasks("host"):
            if module_of(task) in ("service", "systemd", "systemd_service"):
                args = task[next(k for k in task if k.endswith(module_of(task)))]
                self.assertNotEqual(args.get("name"), "docker", task["name"])
        restart = [h for h in handlers("host") if h.get("listen") == "restart docker"]
        self.assertEqual([module_of(h) for h in restart], ["debug", "service"])
        self.assertIn("live-restore", restart[0]["ansible.builtin.debug"]["msg"])
        self.assertEqual(restart[1]["ansible.builtin.service"]["state"], "restarted")

    def test_handlers_run_before_the_app_role(self):
        tasks = [t for _, t in role_tasks("host")]
        self.assertEqual(module_of(tasks[-1]), "meta")
        self.assertEqual(tasks[-1]["ansible.builtin.meta"], "flush_handlers")

    def test_journald_keeps_a_bounded_persistent_journal(self):
        text = (ROLES_DIR / "host" / "templates" / "journald.conf.j2").read_text(encoding="utf-8")
        for line in ("Storage=persistent", "SystemMaxUse=500M", "MaxRetentionSec=3month"):
            self.assertIn(line, text.splitlines())
        self.assertIn("[Journal]", text.splitlines())


class RehearsalMarkerTests(unittest.TestCase):
    def test_apply_writes_the_marker_only_on_a_rehearsal_host(self):
        marker = [
            t
            for t in load_tasks(ROLES_DIR / "baseline" / "tasks" / "apply.yml")
            if "/etc/manuspectrum/rehearsal-host" in " ".join(strings(t))
        ]
        self.assertEqual(len(marker), 1)
        self.assertEqual(marker[0]["when"], "rehearsal_host | bool")


FORBIDDEN_MAKE_TARGETS = {"init", "restore", "cert-init", "secrets", "load-snapshot"}
COMMAND_MODULES = {"command", "shell", "raw"}


def executed_commands():
    """(task name, command line) of every command a role task or handler runs."""
    found = []
    handler_files = sorted(ROLES_DIR.glob("*/handlers/*.yml"))
    tasks = [(f"{r}/{n}", t) for r, n, t in all_tasks()]
    for path in handler_files:
        tasks += [(str(path.relative_to(ROLES_DIR)), t) for t in load_tasks(path)]
    for where, task in tasks:
        if module_of(task) not in COMMAND_MODULES:
            continue
        args = task[next(k for k in task if k.split(".")[-1] in COMMAND_MODULES)]
        if isinstance(args, dict):
            args = args.get("cmd") or " ".join(args.get("argv", []))
        found.append((f"{where}: {task['name']}", re.sub(r"\{\{.*?\}\}", "X", str(args))))
    return found, tasks


class AppRoleTests(unittest.TestCase):
    def test_app_never_runs_destructive_targets(self):
        commands, _ = executed_commands()
        self.assertGreater(len(commands), 10)
        for name, line in commands:
            self.assertNotIn("setup_db", line, name)
            words = shlex.split(line)
            if "make" in words:
                targets = [w for w in words[words.index("make") + 1 :] if not w.startswith("-") and "=" not in w and w != "X"]
                self.assertFalse(FORBIDDEN_MAKE_TARGETS & set(targets), f"{name}: {line}")

    def test_every_command_sets_changed_when(self):
        _, tasks = executed_commands()
        for where, task in tasks:
            if module_of(task) in COMMAND_MODULES:
                self.assertIn("changed_when", task, where)

    def test_gate_summary_names_each_command(self):
        gates = (ROLES_DIR / "app" / "tasks" / "gates.yml").read_text(encoding="utf-8")
        for command in (
            "make -C deploy secrets",
            "make -C deploy secret-set",
            "make -C deploy build",
            "make -C deploy cert-init",
            "make -C deploy certs-local",
            "make -C deploy init",
            "make -C deploy restore",
        ):
            self.assertIn(command, gates)

    def test_a_closed_gate_ends_the_host_with_one_summary_and_nothing_after(self):
        tasks = load_tasks(ROLES_DIR / "app" / "tasks" / "gates.yml")
        self.assertEqual(module_of(tasks[-1]), "meta")
        self.assertEqual(tasks[-1]["ansible.builtin.meta"], "end_host")
        self.assertEqual(module_of(tasks[-2]), "debug")
        self.assertEqual(
            [t["name"] for t in tasks if module_of(t) == "debug"], [tasks[-2]["name"]]
        )
        main = load_tasks(ROLES_DIR / "app" / "tasks" / "main.yml")
        self.assertEqual(
            [t["ansible.builtin.include_tasks"] for t in main],
            ["prepare.yml", "gates.yml", "start.yml"],
        )

    def test_the_stack_starts_after_monitoring_init(self):
        names = [t["name"] for t in load_tasks(ROLES_DIR / "app" / "tasks" / "start.yml")]
        self.assertLess(
            names.index("Start the monitoring prerequisites"),
            names.index("Start or update the stack"),
        )


if __name__ == "__main__":
    unittest.main()
