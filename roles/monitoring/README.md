# Monitoring

A NixOS VM running [Prometheus](https://prometheus.io/), which collects metrics, and [Grafana](https://grafana.com/oss/grafana/), which shows them as dashboards. Grafana comes with Prometheus already set up as its data source. Optionally it also runs [Loki](#loki), which keeps logs, and a [Pushgateway](#pushgateway). Prometheus scrapes itself, this VM's [node_exporter](https://github.com/prometheus/node_exporter), and any targets you list. Both keep their data on a separate data disk.

Only Grafana is reachable from other machines, plus Loki and the Pushgateway when they are on. Prometheus has no login, so it and node_exporter listen on the VM's loopback only.

```yaml
hosts:
  - name: monitoring
    type: monitoring
    vm_id: 121
    ip: 192.168.1.21
    data_disk:
      size_gb: 20          # mounted at /var/lib/monitoring
      storage: local-lvm
    settings:
      # All optional; these are the defaults.
      http_port: 3000      # Grafana
      retention: 30d       # how long Prometheus keeps samples
      scrape_interval: 30s
      scrape: []           # more targets; see below
      root_url: ""         # worked out; see below
      pushgateway: false   # see below
      pushgateway_port: 9091
      loki: false          # see below
      loki_port: 3100
      loki_retention: 30d
```

The defaults are in [defaults/main.yml](defaults/main.yml).

## Grafana's secrets

Copy [env.example](env.example) to `secrets/<network>/<host>.env`, such as `secrets/lab/monitoring.env`, and generate the values:

```bash
echo "GRAFANA_ADMIN_PASSWORD=$(openssl rand -base64 18)"
echo "GRAFANA_SECRET_KEY=$(openssl rand -hex 32)"
```

- `GRAFANA_ADMIN_PASSWORD`: the password of Grafana's `admin` user. At least 12 characters, no spaces.
- `GRAFANA_SECRET_KEY`: encrypts what Grafana stores in its database, such as data source passwords. At least 32 letters and digits. **Never change it** once Grafana has started: what it encrypted can't be read with a new key.

Both are written to root-only files in `/etc/grafana-credentials` on the VM, and systemd hands them to Grafana. They stay out of Ansible's output and the Nix store.

Grafana takes the admin password only when it first creates its database. To change it later, change it in Grafana (Profile, Change password) and in the secrets file. Each deploy logs in with the password from the file, and stops if Grafana refuses it.

## Scrape targets

Add targets under `settings.scrape`. Each entry is a job name and a list of `host:port` targets, with an optional `metrics_path` (default `/metrics`):

```yaml
    settings:
      scrape:
        # Joins this VM's own node_exporter in the "node" job.
        - job: node
          targets:
            - gitea.lab.home.arpa:9100
            - 10.1.0.12:9100
        - job: myapp
          targets: ["10.1.0.30:8080"]
          metrics_path: /api/metrics
```

Targets are fetched from this VM, so they must be reachable from it: on an isolated network, the network's other hosts are, by name or address. A target only answers if something on it serves metrics on that port, and the target's firewall lets it through. The other host types here don't run node_exporter yet.

Prometheus checks its configuration when NixOS builds it, so a mistake stops the deploy before anything restarts.

## Pushgateway

Prometheus pulls metrics, which doesn't suit batch jobs, cron scripts and CI runs that finish before it scrapes them. With `pushgateway: true`, the VM runs a [Pushgateway](https://github.com/prometheus/pushgateway) on `pushgateway_port` (default 9091). Jobs push their metrics to it, it keeps the latest value of each, and Prometheus scrapes it as the `pushgateway` job.

```yaml
    settings:
      pushgateway: true
```

Push from any machine that can reach it:

```bash
cat <<METRICS | curl --data-binary @- http://monitoring.lab.home.arpa:9091/metrics/job/backup/instance/gitea
backup_last_success_timestamp_seconds $(date +%s)
backup_duration_seconds 42
METRICS
```

The `job` and `instance` in the URL become the metrics' labels (Prometheus scrapes it with `honor_labels`, so they aren't replaced). A push replaces everything earlier pushed under the same labels. Values stay until replaced or deleted, so alert on a timestamp, such as `time() - backup_last_success_timestamp_seconds > 86400`, rather than on a job's metrics disappearing. To delete a group:

```bash
curl -X DELETE http://monitoring.lab.home.arpa:9091/metrics/job/backup/instance/gitea
```

Its web page at `http://<monitoring address>:9091` lists what has been pushed.

**It has no login.** Anything that can reach the port can push, overwrite or delete metrics, so the firewall opens it on the VM's network only. Don't add it to `proxy:` or `expose:` unless that's fine for everything able to reach those. Pushed metrics are saved to `/var/lib/private/pushgateway` on the system disk, so they survive restarts; they are small.

## Loki

