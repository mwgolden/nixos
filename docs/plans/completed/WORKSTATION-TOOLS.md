# Plan: user tools and environment variables on workstations

Today a workstation's user gets software only from `settings.packages`, which resolves against the VM's stable nixpkgs channel. Fast-moving tools, such as Claude Code or Python CLIs from PyPI, are often behind there or missing. This plan adds:

- **`settings.tools`**: tools installed into the user's home after the NixOS switch, with **uv** (from PyPI), **npm**, or an install script fetched with **curl**.
- **`settings.environment`**, plus secret variables in the host's secrets file: environment variables for the user's shells, SSH commands and VS Code Remote-SSH.

None of this needs the user to have `sudo`.

## Progress

**Done (2026-11-13).** Phases 1–4 were built on 2026-11-11, and `home.ws` was deployed with tools and variables. The decisions in section 3 were taken as recommended, except decision 2, which was reversed (see below).

Found in the live deploy, and fixed:

- **The login-shell check failed on a VM that was fine.** Ansible's `command` module replaces `$VARS` in its arguments with the deploy's own values by default, so the check's `$PATH` was the deploy's, not the user's. Every `command` task in the role now sets `expand_argument_vars: false`. The check also starts from `env -i`, like a new SSH session, and compares values, because NixOS sets `EDITOR` itself.
- **Claude Code wouldn't start:** "this CPU is missing SSE4.2 support". The VMs use Proxmox's default CPU type, `kvm64`. That is outside this plan: see [CPU-TYPE.md](CPU-TYPE.md).
- **Decision 2 was reversed**, as described below.

Known gap, left as it is: a tool removed in the same deploy as its package manager is reported as left in place, and then dropped from the install record. Later deploys don't uninstall it, even once the package manager is back. The README says to remove the tools first, deploy, then remove the package manager.

Checked without Proxmox:

- 40 new unit tests in [tests/test_workstation.py](../../../tests/test_workstation.py) pass. They cover the checks, env file quoting (sourced by a real bash), and every row of the "Versions" table. The full suite has the one failure it had before (`Examples`, `networks/examples/test.yaml` overlapping `workstation-lab`).
- `--syntax-check` passes on every playbook.
- `prepare.yml` and the planning filters ran on localhost with a fake host. Secret variables are read, the env file comes out as expected, and a bad tool, version or variable name stops with a readable message.
- The workstation's `configuration.nix` was evaluated in the `nixos-lab` container against the pinned nixpkgs. `acl` and nix-ld are in, and the env-file snippet lands in `/etc/set-environment`. NixOS's bash is built with `SSH_SOURCE_BASHRC`, and its `/etc/bashrc` sources `/etc/profile`, so `ssh host command` should load the file. Phase 5 still has to confirm that live.

Differences from the plan below:

- **uv uses its own Pythons** (`UV_PYTHON_PREFERENCE=only-managed`, a default in the env file that `environment` can override), not the system `python3`. A uv tool's environment points at the Python it was made with. With the system Python, that is a store path a NixOS upgrade can replace, which would break the tool. uv's Pythons run through nix-ld.
- **Commands run through a wrapper** that sources the env file, then runs the command (`bash -c '. env; exec "$@"'`). Secret variables never appear in Ansible task arguments, so install tasks don't need `no_log` and their errors stay readable.
- **The pin and environment checks are at the end of `tools.yml`, not in `verify.yml`.** They have to run on the VM as the user, and `verify.yml` runs on localhost. The environment check starts a login shell (`bash -l`) and reports missing names, never values.
- **A pinned npm tool at the wrong version** is fixed with `npm install --global <name>@<version>`, which replaces it. uv uses `uv tool install --reinstall`.
- **Package managers must be listed in `packages`** (changed 2026-11-13; decision 2 reversed). At first, `nodejs_22` and `uv` were added automatically while a tool of that kind was listed. That took uv away from users who use it themselves, whenever they had no uv tools. It also removed it in the same deploy as the last tool, so that tool couldn't be uninstalled. Now an `npm` tool needs `nodejs` or `nodejs_<version>` in `packages`, and a `uv` tool needs `uv` (or `python3<version>Packages.uv`). Otherwise the deploy stops before anything changes. The deploy never adds or removes them.
- **A removed npm or uv tool whose package manager is gone** (removed from `packages` in the same edit) is reported and left in place, not uninstalled. The README says to remove the tools first, deploy, then remove the package manager.
- **No new file in `networks/examples/`.** The role README has the examples instead, so `test.yaml` stays as it is.



