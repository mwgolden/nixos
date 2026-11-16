# roles/monitoring/files/configuration.nix
#
# Installed to /etc/nixos on the monitoring VM by roles/monitoring, next to
# common.nix, network.nix (hostname and static IP) and monitoring.nix
# (Grafana's port and URL, Prometheus's retention and scrape jobs, and the
# firewall), which are generated from the host's network file entry.

{ config, pkgs, ... }:

let
  dataDir = "/var/lib/monitoring";
  grafanaDir = "${dataDir}/grafana";
  # systemd puts the files from LoadCredential here, readable by Grafana.
  credentials = "/run/credentials/grafana.service";
in
{
  imports = [
    ./hardware-configuration.nix
    ./common.nix
    ./network.nix
    ./monitoring.nix
  ];

  # ---- Prometheus ----
  # Below /var/lib, so on the data disk. Loopback only: it has no login, so
  # it is reached through Grafana, or over SSH.
  services.prometheus = {
    enable = true;
    listenAddress = "127.0.0.1";
    port = 9090;
    stateDir = "monitoring/prometheus";
  };

  # This VM's own CPU, memory, disk and network figures.
  services.prometheus.exporters.node = {
    enable = true;
    listenAddress = "127.0.0.1";
    port = 9100;
  };

  # ---- Grafana ----
  services.grafana = {
    enable = true;
    dataDir = grafanaDir;
    settings = {
      server.http_addr = "0.0.0.0";
      security = {
        # Only used when Grafana first creates its database.
        admin_user = "admin";
        admin_password = "$__file{${credentials}/admin_password}";
        secret_key = "$__file{${credentials}/secret_key}";
        cookie_secure = false;
      };
      users.allow_sign_up = false;
      analytics = {
        reporting_enabled = false;
        check_for_updates = false;
        check_for_plugin_updates = false;
      };
    };
    provision = {
      enable = true;
      datasources.settings = {
        apiVersion = 1;
        datasources = [
          {
            name = "Prometheus";
            type = "prometheus";
            uid = "prometheus";
            url = "http://127.0.0.1:${toString config.services.prometheus.port}";
            isDefault = true;
            editable = false;
          }
        ];
      };
    };
  };

  # Written by roles/monitoring, root-only, and kept out of the Nix store,
  # which every user on the VM can read.
  systemd.services.grafana.serviceConfig.LoadCredential = [
    "admin_password:/etc/grafana-credentials/admin_password"
    "secret_key:/etc/grafana-credentials/secret_key"
  ];

  # ---- Data disk ----
  # Prometheus's samples and Grafana's database live on the separate data
  # disk (scsi1, serial "monitoring-data"), which roles/monitoring formats.
  # nofail keeps the VM bootable over SSH if the disk is missing; the
  # services then refuse to start instead of writing to the root disk.
  fileSystems.${dataDir} = {
    device = "/dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_monitoring-data";
    fsType = "ext4";
    options = [ "nofail" ];
  };

  systemd.services.prometheus = {
    requires = [ "var-lib-monitoring.mount" ];
    after = [ "var-lib-monitoring.mount" ];
  };

  systemd.services.grafana = {
    requires = [ "var-lib-monitoring.mount" "grafana-data-dir.service" ];
    after = [ "var-lib-monitoring.mount" "grafana-data-dir.service" ];
  };

  # NixOS makes Grafana's home folder when it activates a configuration,
  # which at boot is before the data disk is mounted. Make it on the disk.
  systemd.services.grafana-data-dir = {
    description = "Create Grafana's folder on the data disk";
    requires = [ "var-lib-monitoring.mount" ];
    after = [ "var-lib-monitoring.mount" ];
    before = [ "grafana.service" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = ''
      install -d -m 0750 -o grafana -g grafana ${grafanaDir}
    '';
  };
}
