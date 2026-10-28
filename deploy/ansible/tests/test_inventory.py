"""The example inventory holds fake values only and every variable of the playbooks."""

import ipaddress
import re
import subprocess
import unittest
from pathlib import Path

import yaml

ANSIBLE_DIR = Path(__file__).resolve().parents[1]
REPO = ANSIBLE_DIR.parents[1]
EXAMPLE = ANSIBLE_DIR / "inventories" / "example"
ENV_EXAMPLE = REPO / "deploy" / "compose" / ".env.example"

DOCUMENTATION_NETWORKS = [
    ipaddress.ip_network(n)
    for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")
]
SPEC_VARIABLES = [
    "baseline_mode",
    "rehearsal_host",
    "min_ram_gb",
    "min_cpus",
    "min_free_root_gb",
    "min_free_data_gb",
    "supported_os",
    "docker_min_version",
    "admin_users",
    "service_user",
    "ssh_password_authentication",
    "docker_apt_codename",
    "data_mount",
    "unattended_reboot",
    "unattended_reboot_time",
    "smtp_relay",
    "root_alias",
    "app_dir",
    "app_git_url",
    "app_git_ref",
    "data_dir",
    "release_operators",
]
READ_FROM_THE_HOST = {"APP_UID", "APP_GID"}


def example_text():
    return "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(EXAMPLE.rglob("*.yml"))
    )


def env_example_keys():
    keys = []
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]*)=", line)
        if match and match.group(1) not in READ_FROM_THE_HOST:
            keys.append(match.group(1))
    return keys


class ExampleInventoryTests(unittest.TestCase):
    def test_example_holds_no_real_value(self):
        text = example_text()
        for found in re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", text):
            address = ipaddress.ip_address(found)
            self.assertTrue(
                any(address in net for net in DOCUMENTATION_NETWORKS),
                f"{found} is outside the documentation ranges",
            )
        hosts = set(re.findall(r"https?://([A-Za-z0-9.-]+)", text))
        hosts |= set(re.findall(r"@([A-Za-z0-9.-]+\.[A-Za-z]{2,})", text))
        hosts |= set(
            re.findall(
                r"\b([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.(?:com|org|net|fr|io|eu|edu|info|gov|dev|app))\b",
                text,
            )
        )
        for host in hosts:
            self.assertRegex(host, r"\.(example|test)$", f"{host} is a real domain")
        for blob in re.findall(r"ssh-[a-z0-9-]+ (\S+)", text):
            self.assertTrue(
                blob.startswith("AAAAexample") and len(blob) < 40,
                f"public key {blob[:20]}... is not a placeholder",
            )
        self.assertNotIn("BEGIN", text)

    def test_every_spec_variable_is_in_the_example(self):
        variables = yaml.safe_load(
            (EXAMPLE / "group_vars" / "all.yml").read_text(encoding="utf-8")
        )
        expected = SPEC_VARIABLES + [f"env_{k.lower()}" for k in env_example_keys()]
        missing = [name for name in expected if name not in variables]
        self.assertEqual(missing, [])
        self.assertEqual(
            set(variables["data_mount"]), {"type", "path", "src", "opts", "nfs_version"}
        )
        for user in variables["admin_users"]:
            self.assertEqual(set(user), {"name", "pubkey"})

    def test_the_release_variables_hold_a_valid_value(self):
        variables = yaml.safe_load(
            (EXAMPLE / "group_vars" / "all.yml").read_text(encoding="utf-8")
        )
        self.assertIn(variables["env_release_channel"], ("prod", "rc"))
        self.assertTrue(str(variables["env_release_ready_wait_seconds"]).isdigit())
        admins = {u["name"] for u in variables["admin_users"]}
        self.assertTrue(set(variables["release_operators"]) <= admins)
        self.assertNotIn(variables["service_user"], variables["release_operators"])
        preflight = (
            ANSIBLE_DIR / "roles" / "preflight" / "tasks" / "main.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("env_release_channel in ['prod', 'rc']", preflight)

    def test_the_example_installs_a_release_tag_and_a_digest(self):
        variables = yaml.safe_load(
            (EXAMPLE / "group_vars" / "all.yml").read_text(encoding="utf-8")
        )
        self.assertRegex(
            variables["app_git_ref"], r"^v[0-9A-Z]+\.[0-9A-Z]+\.[0-9A-Z]+$"
        )
        self.assertRegex(
            variables["env_manuspectrum_image"], r"^[a-z0-9./-]+@sha256:[0-9a-f]{64}$"
        )

    def test_real_inventories_are_ignored(self):
        def ignored(path):
            return (
                subprocess.run(
                    ["git", "check-ignore", "-q", path], cwd=REPO, check=False
                ).returncode
                == 0
            )

        self.assertTrue(ignored("deploy/ansible/inventories/prod/hosts.yml"))
        self.assertFalse(ignored("deploy/ansible/inventories/example/hosts.yml"))
        self.assertFalse(
            ignored("deploy/ansible/inventories/example/group_vars/all.yml")
        )


if __name__ == "__main__":
    unittest.main()
