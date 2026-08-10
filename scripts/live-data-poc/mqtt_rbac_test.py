#!/usr/bin/env python3
"""
Empirical test: Entra-ID (RBAC-only) MQTT v5 publish/subscribe to an Event Grid
topic space that has NO permission bindings.

If this succeeds, it proves the design claim:
    "No EG permission bindings are needed — both publisher and subscriber
     authenticate with Microsoft Entra ID (managed identity), which is
     authorized via Azure RBAC, not permission bindings."

Auth model (per Microsoft Learn):
  - MQTT v5 required.
  - Enhanced authentication: Authentication Method = "OAUTH2-JWT",
    Authentication Data = an Entra JWT for audience https://eventgrid.azure.net/.
  - Authorization is via the EventGrid TopicSpaces Publisher/Subscriber roles.

Prereqs:
  pip install "paho-mqtt>=2.0.0" azure-identity
  The identity resolved by DefaultAzureCredential (e.g. your `az login` user)
  must hold Publisher + Subscriber roles on the topic space / namespace.

Env:
  MQTT_HOST   required  (e.g. livedata-poc-eg.eastus-1.ts.eventgrid.azure.net)
  MQTT_PORT   optional  (default 8883)
  MQTT_TOPIC  optional  (default aio/observability/poc/test)
  CLIENT_ID   optional  (default livedata-poc-client)
"""
import os
import ssl
import sys
import threading

from azure.identity import DefaultAzureCredential
import paho.mqtt.client as mqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

HOST = os.environ.get("MQTT_HOST")
PORT = int(os.environ.get("MQTT_PORT", "8883"))
TOPIC = os.environ.get("MQTT_TOPIC", "aio/observability/poc/test")
CLIENT_ID = os.environ.get("CLIENT_ID", "livedata-poc-client")
EG_SCOPE = "https://eventgrid.azure.net/.default"

if not HOST:
    sys.exit("ERROR: set MQTT_HOST (the Event Grid MQTT hostname).")

print(f"Acquiring Entra token for {EG_SCOPE} ...")
token = DefaultAzureCredential().get_token(EG_SCOPE).token
print("Token acquired.")

_done = threading.Event()
_result = {"connected": None, "subscribed": False, "received": False}


def on_connect(client, userdata, flags, reason_code, properties):
    _result["connected"] = int(reason_code.value) if hasattr(reason_code, "value") else int(reason_code)
    print(f"CONNECT  -> reason_code={reason_code}")
    if _result["connected"] == 0:
        client.subscribe(TOPIC, qos=1)
    else:
        _done.set()


def on_subscribe(client, userdata, mid, reason_code_list, properties):
    rc = reason_code_list[0]
    print(f"SUBSCRIBE-> reason_code={rc}")
    granted = (int(rc.value) if hasattr(rc, "value") else int(rc)) < 128
    _result["subscribed"] = granted
    if granted:
        print(f"PUBLISH  -> topic={TOPIC}")
        client.publish(TOPIC, b"hello-rbac-only", qos=1)
    else:
        _done.set()


def on_message(client, userdata, msg):
    print(f"RECEIVED -> topic={msg.topic} payload={msg.payload!r}")
    _result["received"] = True
    _done.set()


client = mqtt.Client(
    client_id=CLIENT_ID,
    protocol=mqtt.MQTTv5,
    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
)
client.on_connect = on_connect
client.on_subscribe = on_subscribe
client.on_message = on_message
client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)

# MQTT v5 enhanced authentication with the Entra JWT.
connect_props = Properties(PacketTypes.CONNECT)
connect_props.AuthenticationMethod = "OAUTH2-JWT"
connect_props.AuthenticationData = token.encode("utf-8")

print(f"Connecting to {HOST}:{PORT} (MQTT v5, OAUTH2-JWT) ...")
client.connect(HOST, PORT, clean_start=True, properties=connect_props)
client.loop_start()

ok = _done.wait(timeout=30)
client.loop_stop()
client.disconnect()

print("\n================ RESULT ================")
print(f"  connected (rc=0) : {_result['connected'] == 0}")
print(f"  subscribe granted: {_result['subscribed']}")
print(f"  message received : {_result['received']}")
if _result["connected"] == 0 and _result["subscribed"] and _result["received"]:
    print("  VERDICT: PASS — RBAC-only auth works WITHOUT permission bindings.")
    sys.exit(0)
print("  VERDICT: FAIL/INCONCLUSIVE — see reason codes above.")
sys.exit(1)
