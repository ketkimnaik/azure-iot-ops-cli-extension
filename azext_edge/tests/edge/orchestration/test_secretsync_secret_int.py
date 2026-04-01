# coding=utf-8
# ----------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License file in the project root for license information.
# ----------------------------------------------------------------------------------------------

import pytest
from knack.log import get_logger
from typing import List

from azure.cli.core.azclierror import CLIInternalError

from ...generators import generate_random_string
from ...helpers import run

logger = get_logger(__name__)
SYNC_WAIT_SEC = 15
MAX_RETRIES = 5

# pytest mark for rpsaas (cloud-side) tests
pytestmark = pytest.mark.rpsaas


@pytest.fixture
def secretsync_secret_int_setup(settings, tracked_resources: List[str]):
    """
    Setup fixture that ensures:
    - An instance with secretsync enabled exists.
    - A test AKV secret is available for syncing.
    Returns dict with resourceGroup, instanceName, keyvaultName, etc.
    """
    from ...settings import EnvironmentVariables

    settings.add_to_config(EnvironmentVariables.rg.value)
    settings.add_to_config(EnvironmentVariables.instance.value)
    settings.add_to_config(EnvironmentVariables.kv.value)

    if not all([settings.env.azext_edge_instance, settings.env.azext_edge_rg]):
        pytest.skip("Cannot run secretsync secret tests without an instance and resource group.")
    if not settings.env.azext_edge_kv:
        pytest.skip("Cannot run secretsync secret tests without a keyvault id.")

    instance_name = settings.env.azext_edge_instance
    resource_group = settings.env.azext_edge_rg
    kv_id = settings.env.azext_edge_kv
    kv_name = kv_id.rsplit("/", maxsplit=1)[-1]

    # Verify secretsync is enabled
    list_result = run(f"az iot ops secretsync list -n {instance_name} -g {resource_group}")
    if not list_result:
        pytest.skip("Secretsync is not enabled on the instance. Enable it first.")

    # Create test AKV secrets for use in tests
    test_secrets = {}
    for i in range(3):
        secret_name = f"clitest{generate_random_string(size=8, force_lower=True)}"
        secret_value = generate_random_string(size=32)
        try:
            run(
                f"az keyvault secret set --vault-name {kv_name} --name {secret_name} "
                f"--value {secret_value}"
            )
            test_secrets[secret_name] = secret_value
        except CLIInternalError as e:
            logger.warning(f"Failed to create test secret {secret_name}: {e.error_msg}")

    if len(test_secrets) < 2:
        pytest.skip("Could not create enough test secrets in the Key Vault.")

    yield {
        "resourceGroup": resource_group,
        "instanceName": instance_name,
        "keyvaultName": kv_name,
        "testSecrets": test_secrets,
    }

    # Cleanup: remove test secrets from AKV
    for secret_name in test_secrets:
        try:
            run(f"az keyvault secret delete --vault-name {kv_name} --name {secret_name}")
        except CLIInternalError:
            logger.warning(f"Failed to delete test secret {secret_name}")


@pytest.mark.require_wlif_setup
def test_secretsync_secret_set_list_unset(
    cluster_connection,
    secretsync_secret_int_setup,
):
    """End-to-end test: set, list, merge, unset secrets in SecretSync."""
    resource_group = secretsync_secret_int_setup["resourceGroup"]
    instance_name = secretsync_secret_int_setup["instanceName"]
    test_secrets = secretsync_secret_int_setup["testSecrets"]
    secret_names = list(test_secrets.keys())

    # Use a unique SecretSync name for this test
    sync_name = f"cli-test-sync-{generate_random_string(size=6, force_lower=True)}"

    try:
        # --- Step 1: Set a single secret ---
        first_secret = secret_names[0]
        set_result = run(
            f"az iot ops secretsync secret set "
            f"--instance {instance_name} -g {resource_group} "
            f"--secret-sync-name {sync_name} "
            f"--secret-name {first_secret}=certificate"
        )
        assert set_result is not None
        assert set_result["name"] == sync_name
        mappings = set_result.get("properties", {}).get("objectSecretMapping", [])
        assert len(mappings) == 1
        assert mappings[0]["sourcePath"] == first_secret
        assert mappings[0]["targetKey"] == "certificate"

        # --- Step 2: List secrets ---
        list_result = run(
            f"az iot ops secretsync secret list "
            f"--instance {instance_name} -g {resource_group} "
            f"--secret-sync-name {sync_name}"
        )
        assert list_result is not None
        assert len(list_result) == 1
        assert list_result[0]["sourcePath"] == first_secret

        # --- Step 3: Merge another secret into the same SecretSync ---
        second_secret = secret_names[1]
        merge_result = run(
            f"az iot ops secretsync secret set "
            f"--instance {instance_name} -g {resource_group} "
            f"--secret-sync-name {sync_name} "
            f"--secret-name {second_secret}=privateKey"
        )
        merge_mappings = merge_result.get("properties", {}).get("objectSecretMapping", [])
        assert len(merge_mappings) == 2
        source_paths = {m["sourcePath"] for m in merge_mappings}
        assert first_secret in source_paths
        assert second_secret in source_paths

        # --- Step 4: List again to verify both ---
        list_result2 = run(
            f"az iot ops secretsync secret list "
            f"--instance {instance_name} -g {resource_group} "
            f"--secret-sync-name {sync_name}"
        )
        assert len(list_result2) == 2

        # --- Step 5: Unset one secret ---
        unset_result = run(
            f"az iot ops secretsync secret unset "
            f"--instance {instance_name} -g {resource_group} "
            f"--secret-sync-name {sync_name} "
            f"--secret-name {first_secret} -y"
        )
        assert unset_result is not None
        assert "removed" in unset_result.get("message", "").lower()

        # Verify only the second secret remains
        list_result3 = run(
            f"az iot ops secretsync secret list "
            f"--instance {instance_name} -g {resource_group} "
            f"--secret-sync-name {sync_name}"
        )
        assert len(list_result3) == 1
        assert list_result3[0]["sourcePath"] == second_secret

        # --- Step 6: Unset the last secret (should delete the SecretSync) ---
        unset_last_result = run(
            f"az iot ops secretsync secret unset "
            f"--instance {instance_name} -g {resource_group} "
            f"--secret-sync-name {sync_name} "
            f"--secret-name {second_secret} -y"
        )
        assert unset_last_result is not None
        assert "deleted" in unset_last_result.get("message", "").lower()

    except Exception:
        # Best effort cleanup of the SecretSync if the test fails partway through
        try:
            run(
                f"az iot ops secretsync secret unset "
                f"--instance {instance_name} -g {resource_group} "
                f"--secret-sync-name {sync_name} "
                f"--secret-name {secret_names[0]} -y",
                expect_failure=True,
            )
        except CLIInternalError:
            pass
        try:
            run(
                f"az iot ops secretsync secret unset "
                f"--instance {instance_name} -g {resource_group} "
                f"--secret-sync-name {sync_name} "
                f"--secret-name {secret_names[1]} -y",
                expect_failure=True,
            )
        except CLIInternalError:
            pass
        raise


