# coding=utf-8
# ----------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License file in the project root for license information.
# ----------------------------------------------------------------------------------------------

from ...common import ListableEnum
from .base import EdgeResourceApi


class IoTOpsResourceKinds(ListableEnum):
    INSTANCE = "instance"


IOTOPS_API_V1 = EdgeResourceApi(group="iotoperations.azure.com", version="v1", moniker="iotops")

IOTOPS_ACTIVE_API = IOTOPS_API_V1
