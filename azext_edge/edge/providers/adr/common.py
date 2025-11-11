# coding=utf-8
# ----------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License file in the project root for license information.
# ----------------------------------------------------------------------------------------------

from enum import Enum
from ...common import ListableEnum


class DestinationQos(ListableEnum):
    """Quality of Service for MQTT destinations."""
    qos0 = "Qos0"
    qos1 = "Qos1"


class ActionType(Enum):
    """Type of action for management group actions."""
    call = "Call"
    read = "Read"
    write = "Write"


class FileType(ListableEnum):
    """
    Supported file types/extensions for bulk asset operations.
    """

    json = "json"
    csv = "csv"
    yaml = "yaml"


class ADRAuthModes(Enum):
    """
    Authentication modes for asset endpoints/devices
    """

    anonymous = "Anonymous"
    certificate = "Certificate"
    userpass = "UsernamePassword"


class AEPTypes(ListableEnum):
    """Asset Endpoint Profile (connector) Types"""

    opcua = "Microsoft.OpcUa"
    onvif = "Microsoft.Onvif"


class TopicRetain(ListableEnum):
    """Set the retain flag for messages published to an MQTT broker."""

    keep = "Keep"
    never = "Never"


# Help text constants for destination parameters
# These are calculated once to avoid repeated list comprehension on every help call
_RETAIN_VALUES = ', '.join(TopicRetain.list())
_QOS_VALUES = ', '.join(DestinationQos.list())

# Common help text fragments for destinations
DEST_HELP_MQTT_VALUES = (
    f"Allowed values for `retain` are {_RETAIN_VALUES} and "
    f"allowed values for `qos` are {_QOS_VALUES}."
)

DEST_HELP_DATASET_FULL = (
    "Key=value pairs representing the destination for dataset. "
    "Allowed arguments include: `key` for BrokerStateStore; `path` for Storage; or "
    f"`topic`, `retain`, `qos`, and `ttl` for MQTT. {DEST_HELP_MQTT_VALUES}"
)

DEST_HELP_DATASET_BROKER_OR_MQTT = (
    "Key=value pairs representing the destination for datasets. "
    "Allowed arguments include: `key` for BrokerStateStore or "
    f"`topic`, `retain`, `qos`, and `ttl` for MQTT. {DEST_HELP_MQTT_VALUES}"
)

DEST_HELP_DATASET_MQTT_ONLY = (
    "Key=value pairs representing the destination for datasets. "
    "Allowed and required arguments are `topic`, `retain`, `qos`, and `ttl` for MQTT destinations.  "
    f"{DEST_HELP_MQTT_VALUES}"
)

DEST_HELP_EVENT_FULL = (
    "Key=value pairs representing the destination for events. "
    "Allowed arguments include: `key` for BrokerStateStore; `path` for Storage; or "
    f"`topic`, `retain`, `qos`, and `ttl` for MQTT. {DEST_HELP_MQTT_VALUES}"
)

DEST_HELP_EVENT_MQTT_ONLY = (
    "Key=value pairs representing the destination for events. "
    f"Allowed arguments include: `topic`, `retain`, `qos`, and `ttl` for MQTT. {DEST_HELP_MQTT_VALUES}"
)

DEST_HELP_EVENT_GROUP_FULL = (
    "Key=value pairs representing the destination for event groups. "
    "Allowed arguments include: `key` for BrokerStateStore; `path` for Storage; or "
    f"`topic`, `retain`, `qos`, and `ttl` for MQTT. {DEST_HELP_MQTT_VALUES}"
)

DEST_HELP_EVENT_GROUP_MQTT_ONLY = (
    "Key=value pairs representing the destination for events. "
    "Allowed and required arguments are `topic`, `retain`, `qos`, and `ttl` for MQTT destinations.  "
    f"{DEST_HELP_MQTT_VALUES}"
)

DEST_HELP_STREAM_FULL = (
    "Key=value pairs representing the destination for streams. "
    "Allowed arguments include: `key` for BrokerStateStore; `path` for Storage; or "
    f"`topic`, `retain`, `qos`, and `ttl` for MQTT. {DEST_HELP_MQTT_VALUES}"
)

DEST_HELP_STREAM_STORAGE_OR_MQTT = (
    "Key=value pairs representing the destination for streams. "
    "Allowed arguments include: `path` for Storage; or "
    f"`topic`, `retain`, `qos`, and `ttl` for MQTT. {DEST_HELP_MQTT_VALUES}"
)
