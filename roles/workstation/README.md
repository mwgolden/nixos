# Workstation

A headless NixOS VM to log in to over SSH, with one non-root user account. Use it as a place to work inside a network, or as a target for VS Code Remote-SSH. The `admin` account that deploys use stays as it is.

```yaml
hosts:
  - name: ws
    type: workstation
    vm_id: 119
    ip: 10.1.0.19
    settings:
      user: dev            # the login name; the default
      ssh_key_files:       # the user's public key files
        - ~/.ssh/id_ed25519.pub
      sudo: false          # true lets the user run anything as root
      packages:            # extra nixpkgs packages for the user
        - nodejs_22
        - python3Packages.ipython
```

The user needs at least one SSH key, or a password (below). The defaults are in [defaults/main.yml](defaults/main.yml).

- **`user`:** lowercase letters, digits, `_` and `-`, up to 32. Not `root`, `admin` or another account NixOS uses.
- **`ssh_key_files`:** paths to `.pub` files on the machine running Ansible, as for `NIXOS_DEPLOYMENT_PUBLIC_KEY`. Use a full path or one starting with `~`. Every key line in a file is added, so a file in `authorized_keys` format works too. The comment at the end of a key may only have letters, digits, spaces and `@ . _ + = : , / -`.
- **`sudo`:** `true` adds the user to `wheel`, which runs sudo without a password, as `admin` does.
- **`packages`:** nixpkgs attribute names, as shown on [search.nixos.org](https://search.nixos.org/packages). A name that doesn't exist stops the deploy when NixOS builds, before anything changes on the VM.

Every user on the VM also gets curl, wget, vim, tmux, htop, jq, ripgrep, tree and unzip, along with git and python3 from `common.nix`. Change that list in [files/configuration.nix](files/configuration.nix).

## SSH key

If you don't have a key pair yet, make one on the machine you'll log in from:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -C "you@laptop"
```

It asks for a passphrase, which protects the private key if the file is ever copied. This writes two files:

- `~/.ssh/id_ed25519`: the private key. It stays on your machine. Never put it in the repository or a network file.
- `~/.ssh/id_ed25519.pub`: the public key. List this one under `ssh_key_files`.

The `-C` comment is only a label to tell keys apart. It may only have letters, digits, spaces and `@ . _ + = : , / -`.

If you log in from a different machine than the one running Ansible, copy that machine's `.pub` file to the Ansible machine and point `ssh_key_files` at the copy. To log in with a key that isn't `~/.ssh/id_ed25519`, pass it with `ssh -i ~/.ssh/<name> dev@<ip>`, or add it to `~/.ssh/config`.

## Password

A password is optional. It's for logging in on the Proxmox console; SSH only takes keys. To set one, copy [env.example](env.example) to `secrets/<network>/<host>.env`, such as `secrets/lab/ws.env`, and put the password's hash in it, not the password:

```bash
echo "WORKSTATION_PASSWORD_HASH='$(openssl passwd -6)'" > secrets/lab/ws.env
```

The hash is written to `/etc/workstation/password.hash` on the VM, readable only by root, and stays out of the Nix store and Ansible's output. Without the file, the user has no password.

Accounts come only from the configuration (`users.mutableUsers = false`), so a change to the password, keys or `sudo` takes effect on the next deploy. It also means the user can't change their own password with `passwd`: change the hash and redeploy.

## Deploying

```bash
source proxmox/.env
ansible-playbook playbooks/deploy-host.yaml -e network=lab -e host=ws
```

Besides the steps every host goes through, the deploy:

1. Checks the settings and the password hash before anything changes.
2. Installs the password hash, if there is one, and the user account in `workstation.nix`, then switches.
3. Checks the user is in `wheel` only if `sudo` is `true`.
4. Checks SSH answers, and prints how to log in.

## Logging in

On a home network: `ssh dev@<ip>`.

On an isolated network, its VMs and VPN clients use `ssh dev@ws.lab.home.arpa`. From home, use the network's [VPN](../router/README.md#vpn), or forward SSH through the router. TCP 22 on the router is its own SSH, so pick another port:

```yaml
    expose:
      - port: 22
        wan_port: 2222
```

Redeploy the router, then `ssh -p 2222 dev@192.168.1.13`.

The VM listens on nothing but SSH. To use a service you run on it, forward the port over SSH, such as `ssh -L 8000:127.0.0.1:8000 dev@<ip>`.

## Making changes

Edit the host's entry or the files here and redeploy. An existing VM is updated in place, and the user's home folder is kept.

- **Keys, sudo, packages:** change them under `settings:`. A changed key file is picked up on the next deploy.
- **The user's name:** changing `user` makes a new account. The old one is removed, but its home folder stays in `/home`.
- **Address or network:** change `ip`, or move the entry to another network file, and redeploy. See [Moving a VM between networks](../../README.md#moving-a-vm-between-networks).

## Files

| File | Purpose |
|---|---|
| `files/configuration.nix` | NixOS configuration: fixed accounts, key-only SSH, shared tools |
| `templates/workstation.nix.j2` | Generated user account: name, keys, sudo, password file, packages |
| `env.example` | Template for the optional password's secrets file |
| `tasks/` | `prepare.yml` (settings, password), `configure.yml` (password, account, switch), `verify.yml`, `ports.yml` |

## Removing it

```bash
ansible-playbook playbooks/destroy-host.yaml -e network=lab -e host=ws
```

This permanently deletes the VM and its disk, including the user's home folder. It asks you to type the host name. Remove the entry from the network file too, or the next deploy creates it again.
