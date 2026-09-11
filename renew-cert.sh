#!/bin/bash
set -euo pipefail

CERT_DIR=${ZMWALL_CERT_DIR:-/etc/zmwall/tls}
CA_CERT="$CERT_DIR/zmwall-local-ca.crt"
CA_KEY="$CERT_DIR/zmwall-local-ca.key"
SERVER_CERT="$CERT_DIR/zmwall.crt"
SERVER_KEY="$CERT_DIR/zmwall.key"
IDENTITIES="$CERT_DIR/identities.txt"

install -d -m 0755 "$CERT_DIR"

temporary_files=()
cleanup() {
  for temporary_file in "${temporary_files[@]}"; do
    rm -f -- "$temporary_file"
  done
}
trap cleanup EXIT

identity_tmp=$(mktemp "$CERT_DIR/.identities.XXXXXX")
temporary_files+=("$identity_tmp")
wall_hostname=$(hostname)
wall_fqdn=$(hostname -f 2>/dev/null || hostname)
{
  printf 'DNS:%s\n' localhost "$wall_hostname" "$wall_fqdn"
  printf 'IP:%s\n' 127.0.0.1
  ip -o -4 address show scope global 2>/dev/null \
    | awk '{split($4,address,"/"); print "IP:" address[1]}' || true
} | sort -u > "$identity_tmp"

renew_server=0
if [ ! -s "$CA_CERT" ] || [ ! -s "$CA_KEY" ] || ! openssl x509 -checkend 31536000 -noout -in "$CA_CERT"; then
  ca_cert_tmp=$(mktemp "$CERT_DIR/.ca-cert.XXXXXX")
  ca_key_tmp=$(mktemp "$CERT_DIR/.ca-key.XXXXXX")
  temporary_files+=("$ca_cert_tmp" "$ca_key_tmp")
  openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 3650 \
    -subj "/CN=ZMWall Local CA" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -keyout "$ca_key_tmp" -out "$ca_cert_tmp"
  install -m 0600 "$ca_key_tmp" "$CA_KEY"
  install -m 0644 "$ca_cert_tmp" "$CA_CERT"
  rm -f -- "$CERT_DIR/zmwall-local-ca.srl"
  renew_server=1
fi

if [ ! -s "$SERVER_CERT" ] || [ ! -s "$SERVER_KEY" ] \
   || ! openssl x509 -checkend 2592000 -noout -in "$SERVER_CERT" \
   || ! openssl verify -CAfile "$CA_CERT" "$SERVER_CERT" >/dev/null 2>&1 \
   || [ ! -s "$IDENTITIES" ] || ! cmp -s "$identity_tmp" "$IDENTITIES"; then
  renew_server=1
fi

if [ "$renew_server" -eq 0 ]; then
  exit 0
fi

openssl_config=$(mktemp "$CERT_DIR/.openssl.XXXXXX")
server_csr_tmp=$(mktemp "$CERT_DIR/.server-csr.XXXXXX")
server_cert_tmp=$(mktemp "$CERT_DIR/.server-cert.XXXXXX")
server_key_tmp=$(mktemp "$CERT_DIR/.server-key.XXXXXX")
temporary_files+=("$openssl_config" "$server_csr_tmp" "$server_cert_tmp" "$server_key_tmp")

{
  echo '[req]'
  echo 'prompt = no'
  echo 'distinguished_name = dn'
  echo 'req_extensions = server_ext'
  echo '[dn]'
  printf 'CN = %s\n' "$wall_fqdn"
  echo '[server_ext]'
  echo 'basicConstraints = critical,CA:FALSE'
  echo 'keyUsage = critical,digitalSignature,keyEncipherment'
  echo 'extendedKeyUsage = serverAuth'
  echo 'subjectAltName = @alt_names'
  echo '[alt_names]'
  dns_index=1
  ip_index=1
  while IFS=: read -r identity_type identity_value; do
    if [ "$identity_type" = DNS ]; then
      printf 'DNS.%d = %s\n' "$dns_index" "$identity_value"
      dns_index=$((dns_index + 1))
    elif [ "$identity_type" = IP ]; then
      printf 'IP.%d = %s\n' "$ip_index" "$identity_value"
      ip_index=$((ip_index + 1))
    fi
  done < "$identity_tmp"
} > "$openssl_config"

openssl req -new -newkey rsa:2048 -sha256 -nodes -config "$openssl_config" \
  -keyout "$server_key_tmp" -out "$server_csr_tmp"
openssl x509 -req -sha256 -days 90 -in "$server_csr_tmp" \
  -CA "$CA_CERT" -CAkey "$CA_KEY" -CAcreateserial \
  -extfile "$openssl_config" -extensions server_ext -out "$server_cert_tmp"

install -m 0600 "$server_key_tmp" "$SERVER_KEY"
install -m 0644 "$server_cert_tmp" "$SERVER_CERT"
install -m 0644 "$identity_tmp" "$IDENTITIES"

if [ "${ZMWALL_RELOAD_NGINX:-1}" -eq 1 ] && systemctl is-active --quiet nginx; then
  nginx -t
  systemctl reload nginx
fi
