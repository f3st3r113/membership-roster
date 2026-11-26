#!/bin/sh
# Update the app on the NAS: pull the latest code from GitHub, then rebuild the image.
# Run from the code folder (e.g. /volume1/docker/cfd-roster-src):   sh update.sh
# Afterwards, redeploy the stack in Dockhand.
#
# Optional settings (environment variables):
#   CFD_DEPLOY_KEY   path to the read-only deploy key   (default: ~/.ssh/cfd_deploy)
#   CFD_IMAGE        image name to build                 (default: cfd-roster:latest)
set -eu
cd "$(dirname "$0")"

KEY="${CFD_DEPLOY_KEY:-$HOME/.ssh/cfd_deploy}"
IMAGE="${CFD_IMAGE:-cfd-roster:latest}"

echo "==> Pulling latest code"
if [ -f "$KEY" ]; then
  GIT_SSH_COMMAND="ssh -i $KEY -o IdentitiesOnly=yes" git pull --ff-only
else
  git pull --ff-only
fi

echo "==> Building $IMAGE"
if [ "$(id -u)" -eq 0 ]; then
  docker build -t "$IMAGE" .
else
  sudo docker build -t "$IMAGE" .
fi

echo
echo "Done. Now redeploy the stack in Dockhand (stop and start it if it keeps the old container)."
