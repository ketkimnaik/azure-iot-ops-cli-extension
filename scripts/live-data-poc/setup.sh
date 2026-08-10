#!/usr/bin/env bash
#
# Empirical test setup for the Live Data "no permission bindings" claim.
#
# Goal: prove that an Event Grid MQTT topic space with ONLY Azure RBAC roles
# (EventGrid TopicSpaces Publisher/Subscriber) and NO permission bindings allows
# an Entra-ID (managed-identity/user) client to publish and subscribe over MQTT v5.
#
# This script provisions:
#   - an Event Grid namespace with MQTT (topic spaces) enabled
#   - a topic space with the wildcard template  aio/observability/#
#   - NO permission bindings (intentional)
#   - Publisher + Subscriber role assignments for the *signed-in user*
#     (so the same identity that runs mqtt_rbac_test.py holds the roles)
#
# Prereqs: az CLI logged in (`az login`), permission to create EG + assign roles.
#
# Usage:
#   export RG=my-rg LOCATION=eastus NS=livedata-poc-eg
#   ./setup.sh
#
set -euo pipefail

: "${RG:?set RG (resource group)}"
: "${LOCATION:=eastus}"
: "${NS:?set NS (Event Grid namespace name, globally unique)}"
TS="${TS:-live-data-ts-poc}"
# Scope for the role assignments: "topic-space" (least privilege) or "namespace".
RA_SCOPE="${RA_SCOPE:-topic-space}"

PUBLISHER_ROLE="EventGrid TopicSpaces Publisher"   # GUID a12b0b94-b317-4dcd-84a8-502ce99884c6
SUBSCRIBER_ROLE="EventGrid TopicSpaces Subscriber" # GUID 4b0f2fd7-60b4-4eca-896f-4435034f8bf5

echo "==> Resource group"
az group create -n "$RG" -l "$LOCATION" -o none

echo "==> Event Grid namespace ($NS) with MQTT/topic-spaces enabled"
az eventgrid namespace create \
  -g "$RG" -n "$NS" -l "$LOCATION" \
  --topic-spaces-configuration "{state:Enabled}" \
  -o none

echo "==> Topic space ($TS) with wildcard 'aio/observability/#' — NO permission bindings"
az eventgrid namespace topic-space create \
  -g "$RG" --namespace-name "$NS" -n "$TS" \
  --topic-templates "['aio/observability/#']" \
  -o none

MQTT_HOST=$(az eventgrid namespace show -g "$RG" -n "$NS" \
  --query "topicSpacesConfiguration.hostname" -o tsv)

NS_ID=$(az eventgrid namespace show -g "$RG" -n "$NS" --query id -o tsv)
TS_ID=$(az eventgrid namespace topic-space show -g "$RG" --namespace-name "$NS" -n "$TS" --query id -o tsv)

if [[ "$RA_SCOPE" == "namespace" ]]; then
  SCOPE="$NS_ID"
else
  SCOPE="$TS_ID"
fi

PRINCIPAL_ID=$(az ad signed-in-user show --query id -o tsv)

echo "==> Assigning roles to signed-in user ($PRINCIPAL_ID) at scope: $RA_SCOPE"
az role assignment create --assignee-object-id "$PRINCIPAL_ID" \
  --assignee-principal-type User \
  --role "$PUBLISHER_ROLE" --scope "$SCOPE" -o none
az role assignment create --assignee-object-id "$PRINCIPAL_ID" \
  --assignee-principal-type User \
  --role "$SUBSCRIBER_ROLE" --scope "$SCOPE" -o none

cat <<EOF

==================================================================
Setup complete. NO permission bindings were created.

  MQTT hostname : $MQTT_HOST
  Topic space   : $TS  (template: aio/observability/#)
  Role scope    : $RA_SCOPE
  Identity      : signed-in user ($PRINCIPAL_ID)

Next — run the MQTT v5 publish/subscribe test with the SAME identity:

  export MQTT_HOST="$MQTT_HOST"
  python mqtt_rbac_test.py

Expected: CONNECT rc=0, SUBSCRIBE granted, and the published message is
received back — proving RBAC-only (no permission bindings) works.

Role-assignment propagation can take a minute; if you see 'not authorized',
wait ~60s and retry.
==================================================================
EOF
