# Copyright (c) 2024, Peter Magnusson <me@kmpm.se>
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later


from unittest.mock import patch
from ansible.module_utils import basic
from ansible_collections.kmpm.incus.plugins.modules import incus_instance
from ansible_collections.community.general.tests.unit.plugins.modules.utils import (
    AnsibleExitJson,
    ModuleTestCase,
    set_module_args,
)

from .clients import MockClient

mcli = MockClient()


def mock_execute(client, *args, **kwargs):
    return mcli.execute(client, *args, **kwargs)


def fake_bin_path(arg1):
    return "/usr/bin/incus"


@patch(
    "ansible_collections.kmpm.incus.plugins.module_utils.incuscli.get_bin_path",
    fake_bin_path,
)
@patch(
    "ansible_collections.kmpm.incus.plugins.modules.incus_instance.IncusClient._execute",
    mock_execute,
)
class IncusInstanceTestCase(ModuleTestCase):
    module = incus_instance

    def setUp(self):
        super(IncusInstanceTestCase, self).setUp()
        # ansible-core 2.20+ requires _ANSIBLE_PROFILE to be set
        self.mock_profile = patch.object(basic, "_ANSIBLE_PROFILE", "legacy")
        self.mock_profile.start()
        ansible_module_path = "ansible_collections.kmpm.incus.plugins.modules.incus_instance.AnsibleModule"
        self.mock_run_command = patch("%s.run_command" % ansible_module_path)
        self.module_main_command = self.mock_run_command.start()

    def tearDown(self):
        self.mock_run_command.stop()
        self.mock_profile.stop()
        super(IncusInstanceTestCase, self).tearDown()

    def module_main(self, exit_exc):
        with self.assertRaises(exit_exc) as exc:
            self.module.main()
        return exc.exception.args[0]

    def test_absent(self):
        with set_module_args({"name": "testinstance", "state": "absent"}):
            self.module_main_command.side_effect = [
                (0, "{}", ""),
                (0, "{}", ""),
            ]
            result = self.module_main(AnsibleExitJson)
            self.assertFalse(result["changed"], result)

    def test_started_container(self):
        with set_module_args(
            {
                "name": "testinstance",
                "state": "started",
                "source": {
                    "type": "image",
                    "alias": "debian/12/cloud",
                    "server": "https://images.linuxcontainers.org",
                    "protocol": "simplestreams",
                    "mode": "pull",
                },
            }
        ):
            self.module_main_command.side_effect = [
                (0, "{}", ""),
                (0, "{}", ""),
            ]
            result = self.module_main(AnsibleExitJson)
            print("result", result)
            self.assertTrue(result["changed"], result)

    def test_started_vm(self):
        with set_module_args(
            {
                "name": "testvm",
                "state": "started",
                "source": {
                    "type": "image",
                    "alias": "debian/12/cloud",
                    "server": "https://images.linuxcontainers.org",
                    "protocol": "simplestreams",
                    "mode": "pull",
                },
                "type": "virtual-machine",
            }
        ):
            result = self.module_main(AnsibleExitJson)
            print("result", result)
            self.assertTrue(result["changed"], result)
