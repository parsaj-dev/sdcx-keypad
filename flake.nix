{
  description = "Linux driver and CLI for SDCX / SDINNOVATION USB macropads";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});

      # Every vendor ID the vendor's own WebHID bundle filters on (docs/PROTOCOL.md §6).
      # The full list is 196 vid:pid pairs; matching on vendor alone keeps the rule
      # readable and is safe because it is further constrained to hidraw nodes whose
      # device is the vendor-defined config interface; the two keyboard interfaces
      # under the same VID:PID are untouched by a hidraw uaccess tag. `sdcx
      # install-udev-rule` writes the precise 196-line version if you prefer it.
      vendorIds = [
        "0461" "0483" "05ac" "0816" "0817" "0818" "0819" "08a1" "08a3" "08a5" "08ae"
        "3151" "35ae" "36ae" "5566" "68bd" "6d02" "6d03" "6d04" "6d05" "6d06" "6d07"
        "6d7b" "6d7c" "6d7d" "6d7e" "6d7f" "6d80" "6d81" "6d82" "6d83" "7dfa"
      ];

      udevRules = nixpkgs.lib.concatMapStringsSep "\n"
        (vid: ''KERNEL=="hidraw*", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="${vid}", TAG+="uaccess", MODE="0660", GROUP="input"'')
        vendorIds;
    in
    {
      packages = forAllSystems (pkgs: rec {
        sdcx-keypad = pkgs.python3Packages.buildPythonApplication {
          pname = "sdcx-keypad";
          version = "0.1.0";
          src = ./.;

          pyproject = true;
          build-system = [ pkgs.python3Packages.setuptools ];
          dependencies = [ ]; # deliberate: standard library only

          # There is no test suite yet, and the only meaningful check needs hardware.
          doCheck = false;

          meta = with pkgs.lib; {
            description = "Linux driver and CLI for SDCX / SDINNOVATION USB macropads";
            homepage = "https://github.com/parsaj-dev/sdcx-keypad";
            license = licenses.mit;
            platforms = platforms.linux;
            mainProgram = "sdcx";
          };
        };
        default = sdcx-keypad;
      });

      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          # No runtime deps to provide; this shell exists for `python3 -m sdcx`
          # against the checkout and for building/inspecting the package.
          packages = [ pkgs.python3 pkgs.python3Packages.pip pkgs.usbutils ];
          shellHook = ''
            export PYTHONPATH="$PWD:$PYTHONPATH"
            echo "sdcx dev shell, run: python3 -m sdcx list"
          '';
        };
      });

      nixosModules.default = { config, lib, pkgs, ... }:
        let cfg = config.programs.sdcx-keypad;
        in {
          options.programs.sdcx-keypad = {
            enable = lib.mkEnableOption "the sdcx keypad CLI and its udev rule";
            package = lib.mkOption {
              type = lib.types.package;
              default = self.packages.${pkgs.stdenv.hostPlatform.system}.sdcx-keypad;
              description = "Package providing the sdcx binary.";
            };
          };
          config = lib.mkIf cfg.enable {
            environment.systemPackages = [ cfg.package ];
            # uaccess hands the node to whoever is logged in at the seat; the group
            # fallback covers headless use, where there is no seat to inherit from.
            services.udev.extraRules = udevRules + "\n";
          };
        };

      formatter = forAllSystems (pkgs: pkgs.nixpkgs-fmt);
    };
}
