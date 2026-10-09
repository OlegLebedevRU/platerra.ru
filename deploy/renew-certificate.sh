#!/bin/sh
# Runs as root under systemd; settings are supplied by deploy/server.env.
set -eu
: "${PLATERRA_ROOT:?}" "${TARGET_IPV4:?}"
EDGE_CONTAINER="${EDGE_CONTAINER:-l4desk-landing}"
for domain in platerra.ru www.platerra.ru; do
    addresses=$(getent ahostsv4 "$domain" | awk '{print $1}' | sort -u)
    if [ "$addresses" != "$TARGET_IPV4" ]; then
        echo "Certificate enrollment postponed: DNS for $domain is not on the target host."
        exit 0
    fi
done
docker exec "$EDGE_CONTAINER" certbot certonly --webroot -w /var/www/certbot \
    --non-interactive --agree-tos --email info@platerra.ru \
    --cert-name platerra.ru -d platerra.ru -d www.platerra.ru \
    --keep-until-expiring --preferred-challenges http-01
tls="$PLATERRA_ROOT/deploy/tls"
umask 077
docker cp -L "$EDGE_CONTAINER:/etc/letsencrypt/live/platerra.ru/fullchain.pem" "$tls/fullchain.next.pem"
docker cp -L "$EDGE_CONTAINER:/etc/letsencrypt/live/platerra.ru/privkey.pem" "$tls/privkey.next.pem"
openssl x509 -in "$tls/fullchain.next.pem" -noout -checkend 86400
# Verify that the issued certificate and private key match before installation.
cert_pub=$(openssl x509 -in "$tls/fullchain.next.pem" -pubkey -noout | openssl pkey -pubin -outform DER | sha256sum | awk '{print $1}')
key_pub=$(openssl pkey -in "$tls/privkey.next.pem" -pubout -outform DER | sha256sum | awk '{print $1}')
[ "$cert_pub" = "$key_pub" ]
cp "$tls/fullchain.pem" "$tls/fullchain.previous.pem"
cp "$tls/privkey.pem" "$tls/privkey.previous.pem"
mv "$tls/fullchain.next.pem" "$tls/fullchain.pem"
mv "$tls/privkey.next.pem" "$tls/privkey.pem"
if docker exec "$EDGE_CONTAINER" nginx -t; then
    docker exec "$EDGE_CONTAINER" nginx -s reload
    echo "Platerra certificate installed; nginx reloaded."
else
    mv "$tls/fullchain.previous.pem" "$tls/fullchain.pem"
    mv "$tls/privkey.previous.pem" "$tls/privkey.pem"
    exit 1
fi
