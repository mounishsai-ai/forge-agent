#!/usr/bin/env bash
# One-time setup ON THE VM (Ubuntu 22.04). Run after `setup_vm.sh copy`:
#
#   bash ~/forge/swebench/vm_bootstrap.sh
#   exit        # log out and ssh back in so the `docker` group membership applies
#
# Installs: Docker Engine, git, python3 + venv, uv, and a venv (~/sb-venv) with swebench + datasets.
# Creates /opt/forge-rt (owned by you) where run_forge.py builds Forge's own Python runtime;
# that directory is mounted read-only into each SWE-bench container.
# Optional argument: a git URL to clone Forge from instead of using the copied ~/forge.
set -euo pipefail

FORGE_DIR="$HOME/forge"
SWEBENCH_VERSION="5.0.2"   # the version whose CLI flags/dataset fields the scripts were written against

echo "== apt packages"
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl gnupg git python3 python3-venv python3-pip tmux jq

echo "== Docker Engine (official apt repo)"
if ! command -v docker >/dev/null; then
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -y
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io
fi
sudo usermod -aG docker "$USER"
sudo systemctl enable --now docker

echo "== uv"
if ! command -v uv >/dev/null && [ ! -x "$HOME/.local/bin/uv" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
grep -q 'local/bin' "$HOME/.bashrc" || echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"

echo "== venv for the swebench harness (~/sb-venv)"
python3 -m venv "$HOME/sb-venv"
"$HOME/sb-venv/bin/pip" install -q --upgrade pip
"$HOME/sb-venv/bin/pip" install -q "swebench==${SWEBENCH_VERSION}" datasets
grep -q 'sb-venv' "$HOME/.bashrc" || echo 'source "$HOME/sb-venv/bin/activate"' >> "$HOME/.bashrc"

echo "== Forge source"
if [ "${1:-}" != "" ]; then
  rm -rf "$FORGE_DIR"
  git clone "$1" "$FORGE_DIR"
  git -C "$FORGE_DIR" rev-parse HEAD > "$FORGE_DIR/FORGE_COMMIT"
fi
test -f "$FORGE_DIR/forge/cli.py" || { echo "Forge not found at $FORGE_DIR (run setup_vm.sh copy, or pass a git URL)"; exit 1; }

echo "== /opt/forge-rt (Forge runtime, mounted read-only into containers)"
sudo mkdir -p /opt/forge-rt
sudo chown "$USER:$USER" /opt/forge-rt

echo "== project id for Forge"
grep -q FORGE_PROJECT "$HOME/.bashrc" || echo "export FORGE_PROJECT=${FORGE_PROJECT:?pass FORGE_PROJECT=<id> bash vm_bootstrap.sh}" >> "$HOME/.bashrc"

echo
echo "Done. Now: exit, ssh back in (for docker group), then optionally 'docker login' (free Docker Hub"
echo "account; avoids anonymous pull rate limits), then follow swebench/README.md step 4."