## 1. Target

```yaml
- name: ws
  type: workstation
  vm_id: 120
  ip: 10.1.0.10
  settings:
    user: dev
    ssh_key_files: [~/.ssh/ws_lab.pub]
    sudo: false
    packages: [python3Packages.ipython]   # from nixpkgs, as today
    environment:                          # not secret: stored in the network file
      EDITOR: vim
      DISABLE_TELEMETRY: "1"
    tools:
      - npm: "@anthropic-ai/claude-code"  # no version: the latest when installed
      - npm: typescript
        version: 5.6.3                    # pinned
      - uv: ruff
        version: 0.8.4                    # pinned
      - uv: llm                           # latest
        with: [llm-anthropic==0.12]       # extra packages in the same environment
      - curl: https://example.com/install.sh
        creates: ~/.local/bin/example     # required: how the deploy knows it's installed
```

```sh
# secrets/lab/ws.env: secret variables, prefixed so they sit next to the password hash
WORKSTATION_PASSWORD_HASH='$6$...'
WORKSTATION_ENV_ANTHROPIC_API_KEY='sk-ant-...'
```

After a deploy, `ssh dev@ws.lab.home.arpa`, then `claude`, `ruff` and `llm` are on `PATH`, and `ANTHROPIC_API_KEY` and `EDITOR` are set. The same holds for `ssh dev@... claude --version` with no interactive shell, and for VS Code Remote-SSH terminals.

## 2. How it works

### Running as the user without sudo

The user's `sudo` setting doesn't matter. The deploy connects as `admin`, which is in `wheel`, and runs the install tasks with `become_user: <user>`. That is `sudo -u dev` from admin, so the user never needs sudo themselves. Everything installs under the user's home:

| Kind | Command, run as the user | Installs to | On `PATH` from |
|---|---|---|---|
| `npm` | `npm install -g <name>[@<version>]` with `NPM_CONFIG_PREFIX=~/.npm-global` | `~/.npm-global` | `~/.npm-global/bin` |
| `uv` | `uv tool install <name>[==<version>] [--with ...] [--python ...]` | `~/.local/share/uv/tools` | `~/.local/bin` |
| `curl` | `get_url` downloads the script over HTTPS, then `bash <script>`, skipped when `creates` exists | wherever the script puts it | `~/.local/bin`, if the script uses it |

Ansible needs one of two things to become an unprivileged user: `setfacl` on the VM, or pipelining. The plan adds `acl` to the workstation's `environment.systemPackages` (decision 5).

Commands run with `argv:`, never through a shell, so a package spec can't inject a command. Specs are also checked against a strict pattern in `prepare.yml` (section 4).

`/nix/store` is read-only, and home folders survive redeploys. So tools stay installed between deploys, and the deploy only installs what's missing.

### Toolchains

- An `npm` tool needs `nodejs` or `nodejs_<version>` in the user's `packages`, and a `uv` tool needs `uv`. The deploy checks this and never adds them itself (decision 2).
- **nix-ld.** NixOS can't run prebuilt Linux binaries, because they look for `/lib64/ld-linux-x86-64.so.2`. Several things this plan installs use them: Python wheels with compiled code (manylinux), Pythons that uv downloads, and native installers such as Claude Code's. The plan turns on `programs.nix-ld.enable` with a small set of common libraries (`stdenv.cc.cc.lib`, `zlib`, `openssl`) on workstations (decision 3).
- uv uses the system `python3` from `common.nix` unless a tool sets `python:`. Then uv downloads that version, which runs through nix-ld.

