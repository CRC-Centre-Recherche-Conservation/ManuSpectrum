"""Every check of the retired verify-baseline.sh has an assertion in the baseline role."""

import unittest

from roles import ROLES_DIR, load_tasks, module_of

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


# The 37 labels of the checks of the retired verify-baseline.sh, frozen here:
# the script is gone, so PARITY may not lose an entry unnoticed.
RETIRED_LABELS = [
    "${ADMIN2_USER} in the sudo group",
    "${admin} not in the docker group",
    "${ADMIN_USER} in the sudo group",
    "20auto-upgrades: four APT::Periodic lines",
    "account ${ADMIN2_USER}",
    "account manuspectrum",
    "/data in /etc/fstab",
    "/data mounted over NFS ${NFS_VERS}",
    "docker: apt repository download.docker.com",
    "docker: buildx plugin",
    "docker: compose plugin",
    "docker: packages docker-ce, containerd.io, buildx and compose",
    "docker: server present",
    "/etc/docker/daemon.json absent (before Ansible)",
    "/etc/docker/daemon.json present (after Ansible)",
    "fail2ban : jail sshd",
    "manuspectrum in the docker group",
    "manuspectrum without authorized_keys",
    "manuspectrum without password (locked)",
    "manuspectrum without sudo rights",
    "postfix active",
    "postfix: relayhost",
    "rehearsal host marker /etc/manuspectrum/rehearsal-host (root, 0644)",
    "sshd : PasswordAuthentication ${SSH_PASSWORD_AUTH}",
    "sshd : PermitRootLogin no",
    "SSH key of ${ADMIN2_USER}",
    "ufw : actif, deny in / allow out",
    "ufw : allow 443/tcp",
    "ufw : allow 80/tcp",
    "ufw : limit 22/tcp",
    "ufw: no other inbound rule",
    "unattended-upgrades : Automatic-Reboot ${UNATTENDED_REBOOT}",
    "unattended-upgrades : Automatic-Reboot-WithUsers ${UNATTENDED_REBOOT}",
    "unattended-upgrades: four origins",
    "unattended-upgrades : options Remove-*",
    "unattended-upgrades: time ${UNATTENDED_REBOOT_TIME}",
    "vm.max_map_count >= 262144 (after Ansible, value ${max_map})",
]


class BaselineParityTests(unittest.TestCase):
    def test_every_verify_baseline_check_has_an_assertion(self):
        names = {task["name"] for task in load_tasks(VERIFY)}
        self.assertEqual(sorted(RETIRED_LABELS), sorted(PARITY))
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
