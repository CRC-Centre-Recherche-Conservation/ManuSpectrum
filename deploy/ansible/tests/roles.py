"""Helpers to read the tasks of the roles: names, modules and keywords."""

from pathlib import Path

import yaml

ANSIBLE_DIR = Path(__file__).resolve().parents[1]
ROLES_DIR = ANSIBLE_DIR / "roles"

KEYWORDS = {
    "name",
    "when",
    "register",
    "changed_when",
    "failed_when",
    "check_mode",
    "become",
    "become_user",
    "loop",
    "loop_control",
    "with_items",
    "vars",
    "tags",
    "notify",
    "listen",
    "delegate_to",
    "run_once",
    "ignore_errors",
    "no_log",
    "environment",
    "retries",
    "delay",
    "until",
    "args",
    "block",
    "rescue",
    "always",
    "diff",
    "throttle",
    "timeout",
    "any_errors_fatal",
    "ignore_unreachable",
}


def short(module):
    return module.removeprefix("ansible.builtin.")


def flatten(tasks):
    """Every task, with the tasks of `block`, `rescue` and `always` inlined."""
    for task in tasks or []:
        if "block" in task:
            for key in ("block", "rescue", "always"):
                yield from flatten(task.get(key))
        else:
            yield task


def module_of(task):
    for key in task:
        if key not in KEYWORDS:
            return short(key)
    raise AssertionError(f"no module in task {task.get('name')!r}")


def task_files(role, subdir="tasks"):
    return sorted((ROLES_DIR / role / subdir).glob("*.yml"))


def load_tasks(path):
    with open(path, encoding="utf-8") as handle:
        return list(flatten(yaml.safe_load(handle)))


def role_tasks(role):
    """(file name, task) for every task file of a role."""
    return [(f.name, t) for f in task_files(role) for t in load_tasks(f)]


def all_tasks():
    """(role, file name, task) for every task under roles/."""
    return [
        (role.name, name, task)
        for role in sorted(ROLES_DIR.iterdir())
        if role.is_dir()
        for name, task in role_tasks(role.name)
    ]
