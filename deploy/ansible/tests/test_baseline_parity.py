"""Every check of the retired verify-baseline.sh has an assertion in the baseline role."""

import re
import unittest

from roles import ANSIBLE_DIR, ROLES_DIR, load_tasks, module_of

SCRIPT = ANSIBLE_DIR.parents[1] / "deploy" / "rehearsal" / "verify-baseline.sh"
VERIFY = ROLES_DIR / "baseline" / "tasks" / "verify.yml"

# verify-baseline.sh label -> name of the task of verify.yml that asserts it,
# or (None, reason) when no baseline assertion can hold it.
PARITY = {
    "sshd : PermitRootLogin no": "Assert root cannot log in over SSH",
    "sshd : PasswordAuthentication ${SSH_PASSWORD_AUTH}": "Assert the SSH password authentication setting",
    "ufw : actif, deny in / allow out": "Assert UFW is active with deny in and allow out",
    "ufw : limit 22/tcp": "Assert UFW rate-limits SSH",
    "ufw : allow 80/tcp": "Assert UFW allows HTTP",
    "ufw : allow 443/tcp": "Assert UFW allows HTTPS",
    "ufw: no other inbound rule": "Assert UFW has no other inbound rule",
    "fail2ban : jail sshd": "Assert the fail2ban sshd jail runs",
    "docker: server present": "Assert the Docker server answers",
    "docker: packages docker-ce, containerd.io, buildx and compose": "Assert the five Docker packages are installed",
    "docker: apt repository download.docker.com": "Assert the Docker apt repository is configured",
    "docker: compose plugin": "Assert the Docker Compose plugin answers",
    "docker: buildx plugin": "Assert the Docker Buildx plugin answers",
    "${ADMIN_USER} in the sudo group": "Assert the administrators are in the sudo group",
    "account ${ADMIN2_USER}": "Assert the administrator and service accounts exist",
    "${ADMIN2_USER} in the sudo group": "Assert the administrators are in the sudo group",
    "account manuspectrum": "Assert the administrator and service accounts exist",
    "manuspectrum in the docker group": "Assert only the service account is in the docker group",
    "${admin} not in the docker group": "Assert only the service account is in the docker group",
    "manuspectrum without sudo rights": "Assert the service account has no sudo rights",
    "manuspectrum without password (locked)": "Assert the service account password is locked",
    "SSH key of ${ADMIN2_USER}": "Assert the administrators' SSH keys are installed",
    "manuspectrum without authorized_keys": "Assert the service account has no authorized_keys",
    "/data mounted over NFS ${NFS_VERS}": "Assert the data directory is mounted as configured",
    "/data in /etc/fstab": "Assert the data mount is in fstab",
    "unattended-upgrades : Automatic-Reboot ${UNATTENDED_REBOOT}": "Assert the unattended-upgrades reboot settings",
    "unattended-upgrades: time ${UNATTENDED_REBOOT_TIME}": "Assert the unattended-upgrades reboot settings",
    "unattended-upgrades : Automatic-Reboot-WithUsers ${UNATTENDED_REBOOT}": "Assert the unattended-upgrades reboot settings",
    "unattended-upgrades : options Remove-*": "Assert the unattended-upgrades cleanup options",
    "unattended-upgrades: four origins": "Assert unattended-upgrades has its four origins",
    "20auto-upgrades: four APT::Periodic lines": "Assert the four APT::Periodic settings",
    "rehearsal host marker /etc/manuspectrum/rehearsal-host (root, 0644)": "Assert the rehearsal host marker",
    "postfix active": "Assert postfix is active",
    "postfix: relayhost": "Assert the postfix relay host",
    "/etc/docker/daemon.json absent (before Ansible)": (
        None,
        "holds only before Ansible; the host role writes daemon.json",
    ),
    "vm.max_map_count >= 262144 (after Ansible, value ${max_map})": "Assert vm.max_map_count suits Elasticsearch",
    "/etc/docker/daemon.json present (after Ansible)": (
        None,
        "daemon.json belongs to the host role, played after baseline",
    ),
}


def script_labels():
    text = SCRIPT.read_text(encoding="utf-8")
    return re.findall(r'^\s*check "([^"]*)"', text, flags=re.MULTILINE)


class BaselineParityTests(unittest.TestCase):
    def test_every_verify_baseline_check_has_an_assertion(self):
        names = {task["name"] for task in load_tasks(VERIFY)}
        if SCRIPT.exists():
            self.assertEqual(sorted(script_labels()), sorted(PARITY))
        for label, target in PARITY.items():
            if isinstance(target, tuple):
                self.assertIsNone(target[0], label)
                self.assertTrue(target[1], f"{label}: say why nothing asserts it")
            else:
                self.assertIn(target, names, label)

    def test_every_verify_task_is_a_read_or_an_assertion(self):
        allowed = {"assert", "command", "stat", "getent", "systemd_service", "debug"}
        for task in load_tasks(VERIFY):
            module = module_of(task)
            self.assertIn(module, allowed, task["name"])
            if module == "command":
                self.assertIs(task.get("changed_when"), False, task["name"])
                self.assertIs(task.get("check_mode"), False, task["name"])


if __name__ == "__main__":
    unittest.main()
