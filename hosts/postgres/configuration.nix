# hosts/webserver/configuration.nix

{ config, pkgs, ... }:

{
    imports = [ 
        ./common.nix
        ./hardware-configuration.nix
    ];

    networking.hostName = "webserver";

    networking.interfaces.ens18.ipv4.addresses = [{
        address = "192.168.1.13";
        prefixLength = 24;
    }];

    networking.defaultGateway = "192.168.1.1";

    networking.nameservers = [
        "192.168.1.1"
    ];

    config.services.postgresql = {
        enable = true;
        ensureDatabases = [ "mydatabase" ];
        authentication = pkgs.lib.mkOverride 10 ''
            #type database DBUser auth-method
            locall  all all trust
        '';
    };

    networking.firewall.allowedTCPPorts = [
        22
        80
    ];
}