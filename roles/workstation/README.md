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
        - python3Packages.ipython
        - uv               # needed for uv: tools
        - nodejs_22        # needed for npm: tools
      environment:         # variables for the user's shells (not secret)
        EDITOR: vim
      tools:               # installed in the user's home after the switch
        - npm: "@anthropic-ai/claude-code"
        - uv: ruff
          version: "0.8.4"
```

The user needs at least one SSH key, or a password (below). The defaults are in [defaults/main.yml](defaults/main.yml).

- **`user`:** lowercase letters, digits, `_` and `-`, up to 32. Not `root`, `admin` or another account NixOS uses.
- **`ssh_key_files`:** paths to `.pub` files on the machine running Ansible, as for `NIXOS_DEPLOYMENT_PUBLIC_KEY`. Use a full path or one starting with `~`. Every key line in a file is added, so a file in `authorized_keys` format works too. The comment at the end of a key may only have letters, digits, spaces and `@ . _ + = : , / -`.
- **`sudo`:** `true` adds the user to `wheel`, which runs sudo without a password, as `admin` does.
- **`packages`:** nixpkgs attribute names, as shown on [search.nixos.org](https://search.nixos.org/packages). A name that doesn't exist stops the deploy when NixOS builds, before anything changes on the VM. These come from the VM's stable NixOS release, so fast-moving tools may be behind: install those with `tools` instead.
- **`environment`:** see [Environment variables](#environment-variables).
- **`tools`:** see [Tools](#tools).

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

## Tools

`settings.tools` installs software in the user's home, after the NixOS switch: npm packages, Python tools from PyPI with [uv](https://docs.astral.sh/uv/), and install scripts fetched with curl. Use it for tools that move faster than the NixOS release, such as Claude Code.

```yaml
      tools:
        - npm: "@anthropic-ai/claude-code"  # no version: the latest when installed
        - npm: typescript
          version: "5.6.3"                  # pinned
        - uv: ruff
          version: "0.8.4"
        - uv: llm
          with: [llm-anthropic==0.12]       # extra packages in llm's environment
          python: "3.12"                    # optional Python version for this tool
        - curl: https://example.com/install.sh
          creates: ~/.local/bin/example     # required: where the script puts the tool
