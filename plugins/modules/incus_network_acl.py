#!/usr/bin/python
# (c) 2026, Simon Bernier St-Pierre <git.sbstp.ca@gmail.com>
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

DOCUMENTATION = r"""
---
module: incus_network_acl
author: "Simon Bernier St-Pierre (@sbstp)"
short_description: Manage Incus Network ACL resources
description:
  - Management of Incus Network ACL resources
options:
    name:
        description:
            - Name of the network ACL
        type: str
        required: true
    remote:
        description:
            - The remote to use for the Incus CLI.
        type: str
        default: local
    project:
        description:
            - Project to manage the network ACL in
        type: str
        default: default
    description:
        description:
            - Description of the network ACL
        type: str
        required: false
    config:
        description:
            - Configuration options as key/value pairs (only C(user.*) custom keys supported)
        type: dict
        required: false
        default: {}
    ingress:
        description:
            - List of ingress traffic rules
        type: list
        elements: dict
        required: false
        suboptions:
            action:
                description:
                    - Action to take for matching traffic
                type: str
                choices: [allow, allow-stateless, reject, drop]
            state:
                description:
                    - State of the rule
                type: str
                required: false
                choices: [enabled, disabled, logged]
            description:
                description:
                    - Description of the rule
                type: str
                required: false
            source:
                description:
                    - Comma-separated list of CIDR or IP ranges, source subject name selectors (for ingress rules), or empty for any
                type: str
                required: false
            destination:
                description:
                    - Comma-separated list of CIDR or IP ranges, destination subject name selectors (for egress rules), or empty for any
                type: str
                required: false
            protocol:
                description:
                    - Protocol to match (C(icmp4), C(icmp6), C(tcp), C(udp)) or empty string for any
                type: str
                required: false
                choices: ['', icmp4, icmp6, tcp, udp]
            source_port:
                description:
                    - If protocol is C(udp) or C(tcp), a comma-separated list of ports or port ranges (start-end inclusive), or empty for any
                type: str
                required: false
            destination_port:
                description:
                    - If protocol is C(udp) or C(tcp), a comma-separated list of ports or port ranges (start-end inclusive), or empty for any
                type: str
                required: false
            icmp_type:
                description:
                    - If protocol is C(icmp4) or C(icmp6), the ICMP type number, or empty for any
                type: str
                required: false
            icmp_code:
                description:
                    - If protocol is C(icmp4) or C(icmp6), the ICMP code number, or empty for any
                type: str
                required: false
    egress:
        description:
            - List of egress traffic rules
        type: list
        elements: dict
        required: false
        suboptions:
            action:
                description:
                    - Action to take for matching traffic
                type: str
                choices: [allow, allow-stateless, reject, drop]
            state:
                description:
                    - State of the rule
                type: str
                required: false
                choices: [enabled, disabled, logged]
            description:
                description:
                    - Description of the rule
                type: str
                required: false
            source:
                description:
                    - Comma-separated list of CIDR or IP ranges, source subject name selectors (for ingress rules), or empty for any
                type: str
                required: false
            destination:
                description:
                    - Comma-separated list of CIDR or IP ranges, destination subject name selectors (for egress rules), or empty for any
                type: str
                required: false
            protocol:
                description:
                    - Protocol to match (C(icmp4), C(icmp6), C(tcp), C(udp)) or empty string for any
                type: str
                required: false
                choices: ['', icmp4, icmp6, tcp, udp]
            source_port:
                description:
                    - If protocol is C(udp) or C(tcp), a comma-separated list of ports or port ranges (start-end inclusive), or empty for any
                type: str
                required: false
            destination_port:
                description:
                    - If protocol is C(udp) or C(tcp), a comma-separated list of ports or port ranges (start-end inclusive), or empty for any
                type: str
                required: false
            icmp_type:
                description:
                    - If protocol is C(icmp4) or C(icmp6), the ICMP type number, or empty for any
                type: str
                required: false
            icmp_code:
                description:
                    - If protocol is C(icmp4) or C(icmp6), the ICMP code number, or empty for any
                type: str
                required: false
    state:
        description:
            - State of the network ACL
        type: str
        choices: [present, absent]
        default: present
"""

