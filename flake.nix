{
  description = "Kotonoha desktop lyrics overlay";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = {
    self,
    nixpkgs,
    ...
  }: let
    revision = self.shortRev or self.dirtyShortRev or "unknown";
    supportedSystems = [
      "x86_64-linux"
      "aarch64-linux"
    ];
    forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
    mkKotonoha = pkgs: pkgs.callPackage ./packaging/nix/package.nix {inherit revision;};
    overlay = final: _previous: {
      kotonoha = mkKotonoha final;
    };
  in {
    overlays.default = overlay;

    packages = forAllSystems (
      system: let
        pkgs = import nixpkgs {inherit system;};
        kotonoha = mkKotonoha pkgs;
      in {
        inherit kotonoha;
        default = kotonoha;
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

    formatter = forAllSystems (system: nixpkgs.legacyPackages.${system}.alejandra);
  };
}
