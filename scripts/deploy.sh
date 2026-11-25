#!/usr/bin/env bash
# Deploys one published version of movierec on this machine, and rolls back the same way.
#
#   ./scripts/deploy.sh v0.2.0                                        a release (a Git tag)
#   ./scripts/deploy.sh sha-<full commit hash>                        any commit merged to main
#   ./scripts/deploy.sh v0.1.0                                        rollback: deploy the older version
#
# What it does:
#   1. pulls the image from the GitHub Container Registry and records its digest (the image's hash)
#   2. saves the image, pinned to that digest, as MOVIEREC_IMAGE in .env, so Compose and reboots use it
#   3. restarts the stack with that image (never builds one), and checks /health, then /ready
#   4. checks the running app container really uses the pulled image
#   5. appends one line to deploy.log: when, who, which version, the previous and new image, the result
# If the new version fails after the stack restarts, it logs "failed" and rolls back automatically,
# by running itself with the previous version from .env, exactly as a person would. It tries that
# once: if the previous version fails too, it stops, since the problem is then not the new image.
# A failed pull changes nothing, so there is nothing to roll back.
set -euo pipefail

REGISTRY="${MOVIEREC_REGISTRY:-ghcr.io/rvt9bx/dsan6700-project}" # overridable only to test the script
APP_URL="http://127.0.0.1:8080" # works whether APP_BIND is 127.0.0.1 or 0.0.0.0
HEALTH_WAIT=60                  # seconds for the process to start
READY_WAIT=300                  # seconds for Qdrant and the model; the first start downloads the model

cd "$(dirname "$0")/.." # the repository root, where compose.yml and .env are
LOG_FILE="deploy.log"
ENV_FILE=".env"

version="${1:-}"
if [[ ! "$version" =~ ^(v[0-9]+\.[0-9]+\.[0-9]+|sha-[0-9a-f]{40})$ ]]; then
  echo "Usage: $0 <version>   e.g. $0 v0.2.0, or $0 sha-<full 40-character commit hash>" >&2
  exit 2
fi

previous="none"
if [[ -f "$ENV_FILE" ]] && grep -q '^MOVIEREC_IMAGE=' "$ENV_FILE"; then
  previous="$(grep '^MOVIEREC_IMAGE=' "$ENV_FILE" | tail -n 1 | cut -d= -f2-)"
fi
new="$REGISTRY:$version"

log() { # log <result>: one line per deploy, never edited afterwards
  printf '%s user=%s version=%s previous=%s new=%s result=%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${USER:-$(id -un)}" "$version" "$previous" "$new" "$1" >>"$LOG_FILE"
}

fail() { # fail <reason>
  log "failed($1)"
  echo "Deploy of $version FAILED: $1" >&2
  echo "Logged in $LOG_FILE. Look at the app's logs with: docker compose logs --tail 50 app" >&2
  if [[ -n "${ROLLBACK_FROM:-}" ]]; then # this run was already the automatic rollback: stop here
    echo "The rollback from $ROLLBACK_FROM also FAILED, so the new image is probably not the problem." >&2
    echo "Check Qdrant and the movie collection: docker compose ps; curl -s $APP_URL/ready" >&2
    exit 1
  fi
  if [[ "$1" == "pull" ]]; then # nothing was changed yet: the old version is still running
    echo "Nothing was changed; the version that was running is still running." >&2
    exit 1
  fi
  old="${previous#"$REGISTRY:"}"
  old="${old%@*}"
  if [[ "$previous" == "$REGISTRY:"* && "$old" != "$version" ]]; then
    # Roll back the same way as by hand: this script, run with the older version
    echo "==> Rolling back automatically: $0 $old" >&2
    ROLLBACK_FROM="$version" exec "$0" "$old"
  fi
  echo "There is no earlier deployed version in .env to roll back to; deploy a known good one: $0 <version>" >&2
  exit 1
}

wait_for() { # wait_for <path> <seconds>: true once the path answers 200
  local deadline=$((SECONDS + $2))
  until curl -fsS -o /dev/null "$APP_URL$1" 2>/dev/null; do
    ((SECONDS < deadline)) || return 1
    sleep 3
  done
}

echo "==> Pulling $new"
docker pull "$new" || fail "pull"
digest="$(docker image inspect --format '{{index .RepoDigests 0}}' "$new")" # ghcr.io/...@sha256:...
new="$new@${digest#*@}"                                                       # tag kept for people, digest for Docker
echo "    digest ${digest#*@}"

echo "==> Saving MOVIEREC_IMAGE in $ENV_FILE"
touch "$ENV_FILE"
{ grep -v '^MOVIEREC_IMAGE=' "$ENV_FILE" || true; echo "MOVIEREC_IMAGE=$new"; } >"$ENV_FILE.tmp"
cat "$ENV_FILE.tmp" >"$ENV_FILE" # rewrite in place, so the file keeps its owner and permissions
rm "$ENV_FILE.tmp"

echo "==> Starting the stack with $version"
docker compose up -d --no-build || fail "compose up"

echo "==> Waiting for /health (up to ${HEALTH_WAIT}s)"
wait_for /health "$HEALTH_WAIT" || fail "health"
echo "==> Waiting for /ready (up to ${READY_WAIT}s)"
wait_for /ready "$READY_WAIT" || fail "ready"

running="$(docker inspect --format '{{.Image}}' "$(docker compose ps -q app)")"
expected="$(docker image inspect --format '{{.Id}}' "$new")"
[[ "$running" == "$expected" ]] || fail "app container is not running the pulled image"

if [[ -n "${ROLLBACK_FROM:-}" ]]; then
  log "ok(automatic rollback from $ROLLBACK_FROM)"
  echo "Rolled back to $version ($new) after $ROLLBACK_FROM failed. Logged in $LOG_FILE." >&2
  exit 1 # the deploy that was asked for still failed
fi
log "ok"
echo "Deployed $version ($new). Logged in $LOG_FILE."
