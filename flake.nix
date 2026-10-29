{
  description = "NixOS infrastructure";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
  };

  outputs = { self, nixpkgs, ... }: {
    # The VMs' configurations are built on each VM by nixos-rebuild, from
    # files the deploy installs in /etc/nixos (see roles/).
    nixosConfigurations.installer = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";

      modules = [
        ./installer/configuration.nix
      ];
    };
  };
}