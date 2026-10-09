#!/bin/sh
# Run on the target host after unpacking a Git archive and importing deploy/tls.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
: "${RELEASE_TAG:?Set RELEASE_TAG to the source Git commit}" "${TARGET_IPV4:?}"
backup="$root/../platerra-backup-$RELEASE_TAG"
umask 077
mkdir -p "$backup"
sudo -n docker inspect l4desk-landing > "$backup/edge-inspect.json"
sudo -n docker exec l4desk-landing cat /etc/nginx/nginx.conf > "$backup/nginx.conf"
cp /home/user1/l4desk-landing/docker-compose.yml "$backup/l4desk-compose.yml"
sudo -n chmod 700 "$root/deploy/tls"
sudo -n chmod 600 "$root/deploy/tls/"*.pem
sudo -n openssl x509 -in "$root/deploy/tls/fullchain.pem" -noout -checkend 86400
sudo -n env RELEASE_TAG="$RELEASE_TAG" docker compose -f "$root/deploy/compose.yml" build
sudo -n env RELEASE_TAG="$RELEASE_TAG" docker compose -f "$root/deploy/compose.yml" up -d --wait --wait-timeout 120
# Validate against existing persisted L4Desk certs without changing its container.
sed 's|/etc/nginx/ssl/live/|/etc/letsencrypt/live/l4desk.ru/|g' \
    "$root/deploy/edge/nginx.conf" > "$backup/nginx.preflight.conf"
sudo -n docker run --rm --network l4desk-landing_default \
    --volumes-from l4desk-landing \
    -v "$backup/nginx.preflight.conf:/etc/nginx/nginx.conf:ro" \
    -v "$root/deploy/edge/platerra.conf:/etc/nginx/platerra.conf:ro" \
    -v "$root/deploy/tls:/etc/nginx/platerra-tls:ro" \
    --entrypoint nginx l4desk-landing:latest -t
restore_edge() {
    sudo -n docker compose -f /home/user1/l4desk-landing/docker-compose.yml \
        up -d --no-deps --no-build landing
}
trap 'echo "Deployment failed; restoring the previous edge configuration"; restore_edge' HUP INT TERM EXIT
sudo -n env PLATERRA_ROOT="$root" docker compose \
    -f /home/user1/l4desk-landing/docker-compose.yml \
    -f "$root/deploy/edge/compose.override.yml" \
    up -d --no-deps --no-build --force-recreate --wait --wait-timeout 120 landing
sudo -n docker exec l4desk-landing nginx -t
sudo -n docker exec l4desk-landing nginx -s reload
curl --fail --silent --show-error --resolve "platerra.ru:443:$TARGET_IPV4" https://platerra.ru/healthz
curl --fail --silent --show-error --resolve "l4desk.ru:443:$TARGET_IPV4" https://l4desk.ru/healthz
trap - HUP INT TERM EXIT
printf 'PLATERRA_ROOT=%s\nTARGET_IPV4=%s\nEDGE_CONTAINER=l4desk-landing\n' "$root" "$TARGET_IPV4" > "$root/deploy/server.env"
sudo -n install -m 644 "$root/deploy/platerra-certificate.service" /etc/systemd/system/
sudo -n install -m 644 "$root/deploy/platerra-certificate.timer" /etc/systemd/system/
sudo -n systemctl daemon-reload
sudo -n systemctl enable --now platerra-certificate.timer
sudo -n systemctl start platerra-certificate.service
echo "Platerra release $RELEASE_TAG is deployed."