### Versions

`npm` and `uv` tools take an optional `version:`. It must be one exact version, such as `5.6.3` or `0.8.4`, not a range (decision 8).

| `version:` | First install | Later deploys | `-e workstation_upgrade=true` |
|---|---|---|---|
| Not set | The latest version on the registry | Left as installed | Upgraded to the latest |
| Set | That version | If the installed version differs, reinstalled at the pinned version | Not changed. Edit `version:` to move it. |

So a pin is enforced. If the user, or a tool's own updater, moves a pinned tool to another version, the next deploy puts the pinned version back. An unpinned tool is never changed by a plain redeploy: it stays at whatever was latest when it was installed, or at whatever its own updater moved it to.

To check a pin, the deploy reads the installed version from `npm ls -g --depth=0 --json` and `uv tool list`. A pinned tool is reinstalled with `npm install -g <name>@<version>` or `uv tool install --reinstall <name>==<version>`.

Packages under `with:` use PEP 508 specs, so they can be pinned too (`llm-anthropic==0.12`). Changing anything about a uv tool, meaning its version, `with:` or `python:`, reinstalls that tool. The deploy notices the change by comparing against its install record (below).

`curl` tools have no `version:`. If an install script takes a version, put it in the URL or let the script choose. A `curl` tool is installed once, when `creates` is missing.

Self-updating tools such as Claude Code: leave them unpinned to let them update themselves. If you pin one, also turn its updater off with a variable in `environment:` (for Claude Code, `DISABLE_AUTOUPDATER: "1"`). Otherwise it updates itself between deploys, and every deploy reinstalls the pin.

### Installing, upgrading and removing

- **Each deploy** installs tools that are missing, puts pinned tools back on their version, and leaves unpinned tools alone.
- **`-e workstation_upgrade=true`** also runs `npm install -g <name>@latest` and `uv tool upgrade <name>` for every unpinned tool, and runs the curl scripts again (decision 4).
- **Removing a tool from the list** uninstalls it on the next deploy with `npm uninstall -g` or `uv tool uninstall`, but only if the deploy installed it. The deploy keeps a record of what it installed in `~/.local/state/nixlab/tools.json`: each tool's name, kind, `version:`, `with:` and `python:`. Tools the user installed by hand are never touched. Removed `curl` tools are only reported: the deploy doesn't know what their scripts wrote.
- **Each run reports** the version of every npm and uv tool, so you can see what "latest" turned out to be.

### Environment variables

The deploy writes one file, `~/.config/nixlab/env`, owned by the user with mode `0600`. It holds:

1. `PATH` additions: `~/.local/bin` and `~/.npm-global/bin`, and `NPM_CONFIG_PREFIX`.
2. `settings.environment` from the network file.
3. `WORKSTATION_ENV_*` from `secrets/<network>/<host>.env`, with the prefix removed.

Every value is written with shell quoting (`| quote`). Secrets stay out of the Nix store, which every user can read, and out of Ansible's output (`no_log`).

The workstation's `configuration.nix` loads it with `environment.extraInit`:

```nix
environment.extraInit = ''
  if [ -r "$HOME/.config/nixlab/env" ]; then set -a; . "$HOME/.config/nixlab/env"; set +a; fi
'';
```

On NixOS, `extraInit` goes into `/etc/set-environment`. Login shells source that file, and so does `/etc/bashrc` for non-login shells, which should cover `ssh host cmd` and VS Code Remote-SSH. That has to be confirmed live (Phase 5). If a case is missed, the fallback is to also source the file from `programs.bash.interactiveShellInit`.

The install tasks read the same variables, so a token for a private npm registry or a `UV_INDEX_URL` also applies while installing.

The file is rewritten on every deploy. Editing it by hand doesn't last; the user keeps their own variables in `~/.bashrc`.

## 3. Decisions needing approval

