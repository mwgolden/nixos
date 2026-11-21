# Plan: packages and tools in the network diagrams

Each `docs/network-diagrams/<network>.md` shows a host's type, VM ID, zone, address, ports and data disk, but not what software it carries. For a workstation that is the main thing that sets one apart from another. This plan adds a **Software** table listing each host's declared packages and tools, filled from the network file the way the other tables are.

## Progress

**Done (2026-11-21).** The decisions in section 3 were taken on the same day.

- `network_diagram` writes the Software section, and `agent-developer.md` and `home.md` were redrawn with it.
- [tests/test_diagram.py](../../../tests/test_diagram.py): `full()` adds a workstation `ws` with packages and npm, pinned uv and curl tools. It goes in `full()`, not the shared fixture, so the other suites' host counts stay the same. There are 3 new tests (tool labels, only hosts with software get rows, no section without software), and the golden `lab.md` and `README.md` were regenerated. The full suite is 295 of 296. The one failure is the old overlap of `networks/examples/test.yaml` with `workstation-lab`.
- The diagrams were redrawn with `network_config_check_proxmox=false`, which counts every host as deployed. In `home.md` that wrongly marked the lab and workstation-lab routers as deployed, so those lines were put back by hand and only the Software section was kept. The next deploy, or a run with Proxmox access, will write the same file.

Differences from the plan below:

- **A curl tool shows its `creates` path**, such as `~/.local/bin/claude (curl)`. Curl tools have no `name` key, only the script URL and `creates`.

## 1. Target

After the Hosts table (which is unchanged), agent-developer would show:

```markdown
## Software

Packages and tools declared in the network file. Each role's README lists what the role installs itself.

| Host | Packages | Tools |
|---|---|---|
| dev-workstation | uv, nodejs_22, openbao | @anthropic-ai/claude-code (npm), ruff (uv) |
```

- Only hosts with packages or tools get a row, in file order. A network with none has no Software section, like Port forwards and Proxy routes.
- **Packages**: `settings.packages`, in file order, by nixpkgs attribute name. `—` when a host has tools but no packages.
- **Tools**: `settings.tools`, each as `<name> (<kind>)`, with `<name>@<version> (<kind>)` when pinned. A curl tool shows its `name`, not its script URL. `—` when empty.
- The Mermaid flowchart is unchanged. Its node labels are already four lines, and package lists would make them unreadable.

## 2. Where the data comes from

The diagram is drawn from `network_config_inventory`, not from the VMs, so the columns show what the network file **declares**, which the last deploy installed. They can't show a tool the user installed by hand, or one left in place because its package manager was removed (the known gap in [WORKSTATION-TOOLS.md](WORKSTATION-TOOLS.md)). That matches how the Ports column works, and keeps `diagram-network.yaml` runnable without SSH to the VMs.

The inventory host already carries `settings` (the flowchart reads the router's `blocked_networks` from it), so no inventory change is needed.

## 3. Decisions

Taken 2026-11-21.

1. **Declared software only.** The roles' own packages (the workstation's curl, vim, tmux and so on, the router's dnsutils, gitea's own package) are not listed. Copying those lists into the filter would let them drift from the Nix files. The note under the table points to the roles' READMEs.
2. **A separate Software table,** not new columns in Hosts. Hosts stays at 8 columns, and a long package list doesn't widen every row.
3. **Settings like postgres `version: 17` are not software** and are not listed.

## 4. Steps

### Phase 1: filter

In [plugins/filter/network_diagram.py](../../../plugins/filter/network_diagram.py):

- Add `_packages(host)` and `_tools(host)`, reading `host.get("settings") or {}`, each returning a comma-joined string (`""` when empty, which `_cell` turns into `—`).
- `_tools` formats each entry by its kind key (`npm`, `uv`, `curl`), adding `@version` when set. Reuse the kind detection in [plugins/filter/workstation.py](../../../plugins/filter/workstation.py) if it is importable from the filter; otherwise keep a three-line local copy. Tools are already validated before the diagram runs, so no error handling.
- In `network_diagram`, after the Hosts table and before Port forwards, add a `## Software` section with the note line and a `Host | Packages | Tools` table of the hosts that have either. Leave the section out when no host does.

### Phase 2: tests

- Add a workstation host with `packages` and `tools` (one unpinned npm, one pinned uv, one curl) to [tests/fixtures/networks/lab.yaml](../../../tests/fixtures/networks/lab.yaml), or add it in `full()` in [tests/test_diagram.py](../../../tests/test_diagram.py) if the fixture is shared with tests that count hosts.
- Unit test for `_tools` formatting: unpinned, pinned, curl, empty.
- Test that a network with no packages or tools has no Software section (the `home` fixture covers this through its golden file).
- Regenerate the golden files: `UPDATE_DIAGRAMS=1 .venv/bin/python -m unittest discover -s tests -p test_diagram.py`, review the diff, then run the full suite.

### Phase 3: docs and diagrams

- [README.md](../../../README.md#network-diagrams): add the Software table to the list of what the diagrams show.
- [roles/workstation/README.md](../../../roles/workstation/README.md): one line saying the diagram lists `packages` and `tools`.
- Redraw: `ansible-playbook playbooks/diagram-network.yaml -e network_config_check_proxmox=false`, check `agent-developer.md` matches section 1, and commit the diagrams with the code.
- On completion, move this file to `docs/plans/completed/` and fill in Progress.

## 5. Out of scope

- Querying the VMs for what is actually installed (`nix-env`, `npm ls -g`, `uv tool list`). That needs SSH from the diagram playbook and would make diagrams differ between runs.
- Environment variables (`settings.environment`). They are not software, and names alone tell a reader little.
