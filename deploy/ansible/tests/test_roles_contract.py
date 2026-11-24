"""Static rules the roles must keep, read from their YAML."""

import unittest

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

import jinja2
import yaml

from roles import (
    ANSIBLE_DIR,
    ROLES_DIR,
    all_tasks,
    flatten,
    load_tasks,
    module_of,
    role_tasks,
)

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


def host_defaults():
    return yaml.safe_load(
        (ROLES_DIR / "host" / "defaults" / "main.yml").read_text(encoding="utf-8")
    )


def host_task(name):
    found = [t for _, t in role_tasks("host") if t["name"] == name]
    assert len(found) == 1, f"{name}: {len(found)} tasks"
    return found[0]


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
        reload_handlers = [
            h for h in handlers("baseline") if h.get("listen") == "reload sshd"
        ]
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
            self.assertNotIn(
                "noble", template.read_text(encoding="utf-8"), template.name
            )

    def test_the_suite_probe_comes_before_any_change(self):
        tasks = self.apply_tasks()
        probe = tasks[0]
        self.assertEqual(module_of(probe), "uri")
        self.assertIn("docker_apt_codename", probe["ansible.builtin.uri"]["url"])
        self.assertIs(probe.get("check_mode"), False)
        follow_up = tasks[1]
        self.assertEqual(module_of(follow_up), "assert")
        self.assertIn(
            "docker_apt_codename", follow_up["ansible.builtin.assert"]["fail_msg"]
        )


class HostRoleTests(unittest.TestCase):
    def test_daemon_json_holds_the_logging_and_restart_policy(self):
        text = (ROLES_DIR / "host" / "templates" / "daemon.json.j2").read_text(
            encoding="utf-8"
        )
        self.assertNotIn(
            "{{", text, "daemon.json is static: a variable would need a render test"
        )
        config = json.loads(text)
        self.assertEqual(config["log-driver"], "json-file")
        self.assertEqual(config["log-opts"], {"max-size": "10m", "max-file": "5"})
        self.assertNotIn("live-restore", config)
        self.assertIs(config["no-new-privileges"], True)

    def test_daemon_json_is_validated_before_it_replaces_the_old_one(self):
        copies = [
            t
            for t in role_tasks("host")
            if module_of(t[1]) in ("template", "copy")
            and t[1][f"ansible.builtin.{module_of(t[1])}"]["dest"]
            == "/etc/docker/daemon.json"
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
        self.assertIn("make -C deploy up", restart[0]["ansible.builtin.debug"]["msg"])
        self.assertEqual(restart[1]["ansible.builtin.service"]["state"], "restarted")

    def test_handlers_run_before_the_app_role(self):
        tasks = [t for _, t in role_tasks("host")]
        self.assertEqual(module_of(tasks[-1]), "meta")
        self.assertEqual(tasks[-1]["ansible.builtin.meta"], "flush_handlers")

    def test_journald_keeps_a_persistent_journal_for_thirty_days(self):
        text = (ROLES_DIR / "host" / "templates" / "journald.conf.j2").read_text(
            encoding="utf-8"
        )
        for line in (
            "Storage=persistent",
            "SystemMaxUse=2G",
            "MaxRetentionSec=30day",
            "MaxFileSec=1day",
            "SystemMaxFiles=2000",
        ):
            self.assertIn(line, text.splitlines())
        self.assertIn("[Journal]", text.splitlines())

    def test_every_retention_change_waits_for_the_gate(self):
        tasks = load_tasks(ROLES_DIR / "host" / "tasks" / "main.yml")
        names = [t["name"] for t in tasks]
        gate = names.index("Decide whether the log retention may shrink")
        self.assertEqual(
            module_of(tasks[gate]), "import_tasks", "the gate lives in its own file"
        )
        shrinking = [
            "Create the journald drop-in directory",
            "Keep a persistent journal for thirty days, one file per day",
            "Find the logrotate rules of the system logs",
            "Keep four weekly files of the system logs",
            "Set the rotation frequency of the system logs",
        ]
        for name in shrinking:
            self.assertGreater(names.index(name), gate, name)
            if not name.startswith("Find"):
                self.assertIn(
                    "host_log_retention_ready", str(tasks[names.index(name)]["when"])
                )
        for task in tasks[:gate]:
            text = " ".join(strings(task))
            self.assertNotIn("journald", text, task["name"])
            self.assertNotIn("logrotate.d", text, task["name"])
        say = tasks[names.index("Say the log retention was left unchanged")]
        self.assertEqual(say["when"], "not host_log_retention_ready")
        self.assertIn("again", say["ansible.builtin.debug"]["msg"])
        self.assertEqual(
            names[-1],
            "Restart Docker and journald, reload systemd, now, before the stack starts",
        )

    def test_the_frequency_rule_replaces_the_period_line_of_a_rule(self):
        task = host_task("Set the rotation frequency of the system logs")
        args = task["ansible.builtin.replace"]
        self.assertIn("item.stat.exists", task["when"])
        text = "/var/log/syslog {\n    daily\n    rotate 7\n    minsize 1M\n}\n"
        out = re.sub(args["regexp"], r"\g<1>weekly", text, flags=re.M)
        self.assertEqual(
            out, "/var/log/syslog {\n    weekly\n    rotate 7\n    minsize 1M\n}\n"
        )

    def test_docker_scopes_get_a_zero_swap_limit_that_survives_a_reload(self):
        text = (
            ROLES_DIR / "host" / "templates" / "docker-scope-no-swap.conf.j2"
        ).read_text(encoding="utf-8")
        lines = text.splitlines()
        self.assertIn("[Scope]", lines)
        self.assertEqual(lines[lines.index("[Scope]") + 1], "MemorySwapMax=0")
        self.assertNotIn("{{", text)
        writes = [
            t[1]
            for t in role_tasks("host")
            if module_of(t[1]) == "template"
            and t[1]["ansible.builtin.template"]["dest"]
            == "/etc/systemd/system/docker-.scope.d/10-manuspectrum-no-swap.conf"
        ]
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]["notify"], "reload systemd")
        self.assertEqual(writes[0]["ansible.builtin.template"]["mode"], "0644")
        reload = [h for h in handlers("host") if h.get("listen") == "reload systemd"]
        self.assertEqual([module_of(h) for h in reload], ["systemd_service"])
        self.assertIs(
            reload[0]["ansible.builtin.systemd_service"]["daemon_reload"], True
        )


