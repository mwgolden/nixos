# roles/ldap/files/configuration.nix
#
# Installed to /etc/nixos on the ldap VM by roles/ldap, next to common.nix,
# network.nix (hostname and static IP) and ldap.nix (base DN, ports and web
# address), which are generated from the network file.
#
# lldap: a small LDAP server for user accounts and groups, with a web
# interface for managing them. Its database is a SQLite file in
# /var/lib/private/lldap.

{ config, pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ./common.nix
    ./network.nix
    ./ldap.nix
  ];

  services.lldap = {
    enable = true;
    settings = {
      ldap_host = "0.0.0.0";
      http_host = "0.0.0.0";
      ldap_user_dn = "admin";
    };
    # The secrets come from root-only files in /var/lib/lldap-secrets,
    # written by roles/ldap, through systemd credentials (%d is their
    # folder). Resetting the admin password on every start keeps it equal
    # to the one in the secrets file.
    environment = {
      LLDAP_JWT_SECRET_FILE = "%d/jwt_secret";
      LLDAP_LDAP_USER_PASS_FILE = "%d/admin_password";
      LLDAP_FORCE_LDAP_USER_PASS_RESET = "true";
    };
  };

  systemd.services.lldap.serviceConfig.LoadCredential = [
    "jwt_secret:/var/lib/lldap-secrets/jwt_secret"
    "admin_password:/var/lib/lldap-secrets/admin_password"
  ];
}