EXAMPLES = r"""
- name: Create a network ACL with ingress and egress rules
  sbstp.incus.incus_network_acl:
    name: my-acl
    description: My network ACL
    ingress:
      - action: allow
        source: 10.0.0.0/8
        protocol: tcp
        destination_port: "80,443"
    egress:
      - action: allow-stateless
        destination: 0.0.0.0/0
        protocol: tcp
        source_port: "80,443"
    state: present

- name: Delete a network ACL
  sbstp.incus.incus_network_acl:
    name: my-acl
    state: absent
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.sbstp.incus.plugins.module_utils.incuscli import (
    IncusClient,
    Patch,
)

SUPPORTED_FIELDS = {"name", "description", "ingress", "egress", "config"}


class IncusNetworkAclManagement(object):
    def __init__(self, module):
        self.module = module
        self.name = self.module.params["name"]
        remote = self.module.params["remote"]
        project = module.params["project"]
        description = self.module.params["description"]
        ingress = self.module.params["ingress"]
        egress = self.module.params["egress"]
        config = self.module.params["config"]
        next_state = self.module.params["state"]

        self.client = IncusClient(project=project, remote=remote)
        self.actions = []

        current = self.client.get_network_acl(self.name)
        self.patch = Patch(
            current=current,
            supported_fields=SUPPORTED_FIELDS,
            patch=dict(
                name=self.name,
                description=description,
                ingress=ingress,
                egress=egress,
                config=config,
            ),
            next_state=next_state,
        )

    def run(self):
        patch = self.patch
        if patch.is_created():
            if not self.module.check_mode:
                self.client.query_raw_checked(
                    "POST", "/1.0/network-acls", patch.payload
                )
            self.actions.append("create")
        elif patch.is_updated():
            if not self.module.check_mode:
                self.client.query_raw_checked(
                    "PATCH", "/1.0/network-acls/{0}".format(self.name), patch.payload
                )
            self.actions.append("update")
        elif patch.is_deleted():
            if not self.module.check_mode:
                self.client.query_raw_checked(
                    "DELETE", "/1.0/network-acls/{0}".format(self.name)
                )
            self.actions.append("delete")

        return self.state()

    def state(self):
        return self.patch.result(actions=self.actions)


def main():
    props = dict(
        action=dict(
            type="str",
            choices=["allow", "allow-stateless", "reject", "drop"],
            required=False,
        ),
        state=dict(
            type="str", choices=["enabled", "disabled", "logged"], required=False
        ),
        description=dict(type="str", required=False),
        source=dict(type="str", required=False),
        destination=dict(type="str", required=False),
        protocol=dict(
            type="str", choices=["", "icmp4", "icmp6", "tcp", "udp"], required=False
        ),
        source_port=dict(type="str", required=False),
        destination_port=dict(type="str", required=False),
        icmp_type=dict(type="str", required=False),
        icmp_code=dict(type="str", required=False),
    )
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type="str", required=True),
            remote=dict(type="str", default="local"),
            project=dict(type="str", default="default"),
            description=dict(type="str", required=False),
            ingress=dict(type="list", elements="dict", options=props),
            egress=dict(type="list", elements="dict", options=props),
            config=dict(type="dict", required=False, default={}),
            state=dict(type="str", choices=["present", "absent"], default="present"),
        ),
        supports_check_mode=True,
    )
    incus = IncusNetworkAclManagement(module)
    try:
        module.exit_json(**incus.run())
    except Exception as e:
        module.fail_json(
            {
                "error": str(e),
                **incus.state(),
            }
        )


if __name__ == "__main__":
    main()
