# roles/gitea/files/configuration.nix
#
# Installed to /etc/nixos on the gitea VM by roles/gitea, next to common.nix,
# network.nix (hostname and static IP) and gitea.nix (addresses, ports and
# registration), which are generated from the host's network file entry.

{ config, pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ./common.nix
    ./network.nix
    ./gitea.nix
  ];

  services.gitea = {
    enable = true;
    # The database is a file in /var/lib/gitea, on the data disk.
    database.type = "sqlite3";
    lfs.enable = true;
    settings = {
      # session.COOKIE_SECURE is in gitea.nix: it depends on the proxy.
      # Git over SSH goes through the system's SSH server as the gitea user.
      server.START_SSH_SERVER = false;
    };
  };

  # For roles/gitea, which manages the admin user with the gitea command.
  environment.systemPackages = [ config.services.gitea.package ];

  # Everything Gitea keeps (repositories, LFS, the database, its settings,
  # and the gitea user's SSH keys) lives on the separate data disk (scsi1,
  # serial "gitea-data"), which roles/gitea formats.
  # nofail keeps the VM bootable over SSH if the disk is missing; Gitea then
  # refuses to start instead of writing to the root disk.
  fileSystems."/var/lib/gitea" = {
    device = "/dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_gitea-data";
    fsType = "ext4";
    options = [ "nofail" ];
  };

  # Gitea's folders are created at boot, possibly before the disk is
  # mounted. Create them again on the mounted disk, owned by gitea.
  systemd.services.gitea-data-dirs = {
    description = "Create Gitea's folders on its data disk";
    requires = [ "var-lib-gitea.mount" ];
    after = [ "var-lib-gitea.mount" ];
    before = [ "gitea.service" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = ''
      ${config.systemd.package}/bin/systemd-tmpfiles --create --prefix=/var/lib/gitea
    '';
  };

  systemd.services.gitea = {
    requires = [ "var-lib-gitea.mount" "gitea-data-dirs.service" ];
    after = [ "var-lib-gitea.mount" "gitea-data-dirs.service" ];
  };
}
