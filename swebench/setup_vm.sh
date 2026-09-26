#!/usr/bin/env bash
# Create / manage / delete the GCE VM that runs the SWE-bench Verified pipeline.
# Run from YOUR machine (Git Bash is fine), one subcommand at a time, reading each first:
#
#   bash swebench/setup_vm.sh create     # create the VM (starts billing)
#   bash swebench/setup_vm.sh iam        # let the VM's service account call Gemini on Vertex AI
#   bash swebench/setup_vm.sh copy       # tar the Forge repo and scp it to the VM
#   bash swebench/setup_vm.sh ssh        # open a shell on the VM
#   bash swebench/setup_vm.sh fetch      # copy results (VM ~/swebench-runs) to swebench/out/vm-<date>/ here
#   bash swebench/setup_vm.sh stop       # stop the VM (CPU billing stops; the 250 GB disk is still billed)
#   bash swebench/setup_vm.sh start      # start it again
#   bash swebench/setup_vm.sh delete     # TEARDOWN: delete VM + disk (stops all billing)
#
# Machine sizing (quotas read 2026-09-26 with `gcloud compute regions describe us-central1`
# and `gcloud compute project-info describe`, on a free-trial project):
#   CPUS_ALL_REGIONS = 12   <- the limit that matters: at most 12 vCPUs across the whole project
#   N2_CPUS (us-central1) = 32, E2_CPUS = 8, C3_CPUS = 8, N2D_CPUS = 8, C2_CPUS = 0
#   SSD_TOTAL_GB (us-central1) = 250  <- pd-balanced counts as SSD, so a 250 GB disk uses ALL of it
#   PREEMPTIBLE_CPUS = 0    <- Spot/preemptible VMs are not allowed on this free trial
#   IN_USE_ADDRESSES = 4    <- one external IP is fine
# => n2-standard-8 (8 vCPU, 32 GB RAM). n2-standard-16 would exceed the 12-vCPU global limit.
#    SWE-bench recommends >= 8 cores, >= 16 GB RAM, >= 120 GB free disk for local Docker evaluation.
# Approx. price (us-central1, on-demand, check the pricing page): n2-standard-8 ~ $0.39/h,
# 250 GB pd-balanced ~ $25/month (~ $0.035/h). 
set -euo pipefail

PROJECT="${FORGE_PROJECT:?export FORGE_PROJECT=<your-gcp-project-id> first}"
ZONE="us-central1-a"
VM="forge-swebench"
MACHINE="n2-standard-8"
DISK_GB=250
# Default compute service account of the project (read with `gcloud compute project-info describe`).
VM_SA="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')-compute@developer.gserviceaccount.com"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"   # the Forge repo root on your machine

cmd="${1:-help}"
case "$cmd" in
  create)
    # --scopes=cloud-platform: the VM's access token may call any Google API; what it is actually
    # allowed to do is decided by IAM (see `iam` below). No Spot (quota 0), no GPU.
    gcloud compute instances create "$VM" \
      --project="$PROJECT" --zone="$ZONE" \
      --machine-type="$MACHINE" \
      --image-family=ubuntu-2204-lts --image-project=ubuntu-os-cloud \
      --boot-disk-size="${DISK_GB}GB" --boot-disk-type=pd-balanced \
      --service-account="$VM_SA" \
      --scopes=cloud-platform
    ;;
  iam)
    # Grants the VM's service account permission to call Vertex AI (Gemini) in this project.
    # This changes the project's IAM policy: one binding, role roles/aiplatform.user.
    # It can take ~1-2 minutes to take effect.
    gcloud projects add-iam-policy-binding "$PROJECT" \
      --member="serviceAccount:${VM_SA}" \
      --role="roles/aiplatform.user" \
      --condition=None
    ;;
  copy)
    # Pack the repo (without .git / venvs / caches / local outputs) and copy it to ~/forge on the VM.
    tmp="$(mktemp -d)"
    tar -C "$REPO_DIR" -czf "$tmp/forge.tar.gz" \
      --exclude=.git --exclude=.venv --exclude=__pycache__ --exclude='*.egg-info' \
      --exclude=.forge --exclude=CLAUDE.local.md --exclude=swebench/out --exclude=evals/results .
    # Record the commit so results can name the exact Forge version.
    {
      git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || echo "unknown"
      if [ -n "$(git -C "$REPO_DIR" status --porcelain 2>/dev/null)" ]; then echo "dirty: uncommitted changes present"; fi
    } > "$tmp/FORGE_COMMIT"
    gcloud compute scp --project="$PROJECT" --zone="$ZONE" "$tmp/forge.tar.gz" "$tmp/FORGE_COMMIT" "$VM":
    gcloud compute ssh "$VM" --project="$PROJECT" --zone="$ZONE" --command \
      'rm -rf ~/forge && mkdir -p ~/forge && tar -xzf ~/forge.tar.gz -C ~/forge && mv ~/FORGE_COMMIT ~/forge/ && echo copied to ~/forge'
    rm -rf "$tmp"
    ;;
  ssh)
    gcloud compute ssh "$VM" --project="$PROJECT" --zone="$ZONE"
    ;;
  fetch)
    # Results live OUTSIDE ~/forge on the VM (~/swebench-runs/<name>), so `copy` never deletes them.
    dest="$REPO_DIR/swebench/out/vm-$(date +%Y%m%d-%H%M)"
    mkdir -p "$dest"
    gcloud compute scp --recurse --project="$PROJECT" --zone="$ZONE" "$VM":swebench-runs "$dest"
    echo "fetched into $dest (gitignored)"
    ;;
  stop)
    gcloud compute instances stop "$VM" --project="$PROJECT" --zone="$ZONE"
    ;;
  start)
    gcloud compute instances start "$VM" --project="$PROJECT" --zone="$ZONE"
    ;;
  delete)
    # TEARDOWN. Deletes the VM and its boot disk (auto-delete is on by default for the boot disk).
    # Run `fetch` first if you want the results. Then verify nothing is left:
    gcloud compute instances delete "$VM" --project="$PROJECT" --zone="$ZONE" --delete-disks=all
    echo "Remaining instances / disks (should be empty):"
    gcloud compute instances list --project="$PROJECT"
    gcloud compute disks list --project="$PROJECT"
    # Optional: remove the IAM binding again.
    echo "Optional: remove the IAM binding with:"
    echo "  gcloud projects remove-iam-policy-binding $PROJECT --member=serviceAccount:${VM_SA} --role=roles/aiplatform.user --condition=None"
    ;;
  *)
    sed -n '2,13p' "$0"
    ;;
esac
