#!/usr/bin/python
# (c) 2024, Peter Magnusson <me@kmpm.se>
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

DOCUMENTATION = """
---
module: incus_info
author: "Simon Bernier St-Pierre (@sbstp)"
short_description: Get information about incus objects
description:
  - Get information about incus objects
options:
    remote:
        description: The remote to use for the Incus CLI.
        type: str
        default: local
    project:
        description:
            - Project to get network information from
        type: str
        default: default
    name:
        description:
            - Name of the object. If empty, all objects of this C(type) will be returned.
        type: str
        required: false
    type:
        description:
            - Type of object to get info about.
        type: str
        required: true
        choices:
            - image
            - image_alias
            - instance
            - network
            - network_acl
            - profile
            - storage
"""

RETURN = """
object:
    description: When name is used to select a specific object
    type: dict
    returned: success
objects:
    description: When name is not used and all the objects of C(type) are returned.
    type: list
    elements: dict
    returned: success
name:
    description: Same value as input name, if specified
    type: str
    returned: success
"""

EXAMPLES = """
- host: localhost
  connection: local
  tasks:
    - name: Get all networks
      sbstp.incus.incus_info:
          type: network
      register: networks_info
    - name: Get default storage pool
      sbstp.incus.incus_info:
          type: storage
          name: default
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.sbstp.incus.plugins.module_utils.incuscli import (
    IncusClient,
)


class _ObjectDef:
    def __init__(self, type, path, can_select=True, can_list=True):
        self.type = type
        self.path = path
        self.can_select = can_select
        self.can_list = can_list


_OBJECTS = [
    _ObjectDef("image", "images", can_select=False),
    _ObjectDef("image_alias", "image/aliases"),
    _ObjectDef("instance", "instances"),
    _ObjectDef("network", "networks"),
    _ObjectDef("network_acl", "network-acls"),
    _ObjectDef("profile", "profiles"),
    _ObjectDef("storage", "storage-pools"),
]
_OBJECT_MAP = {x.type: x for x in _OBJECTS}


def main():
    """Ansible Main module."""

    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type="str", required=False),
            remote=dict(type="str", default="local"),
            project=dict(type="str", default="default"),
            type=dict(
                type="str",
                required=True,
                choices=[x.type for x in _OBJECTS],
            ),
        ),
        supports_check_mode=True,
    )

    name = module.params["name"]
    remote = module.params["remote"]
    project = module.params["project"]
    type = module.params["type"]

    result = dict(
        changed=False,
        name=name,
    )
    try:
        client = IncusClient(project=project, remote=remote, debug=True)
        obj = _OBJECT_MAP[type]
        if name:
            if not obj.can_select:
                raise Exception(f"cannot select objects of type {obj.type} by name")
            req_url = f"/1.0/{obj.path}/{name}"
        else:
            if not obj.can_list:
                raise Exception(f"cannot list objects of type {obj.type}")
            req_url = f"/1.0/{obj.path}?recursion=1"
        data = client.query_raw_checked("GET", req_url)
        status_code = data.get("status_code", 500)
        if status_code == 404:
            raise Exception("object not found")
        elif status_code != 200:
            raise Exception(f"error fetching information (status_code={status_code}")
        if name:
            result["object"] = data["metadata"]
        else:
            result["objects"] = data["metadata"]
        module.exit_json(**result)
    except Exception as e:
        module.fail_json(repr(e), exception=e, **result)


if __name__ == "__main__":
    main()
