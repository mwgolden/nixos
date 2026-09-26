# hosts/webserver/configuration.nix

{ config, pkgs, ... }:

{
    imports = [ 
        ./common.nix
        ./hardware-configuration.nix
    ];

    networking.hostName = "webserver";

    networking.interfaces.ens18.ipv4.addresses = [{
        address = "192.168.1.12";
        prefixLength = 24;
    }];

    networking.defaultGateway = "192.168.1.1";

    networking.nameservers = [
        "192.168.1.1"
    ];

    services.nginx = {
        enable = true;

        virtualHosts."_" = {
            root = "/var/www";
        };
    };

    networking.firewall.allowedTCPPorts = [
        22
        80
    ];
}