class TsmPlayCase(unittest.TestCase):
    """Runs the real TSM tasks of the host role, and the app role's render tasks,
    through ansible-playbook on scratch files."""

    FIRST = "Find the hosting provider's TSM client options and nightly job"
    LAST = "Say the log retention was left unchanged"
    GATE = "Decide whether the log retention may shrink"
    LOG = "Successful incremental backup of '/var/log'"
    HOUR = 3600

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.include = self.tmp / "inclexcl.def"
        self.report = self.tmp / "report.log"
        self.options = self.tmp / "dsm.sys"
        self.logrotate = self.tmp / "logrotate.conf"
        self.data = self.tmp / "data"
        self.nginx = self.data / "nginx-logs"

    def both(self):
        return [self.LOG, f"Successful incremental backup of '{self.data}'"]

    def lines(self):
        return [
            "* BEGIN ManuSpectrum logs",
            "include /var/log/.../* LOG_ROTATED_FILES_MG",
            f"include {self.nginx}/.../* LOG_ROTATED_FILES_MG",
            "* END ManuSpectrum logs",
        ]

    def tsm_host(self, options=None, logrotate="dateext\nweekly\n", include=""):
        self.options.write_text(
            (
                options
                if options is not None
                else f'SErvername  node\n  DOMAIN /etc /home\n  Inclexcl "{self.include}"\n'
            ),
            encoding="utf-8",
        )
        (self.tmp / "cron-tsm").write_text(
            "#!/bin/sh\n/usr/bin/dsmc incremental -se=node\n", encoding="utf-8"
        )
        self.include.write_text(include, encoding="utf-8")
        self.logrotate.write_text(logrotate, encoding="utf-8")
        self.write_report(self.both())

    def write_report(self, lines, mtime=None):
        body = b"Normal File--> 5 /data/caf\xe9.txt [Sent]\n"
        body += "".join(f"{line}\n" for line in lines).encode()
        self.report.write_bytes(body)
        if mtime is not None:
            os.utime(self.report, (mtime, mtime))

    def after_backup(self, lines, report_offset):
        """Rewrites the report with `lines`, `report_offset` seconds from the include file."""
        base = self.include.stat().st_mtime
        self.write_report(lines, mtime=base + report_offset)

    def extra_vars(self):
        return {
            "host_tsm_options": str(self.options),
            "host_tsm_cron": str(self.tmp / "cron-tsm"),
            "host_tsm_inclexcl": str(self.include),
            "host_tsm_report": str(self.report),
            "host_logrotate_conf": str(self.logrotate),
            "env_nginx_log_host_dir": str(self.nginx),
            "data_mount": {"path": str(self.data)},
        }

    def ansible(self, args):
        return subprocess.run(
            [str(Path(sys.executable).parent / "ansible-playbook"), *args],
            cwd=ANSIBLE_DIR,
            env=dict(os.environ, ANSIBLE_HOME=str(self.tmp), ANSIBLE_NOCOLOR="1"),
            capture_output=True,
            text=True,
            check=False,
        )

    def host_play(self):
        """The host role's tasks FIRST..LAST, the gate file inlined in place of its import."""
        tasks = list(load_tasks(ROLES_DIR / "host" / "tasks" / "main.yml"))
        names = [t["name"] for t in tasks]
        tasks = tasks[names.index(self.FIRST) : names.index(self.LAST) + 1]
        gate = load_tasks(ROLES_DIR / "host" / "tasks" / "log_retention_gate.yml")
        at = [t["name"] for t in tasks].index(self.GATE)
        tasks[at : at + 1] = gate
        tasks.append(
            {
                "name": "Write the fact",
                "ansible.builtin.copy": {
                    "dest": str(self.tmp / "fact"),
                    "content": "{{ host_log_retention_ready }} "
                    "{{ host_log_retention_ready | type_debug }}",
                },
            }
        )
        return [
            {
                "hosts": "localhost",
                "gather_facts": False,
                "vars_files": [str(ROLES_DIR / "host" / "defaults" / "main.yml")],
                "tasks": tasks,
            }
        ]

    def run_play(self, extra=None):
        """Returns (return code, output, fact value and type or None)."""
        (self.tmp / "fact").unlink(missing_ok=True)
        play = self.tmp / "play.yml"
        play.write_text(yaml.safe_dump(self.host_play()), encoding="utf-8")
        result = self.ansible(
            [
                "-i",
                "localhost,",
                "-c",
                "local",
                "-e",
                json.dumps({**self.extra_vars(), **(extra or {})}),
                str(play),
            ]
        )
        fact = self.tmp / "fact"
        return (
            result.returncode,
            result.stdout + result.stderr,
            fact.read_text(encoding="utf-8") if fact.exists() else None,
        )

    def render_rule(self):
        """Runs the app role's render tasks alone; True when the nginx rule was written."""
        out = self.tmp / "rendered"
        (out / "env").mkdir(parents=True, exist_ok=True)
        result = self.ansible(
            [
                "-i",
                "inventories/example",
                "render.yml",
                "-e",
                json.dumps({**self.extra_vars(), "render_dir": str(out)}),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return (out / "logrotate" / "manuspectrum-nginx").exists()

    def settled(self):
        """A TSM host after its first run, the include lines written."""
        self.tsm_host()
        code, output, _ = self.run_play()
        self.assertEqual(code, 0, output)
        return self.include.read_text(encoding="utf-8")


class TsmBranchRunTests(TsmPlayCase):
    def test_the_first_run_writes_the_include_lines_and_holds_the_retention(self):
        self.tsm_host()
        code, output, fact = self.run_play()
        self.assertEqual(code, 0, output)
        self.assertEqual(
            self.include.read_text(encoding="utf-8").splitlines(), self.lines()
        )
        self.assertEqual(fact, "False bool")
        self.assertIn("retention tasks were skipped", output)

    def test_a_report_more_than_an_hour_newer_releases_the_retention(self):
        before = self.settled()
        self.after_backup(self.both(), self.HOUR + 60)
        code, output, fact = self.run_play()
        self.assertEqual(code, 0, output)
        self.assertEqual(self.include.read_text(encoding="utf-8"), before)
        self.assertEqual(fact, "True bool")

    def test_a_report_only_seconds_newer_holds_the_retention(self):
        self.settled()
        self.after_backup(self.both(), 3)
        self.assertEqual(self.run_play()[2], "False bool")

    def test_a_report_without_the_var_log_line_holds_the_retention(self):
        self.settled()
        self.after_backup([self.both()[1]], self.HOUR + 60)
        self.assertEqual(self.run_play()[2], "False bool")

    def test_a_report_without_the_data_line_holds_the_retention(self):
        self.settled()
        self.after_backup([self.LOG], self.HOUR + 60)
        self.assertEqual(self.run_play()[2], "False bool")

    def test_a_report_older_than_the_include_lines_holds_the_retention(self):
        self.settled()
        self.after_backup(self.both(), -100)
        self.assertEqual(self.run_play()[2], "False bool")

    def test_dsm_sys_without_the_include_option_stops_the_play(self):
        self.tsm_host(options="SErvername  node\n  DOMAIN /etc /home\n")
        code, output, fact = self.run_play()
        self.assertNotEqual(code, 0)
        self.assertIn(str(self.include), output)
        self.assertIn("Inclexcl", output)
        self.assertIsNone(fact)

    def test_a_missing_include_file_stops_the_play(self):
        self.tsm_host()
        self.include.unlink()
        code, output, _ = self.run_play()
        self.assertNotEqual(code, 0, output)
        self.assertFalse(self.include.exists())

    def test_logrotate_without_dateext_stops_the_play(self):
        for text in ("weekly\n", "# dateext\n#dateext\nweekly\n"):
            with self.subTest(text=text):
                self.tsm_host(logrotate=text)
                code, output, _ = self.run_play()
                self.assertNotEqual(code, 0)
                self.assertIn("dateext", output)
                self.assertIn("dated names", output)
                self.assertEqual(self.include.read_text(encoding="utf-8"), "")

    def test_a_log_directory_outside_the_checked_filespaces_stops_the_play(self):
        self.tsm_host()
        code, output, fact = self.run_play(
            {"env_nginx_log_host_dir": str(self.tmp / "elsewhere")}
        )
        self.assertNotEqual(code, 0)
        self.assertIn("outside the filespaces", output)
        self.assertIn("elsewhere", output)
        self.assertEqual(self.include.read_text(encoding="utf-8"), "")
        self.assertIsNone(fact)

    def test_a_host_without_tsm_files_gets_the_retention_at_once(self):
        code, output, fact = self.run_play()
        self.assertEqual(code, 0, output)
        self.assertEqual(fact, "True bool")
        self.assertFalse(self.include.exists())

    def test_the_nginx_rule_is_not_written_while_the_include_lines_are_absent(self):
        self.tsm_host()
        self.after_backup(self.both(), self.HOUR + 60)
        self.assertFalse(self.render_rule())

    def test_the_nginx_rule_is_not_written_while_the_report_is_older_than_the_lines(
        self,
    ):
        self.tsm_host(include="\n".join(self.lines()) + "\n")
        self.after_backup(self.both(), -100)
        self.assertFalse(self.render_rule())

    def test_the_nginx_rule_is_written_once_a_good_backup_followed_the_lines(self):
        self.tsm_host(include="\n".join(self.lines()) + "\n")
        self.after_backup(self.both(), self.HOUR + 60)
        self.assertTrue(self.render_rule())

    def test_the_nginx_rule_is_written_on_a_host_without_tsm_files(self):
        self.assertTrue(self.render_rule())


class RepoGuardRunTests(TsmPlayCase):
    """Runs the guard tasks of the host role on a scratch copy of a provider job."""

    LAST = "Run the restic repository guard before the nightly TSM backup"
    GUARD = "restic-repo-guard.sh"
    JOB = (
        "#!/bin/sh\n"
        "PATH=/bin:/usr/bin:/sbin:/usr/sbin\n"
        "export PATH\n"
        "export LANG=C.UTF-8 LC_ALL=C.UTF-8\n"
        "{dsmc} Incremental -TAPEPrompt=No > {report} 2>&1\n"
        "exit 0\n"
    )

    def setUp(self):
        super().setUp()
        self.guard_dir = self.tmp / "lib" / "repo-guard"
        self.state_dir = self.tmp / "state" / "repo-guard"
        self.marker = self.tmp / "dsmc-ran"
        self.repo = self.tmp / "restic"
        self.metrics = self.tmp / "metrics"

    def extra_vars(self):
        return {
            **super().extra_vars(),
            "host_repo_guard_dir": str(self.guard_dir),
            "host_repo_guard_state_dir": str(self.state_dir),
            "host_repo_guard_owner": str(os.getuid()),
            "host_repo_guard_group": str(os.getgid()),
            "host_repo_guard_src_dir": str(ANSIBLE_DIR.parent / "scripts"),
            "env_restic_repository_dir": str(self.repo),
            "env_metrics_textfile_dir": str(self.metrics),
        }

    def provider_job(self):
        dsmc = self.tmp / "dsmc"
        dsmc.write_text(f"#!/bin/sh\ntouch {self.marker}\n", encoding="utf-8")
        dsmc.chmod(0o755)
        self.tsm_host()
        (self.tmp / "cron-tsm").write_text(
            self.JOB.format(dsmc=dsmc, report=self.tmp / "dsmc.log"), encoding="utf-8"
        )

    def job_lines(self):
        return (self.tmp / "cron-tsm").read_text(encoding="utf-8").splitlines()

    def run_job(self, guard_exit, shell=("sh",)):
        """Runs the job with a chatty stub guard exiting `guard_exit` (None: no guard
        script); returns (dsmc ran, what the job printed)."""
        self.marker.unlink(missing_ok=True)
        stub = self.guard_dir / self.GUARD
        stub.unlink(missing_ok=True)
        if guard_exit is not None:
            stub.write_text(
                "#!/bin/sh\n"
                'printf "%s\\n%s\\n%s\\n" "$METRICS_TEXTFILE_DIR"'
                ' "$RESTIC_REPOSITORY_DIR" "$RESTIC_GUARD_STATE_DIR"'
                f" > {self.tmp}/guard-env\n"
                "echo chatter; echo ALTERED >&2\n"
                f"exit {guard_exit}\n",
                encoding="utf-8",
            )
            stub.chmod(0o755)
        result = subprocess.run(
            [*shell, str(self.tmp / "cron-tsm")], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.marker.exists(), result.stdout + result.stderr

    def test_the_guard_line_stops_the_job_only_on_an_alteration(self):
        self.provider_job()
        code, output, _ = self.run_play()
        self.assertEqual(code, 0, output)
        for shell in (("sh",), ("sh", "-e")):
            for guard_exit, dsmc_runs in (
                (0, True),
                (1, False),
                (2, True),
                (None, True),
            ):
                with self.subTest(shell=shell, guard_exit=guard_exit):
                    ran, printed = self.run_job(guard_exit, shell)
                    self.assertIs(ran, dsmc_runs)
                    self.assertEqual(printed, "")

    def test_the_line_sits_before_dsmc_and_a_second_run_changes_nothing(self):
        self.provider_job()
        self.assertEqual(self.run_play()[0], 0)
        first = self.job_lines()
        guard = [i for i, line in enumerate(first) if self.GUARD in line]
        dsmc = [i for i, line in enumerate(first) if "dsmc " in line]
        locale = first.index("export LANG=C.UTF-8 LC_ALL=C.UTF-8")
        self.assertEqual(len(guard), 1)
        self.assertEqual(guard[0], dsmc[0] - 1)
        self.assertEqual(locale, guard[0] - 1)
        code, output, _ = self.run_play()
        self.assertEqual(code, 0, output)
        self.assertEqual(self.job_lines(), first)

    def test_the_line_names_both_directories_and_is_one_exact_line(self):
        self.provider_job()
        self.run_play()
        line = next(l for l in self.job_lines() if self.GUARD in l)
        self.assertEqual(
            line,
            f"METRICS_TEXTFILE_DIR={self.metrics} RESTIC_REPOSITORY_DIR={self.repo} "
            f"RESTIC_GUARD_STATE_DIR={self.state_dir} "
            f'{self.guard_dir}/{self.GUARD} >/dev/null 2>&1 || [ "$?" -ne 1 ] || exit 0',
        )

    def test_a_changed_inventory_path_rewrites_the_line_in_place(self):
        self.provider_job()
        self.run_play()
        before = self.job_lines()
        self.repo = self.tmp / "other restic"
        code, output, _ = self.run_play()
        self.assertEqual(code, 0, output)
        after = self.job_lines()
        self.assertEqual(len(after), len(before))
        self.assertEqual(sum(self.GUARD in l for l in after), 1)
        self.assertIn(f"RESTIC_REPOSITORY_DIR='{self.repo}'", "\n".join(after))
        self.metrics = self.tmp / "other metrics"
        self.run_play()
        self.assertEqual(sum(self.GUARD in l for l in self.job_lines()), 1)

    def test_a_path_with_a_blank_does_not_break_the_line(self):
        self.provider_job()
        self.repo = self.tmp / "a b; touch injected"
        self.metrics = self.tmp / "m 1"
        self.state_dir = self.tmp / "s 1" / "repo-guard"
        code, output, _ = self.run_play()
        self.assertEqual(code, 0, output)
        ran, _ = self.run_job(0)
        self.assertTrue(ran)
        self.assertFalse((self.tmp / "injected").exists())
        self.assertEqual(
            (self.tmp / "guard-env").read_text(encoding="utf-8").splitlines(),
            [str(self.metrics), str(self.repo), str(self.state_dir)],
        )

    def test_the_default_owner_of_the_guard_is_root(self):
        """Ownership cannot be exercised unprivileged: the scratch runs override it."""
        defaults = host_defaults()
        self.assertEqual(defaults["host_repo_guard_owner"], "root")
        self.assertEqual(defaults["host_repo_guard_group"], "root")

    def test_a_job_without_a_dsmc_line_to_anchor_on_stops_the_play(self):
        self.provider_job()
        job = self.tmp / "cron-tsm"
        text = job.read_text(encoding="utf-8").replace(
            f"{self.tmp}/dsmc Incremental", f"exec {self.tmp}/dsmc Incremental"
        )
        job.write_text(text, encoding="utf-8")
        code, output, _ = self.run_play()
        self.assertNotEqual(code, 0, output)
        self.assertIn("guard was not installed", output)
        self.assertNotIn(self.GUARD, job.read_text(encoding="utf-8"))
        self.assertFalse(self.guard_dir.exists())

    def test_a_job_made_non_executable_by_the_operator_stays_so(self):
        self.provider_job()
        job = self.tmp / "cron-tsm"
        job.chmod(0o644)
        before = self.run_play()
        self.assertEqual(before[0], 0, before[1])
        line = [l for l in self.job_lines() if self.GUARD in l]
        self.assertEqual(len(line), 1)
        self.assertEqual(oct(job.stat().st_mode & 0o777), "0o644")
        job.chmod(0o755)
        job.chmod(0o644)
        code, output, _ = self.run_play()
        self.assertEqual(code, 0, output)
        self.assertEqual([l for l in self.job_lines() if self.GUARD in l], line)
        self.assertEqual(oct(job.stat().st_mode & 0o777), "0o644")

    def test_a_host_without_the_provider_job_installs_nothing(self):
        code, output, _ = self.run_play()
        self.assertEqual(code, 0, output)
        self.assertFalse(self.guard_dir.exists())
        self.assertFalse(self.state_dir.exists())

    def test_the_installed_guard_dir_is_private_to_root_and_executable(self):
        self.provider_job()
        self.run_play()
        self.assertEqual(oct(self.state_dir.stat().st_mode & 0o777), "0o700")
        self.assertEqual(
            oct((self.guard_dir / self.GUARD).stat().st_mode & 0o777), "0o755"
        )
        self.assertEqual(
            oct((self.guard_dir / "lib-metrics.sh").stat().st_mode & 0o777), "0o644"
        )


class BackupFreezeTests(unittest.TestCase):
    """Runs the stat, the debug and the loop of start.yml's « Enable the timers »
    through ansible-playbook, the systemd module replaced by a recorder."""

    def run_freeze(self, marker_present):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            marker = tmp / "backups-frozen"
            if marker_present:
                marker.write_text("", encoding="utf-8")
            enabled = tmp / "enabled"
            real = {t["name"]: t for t in load_tasks(APP / "tasks" / "start.yml")}
            stat = real["Look for the backup freeze marker"]
            say = real["Say the backup timers were left alone"]
            loop = {
                k: v
                for k, v in real["Enable the timers"].items()
                if k in ("name", "loop", "when")
            }
            loop["ansible.builtin.lineinfile"] = {
                "path": str(enabled),
                "line": "{{ item }}",
                "create": True,
            }
            play = [
                {
                    "hosts": "localhost",
                    "gather_facts": False,
                    "vars_files": [str(APP / "defaults" / "main.yml")],
                    "tasks": [stat, say, loop],
                }
            ]
            (tmp / "play.yml").write_text(yaml.safe_dump(play), encoding="utf-8")
            result = subprocess.run(
                [
                    str(Path(sys.executable).parent / "ansible-playbook"),
                    "-i",
                    "localhost,",
                    "-c",
                    "local",
                    "-e",
                    json.dumps(
                        {
                            "app_backups_frozen_marker": str(marker),
                            "env_cert_mode": "acme",
                        }
                    ),
                    str(tmp / "play.yml"),
                ],
                cwd=ANSIBLE_DIR,
                env=dict(os.environ, ANSIBLE_HOME=str(tmp), ANSIBLE_NOCOLOR="1"),
                capture_output=True,
                text=True,
                check=False,
            )
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, output)
            names = (
                enabled.read_text(encoding="utf-8").split() if enabled.exists() else []
            )
            return names, output

    def test_without_the_marker_every_timer_is_enabled(self):
        names, output = self.run_freeze(False)
        d = app_defaults()
        self.assertEqual(
            sorted(names), sorted(d["app_timer_names"] + d["app_acme_timer_names"])
        )
        self.assertNotIn("were left as they are", output)

    def test_with_the_marker_the_backup_timers_are_left_alone(self):
        names, output = self.run_freeze(True)
        d = app_defaults()
        everything = d["app_timer_names"] + d["app_acme_timer_names"]
        self.assertEqual(
            sorted(names),
            sorted(n for n in everything if n not in d["app_frozen_timer_names"]),
        )
        self.assertIn("manuspectrum-backup", d["app_frozen_timer_names"])
        self.assertIn("manuspectrum-restore-test", d["app_frozen_timer_names"])
        self.assertIn("were left as they are", output)
        self.assertIn("deploy/INCIDENT.md", output)

    def test_no_other_task_of_the_app_role_starts_or_enables_the_frozen_timers(self):
        for _, task in role_tasks("app"):
            if module_of(task) in ("systemd_service", "systemd", "service"):
                self.assertIn(
                    task["name"],
                    (
                        "Enable the timers",
                        "Remove the 1.0.4 log archive timer from the running units",
                    ),
                )
        text = "".join(
            p.read_text(encoding="utf-8") for p in (APP / "tasks").glob("*.yml")
        )
        self.assertNotRegex(
            text, r"(enable|start)[^\n]*(manuspectrum-backup|restore-test)"
        )


class ContractParityTests(unittest.TestCase):
    """Facts one file states and another must agree with."""

    def test_the_tsm_check_unit_runs_what_the_role_installs(self):
        unit = (REPO / "deploy/systemd/manuspectrum-tsm-check.service.in").read_text(
            encoding="utf-8"
        )
        d = app_defaults()
        self.assertIn(
            f"ExecStart={d['app_tsm_check_dir']}/tsm-check.sh", unit.splitlines()
        )
        conf = task_named("app", "release.yml", "Write the TSM check configuration")
        self.assertIn(
            f"EnvironmentFile={conf['ansible.builtin.template']['dest']}",
            unit.splitlines(),
        )

    def test_every_script_run_from_the_lib_directory_is_managed(self):
        scripts = set()
        for unit in (REPO / "deploy/systemd").glob("*.service.in"):
            scripts |= set(
                re.findall(
                    r"^ExecStart=/usr/local/lib/manuspectrum/[\w-]+/([\w.-]+\.sh)",
                    unit.read_text(encoding="utf-8"),
                    re.M,
                )
            )
        scripts |= {
            f["name"]
            for f in host_defaults()["host_repo_guard_files"]
            if f["mode"] == "0755"
        }
        d = app_defaults()
        released = {f["name"] for f in d["app_release_program_files"]}
        self.assertTrue({"tsm-check.sh", "restic-repo-guard.sh"} <= scripts)
        for name in scripts:
            self.assertIn(name, managed_script_names(), name)
            self.assertTrue(
                f"deploy/scripts/{name}" in d["app_release_managed_paths"]
                or name in released,
                name,
            )

    def test_lib_metrics_is_installed_beside_each_script_that_sources_it(self):
        lists = [
            app_defaults()["app_tsm_check_files"],
            app_defaults()["app_release_program_files"],
            host_defaults()["host_repo_guard_files"],
        ]
        for files in lists:
            names = {f["name"] for f in files}
            for name in names:
                text = (REPO / "deploy/scripts" / name).read_text(encoding="utf-8")
                for lib in re.findall(r'^source "\$HERE/(lib-[\w-]+\.sh)"', text, re.M):
                    self.assertIn(lib, names, f"{name} sources {lib}")

    def test_every_timer_unit_the_role_installs_is_enabled_by_it(self):
        d = app_defaults()
        stems = {
            p.name.removesuffix(".timer.in")
            for p in (REPO / "deploy/systemd").glob("*.timer.in")
        }
        installed = stems & set(d["app_unit_names"])
        self.assertIn("manuspectrum-tsm-check", installed)
        enabled = set(d["app_timer_names"]) | set(d["app_acme_timer_names"])
        self.assertEqual(
            installed - enabled,
            {"manuspectrum-update-at"},
            "written by the update command",
        )


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
        found.append(
            (f"{where}: {task['name']}", re.sub(r"\{\{.*?\}\}", "X", str(args)))
        )
    return found, tasks


class AppRoleTests(unittest.TestCase):
    def test_app_never_runs_destructive_targets(self):
        commands, _ = executed_commands()
        self.assertGreater(len(commands), 10)
        for name, line in commands:
            self.assertNotIn("setup_db", line, name)
            words = shlex.split(line)
            if "make" in words:
                targets = [
                    w
                    for w in words[words.index("make") + 1 :]
                    if not w.startswith("-") and "=" not in w and w != "X"
                ]
                self.assertFalse(
                    FORBIDDEN_MAKE_TARGETS & set(targets), f"{name}: {line}"
                )

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
        self.assertEqual(module_of(tasks[-1]), "debug")
        self.assertEqual(
            [t["name"] for t in tasks if module_of(t) == "debug"], [tasks[-1]["name"]]
        )
        self.assertEqual(
            main_includes(),
            [
                "marker.yml",
                "update_guard.yml",
                "refusals.yml",
                "prepare.yml",
                "release.yml",
                "gates.yml",
                "start.yml",
                "marker_release.yml",
            ],
        )
        start = [
            t
            for t in load_tasks(ROLES_DIR / "app" / "tasks" / "main.yml")
            if t.get("ansible.builtin.include_tasks") == "start.yml"
        ][0]
        self.assertEqual(start["when"], "app_todo | length == 0")
        for _, task in role_tasks("app"):
            self.assertNotEqual(task.get("ansible.builtin.meta"), "end_host")

    def test_the_stack_starts_after_monitoring_init(self):
        names = [
            t["name"] for t in load_tasks(ROLES_DIR / "app" / "tasks" / "start.yml")
        ]
        self.assertLess(
            names.index("Start the monitoring prerequisites"),
            names.index("Start or update the stack"),
        )


APP = ROLES_DIR / "app"
ANSIBLE = ROLES_DIR.parent
REPO = ROLES_DIR.parents[2]


def app_defaults():
    return yaml.safe_load((APP / "defaults" / "main.yml").read_text(encoding="utf-8"))


def managed_script_names():
    """The deploy/scripts files release-managed.sh treats as managed."""
    text = (REPO / "deploy" / "scripts" / "release-managed.sh").read_text(
        encoding="utf-8"
    )
    body = text[text.index("is_managed()") : text.index("no_dotdot()")]
    return set(re.findall(r"deploy/scripts/([A-Za-z0-9._-]+\.sh)", body))


def release_tasks():
    return load_tasks(APP / "tasks" / "release.yml")


def all_app_tasks():
    return [t for _, t in role_tasks("app")]


class ReleaseInstallTests(unittest.TestCase):
    def test_units_lists_keep_the_update_timer_and_template_out_of_the_enabled_set(
        self,
    ):
        d = app_defaults()
        self.assertIn("manuspectrum-watch", d["app_unit_names"])
        self.assertIn("manuspectrum-watch", d["app_timer_names"])
        self.assertIn("manuspectrum-update-at", d["app_unit_names"])
        self.assertEqual(d["app_oneshot_unit_names"], ["manuspectrum-update@"])
        enabled = set(d["app_timer_names"]) | set(d["app_acme_timer_names"])
        for name in enabled:
            self.assertNotIn("update", name)
        self.assertNotIn("manuspectrum-update@", d["app_unit_names"])

    def test_no_task_enables_or_starts_an_update_unit_or_touches_its_slot(self):
        for task in all_app_tasks():
            if module_of(task) in ("systemd", "systemd_service", "service"):
                args = task[next(k for k in task if k.endswith(module_of(task)))]
                self.assertNotIn("update", str(args.get("name", "")), task["name"])
            for text in strings(task):
                self.assertNotIn("timer.d", text, task["name"])
                self.assertNotIn("slot.conf", text, task["name"])
        start = task_named("app", "start.yml", "Enable the timers")
        loop = start["loop"]
        self.assertIn("app_timer_names", loop)
        self.assertNotIn("app_unit_names", loop)
        self.assertNotIn("oneshot", loop)

    def test_render_makes_the_oneshot_unit_a_service_only(self):
        text = (APP / "tasks" / "render.yml").read_text(encoding="utf-8")
        self.assertIn("app_oneshot_unit_names", text)
        self.assertNotIn("twelve", text)

    def test_the_sudoers_rule_is_validated_and_asks_for_a_password(self):
        task = task_named("app", "release.yml", "Allow the operators to run the update")
        args = task["ansible.builtin.template"]
        self.assertEqual(args["validate"], "visudo -cf %s")
        self.assertEqual(args["dest"], "/etc/sudoers.d/manuspectrum-update")
        self.assertEqual(args["mode"], "0440")
        self.assertEqual(args["owner"], "root")
        text = (APP / "templates" / args["src"]).read_text(encoding="utf-8")
        self.assertNotIn("NOPASSWD", text)
        rules = [ln for ln in text.splitlines() if ln.strip() and ln[0] != "#"]
        self.assertEqual(
            rules,
            ["%{{ app_ops_group }} ALL=(root) /usr/local/sbin/manuspectrum-update"],
        )
        self.assertEqual(app_defaults()["app_ops_group"], "manuspectrum-ops")

    def test_the_sudoers_rule_passes_visudo(self):
        import shutil
        import subprocess
        import tempfile

        if not shutil.which("visudo"):
            self.skipTest("visudo is not installed")
        import jinja2

        text = (APP / "templates" / "sudoers-manuspectrum-update.j2").read_text(
            encoding="utf-8"
        )
        rendered = jinja2.Template(text, keep_trailing_newline=True).render(
            app_ops_group="manuspectrum-ops"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".sudoers") as handle:
            handle.write(rendered)
            handle.flush()
            result = subprocess.run(
                ["visudo", "-cf", handle.name], capture_output=True, text=True
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_program_files_are_root_owned_and_not_writable_by_others(self):
        for task in release_tasks():
            if module_of(task) in ("copy", "template", "file"):
                args = task[next(k for k in task if k.endswith(module_of(task)))]
                dest = str(args.get("dest", args.get("path", "")))
                if dest.startswith(("/usr/local", "/etc/manuspectrum", "/etc/sudoers")):
                    self.assertEqual(args.get("owner"), "root", task["name"])
                    self.assertEqual(args.get("group"), "root", task["name"])
                    self.assertNotIn(
                        args["mode"][-2:], ("22", "66", "77"), task["name"]
                    )
                    self.assertRegex(args["mode"], r"^0[0-7]{3}$", task["name"])

    def test_the_release_file_list_is_the_managed_list_of_release_managed(self):
        files = app_defaults()["app_release_program_files"]
        names = {f["name"] for f in files}
        self.assertEqual(
            names, managed_script_names() - {"tsm-check.sh", "restic-repo-guard.sh"}
        )
        modes = {f["name"]: f["mode"] for f in files}
        for name in ("lib-release.sh", "lib-metrics.sh"):
            self.assertEqual(modes[name], "0644")
        for name in names - {"lib-release.sh", "lib-metrics.sh"}:
            self.assertEqual(modes[name], "0755")
        install = task_named("app", "release.yml", "Install the release programs")
        self.assertIn("app_release_program_files", install["loop"])
        self.assertEqual(
            install["ansible.builtin.copy"]["dest"],
            "{{ app_release_lib_dir }}/{{ item.name }}",
        )
        self.assertEqual(
            app_defaults()["app_release_lib_dir"], "/usr/local/lib/manuspectrum/release"
        )
        front = task_named("app", "release.yml", "Install the update command")
        self.assertEqual(
            front["ansible.builtin.copy"]["dest"], "/usr/local/sbin/manuspectrum-update"
        )
        self.assertEqual(front["ansible.builtin.copy"]["mode"], "0755")

    def test_the_tsm_check_environment_reaches_the_script(self):
        text = (APP / "templates" / "tsm-check.env.j2").read_text(encoding="utf-8")
        default = app_defaults()["app_data_mount_path"]
        env = jinja2.Environment()
        for data_mount, filespace in (
            ({"path": "/srv/data"}, "/srv/data"),
            (None, "/data"),
        ):
            known = {"data_mount": data_mount} if data_mount else {}
            path = env.from_string(default).render(**known)
            self.assertEqual(path, filespace)
            rendered = env.from_string(text).render(
                env_metrics_textfile_dir="/home/svc/metrics",
                env_nginx_log_host_dir="/data/app/nginx-logs",
                app_data_mount_path=path,
            )
            values = {
                key: shlex.split(value)[0].split()
                for key, value in (
                    line.split("=", 1)
                    for line in rendered.splitlines()
                    if line and not line.startswith("#")
                )
            }
            self.assertEqual(values["METRICS_TEXTFILE_DIR"], ["/home/svc/metrics"])
            self.assertEqual(
                values["TSM_LOG_DIRS"], ["/var/log", "/data/app/nginx-logs"]
            )
            self.assertEqual(values["TSM_REQUIRED_FILESPACES"], [filespace, "/var/log"])

    def test_what_release_1_0_4_installed_is_removed_and_the_removal_tolerates_a_fresh_host(
        self,
    ):
        removed = set()
        for task in release_tasks():
            if task["name"].startswith("Remove the 1.0.4 log archive"):
                module = module_of(task)
                args = task[next(k for k in task if k.endswith(module))]
                if module == "file":
                    self.assertEqual(args["state"], "absent", task["name"])
                    self.assertEqual(args["path"], "{{ item }}")
                    removed.update(task["loop"])
                    continue
                if module == "systemd_service":
                    self.assertEqual(args["name"], "manuspectrum-log-archive.timer")
                    self.assertIs(args["enabled"], False)
                    self.assertEqual(args["state"], "stopped")
                    self.assertIs(task["failed_when"], False)
                    self.assertEqual(task["when"], "app_old_archive_timer.stat.exists")
                    removed.add("timer")
        self.assertEqual(
            removed,
            {
                "timer",
                "/etc/systemd/system/manuspectrum-log-archive.service",
                "/etc/systemd/system/manuspectrum-log-archive.timer",
                "/etc/manuspectrum/log-archive.env",
                "/usr/local/lib/manuspectrum/log-archive",
                "/var/lib/manuspectrum/log-archive",
                "{{ env_metrics_textfile_dir }}/manuspectrum_log_archive.prom",
                "{{ env_metrics_textfile_dir }}/manuspectrum_log_archive_success.prom",
            },
        )
        files = task_named("app", "release.yml", "Remove the 1.0.4 log archive files")
        self.assertEqual(files["notify"], "reload systemd")

    def test_the_tsm_check_program_and_configuration_are_root_owned(self):
        directory = task_named(
            "app", "release.yml", "Create the TSM check program directory"
        )
        self.assertEqual(
            {
                k: directory["ansible.builtin.file"][k]
                for k in ("owner", "group", "mode")
            },
            {"owner": "root", "group": "root", "mode": "0755"},
        )
        install = task_named("app", "release.yml", "Install the TSM check program")
        args = install["ansible.builtin.copy"]
        self.assertEqual((args["owner"], args["group"]), ("root", "root"))
        self.assertEqual(args["mode"], "{{ item.mode }}")
        for entry in app_defaults()["app_tsm_check_files"]:
            self.assertRegex(entry["mode"], r"^0[0-7][045][045]$", entry["name"])
        conf = task_named("app", "release.yml", "Write the TSM check configuration")
        args = conf["ansible.builtin.template"]
        self.assertEqual(
            (args["owner"], args["group"], args["mode"]), ("root", "root", "0644")
        )

    def test_managed_sources_come_from_the_laptop_checkout_worktree(self):
        compute = task_named(
            "app", "release.yml", "Hash the managed files of the laptop checkout"
        )
        line = command_line(compute)
        self.assertIn("release-managed.sh", line)
        self.assertIn("--worktree", line)
        self.assertEqual(compute["delegate_to"], "localhost")
        self.assertIs(compute["become"], False)
        self.assertIs(compute["changed_when"], False)
        self.assertIs(compute["check_mode"], False)
        write = task_named("app", "release.yml", "Record the managed sources")
        args = write["ansible.builtin.copy"]
        self.assertEqual(args["dest"], "/etc/manuspectrum/managed-sources")
        self.assertEqual(
            (args["owner"], args["group"], args["mode"]), ("root", "root", "0644")
        )

    def test_a_dirty_laptop_checkout_stops_before_anything_is_installed(self):
        names = [t["name"] for t in load_tasks(APP / "tasks" / "refusals.yml")]
        dirty = task_named(
            "app", "refusals.yml", "Look for uncommitted changes in the managed paths"
        )
        self.assertIn("status --porcelain", command_line(dirty))
        self.assertEqual(dirty["delegate_to"], "localhost")
        self.assertIs(dirty["become"], False)
        check = names.index("Assert the laptop checkout is clean in the managed paths")
        self.assertGreater(len(names), check)
        includes = main_includes()
        self.assertLess(includes.index("refusals.yml"), includes.index("prepare.yml"))
        self.assertNotIn(
            "Assert the laptop checkout is clean in the managed paths",
            [t["name"] for t in release_tasks()],
        )

    def test_the_service_account_is_never_an_operator(self):
        task = task_named(
            "app", "refusals.yml", "Assert the service account is not an operator"
        )
        text = " ".join(strings(task))
        self.assertIn("service_user", text)
        self.assertIn("release_operators", text)
        defaults = (APP / "defaults" / "main.yml").read_text(encoding="utf-8")
        self.assertIn("admin_users", defaults)

    def test_release_conf_names_the_three_keys_the_front_reads(self):
        text = (APP / "templates" / "release.conf.j2").read_text(encoding="utf-8")
        keys = re.findall(r"^([A-Z_]+)=", text, re.M)
        self.assertEqual(keys, ["SERVICE_USER", "APP_DIR", "PUBLIC_HOST"])
        task = task_named("app", "release.yml", "Write the release configuration")
        args = task["ansible.builtin.template"]
        self.assertEqual(args["dest"], "/etc/manuspectrum/release.conf")
        self.assertEqual(
            (args["owner"], args["group"], args["mode"]), ("root", "root", "0644")
        )

    def test_an_active_update_stops_the_play_before_the_stack_is_touched(self):
        guard = task_named("app", "update_guard.yml", "Look for a running update")
        line = command_line(guard)
        self.assertIn("manuspectrum-update@*", line)
        self.assertIn("--state=active,activating", line)
        refuse = task_named("app", "update_guard.yml", "Refuse to run during an update")
        self.assertIn("app_update_units", " ".join(strings(refuse)))
        start = load_tasks(APP / "tasks" / "start.yml")
        self.assertEqual(start[0]["ansible.builtin.include_tasks"], "update_guard.yml")
        self.assertIn("update_guard.yml", main_includes())

    def test_release_comes_after_the_checkout_and_before_the_gates(self):
        main = main_includes()
        self.assertLess(main.index("prepare.yml"), main.index("release.yml"))
        self.assertLess(main.index("release.yml"), main.index("start.yml"))

    def test_the_host_has_the_tools_the_release_scripts_use(self):
        task = task_named(
            "app",
            "prepare.yml",
            "Install the tools the make targets and the checkout need",
        )
        self.assertTrue(
            {"curl", "tzdata", "util-linux"} <= set(task["ansible.builtin.apt"]["name"])
        )


def main_includes():
    return [
        t["ansible.builtin.include_tasks"]
        for t in load_tasks(APP / "tasks" / "main.yml")
        if "ansible.builtin.include_tasks" in t
    ]


def task_named(role, file, name):
    tasks = load_tasks(ROLES_DIR / role / "tasks" / file)
    found = [t for t in tasks if t["name"] == name]
    assert len(found) == 1, f"{name}: {len(found)} tasks"
    return found[0]


def command_line(task):
    args = task[next(k for k in task if k.split(".")[-1] in COMMAND_MODULES)]
    if isinstance(args, dict):
        args = args.get("cmd") or " ".join(args.get("argv", []))
    return str(args)


class FixWaveTests(unittest.TestCase):
    def test_every_make_call_hides_the_directory_messages(self):
        commands, _ = executed_commands()
        calls = [(n, line) for n, line in commands if re.search(r"\bmake\b", line)]
        self.assertGreater(len(calls), 3)
        for name, line in calls:
            self.assertIn("--no-print-directory", line, name)

    def test_app_installs_the_tools_the_make_targets_need(self):
        task = task_named(
            "app",
            "prepare.yml",
            "Install the tools the make targets and the checkout need",
        )
        args = task["ansible.builtin.apt"]
        self.assertEqual(args["state"], "present")
        self.assertTrue({"make", "git", "openssl", "python3"} <= set(args["name"]))
        self.assertNotIn("when", task, "installed in verify mode too")

    def test_the_parent_of_the_secrets_directory_belongs_to_the_service_user(self):
        task = task_named(
            "app", "prepare.yml", "Create the parent of the secrets directory"
        )
        args = task["ansible.builtin.file"]
        self.assertIn("env_secrets_dir | dirname", args["path"])
        self.assertEqual(args["mode"], "0750")
        self.assertIn("app_uid", args["owner"])

    def test_the_smtp_port_has_a_default_when_the_relay_names_none(self):
        task = task_named("preflight", "main.yml", "Reach the SMTP relay")
        self.assertIn(
            "default([25], true) | first", task["ansible.builtin.wait_for"]["port"]
        )
        audit = yaml.safe_load(
            (ROLES_DIR.parent / "audit.yml").read_text(encoding="utf-8")
        )
        text = " ".join(strings(audit))
        self.assertIn("default([-1], true) | first", text)

    def test_apply_refuses_a_run_that_could_lock_the_administrator_out(self):
        tasks = load_tasks(ROLES_DIR / "baseline" / "tasks" / "apply.yml")
        guard = [
            t
            for t in tasks
            if t["name"] == "Assert the connecting account stays able to sign in"
        ]
        self.assertEqual(len(guard), 1)
        text = " ".join(strings(guard[0]))
        for needle in ("ansible_user", "admin_users", "pubkey", "ansible_port"):
            self.assertIn(needle, text)
        names = [t["name"] for t in tasks]
        self.assertLess(
            names.index(guard[0]["name"]), names.index("Install the baseline packages")
        )

    def test_the_database_gate_waits_for_postgres_and_tells_unreachable_from_empty(
        self,
    ):
        ready = task_named(
            "app", "gates.yml", "Wait for the database to accept connections"
        )
        self.assertIn("pg_isready", command_line(ready))
        self.assertIn("until", ready)
        text = (ROLES_DIR / "app" / "tasks" / "gates.yml").read_text(encoding="utf-8")
        self.assertIn("app_db_state", text)
        self.assertIn("unreachable", text)

    def test_the_docker_repository_is_read_from_apt_not_from_files(self):
        task = task_named("baseline", "verify.yml", "Search the Docker apt repository")
        line = command_line(task)
        self.assertIn("apt-cache policy docker-ce", line)
        self.assertNotIn("grep", line)

    def test_the_docker_key_is_checked_against_its_fingerprint(self):
        tasks = load_tasks(ROLES_DIR / "baseline" / "tasks" / "apply.yml")
        names = [t["name"] for t in tasks]
        check = names.index(
            "Assert the Docker repository key has the expected fingerprint"
        )
        self.assertLess(check, names.index("Install the Docker repository key"))
        defaults = (ROLES_DIR / "baseline" / "defaults" / "main.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("9DC858229FC7DD38854AE2D88D81803C0EBFCD88", defaults)

    def test_daemon_json_keeps_the_keys_of_the_sysadmin_and_asks_before_a_restart(self):
        names = [t["name"] for _, t in role_tasks("host")]
        guard = names.index(
            "Assert the existing daemon.json holds only keys this role sets"
        )
        ask = names.index("Assert a restart of Docker is allowed")
        write = names.index("Configure the Docker daemon")
        self.assertLess(guard, write)
        self.assertLess(ask, write)
        text = (ROLES_DIR / "host" / "tasks" / "main.yml").read_text(encoding="utf-8")
        self.assertIn("docker_restart_ok", text)

    def test_the_image_in_service_is_the_last_line_of_the_env_file(self):
        text = (ROLES_DIR / "app" / "tasks" / "render.yml").read_text(encoding="utf-8")
        self.assertRegex(
            text, r"regex_findall\('[^\n]*MANUSPECTRUM_IMAGE[^\n]*\n\s*\| last \|"
        )

    def test_baseline_apply_flushes_its_handlers_last(self):
        tasks = load_tasks(ROLES_DIR / "baseline" / "tasks" / "apply.yml")
        self.assertEqual(module_of(tasks[-1]), "meta")
        self.assertEqual(tasks[-1]["ansible.builtin.meta"], "flush_handlers")

    def test_the_env_file_belongs_to_the_primary_group_of_the_service_user(self):
        text = (ROLES_DIR / "app" / "tasks" / "render.yml").read_text(encoding="utf-8")
        self.assertIn("app_render_env_group", text)
        self.assertNotIn('group: "{{ app_render_env_owner', text)

    def test_preflight_messages_for_time_and_sysctl(self):
        text = (ROLES_DIR / "preflight" / "tasks" / "main.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("/etc/sysctl.d", text)
        self.assertIn("Debian 13", text)
        ntp = task_named(
            "preflight", "main.yml", "Read the clock synchronisation state"
        )
        self.assertIn("until", ntp)

    def test_verify_collects_every_mismatch_before_failing(self):
        tasks = load_tasks(ROLES_DIR / "baseline" / "tasks" / "verify.yml")
        asserts = [t for t in tasks if module_of(t) == "assert"]
        summary = asserts[-1]
        self.assertEqual(summary["name"], "Fail once, listing every mismatch")
        for task in asserts[:-1]:
            self.assertIs(task.get("failed_when"), False, task["name"])
            self.assertTrue(
                str(task.get("register", "")).startswith("baseline_chk_"), task["name"]
            )


class RunMarkerTests(unittest.TestCase):
    """An Ansible run and an update never run together."""

    def main_play(self):
        return yaml.safe_load((APP / "tasks" / "main.yml").read_text(encoding="utf-8"))

    def test_the_role_runs_in_a_block_that_always_removes_the_marker(self):
        play = self.main_play()
        self.assertEqual(len(play), 1)
        block = play[0]
        self.assertEqual(
            block["block"][0]["ansible.builtin.include_tasks"], "marker.yml"
        )
        always = block["always"]
        self.assertEqual(len(always), 1)
        self.assertEqual(
            always[0]["ansible.builtin.include_tasks"], "marker_release.yml"
        )
        release = load_tasks(APP / "tasks" / "marker_release.yml")
        self.assertEqual(len(release), 1)
        args = release[0]["ansible.builtin.file"]
        self.assertEqual(args["state"], "absent")
        self.assertEqual(args["path"], "{{ app_ansible_marker }}")
        self.assertEqual(
            app_defaults()["app_ansible_marker"], "/run/manuspectrum/ansible-running"
        )

    def test_the_marker_is_taken_before_the_update_guard_looks(self):
        names = [
            t["ansible.builtin.include_tasks"]
            for t in self.main_play()[0]["block"]
            if "ansible.builtin.include_tasks" in t
        ]
        self.assertLess(names.index("marker.yml"), names.index("update_guard.yml"))
        self.assertEqual(names.index("update_guard.yml"), 1)

    def test_the_marker_is_a_root_file_in_a_root_directory(self):
        tasks = load_tasks(APP / "tasks" / "marker.yml")
        directory = tasks[0]["ansible.builtin.file"]
        self.assertEqual(directory["path"], "{{ app_ansible_marker | dirname }}")
        self.assertEqual(
            (directory["state"], directory["owner"], directory["mode"]),
            ("directory", "root", "0755"),
        )
        marker = tasks[1]["ansible.builtin.file"]
        self.assertEqual(
            (marker["state"], marker["owner"], marker["group"], marker["mode"]),
            ("touch", "root", "root", "0644"),
        )
        self.assertEqual(marker["modification_time"], "now")

    def test_the_role_leaves_the_marker_to_a_play_that_holds_it(self):
        block = self.main_play()[0]
        taken = block["block"][0]
        self.assertEqual(
            taken["when"], "not (app_marker_outer | default(false) | bool)"
        )
        self.assertEqual(block["always"][0]["when"], taken["when"])
        guard = [
            t
            for t in block["block"]
            if t.get("ansible.builtin.include_tasks") == "update_guard.yml"
        ][0]
        self.assertNotIn("when", guard)

    def site_block(self):
        play = yaml.safe_load((ANSIBLE / "site.yml").read_text(encoding="utf-8"))
        self.assertEqual(len(play), 2)
        self.assertNotIn("roles", play[1])
        self.assertEqual(len(play[1]["tasks"]), 1)
        return play[1]["tasks"][0]

    def test_sudo_rs_hosts_use_the_classic_sudo(self):
        for name in ("site.yml", "audit.yml"):
            plays = yaml.safe_load((ANSIBLE / name).read_text(encoding="utf-8"))
            first, main = plays[0], plays[1] if len(plays) > 1 else None
            self.assertIs(first["become"], False, name)
            self.assertIs(first["gather_facts"], False, name)
            stat, fact = first["tasks"]
            self.assertEqual(stat["ansible.builtin.stat"]["path"], "/usr/bin/sudo.ws")
            self.assertEqual(
                fact["ansible.builtin.set_fact"], {"ansible_become_exe": "sudo.ws"}
            )
            for task in (stat, fact):
                self.assertIn("ansible_become_exe is not defined", task["when"])
                self.assertEqual(task["tags"], ["always"])
            self.assertIs(main["become"], True, name)

    def test_every_role_of_the_site_play_runs_under_the_marker(self):
        block = self.site_block()
        steps = block["block"]
        roles = [
            (
                t["ansible.builtin.import_role"]["name"],
                t["ansible.builtin.import_role"].get("tasks_from"),
            )
            for t in steps
            if "ansible.builtin.import_role" in t
        ]
        self.assertEqual(
            roles,
            [
                ("app", "marker"),
                ("app", "update_guard"),
                ("preflight", None),
                ("baseline", None),
                ("host", None),
                ("app", None),
            ],
        )
        self.assertEqual(
            steps[0]["ansible.builtin.set_fact"], {"app_marker_outer": True}
        )
        for step in steps[:3]:
            self.assertEqual(step["tags"], ["always"], step["name"])
        for step, tag in zip(steps[3:], ["preflight", "baseline", "host", "app"]):
            self.assertEqual(step["tags"], [tag], step["name"])

    def test_the_site_play_removes_the_marker_after_a_failure_too(self):
        always = self.site_block()["always"]
        self.assertEqual(len(always), 1)
        self.assertEqual(
            always[0]["ansible.builtin.import_role"],
            {"name": "app", "tasks_from": "marker_release"},
        )
        self.assertEqual(always[0]["tags"], ["always"])

    def test_the_read_only_audit_takes_no_marker(self):
        text = (ANSIBLE / "audit.yml").read_text(encoding="utf-8")
        self.assertNotIn("marker", text)
        self.assertNotIn("update_guard", text)

    def test_the_stack_starts_only_if_the_image_and_checkout_are_unchanged(self):
        start = load_tasks(APP / "tasks" / "start.yml")
        names = [t["name"] for t in start]
        self.assertEqual(start[0]["ansible.builtin.include_tasks"], "update_guard.yml")
        self.assertEqual(start[1]["ansible.builtin.include_tasks"], "source_state.yml")
        check = task_named(
            "app",
            "start.yml",
            "Assert nothing changed the image or the checkout during the run",
        )
        text = " ".join(strings(check))
        self.assertIn("app_current_image == app_seen_image", text)
        self.assertIn("app_current_commit == app_seen_commit", text)
        self.assertLess(
            names.index(check["name"]), names.index("Start or update the stack")
        )
        prepare = load_tasks(APP / "tasks" / "prepare.yml")
        self.assertEqual(
            prepare[-2]["ansible.builtin.include_tasks"], "source_state.yml"
        )
        seen = prepare[-1]["ansible.builtin.set_fact"]
        self.assertEqual(set(seen), {"app_seen_image", "app_seen_commit"})
        state = " ".join(strings(load_tasks(APP / "tasks" / "source_state.yml")))
        self.assertIn("rev-parse HEAD", state)
        self.assertIn("MANUSPECTRUM_IMAGE", state)


class CheckModeTests(unittest.TestCase):
    def test_a_group_created_in_the_same_run_is_not_read_in_check_mode(self):
        for name in (
            "Read the members of that group",
            "Remove the members who are no longer operators",
        ):
            task = task_named("app", "release.yml", name)
            self.assertEqual(task["when"], "not ansible_check_mode", name)


class TimezoneTests(unittest.TestCase):
    def test_baseline_sets_and_verifies_the_paris_time_zone(self):
        defaults = yaml.safe_load(
            (ROLES_DIR / "baseline" / "defaults" / "main.yml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(defaults["baseline_timezone"], "Europe/Paris")
        apply = task_named("baseline", "apply.yml", "Set the host time zone")
        self.assertEqual(
            apply["community.general.timezone"], {"name": "{{ baseline_timezone }}"}
        )
        names = [
            t["name"]
            for t in load_tasks(ROLES_DIR / "baseline" / "tasks" / "apply.yml")
        ]
        self.assertLess(
            names.index("Set the host time zone"),
            names.index("Configure unattended-upgrades"),
        )
        check = task_named("baseline", "verify.yml", "Assert the host time zone")
        self.assertIn("baseline_timezone", " ".join(strings(check)))
        self.assertTrue(check["register"].startswith("baseline_chk_"))


class ReadyWaitCapTests(unittest.TestCase):
    def assert_with(self, value):
        """Runs the inventory assertion of preflight with the given wait."""
        first = load_tasks(ROLES_DIR / "preflight" / "tasks" / "main.yml")[0]
        play = [
            {
                "hosts": "localhost",
                "gather_facts": False,
                "vars_files": [
                    str(ANSIBLE / "inventories" / "example" / "group_vars" / "all.yml")
                ],
                "tasks": [first],
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "play.yml"
            path.write_text(yaml.safe_dump(play), encoding="utf-8")
            return subprocess.run(
                [
                    str(Path(sys.executable).parent / "ansible-playbook"),
                    "-i",
                    "localhost,",
                    "-c",
                    "local",
                    "-e",
                    json.dumps({"env_release_ready_wait_seconds": value}),
                    str(path),
                ],
                cwd=ANSIBLE,
                env=dict(os.environ, ANSIBLE_HOME=tmp),
                capture_output=True,
                text=True,
                check=False,
            ).returncode

    def test_the_readiness_wait_is_digits_from_1_to_1800(self):
        self.assertEqual(self.assert_with("1800"), 0)
        self.assertEqual(self.assert_with("600"), 0)
        self.assertEqual(self.assert_with("1"), 0)
        self.assertNotEqual(self.assert_with("0"), 0)
        self.assertNotEqual(self.assert_with("00"), 0)
        self.assertNotEqual(self.assert_with("1801"), 0)
        self.assertNotEqual(self.assert_with("abc"), 0)


class ConditionalTests(unittest.TestCase):
    """A conditional that YAML parses as a mapping or a number is refused by Ansible."""

    CONDITIONAL_KEYS = ("when", "changed_when", "failed_when", "until", "that")

    def documents(self):
        files = [*ROLES_DIR.rglob("*.yml"), *ANSIBLE_DIR.glob("*.yml")]
        for path in sorted(files):
            yield path, yaml.safe_load(path.read_text(encoding="utf-8"))

    def conditionals(self, node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in self.CONDITIONAL_KEYS:
                    yield key, value
                yield from self.conditionals(value)
        elif isinstance(node, list):
            for item in node:
                yield from self.conditionals(item)

    def test_every_conditional_is_a_string_a_bool_or_a_list_of_strings(self):
        seen = 0
        for path, document in self.documents():
            for key, value in self.conditionals(document):
                items = value if isinstance(value, list) else [value]
                for item in items:
                    seen += 1
                    self.assertIsInstance(
                        item, (str, bool), f"{path.name}: {key}: {item!r}"
                    )
        self.assertGreater(seen, 100)

    def test_the_ufw_default_policy_regex_matches_what_ufw_prints(self):
        task = next(
            t
            for t in load_tasks(ROLES_DIR / "baseline" / "tasks" / "verify.yml")
            if t.get("name") == "Assert UFW is active with deny in and allow out"
        )
        condition = next(
            c for c in task["ansible.builtin.assert"]["that"] if "Default:" in c
        )
        pattern = re.search(r"'(\^Default:[^']*)'", condition).group(1)
        self.assertTrue(
            re.match(
                pattern,
                "Default: deny (incoming), allow (outgoing), deny (routed)",
            )
        )


if __name__ == "__main__":
    unittest.main()
