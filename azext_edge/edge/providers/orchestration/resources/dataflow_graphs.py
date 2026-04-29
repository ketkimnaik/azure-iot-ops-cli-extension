# coding=utf-8
# ----------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License file in the project root for license information.
# ----------------------------------------------------------------------------------------------

from typing import TYPE_CHECKING, Iterable, Optional

from rich.console import Console

from azure.cli.core.azclierror import InvalidArgumentValueError
from azure.core.exceptions import ResourceNotFoundError

from ....util.az_client import wait_for_terminal_state
from ....util.common import should_continue_prompt
from ....util.queryable import Queryable
from ..common import (
    DATAFLOW_ENDPOINT_TYPE_SETTINGS,
    KAFKA_ENDPOINT_TYPE,
    MQTT_ENDPOINT_TYPE,
    OPENTELEMETRY_ENDPOINT_TYPE,
)
from .instances import Instances
from .reskit import get_file_config

console = Console()

# Endpoint types supported in data flow graphs (explicit allow-list).
# MQTT, Kafka, and OpenTelemetry are supported.
# All other types (DataExplorer, DataLakeStorage, FabricOneLake, LocalStorage, etc.) are not.
_GRAPH_SUPPORTED_ENDPOINT_TYPES = frozenset([
    MQTT_ENDPOINT_TYPE,
    KAFKA_ENDPOINT_TYPE,
    OPENTELEMETRY_ENDPOINT_TYPE,
])


if TYPE_CHECKING:
    from ....vendor.clients.iotopsmgmt.operations import (
        DataflowEndpointOperations,
        DataflowGraphOperations,
    )


