# Gitea runner

A NixOS VM running Gitea's [act_runner](https://docs.gitea.com/usage/actions/act-runner), which runs the [Gitea Actions](https://docs.gitea.com/usage/actions/overview) workflows of a gitea host on the same network. Jobs run in Docker containers by default.

```yaml
hosts:
  - name: runner
    type: gitea_runner
    vm_id: 115
    ip: 10.1.0.15
    cores: 4
    memory_mb: 8192
    data_disk:             # optional: Docker's images and containers
      size_gb: 60          # mounted at /var/lib/docker
      storage: local-lvm
    settings:
      # All optional; these are the defaults.
      gitea: ""            # the gitea host to register with; empty: the network's only one
      capacity: 1          # jobs at once
      docker: true
      labels:
        - ubuntu-latest:docker://docker.gitea.com/runner-images:ubuntu-latest
        - ubuntu-24.04:docker://docker.gitea.com/runner-images:ubuntu-24.04
      cache_port: 8088     # for actions/cache
```

It needs a gitea host on the same network, which validation checks. It has no secrets file of its own.

## Deploying

Deploy the gitea host first, then the runner:

```bash
source proxmox/.env
ansible-playbook playbooks/deploy-host.yaml -e network=lab -e host=runner
```

`deploy-network` deploys runners last, after the network's gitea host.

Before anything changes, the deploy reads the gitea host's admin login, from `secrets/<network>/<gitea>.env` or the network's OpenBao. It uses that login to get the instance-wide runner registration token from Gitea's API. It writes the token to a root-only file on the VM. The runner registers with it on its first start and shows up under Site Administration → Actions → Runners. The deploy waits for the registration and checks the runner is running.

Gitea hands out the same token until it is reset, so a redeploy changes nothing. If the token changes (it was reset in Gitea, or the gitea host was built again from scratch), the deploy registers the runner again. The old entry then shows offline in Gitea; delete it there.

## Labels

A workflow's `runs-on:` picks a runner by label. Each label says where its jobs run:

| Label | Jobs run |
|---|---|
| `<name>:docker://<image>` | in a fresh container of that image, removed afterwards. Needs `docker: true`. |
| `<name>:host` | straight on the VM, as the runner's own user, with bash, coreutils, curl, git and Node.js |

The default images are Gitea's [runner-images](https://gitea.com/gitea/runner-images), built to run GitHub-style actions. They are large, over 1 GB each, so give the VM a `data_disk` for Docker. Old images and stopped containers are pruned weekly.

Host jobs can use the Docker socket, which makes them root on the VM in effect. Use them only for workflows you trust.

A changed label list registers the runner again under the same name.

## HTTPS and certificates

The runner talks to Gitea directly, on its address and `http_port`. Jobs clone from the address Gitea gives them (its `ROOT_URL`), which is the proxy's HTTPS name when Gitea has a `proxy:` route. For that to work:

- **With `security.pki`** on the network, the VM trusts the network's root already.
- **Without it**, the proxy signs with its own authority. The deploy copies `secrets/<network>/<proxy>-ca.crt` to the VM and trusts it. If that file isn't there yet, the deploy says so; deploy the proxy, then the runner again.

The VM's certificate bundle is mounted into every job container. `NODE_EXTRA_CA_CERTS` points Node.js, which runs most actions, at it.

## The cache server

The runner serves `actions/cache` on `cache_port`. The firewall lets only job containers (on `docker0` and the jobs' own `br-*` bridges) and the VM itself connect. The rest of the network can't. `network_verify` expects the port to be open.

## Making changes

Edit the host's entry or the files here and redeploy. An existing VM is updated in place.

- **Labels, capacity, Docker, cache port:** change them under `settings:`.
- **Other runner settings:** add them to `settings` in [templates/gitea_runner.nix.j2](templates/gitea_runner.nix.j2), which becomes act_runner's `config.yaml`.
- **More runners:** add more `gitea_runner` hosts. Each registers under its own host name.

## Files

| File | Purpose |
|---|---|
| `files/configuration.nix` | NixOS configuration: imports and the runner package |
| `templates/gitea_runner.nix.j2` | Generated settings: the runner, its labels, Docker, the firewall, the data disk |
| `defaults/main.yml` | Settings, and how the gitea host and its address are found |
| `tasks/` | `prepare.yml` (settings, token), `configure.yml` (token file, switch, registration), `verify.yml`, `ports.yml` |

## Removing it

```bash
ansible-playbook playbooks/destroy-host.yaml -e network=lab -e host=runner
```

The runner stays listed in Gitea, offline. Delete it under Site Administration → Actions → Runners.
