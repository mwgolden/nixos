# roles/monitoring/files/configuration.nix
#
# Installed to /etc/nixos on the monitoring VM by roles/monitoring, next to
# common.nix, network.nix (hostname and static IP) and monitoring.nix
# (Grafana's port and URL, Prometheus's retention and scrape jobs, whether
# the Pushgateway and Loki run, and the firewall), which are generated from
# the host's network file entry.

{ config, lib, pkgs, ... }:

let
  dataDir = "/var/lib/monitoring";
  grafanaDir = "${dataDir}/grafana";
  lokiDir = "${dataDir}/loki";
  # Set by monitoring.nix when settings.loki is on.
  loki = config.services.loki.enable;
  lokiPort = toString config.services.loki.configuration.server.http_listen_port;
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
        ] ++ lib.optional loki {
          name = "Loki";
          type = "loki";
          uid = "loki";
          url = "http://127.0.0.1:${lokiPort}";
          editable = false;
        };
      };
    };
  };

  # Written by roles/monitoring, root-only, and kept out of the Nix store,
  # which every user on the VM can read.
  systemd.services.grafana.serviceConfig.LoadCredential = [
    "admin_password:/etc/grafana-credentials/admin_password"
    "secret_key:/etc/grafana-credentials/secret_key"
  ];

  # ---- Loki ----
  # Keeps logs pushed to its HTTP port, by this VM's Alloy and by other
  # hosts, on the data disk. monitoring.nix turns it on and sets the port
  # and retention. It has no login, like the Pushgateway. NixOS checks the
  # configuration with loki -verify-config when it builds it.
  services.loki = lib.mkIf loki {
    dataDir = lokiDir;
    configuration = {
      auth_enabled = false;
      server = {
        # gRPC is only for Loki's parts talking to each other.
        grpc_listen_address = "127.0.0.1";
        grpc_listen_port = 9095;
        log_level = "warn";
      };
      # A single Loki, with nothing shared between instances.
      common = {
        path_prefix = lokiDir;
        replication_factor = 1;
        ring = {
          kvstore.store = "inmemory";
          instance_addr = "127.0.0.1";
        };
        storage.filesystem = {
          chunks_directory = "${lokiDir}/chunks";
          rules_directory = "${lokiDir}/rules";
        };
      };
      # The address the query frontend gives the querier to answer on.
      # Otherwise it is the VM's own address, where gRPC doesn't listen,
      # and every query hangs.
      frontend.address = "127.0.0.1";
      schema_config.configs = [
        {
          from = "2024-01-01";
          store = "tsdb";
          object_store = "filesystem";
          schema = "v13";
          index = {
            prefix = "index_";
            period = "24h";
          };
        }
      ];
      # The compactor deletes logs older than limits_config.retention_period.
      compactor = {
        working_directory = "${lokiDir}/compactor";
        retention_enabled = true;
        delete_request_store = "filesystem";
      };
      analytics.reporting_enabled = false;
    };
  };

  # ---- Alloy ----
  # Sends this VM's systemd journal to Loki. Its web interface stays on
  # loopback. It keeps its place in the journal in /var/lib/private/alloy.
  services.alloy = lib.mkIf loki {
    enable = true;
    extraFlags = [
      "--server.http.listen-addr=127.0.0.1:12345"
      "--disable-reporting"
    ];
  };

  environment.etc."alloy/config.alloy" = lib.mkIf loki {
    text = ''
      loki.relabel "journal" {
        forward_to = []

        rule {
          source_labels = ["__journal__systemd_unit"]
          target_label  = "unit"
        }
        rule {
          source_labels = ["__journal_priority_keyword"]
          target_label  = "level"
        }
      }

      loki.source.journal "journal" {
        max_age       = "12h"
        relabel_rules = loki.relabel.journal.rules
        labels        = { host = "${config.networking.hostName}", job = "systemd-journal" }
        forward_to    = [loki.write.local.receiver]
      }

      loki.write "local" {
        endpoint {
          url = "http://127.0.0.1:${lokiPort}/loki/api/v1/push"
        }
      }
    '';
  };

  systemd.services.alloy = lib.mkIf loki {
    wants = [ "loki.service" ];
    after = [ "loki.service" ];
  };

  # ---- Data disk ----
  # Prometheus's samples, Grafana's database and Loki's logs live on the separate data
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

  systemd.services.loki = lib.mkIf loki {
    requires = [ "var-lib-monitoring.mount" "loki-data-dir.service" ];
    after = [ "var-lib-monitoring.mount" "loki-data-dir.service" ];
  };

  # NixOS makes Grafana's and Loki's home folders when it activates a configuration,
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

  systemd.services.loki-data-dir = lib.mkIf loki {
    description = "Create Loki's folder on the data disk";
    requires = [ "var-lib-monitoring.mount" ];
    after = [ "var-lib-monitoring.mount" ];
    before = [ "loki.service" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = ''
      install -d -m 0750 -o loki -g loki ${lokiDir}
    '';
  };
}
