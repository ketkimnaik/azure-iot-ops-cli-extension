# coding=utf-8
# ----------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License file in the project root for license information.
# ----------------------------------------------------------------------------------------------

import pytest
from kubernetes.client.exceptions import ApiException

from azext_edge.edge.providers.base import (
    ClusterAccessDeniedError,
    get_custom_objects,
    reraise_cluster_access_errors,
)
from azext_edge.edge.providers.check.base.deployment import (
    _build_access_denied_result,
    check_post_deployment,
)
from azext_edge.edge.providers.check.base.resource import (
    enumerate_ops_service_resources,
    get_resources_by_name,
)
from azext_edge.edge.providers.check.common import CoreServiceResourceKinds
from azext_edge.edge.providers.check.summary import check_summary
from azext_edge.edge.providers.edge_api import MQ_ACTIVE_API, EdgeResourceApi


def _mock_custom_objects_api(mocker, status: int):
    api = mocker.Mock()
    api.list_namespaced_custom_object.side_effect = ApiException(status=status, reason="denied")
    api.list_cluster_custom_object.side_effect = ApiException(status=status, reason="denied")
    mocker.patch("azext_edge.edge.providers.base.client.CustomObjectsApi", return_value=api)
    return api


def _display_text(result: dict, target: str) -> str:
    displays = result["targets"][target]["_all_"].get("displays", [])
    return " ".join(str(getattr(d, "renderable", d)) for d in displays)


@pytest.mark.parametrize("status", [401, 403])
def test_get_custom_objects_raises_within_context(mocker, status):
    # Within the check context, a 401/403 read must raise ClusterAccessDeniedError (propagation gate).
    _mock_custom_objects_api(mocker, status)
    with reraise_cluster_access_errors():
        with pytest.raises(ClusterAccessDeniedError) as exc_info:
            get_custom_objects(group="g", version="v", plural="widgets", namespace="ns", use_cache=False)
    assert exc_info.value.status == status
    assert exc_info.value.resource == "widgets"


@pytest.mark.parametrize("status", [401, 403])
def test_get_custom_objects_swallows_outside_context(mocker, status):
    # Outside the check context, behavior is unchanged (tolerant): returns None, never raises.
    _mock_custom_objects_api(mocker, status)
    assert get_custom_objects(group="g", version="v", plural="widgets", namespace="ns", use_cache=False) is None


def test_get_resources_by_name_propagates_403(mocker):
    # A 403 originating at the client must flow through get_resources_by_name as ClusterAccessDeniedError,
    # labeled with the actual plural being read.
    _mock_custom_objects_api(mocker, 403)
    api = EdgeResourceApi(group="deviceregistry.microsoft.com", version="v1", moniker="deviceregistry")
    api._kinds = {"asset": "assets"}
    with reraise_cluster_access_errors():
        with pytest.raises(ClusterAccessDeniedError) as exc_info:
            get_resources_by_name(api_info=api, kind="asset", resource_name=None)
    assert exc_info.value.status == 403
    assert exc_info.value.resource == "assets"


@pytest.mark.parametrize("status", [401, 403])
def test_check_post_deployment_builds_access_denied_result(status):
    # An evaluator raising ClusterAccessDeniedError yields a per-resource access-denied result
    # (with the accessDenied marker) instead of aborting the command.
    def denied_evaluator(**kwargs):
        raise ClusterAccessDeniedError(status=status, resource="brokers")

    results = check_post_deployment(
        evaluate_funcs={CoreServiceResourceKinds.RUNTIME_RESOURCE: denied_evaluator},
        as_list=True,
    )
    assert len(results) == 1
    result = results[0]
    assert result["accessDenied"] == status
    assert result["status"] == "error"
    assert "reading 'brokers'" in str(result["targets"]["brokers"]["_all_"]["evaluations"][0]["value"])


@pytest.mark.parametrize(
    "status, expected_phrase, unexpected_phrase",
    [
        (403, "lacks permission", "authenticate"),
        (401, "authenticate", "lacks permission"),
    ],
)
def test_build_access_denied_result_wording(status, expected_phrase, unexpected_phrase):
    # 403 asserts a permissions cause; 401 (authentication) must not.
    error = ClusterAccessDeniedError(status=status, resource="assetendpointprofiles")
    result = _build_access_denied_result(CoreServiceResourceKinds.RUNTIME_RESOURCE, error, as_list=True)
    assert result["accessDenied"] == status
    # Nested read: the result names the actual denied resource, not the outer evaluator kind.
    assert "assetendpointprofiles" in result["targets"]
    text = _display_text(result, "assetendpointprofiles")
    assert expected_phrase in text
    assert unexpected_phrase not in text


@pytest.mark.parametrize("status", [401, 403])
def test_enumerate_discovery_access_denied(mocker, status):
    # A denied API-discovery call produces an access-denied enumeration result with the marker,
    # rather than the misleading "API resources not detected".
    mocker.patch(
        "azext_edge.edge.providers.check.base.resource.get_cluster_custom_api",
        side_effect=ClusterAccessDeniedError(status=status, resource=f"{MQ_ACTIVE_API.group}/{MQ_ACTIVE_API.version}"),
    )
    result, resource_map = enumerate_ops_service_resources(
        api_info=MQ_ACTIVE_API,
        check_name="mq",
        check_desc="MQ",
        as_list=True,
    )
    assert result["accessDenied"] == status
    assert not resource_map
    assert result["status"] == "error"


def test_summary_footer_flips_on_access_denied(mocker):
    # When a service reports an access-denied resource, the summary footer flips to the
    # permissions/access-denied footer instead of the generic "See details" one.
    denied_service_result = [
        {
            "name": "evalBrokerAccess",
            "description": "Evaluate Broker",
            "status": "error",
            "targets": {"brokers": {"_all_": {"status": "error", "evaluations": [], "conditions": None}}},
            "accessDenied": 403,
        }
    ]
    healthy_service_result = [
        {
            "name": "svc",
            "description": "Evaluate service",
            "status": "success",
            "targets": {"svc": {"_all_": {"status": "success", "evaluations": [], "conditions": None}}},
        }
    ]

    mocker.patch("azext_edge.edge.providers.check.mq.check_post_deployment", return_value=denied_service_result)
    mocker.patch("azext_edge.edge.providers.check.akri.check_post_deployment", return_value=healthy_service_result)
    mocker.patch(
        "azext_edge.edge.providers.check.deviceregistry.check_post_deployment",
        return_value=healthy_service_result,
    )
    mocker.patch("azext_edge.edge.providers.check.opcua.check_post_deployment", return_value=healthy_service_result)
    mocker.patch("azext_edge.edge.providers.check.dataflow.check_post_deployment", return_value=healthy_service_result)

    result = check_summary(resource_name=None, resource_kinds=None, as_list=True)

    broker_text = _display_text(result, MQ_ACTIVE_API.as_str())
    assert "access denied" in broker_text.lower()
    # generic footer should not be used for the denied service
    assert "See details by running" not in broker_text
