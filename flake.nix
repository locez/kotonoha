{
  description = "Kotonoha desktop lyrics overlay";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      supportedSystems = [
        "aarch64-linux"
        "x86_64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
      overlay = final: _previous: {
        kotonoha = final.callPackage ./nix/package.nix { };
      };
      packagesFor =
        system:
        import nixpkgs {
          inherit system;
          overlays = [ overlay ];
        };
    in
    {
      overlays.default = overlay;

      packages = forAllSystems (
        system:
        let
          pkgs = packagesFor system;
        in
        {
          inherit (pkgs) kotonoha;
          default = pkgs.kotonoha;
        }
      );

      apps = forAllSystems (system: {
        kotonoha = {
          type = "app";
          program = nixpkgs.lib.getExe self.packages.${system}.kotonoha;
          meta = {
            description = self.packages.${system}.kotonoha.meta.description;
          };
        };
        default = self.apps.${system}.kotonoha;
      });

      checks = forAllSystems (system: {
        package = self.packages.${system}.kotonoha;
      });
    };
}