@pytest.mark.require_wlif_setup
def test_secretsync_secret_set_multiple_at_once(
    cluster_connection,
    secretsync_secret_int_setup,
):
    """Test setting multiple secrets in a single command invocation."""
    resource_group = secretsync_secret_int_setup["resourceGroup"]
    instance_name = secretsync_secret_int_setup["instanceName"]
    test_secrets = secretsync_secret_int_setup["testSecrets"]
    secret_names = list(test_secrets.keys())

    sync_name = f"cli-test-multi-{generate_random_string(size=6, force_lower=True)}"

    try:
        # Set multiple secrets at once
        secret_args = " ".join(
            f"--secret-name {name}=key{i}" for i, name in enumerate(secret_names[:2])
        )
        set_result = run(
            f"az iot ops secretsync secret set "
            f"--instance {instance_name} -g {resource_group} "
            f"--secret-sync-name {sync_name} "
            f"{secret_args}"
        )
        assert set_result is not None
        mappings = set_result.get("properties", {}).get("objectSecretMapping", [])
        assert len(mappings) == 2

        # Cleanup: unset all secrets (last one deletes the SS)
        for name in secret_names[:2]:
            run(
                f"az iot ops secretsync secret unset "
                f"--instance {instance_name} -g {resource_group} "
                f"--secret-sync-name {sync_name} "
                f"--secret-name {name} -y"
            )

    except Exception:
        # Best effort cleanup
        for name in secret_names[:2]:
            try:
                run(
                    f"az iot ops secretsync secret unset "
                    f"--instance {instance_name} -g {resource_group} "
                    f"--secret-sync-name {sync_name} "
                    f"--secret-name {name} -y",
                    expect_failure=True,
                )
            except CLIInternalError:
                pass
        raise


@pytest.mark.require_wlif_setup
def test_secretsync_secret_set_invalid_akv_secret(
    cluster_connection,
    secretsync_secret_int_setup,
):
    """Test that setting a nonexistent AKV secret raises an error."""
    resource_group = secretsync_secret_int_setup["resourceGroup"]
    instance_name = secretsync_secret_int_setup["instanceName"]

    sync_name = f"cli-test-invalid-{generate_random_string(size=6, force_lower=True)}"

    with pytest.raises(CLIInternalError, match="not found in Key Vault"):
        run(
            f"az iot ops secretsync secret set "
            f"--instance {instance_name} -g {resource_group} "
            f"--secret-sync-name {sync_name} "
            f"--secret-name nonexistentsecret{generate_random_string(size=8)}=certificate"
        )


@pytest.mark.require_wlif_setup
def test_secretsync_secret_unset_nonexistent(
    cluster_connection,
    secretsync_secret_int_setup,
):
    """Test that unsetting a nonexistent secret from an existing SecretSync raises an error."""
    resource_group = secretsync_secret_int_setup["resourceGroup"]
    instance_name = secretsync_secret_int_setup["instanceName"]
    test_secrets = secretsync_secret_int_setup["testSecrets"]
    secret_names = list(test_secrets.keys())

    sync_name = f"cli-test-unset-{generate_random_string(size=6, force_lower=True)}"

    try:
        # Create a SecretSync first
        run(
            f"az iot ops secretsync secret set "
            f"--instance {instance_name} -g {resource_group} "
            f"--secret-sync-name {sync_name} "
            f"--secret-name {secret_names[0]}=certificate"
        )

        # Try to unset a secret that doesn't exist in the SecretSync
        with pytest.raises(CLIInternalError, match="not found in SecretSync"):
            run(
                f"az iot ops secretsync secret unset "
                f"--instance {instance_name} -g {resource_group} "
                f"--secret-sync-name {sync_name} "
                f"--secret-name nonexistent_secret -y"
            )

    finally:
        # Cleanup
        try:
            run(
                f"az iot ops secretsync secret unset "
                f"--instance {instance_name} -g {resource_group} "
                f"--secret-sync-name {sync_name} "
                f"--secret-name {secret_names[0]} -y"
            )
        except CLIInternalError:
            pass