| # | Decision | Recommended | Alternative |
|---|---|---|---|
| 1 | Where secret variables go | `WORKSTATION_ENV_<NAME>` lines in the existing `secrets/<network>/<host>.env` | A second file, `<host>-env.env`, like postgres's `<host>-users.env` |
| 2 | Toolchains for `npm`/`uv` tools | **Taken (2026-11-13):** the user must list them in `packages:`, and the deploy fails if they're missing. | Added automatically (`nodejs_22`, `uv`). This was built first, then reversed: see Progress. |
| 3 | nix-ld | On for every workstation, with `stdenv.cc.cc.lib`, `zlib` and `openssl` | Only when a tool needs it (`settings.nix_ld: true`). Wheels with compiled code fail confusingly without it. |
| 4 | Upgrading unpinned tools | Only with `-e workstation_upgrade=true`. A plain deploy installs missing tools and enforces pins only. | Upgrade unpinned tools on every deploy. Simpler, but a redeploy for an unrelated change can then break a tool. |
| 5 | Becoming the user | Add `acl` to the workstation's system packages | Turn on pipelining for these tasks. That covers `command`, but `copy`/`template` as the user still need temp files. |
| 6 | Removing tools | Uninstall only what the deploy recorded installing; report removed curl tools | Never uninstall, only report |
| 7 | Variable names that aren't allowed | `PATH`, `HOME`, `USER`, `LOGNAME`, `SHELL`, `NPM_CONFIG_PREFIX`, and anything starting with `LD_` or `NIX_` | No reserved names |
| 8 | What `version:` accepts | One exact version (`5.6.3`, `0.8.4`, `1.0.0-beta.2`, `2.1.0rc1`), so the installed version can be checked against it | Ranges too (`^5.6`, `>=0.8,<0.9`). Pins could then no longer be enforced, only installed. |
| 9 | Pinned tool found at another version | Reinstall the pinned version, and report it as a change | Fail the deploy and ask the user to fix it |

## 4. Changes

| Where | Change |
|---|---|
| [defaults/main.yml](../../../roles/workstation/defaults/main.yml) | `environment: {}` and `tools: []` in the settings defaults. `workstation_tools`, `workstation_environment`, `workstation_env_file`, `workstation_upgrade: false`. |
| New filter, `plugins/filter/workstation.py` | `workstation_tools_errors(tools)` and `workstation_env_errors(env, secrets)`. Checks like these are easier to unit test in Python than in assert lists. They check: one kind per entry (`npm`, `uv` or `curl`); npm names like `@scope/name` and uv names as PEP 508 names with optional extras, with no version in the name; `version:` as one exact version (decision 8), only on npm and uv tools; `with:` as PEP 508 specs; `python:` like `3.12`; curl URLs `https://` only, with `creates` required and starting with `~/`; variable names `^[A-Za-z_][A-Za-z0-9_]*$`, not reserved (decision 7), and not both in `environment` and secrets. |
| [tasks/prepare.yml](../../../roles/workstation/tasks/prepare.yml) | Read `WORKSTATION_ENV_*` from the secrets file (`no_log`). Assert the filters return no errors, including the package managers the tools need (decision 2). |
| [templates/workstation.nix.j2](../../../roles/workstation/templates/workstation.nix.j2) | Toolchain packages added to `packages`. |
| [files/configuration.nix](../../../roles/workstation/files/configuration.nix) | `acl` in system packages, `programs.nix-ld`, and `environment.extraInit` loading the env file. |
| New `tasks/tools.yml`, included at the end of [configure.yml](../../../roles/workstation/tasks/configure.yml) after the switch | As the user: create `~/.config/nixlab` and `~/.local/state/nixlab`, write the env file, read the install record and the installed versions, then install, reinstall at its pin, upgrade or uninstall each tool. Then write the record and report each tool's version. `PATH` for these tasks is set explicitly: `/etc/profiles/per-user/<user>/bin`, `/run/current-system/sw/bin`, then the user's bin folders. |
| [tasks/verify.yml](../../../roles/workstation/tasks/verify.yml) | As the user over a non-interactive SSH command: each npm/uv tool's command is found, each pinned tool is at its version, and each `environment` name is set. Values aren't printed. |
| [env.example](../../../roles/workstation/env.example), [README.md](../../../roles/workstation/README.md) | Document `tools`, `environment`, `WORKSTATION_ENV_*`, upgrades, and that no sudo is needed. |
| New filter, `workstation_tool_actions(tools, record, installed, upgrade)` | Decides per tool: install, reinstall at its pin, upgrade, uninstall, or leave alone. Pure logic, so the cases in "Versions" are unit tested. `installed` is parsed from `npm ls` and `uv tool list`. |
| `tests/test_workstation.py` | Unit tests for the filters. |