```

| Kind | Installed with, as the user | Goes in | Takes |
|---|---|---|---|
| `npm` | `npm install --global` | `~/.npm-global` | `version` |
| `uv` | `uv tool install` | `~/.local/share/uv/tools`, commands in `~/.local/bin` | `version`, `with`, `python` |
| `curl` | `bash <script>`, downloaded over HTTPS | wherever the script puts it | `creates` |

The user doesn't need `sudo`: the deploy runs the installs as the user, from the `admin` account. `~/.local/bin` and `~/.npm-global/bin` are put on the user's `PATH`.

Each kind's package manager must be in `packages`, or the deploy stops before anything changes:

| Kind | Needs in `packages` | Accepted |
|---|---|---|
| `npm` | Node.js | `nodejs` or `nodejs_<version>`, such as `nodejs_22`. Not `nodejs-slim_*`, which has no npm. |
| `uv` | uv | `uv`, or `python3<version>Packages.uv`. Use `uv`: the other is the Python library copy, tied to one Python. |
| `curl` | nothing | curl is always installed. |

The deploy never adds or removes them, so they're there for your own use too (`uv venv`, `uv run`, `npx`), with or without tools listed.

- **`with`:** more PyPI packages installed in the tool's own environment, such as plugins the tool imports. Their commands aren't put on `PATH`; list a package as its own tool for that. Entries can be pinned, like `llm-anthropic==0.12`.
- **`python`:** the Python version for a uv tool, such as `"3.12"`. uv uses its own Pythons rather than the system one, so a tool keeps working after a NixOS upgrade. Set `UV_PYTHON_PREFERENCE` in `environment` to change that.
- **`creates`:** a path in the user's home, starting with `~/`. The deploy runs the script only while it's missing, and fails if the script doesn't make it.

Names are checked before anything changes, and every command runs without a shell, so a name can't run anything else.

### Versions

`version` is one exact version, quoted, such as `"5.6.3"`. Ranges aren't allowed, so the deploy can check the installed version against it.

| `version` | First deploy | Later deploys | With `-e workstation_upgrade=true` |
|---|---|---|---|
| Not set | The latest | Left as it is | Upgraded to the latest |
| Set | That version | Put back on that version if it changed | Not changed: edit `version` |

Each deploy prints every tool's version. A curl tool is installed once; `-e workstation_upgrade=true` runs its script again.

A tool that updates itself, such as Claude Code, stays up to date between deploys when it isn't pinned. If you pin one, turn its updater off too (for Claude Code, `DISABLE_AUTOUPDATER: "1"` in `environment`), or every deploy puts the pin back.

### Removing a tool

Take it out of the list and redeploy. npm and uv tools are uninstalled, but only ones the deploy installed: it keeps a list in `~/.local/state/nixlab/tools.json`. Tools the user installed by hand are left alone. A curl tool's files stay, since the deploy doesn't know what the script wrote; delete them by hand.

To drop a package manager as well, remove its tools and deploy first, then remove it from `packages` and deploy again. Removing both at once takes the package manager away before the tools can be uninstalled: the deploy reports them as left in place, and their commands keep working unmanaged.

### nix-ld

NixOS can't run prebuilt Linux programs on its own. The workstation turns on [nix-ld](https://github.com/nix-community/nix-ld), so Python wheels with compiled code, the Pythons uv downloads, and native installers work. If a tool fails with a missing `.so` file, add the library to `programs.nix-ld.libraries` in [files/configuration.nix](files/configuration.nix).

## Environment variables

Variables for the user's shells, SSH commands (`ssh dev@ws env`) and VS Code Remote-SSH:

- **Not secret:** `settings.environment` in the network file.

  ```yaml
      environment:
        EDITOR: vim
        DISABLE_AUTOUPDATER: "1"
  ```

- **Secret:** `WORKSTATION_ENV_<NAME>` lines in `secrets/<network>/<host>.env`, which set `<NAME>`. See [env.example](env.example).

  ```bash
  WORKSTATION_ENV_ANTHROPIC_API_KEY='sk-ant-...'
  ```

The deploy writes both to `~/.config/nixlab/env`, readable by the user alone, and every shell loads it. Secrets stay out of the Nix store, which everyone on the VM can read, and out of Ansible's output. The tool installs see the same variables, so a registry token there also works while installing.

The file is rewritten on every deploy. The user keeps variables of their own in `~/.bashrc`.

Names are letters, digits and `_`. `PATH`, `HOME`, `USER`, `LOGNAME`, `SHELL`, `NPM_CONFIG_PREFIX` and names starting with `LD_` or `NIX_` can't be set. A name can't be in both `environment` and the secrets file.

## Password

A password is optional. It's for logging in on the Proxmox console; SSH only takes keys. To set one, copy [env.example](env.example) to `secrets/<network>/<host>.env`, such as `secrets/lab/ws.env`, and put the password's hash in it, not the password. The same file holds [secret environment variables](#environment-variables).

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

1. Checks the settings, tools, environment variables and the password hash before anything changes.
2. Installs the password hash, if there is one, and the user account in `workstation.nix`, then switches.
3. Checks the user is in `wheel` only if `sudo` is `true`.
4. Writes the user's environment variables, then installs, pins, upgrades or removes their tools, and prints their versions.
5. Checks a login shell sees the variables and `PATH`.
6. Checks SSH answers, and prints how to log in.

To upgrade the unpinned tools as well:

```bash
ansible-playbook playbooks/deploy-host.yaml -e network=lab -e host=ws -e workstation_upgrade=true
```

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

- **Keys, sudo, packages, environment, tools:** change them under `settings:`. A changed key file is picked up on the next deploy.
- **The user's name:** changing `user` makes a new account. The old one is removed, but its home folder stays in `/home`.
- **Address or network:** change `ip`, or move the entry to another network file, and redeploy. See [Moving a VM between networks](../../README.md#moving-a-vm-between-networks).

## Files

| File | Purpose |
|---|---|
| `files/configuration.nix` | NixOS configuration: fixed accounts, key-only SSH, shared tools, nix-ld, loading the env file |
| `templates/workstation.nix.j2` | Generated user account: name, keys, sudo, password file, packages |
| `env.example` | Template for the optional secrets file: password hash and secret variables |
| `tasks/` | `prepare.yml` (settings, tools, variables, password), `configure.yml` (password, account, switch), `tools.yml` and `tools-installed.yml` (env file, tools), `verify.yml`, `ports.yml` |
| [plugins/filter/workstation.py](../../plugins/filter/workstation.py) | Checks for `tools` and `environment`, the env file, and what to install, upgrade or remove. Tested in [tests/test_workstation.py](../../tests/test_workstation.py). |

## Removing it

```bash
ansible-playbook playbooks/destroy-host.yaml -e network=lab -e host=ws
```

This permanently deletes the VM and its disk, including the user's home folder and the tools in it. It asks you to type the host name. Remove the entry from the network file too, or the next deploy creates it again.