With `loki: true`, the VM runs [Loki](https://grafana.com/oss/loki/), which stores logs, and Grafana gets it as a second data source. [Grafana Alloy](https://grafana.com/docs/alloy/latest/) on the VM sends it the VM's own systemd journal, with the labels `host`, `job="systemd-journal"`, `unit` and `level`.

```yaml
    settings:
      loki: true
      loki_retention: 30d  # whole days: 30d, 8w, 1y
```

Look at the logs in Grafana under **Explore** with the Loki data source, using a query such as `{host="monitoring", unit="grafana.service"}` or `{job="systemd-journal", level="err"}`.

Other hosts push to `http://<monitoring address>:3100/loki/api/v1/push`. The other host types here don't send their logs yet. To send a host's journal, run Alloy there with the same configuration as in [files/configuration.nix](files/configuration.nix), using the monitoring VM's address in `loki.write`. To push a line by hand:

```bash
curl -H 'Content-Type: application/json' -X POST http://monitoring.lab.home.arpa:3100/loki/api/v1/push \
  --data "{\"streams\":[{\"stream\":{\"job\":\"test\"},\"values\":[[\"$(date +%s%N)\",\"hello\"]]}]}"
```

Logs are kept in `/var/lib/monitoring/loki` on the data disk, and the ones older than `loki_retention` are deleted. Leave room on the disk for both them and Prometheus's samples. Alloy keeps its place in the journal in `/var/lib/private/alloy`, so a restart doesn't send logs twice.

**It has no login,** like the Pushgateway. Anything that can reach the port can push logs and read every log, so the firewall opens it on the VM's network only. Don't add it to `proxy:` or `expose:` unless that's fine for everything able to reach those. Loki's gRPC port (9095) and Alloy's web interface (12345) stay on loopback.

## Deploying

```bash
source proxmox/.env
ansible-playbook playbooks/deploy-host.yaml -e network=lab -e host=monitoring
```

Besides the steps every host goes through, the deploy:

1. Adds the data disk (scsi1, serial `monitoring-data`) and formats it as ext4 if it has no filesystem yet, then checks it is mounted.
2. Installs Grafana's credentials, Prometheus's scrape jobs and Grafana's settings.
3. Waits for Prometheus, Grafana, and Loki and the Pushgateway if on, to be ready, and checks the admin password works.
4. Checks Grafana, Loki and the Pushgateway answer on the VM's address (from the router, on an isolated network) and prints how to reach them.

## Using it

Open Grafana at `http://192.168.1.21:3000` and log in as `admin`. Under **Explore**, pick the Prometheus data source and try a query such as `up` (which targets answer) or `node_load1`.

For a ready-made host dashboard, go to **Dashboards, New, Import**, enter `1860` (Node Exporter Full) and choose the Prometheus data source. This needs the VM to reach grafana.com; otherwise download the dashboard's JSON elsewhere and paste it in.

Grafana is plain HTTP. For HTTPS, put it behind the [proxy](../proxy/README.md):

```yaml
    proxy:
      - name: grafana
        port: 3000
```

With that entry, Grafana's `root_url` is set to `https://grafana.<domain>/` so its links and redirects use that name. Set `root_url` yourself only to use another address.

### Prometheus's own interface

Forward it over SSH:

```bash
ssh -L 9090:127.0.0.1:9090 admin@<monitoring address>
```

Then open `http://127.0.0.1:9090`. **Status, Targets** shows whether each target answers.

## On an isolated network

The network's VMs and VPN clients use `http://monitoring.lab.home.arpa:3000`. To reach it from home, add a `proxy:` entry with `external: true` (HTTPS, preferred), or forward the port and redeploy the router:

```yaml
    expose:
      - port: 3000
```

## Data disk

Prometheus's samples are in `/var/lib/monitoring/prometheus`, Grafana's database (dashboards, users, settings) in `/var/lib/monitoring/grafana`, and Loki's logs in `/var/lib/monitoring/loki`, on the data disk.

- **Size:** Prometheus needs roughly 1 to 2 bytes per sample. With the defaults, a few hosts' node_exporter fit easily in 20 GB for 30 days; raise the disk before raising `retention` a lot or adding many targets. Logs vary much more: a quiet VM's journal is a few MB a day, but a host pushing busy application logs can be GBs.
- **Growing:** raise `data_disk.size_gb` and redeploy. The filesystem grows while both keep running.
- **Shrinking isn't possible.** The deploy stops if the size is smaller than the current disk.
- **Redeploys never wipe it.** It is only formatted if it has no filesystem yet.

If the disk is missing at boot, the VM still starts, but Prometheus, Grafana and Loki don't. That stops them starting over empty on the system disk.

## Making changes

Edit the host's entry or the files here and redeploy. An existing VM is updated in place.

- **Ports, retention, scrape jobs, root URL, Pushgateway, Loki:** change them under `settings:`. The firewall follows the ports. If the host is exposed or proxied, change those ports to match.
- **Other settings:** add them in [files/configuration.nix](files/configuration.nix), such as `services.prometheus.ruleFiles` for alerts, or `services.grafana.provision.dashboards` for dashboards kept in this repository.
- **Address or network:** change `ip`, or move the entry to another network file, and redeploy. See [Moving a VM between networks](../../README.md#moving-a-vm-between-networks).

## Files

| File | Purpose |
|---|---|
| `files/configuration.nix` | NixOS configuration: Prometheus, node_exporter, Grafana with its data sources and credentials, Loki and Alloy, the data disk mount |
| `templates/monitoring.nix.j2` | Generated settings: Grafana's port and URL, retention, scrape jobs, the Pushgateway, turning on Loki with its port and retention, firewall |
| `env.example` | Template for Grafana's secrets file |
| `tasks/` | `prepare.yml` (secrets, settings), `configure.yml` (disk, credentials, switch, readiness, login), `verify.yml`, `ports.yml` |

## Removing it

```bash
ansible-playbook playbooks/destroy-host.yaml -e network=lab -e host=monitoring
```

This permanently deletes the VM, its data disk, every sample, log and Grafana dashboard on it. It asks you to type the host name. Remove the entry from the network file too, or the next deploy creates it again.