class DataFlowGraphs(Queryable):
    def __init__(self, cmd):
        super().__init__(cmd=cmd)
        self.instances = Instances(cmd=cmd)
        self.iotops_mgmt_client = self.instances.iotops_mgmt_client
        self.ops: "DataflowGraphOperations" = self.iotops_mgmt_client.dataflow_graph
        self.ops_endpoint: "DataflowEndpointOperations" = self.iotops_mgmt_client.dataflow_endpoint

    def show(
        self,
        name: str,
        dataflow_profile_name: str,
        instance_name: str,
        resource_group_name: str,
    ) -> dict:
        return self.ops.get(
            resource_group_name=resource_group_name,
            instance_name=instance_name,
            dataflow_profile_name=dataflow_profile_name,
            dataflow_graph_name=name,
        )

    def list(
        self,
        dataflow_profile_name: str,
        instance_name: str,
        resource_group_name: str,
    ) -> Iterable[dict]:
        return self.ops.list_by_dataflow_profile(
            resource_group_name=resource_group_name,
            instance_name=instance_name,
            dataflow_profile_name=dataflow_profile_name,
        )

    def apply(
        self,
        name: str,
        dataflow_profile_name: str,
        instance_name: str,
        resource_group_name: str,
        config_file: str,
        **kwargs,
    ) -> dict:
        resource = {}
        graph_config = get_file_config(config_file)
        resource["extendedLocation"] = self.instances.get_ext_loc(
            name=instance_name,
            resource_group_name=resource_group_name,
        )
        resource["properties"] = graph_config

        self._validate_graph_config(graph_config, instance_name, resource_group_name)

        with console.status("Working..."):
            poller = self.ops.begin_create_or_update(
                resource_group_name=resource_group_name,
                instance_name=instance_name,
                dataflow_profile_name=dataflow_profile_name,
                dataflow_graph_name=name,
                resource=resource,
            )
            return wait_for_terminal_state(poller, **kwargs)

    def _validate_graph_config(  # noqa: C901
        self,
        graph_config: dict,
        instance_name: str,
        resource_group_name: str,
    ):
        VALID_NODE_TYPES = {"Source", "Graph", "Destination"}

        nodes = graph_config.get("nodes", [])
        if not nodes:
            raise InvalidArgumentValueError(
                "'nodes' is required and must contain at least one node in the dataflow graph config."
            )

        declared_names = set()
        for i, node in enumerate(nodes):
            node_name = node.get("name", "")
            node_type = node.get("nodeType", "")

            if not node_name:
                raise InvalidArgumentValueError(
                    f"Node at index {i} is missing a 'name'."
                )
            if not node_type:
                raise InvalidArgumentValueError(
                    f"Node '{node_name}' is missing a 'nodeType'."
                )
            if node_type not in VALID_NODE_TYPES:
                raise InvalidArgumentValueError(
                    f"Node '{node_name}' has invalid nodeType '{node_type}'. "
                    f"Valid nodeType values are: {', '.join(sorted(VALID_NODE_TYPES))}."
                )
            if node_name in declared_names:
                raise InvalidArgumentValueError(
                    f"Duplicate node name '{node_name}' found at index {i}. "
                    "Each node in the dataflow graph config must have a unique 'name'."
                )
            declared_names.add(node_name)

        source_nodes = [n for n in nodes if n.get("nodeType") == "Source"]
        destination_nodes = [n for n in nodes if n.get("nodeType") == "Destination"]

        if not source_nodes:
            raise InvalidArgumentValueError(
                "The dataflow graph config must contain at least one node with nodeType 'Source'."
            )
        if not destination_nodes:
            raise InvalidArgumentValueError(
                "The dataflow graph config must contain at least one node with nodeType 'Destination'."
            )

        node_connections = graph_config.get("nodeConnections", [])
        for i, conn in enumerate(node_connections):
            from_val = conn.get("from", {})
            to_val = conn.get("to", {})
            from_name = from_val.get("name", "") if isinstance(from_val, dict) else from_val
            to_name = to_val.get("name", "") if isinstance(to_val, dict) else to_val
            if from_name and from_name not in declared_names:
                raise InvalidArgumentValueError(
                    f"nodeConnection at index {i} references unknown 'from' node '{from_name}'. "
                    f"Declared node names: {', '.join(sorted(declared_names))}."
                )
            if to_name and to_name not in declared_names:
                raise InvalidArgumentValueError(
                    f"nodeConnection at index {i} references unknown 'to' node '{to_name}'. "
                    f"Declared node names: {', '.join(sorted(declared_names))}."
                )

        # Cache endpoint lookups to avoid repeated GETs for the same endpointRef
        endpoint_cache: dict = {}

        def get_endpoint_cached(endpoint_ref: str) -> dict:
            if endpoint_ref not in endpoint_cache:
                endpoint_cache[endpoint_ref] = self._get_endpoint(
                    endpoint_ref, instance_name, resource_group_name
                )
            return endpoint_cache[endpoint_ref]

        # Validate each source node's endpoint
        for node in source_nodes:
            source_settings = node.get("sourceSettings", {})
            endpoint_ref = source_settings.get("endpointRef", "")
            if not endpoint_ref:
                raise InvalidArgumentValueError(
                    f"Source node '{node.get('name')}' is missing 'sourceSettings.endpointRef'."
                )
            endpoint_obj = get_endpoint_cached(endpoint_ref)
            endpoint_props = endpoint_obj.get("properties", {})
            endpoint_type = endpoint_props.get("endpointType", "")

            if endpoint_type and endpoint_type not in _GRAPH_SUPPORTED_ENDPOINT_TYPES:
                raise InvalidArgumentValueError(
                    f"Source node '{node.get('name')}' references endpoint '{endpoint_ref}' "
                    f"of type '{endpoint_type}', which is not supported in data flow graphs. "
                    f"Supported endpoint types are: "
                    f"{', '.join(sorted(_GRAPH_SUPPORTED_ENDPOINT_TYPES))}."
                )
            if endpoint_type == OPENTELEMETRY_ENDPOINT_TYPE:
                raise InvalidArgumentValueError(
                    f"Source node '{node.get('name')}' references OpenTelemetry endpoint '{endpoint_ref}'. "
                    f"OpenTelemetry is a destination-only endpoint type and cannot be used as a source."
                )

            # Kafka source endpoints require a consumerGroupId on the endpoint
            if DATAFLOW_ENDPOINT_TYPE_SETTINGS.get(endpoint_type) == "kafkaSettings":
                consumer_group_id = endpoint_props.get("kafkaSettings", {}).get("consumerGroupId", "")
                if not consumer_group_id:
                    raise InvalidArgumentValueError(
                        f"Source node '{node.get('name')}' references Kafka endpoint '{endpoint_ref}', "
                        f"but the endpoint does not have 'kafkaSettings.consumerGroupId' set. "
                        f"A consumer group ID is required for Kafka source endpoints."
                    )

        # Validate each destination node's endpoint
        for node in destination_nodes:
            dest_settings = node.get("destinationSettings", {})
            endpoint_ref = dest_settings.get("endpointRef", "")
            if not endpoint_ref:
                raise InvalidArgumentValueError(
                    f"Destination node '{node.get('name')}' is missing 'destinationSettings.endpointRef'."
                )
            endpoint_obj = get_endpoint_cached(endpoint_ref)
            endpoint_type = endpoint_obj.get("properties", {}).get("endpointType", "")

            if endpoint_type and endpoint_type not in _GRAPH_SUPPORTED_ENDPOINT_TYPES:
                raise InvalidArgumentValueError(
                    f"Destination node '{node.get('name')}' references endpoint '{endpoint_ref}' "
                    f"of type '{endpoint_type}', which is not supported in data flow graphs. "
                    f"Supported endpoint types are: "
                    f"{', '.join(sorted(_GRAPH_SUPPORTED_ENDPOINT_TYPES))}."
                )

    def _get_endpoint(
        self,
        endpoint_name: str,
        instance_name: str,
        resource_group_name: str,
    ) -> dict:
        """Fetch a dataflow endpoint by name, raising a clear error if not found."""
        try:
            endpoint_obj = self.ops_endpoint.get(
                instance_name=instance_name,
                resource_group_name=resource_group_name,
                dataflow_endpoint_name=endpoint_name,
            )
        except ResourceNotFoundError:
            endpoint_obj = None
        if not endpoint_obj:
            raise ResourceNotFoundError(
                f"Dataflow endpoint '{endpoint_name}' not found in instance '{instance_name}'. "
                "Please provide a valid 'endpointRef' using --config-file."
            )
        return endpoint_obj

    def delete(
        self,
        name: str,
        dataflow_profile_name: str,
        instance_name: str,
        resource_group_name: str,
        confirm_yes: Optional[bool] = None,
        **kwargs,
    ):
        should_bail = not should_continue_prompt(confirm_yes=confirm_yes)
        if should_bail:
            return

        with console.status("Working..."):
            poller = self.ops.begin_delete(
                resource_group_name=resource_group_name,
                instance_name=instance_name,
                dataflow_profile_name=dataflow_profile_name,
                dataflow_graph_name=name,
            )
            return wait_for_terminal_state(poller, **kwargs)
