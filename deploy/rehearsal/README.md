# VM de répétition

Ce kit construit, sur le portable (Linux, libvirt + virt-manager), une VM qui a la
même forme que la VM de production : Ubuntu 26.04, BIOS, disque partitionné en
`/boot` + LVM (`vg0`, volumes `root` et `swap`), réseau dédié, `/data` en NFS et
la même baseline système. On y répète le déploiement (PP-8, Ansible) avant la
production, et l'on revient à zéro en une commande.

Rien ici ne tourne sur la VM de dev.

## 0. Ce que la VM reproduit, et ce qu'elle ne reproduit pas

Ce dépôt est public : il décrit des mécanismes, jamais les valeurs de la production.
Les valeurs de la VM de production (ressources, taille du volume racine, locale,
clavier, options NFS et version, réglages SSH, heure de redémarrage automatique,
noms de comptes…) se mettent dans `rehearsal.env`, un fichier local ignoré par
Git : `cp rehearsal.env.example rehearsal.env`, puis on y met les valeurs réelles.
Sans ce fichier, le kit utilise des valeurs génériques et la VM ne colle pas à la
production.

| Point | Reproduit |
| --- | --- |
| Ubuntu 26.04.1, BIOS, table `msdos`, `/boot` ext4 + LVM `vg0` (`root`, `swap`) | oui |
| SSH : `PermitRootLogin no` ; `PasswordAuthentication` selon `rehearsal.env` | oui |
| UFW : deny en entrée, allow en sortie, `limit 22/tcp`, `allow 80/tcp`, `allow 443/tcp` | oui |
| fail2ban, jail `sshd` | oui |
| Docker CE + plugins buildx et compose (dépôt apt officiel), premier admin dans `docker` | oui |
| Deuxième admin (sudo) et compte de service `manuspectrum` (sans mot de passe, sans clé) | oui |
| `/data` en NFS, options et version selon `rehearsal.env` | oui |
| unattended-upgrades et postfix | oui |
| `vm.max_map_count` et `/etc/docker/daemon.json` | non : travail d'Ansible |
| Ce qui se trouve devant la VM en production (pare-feu, sauvegarde, instantanés du stockage) | non |

Réflexe utile : mesurer un sous-dossier de `/data` plutôt que `/data` entier.

## 1. Prérequis du portable

- [ ] Paquets. Debian/Ubuntu : `sudo apt install qemu-kvm libvirt-daemon-system virtinst virt-manager libvirt-clients qemu-utils cloud-image-utils whois nfs-kernel-server libosinfo-bin libxml2-utils`. Fedora : `sudo dnf install @virtualization virt-install libvirt-client qemu-img cloud-utils mkpasswd nfs-utils libosinfo libxml2`.
- [ ] Accès à libvirt : `virsh -c qemu:///system uri` répond `qemu:///system`. Sinon : `sudo usermod -aG libvirt $USER`, puis se reconnecter. Pour la suite, `export LIBVIRT_DEFAULT_URI=qemu:///system` évite de répéter `-c qemu:///system` dans les commandes `virsh`.
- [ ] Mémoire : la VM prend les ressources fixées dans `rehearsal.env` ; sur un portable plus petit, passer `VCPUS=… RAM_MB=…` au lancement de `make-vm.sh`.
- [ ] Arrêter la VM de dev pendant les tests lourds : `virsh -c qemu:///system shutdown <nom-de-la-vm-de-dev>`.
- [ ] Créer votre fichier de valeurs : `cp rehearsal.env.example rehearsal.env`, puis y mettre les valeurs réelles de la prod. Le fichier est ignoré par Git.
- [ ] ISO `ubuntu-26.04.1-live-server-amd64.iso` et `SHA256SUMS` depuis <https://releases.ubuntu.com/26.04.1/>, dans le même dossier, lisibles par le service libvirt : un dossier personnel ne l'est en général pas, donc les copier dans `/var/lib/libvirt/images/`. `make-vm.sh` vérifie la somme de l'ISO et sa lisibilité.
- [ ] Une clé SSH existe : `~/.ssh/id_ed25519.pub` (sinon `SSH_PUBKEY=…`).

## 2. Réseau et NFS