## 5. Phases

Each phase leaves the repo working, and the unit tests pass after each one.

### Phase 1: Environment variables

- `settings.environment`, `WORKSTATION_ENV_*`, the env file, and `extraInit`. `acl` goes in here, since writing the file as the user needs it.
- Tests: names, reserved names, clashes, and quoting of values with spaces, quotes and `$`.

### Phase 2: Toolchain and nix-ld

- nix-ld, the PATH additions, and the check that `npm`/`uv` tools have their package manager in `packages`.
- Nothing is installed yet, so this can be checked on its own: `uv tool install ruff` by hand as the user.

### Phase 3: Tools

- `tools.yml`: install missing tools, enforce pins, the record, uninstalling, and `workstation_upgrade`.
- Tests:
  - Names and versions, including ones that must fail: `; rm -rf ~`, `ruff==0.8` in the name, `^5.6` as a version, `version:` on a curl tool, `http://`, and a curl entry without `creates`.
  - `workstation_tool_actions` for each row of the "Versions" table, a changed `with:`, an upgrade that skips pinned tools, and a hand-installed tool that is never uninstalled.

### Phase 4: Verify and docs

- The `verify.yml` checks, README, `env.example`, and an example in `networks/examples/`.

### Phase 5: Live check

On a throwaway workstation on an isolated network:

1. Deploy with `sudo: false`, `environment`, one secret, and one tool of each kind: unpinned `@anthropic-ai/claude-code`, a pinned npm tool one version behind the latest, a pinned uv tool, and an unpinned uv tool with `with:`.
2. Check variables and `PATH` in an interactive login, `ssh ws 'env; command -v claude ruff'`, and a VS Code Remote-SSH terminal.
3. Check the versions: the unpinned tools are the latest, and the pinned ones are at their pins.
4. Redeploy with no changes: nothing is installed again, and the run reports no changes.
5. As the user, upgrade a pinned tool by hand, then redeploy: it's put back on its pin.
6. Change a pin and a `with:` entry, then redeploy: both tools are reinstalled.
7. Remove a uv tool from the list and redeploy: it's uninstalled. A tool installed by hand stays.
8. `-e workstation_upgrade=true` upgrades the unpinned tools and leaves the pinned ones alone.
9. A uv tool with compiled wheels (for example `llm` with a plugin that uses numpy), and a `python:` version uv must download, both run through nix-ld.

## 6. Risks

- **Installs need the internet at deploy time.** A registry or install script that's down fails the deploy after the switch. The VM is fine, but its tools are incomplete. Re-running the deploy finishes them.
- **curl scripts run whatever the URL serves.** They run as the user, never as root, over HTTPS only. Still, list only sources you trust.
- **Unpinned tools differ between workstations.** Each gets whatever was latest when it was installed. Set `version:` where that matters.
- **A pinned version can disappear.** npm packages are rarely unpublished, and PyPI releases can be yanked. Then the deploy fails on that tool. Move the pin.
- **Pinned self-updating tools fight the deploy** unless their updater is turned off (see "Versions").
- **Pins cover the tool, not its dependencies.** npm and uv resolve dependencies again on each install, so a reinstall at the same pin can still pull newer dependencies.
- **Changing `user` leaves the old home behind**, as today. The new user gets fresh installs.
- **nix-ld covers common libraries only.** A tool needing something else fails with a missing `.so`. Then the library is added to nix-ld's list.
