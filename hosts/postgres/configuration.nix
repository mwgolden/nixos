# hosts/postgres/configuration.nix
#
# Installed to /etc/nixos on the postgres VM by postgres.yaml, next to
# common.nix, network.nix (hostname and static IP) and postgres.nix
# (version, port and allowed networks), which are generated from vars.yaml.

{ config, pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ./common.nix
    ./network.nix
    ./postgres.nix
  ];

  services.postgresql = {
    enable = true;
    # Listen on all addresses. Which networks may log in is set in postgres.nix.
    enableTCPIP = true;
    settings.password_encryption = "scram-sha-256";
  };

  # Database files live on the separate data disk (scsi1, serial
  # "postgres-data"), which postgres.yaml formats.
  # nofail keeps the VM bootable over SSH if the disk is missing;
  # PostgreSQL then refuses to start instead of writing to the root disk.
  fileSystems."/var/lib/postgresql" = {
    device = "/dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_postgres-data";
    fsType = "ext4";
    options = [ "nofail" ];
  };

  systemd.services.postgresql = {
    requires = [ "var-lib-postgresql.mount" ];
    after = [ "var-lib-postgresql.mount" ];
  };
}