- [ ] `sudo ./host-network.sh` : le réseau libvirt `ms-rehearsal` (192.168.123.0/24) est actif. Le réseau `default` n'est jamais modifié.
- [ ] `sudo ./host-nfs.sh` : `/srv/ms-rehearsal-data` est exporté vers la seule VM (192.168.123.10/32), avec `NFS_EXPORT_OPTIONS` de `rehearsal.env`. Avec firewalld (Fedora, openSUSE…), le script ouvre `nfs` dans la zone `libvirt` et le dit ; sans cela `/data` ne monte pas. Avec ufw actif sur le portable, autoriser NFS depuis 192.168.123.0/24 (le script le rappelle).

## 3. Installer la VM

- [ ] `ISO=/chemin/ubuntu-26.04.1-live-server-amd64.iso ./make-vm.sh` (10 à 15 minutes). Le script demande le mot de passe du compte administrateur deux fois ; seul son hash SHA-512 est écrit, dans un dossier temporaire supprimé ensuite.
- [ ] Résultat attendu : la VM répond en SSH sur 192.168.123.10 et le snapshot `installed` existe (`virsh -c qemu:///system snapshot-list ms-rehearsal`).
- [ ] Pour voir ce que le script ferait sans rien créer : `DRY_RUN=1 ISO=… ./make-vm.sh`.
- [ ] Si l'installeur échoue, `virt-install` attend sans fin : suivre l'installation avec `virsh -c qemu:///system console ms-rehearsal`.
- [ ] Si la VM existe déjà, le script refuse ; pour repartir : `virsh -c qemu:///system undefine --remove-all-storage --snapshots-metadata ms-rehearsal`.

## 4. Baseline

- [ ] `scp host-baseline.sh verify-baseline.sh rehearsal.env <admin>@192.168.123.10:` (`<admin>` = `ADMIN_USER` de votre `rehearsal.env`). Après une reconstruction de la VM : `ssh-keygen -R 192.168.123.10`.
- [ ] `ssh -t <admin>@192.168.123.10 'sudo ./host-baseline.sh && sudo ./verify-baseline.sh'` : chaque ligne de `verify-baseline.sh` commence par `OK`, code de sortie 0. Le script est relançable ; ce qui est en place est signalé « déjà fait ».
- [ ] Si le dépôt Docker n'a pas encore la suite d'Ubuntu 26.04, le script s'arrête et propose `DOCKER_APT_CODENAME=noble` dans `rehearsal.env` ; il ne replie jamais en silence. Notez la suite réellement utilisée en prod.
- [ ] Éteindre la VM (`virsh -c qemu:///system shutdown ms-rehearsal`) puis `virsh -c qemu:///system snapshot-create-as ms-rehearsal baseline` : point de départ de toute répétition, équivalent de la VM telle que livrée. Redémarrer : `virsh -c qemu:///system start ms-rehearsal`.

Avant Ansible, `verify-baseline.sh` affiche `vm.max_map_count` sans le contrôler et exige l'absence de `/etc/docker/daemon.json`. `verify-baseline.sh --after-ansible` exige `vm.max_map_count` ≥ 262144 et la présence de `/etc/docker/daemon.json`.

## 5. Nom de la VM sur le portable

- [ ] Ajouter dans `/etc/hosts` : `192.168.123.10 manuspectrum.test`. `ping -c1 manuspectrum.test` répond.

## 6. Revenir à zéro

- [ ] `virsh -c qemu:///system snapshot-revert ms-rehearsal baseline` (ou `installed` pour rejouer la baseline).

## 7. Tout supprimer

- [ ] `virsh -c qemu:///system destroy ms-rehearsal`
- [ ] `virsh -c qemu:///system undefine --remove-all-storage --snapshots-metadata ms-rehearsal`
- [ ] `sudo ./host-nfs.sh --remove`
- [ ] `virsh -c qemu:///system net-destroy ms-rehearsal && virsh -c qemu:///system net-undefine ms-rehearsal`

## 8. Ce qui vient ensuite

PP-8 : Ansible, lancé depuis le portable sur cette VM. `/data` y est en NFS selon
les options de `rehearsal.env`.

## Contrôles

`bash check.sh` : shellcheck, tests de rendu du seed, validation du seed contre le
schéma autoinstall de subiquity (épinglé), XML du réseau, gitleaks.

## Ce qui ne va jamais dans Git

Dépôt public : aucun nom de compte personnel, uid, adresse IP interne, adresse e-mail,
mot de passe, clé privée, ni réglage décrivant la production. Toutes les valeurs
propres à la production vivent dans `deploy/rehearsal/rehearsal.env`
(ignoré par Git) ; seul `rehearsal.env.example`, aux valeurs génériques, est versionné.
gitleaks tourne dans `check.sh` et en hook `pre-commit`.
