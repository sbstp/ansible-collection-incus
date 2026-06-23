# Copyright (c) Ansible project
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from unittest.mock import patch

import pytest
from ansible_collections.sbstp.incus.plugins.module_utils.incuscli import (
    IncusClient,
    ensure_remote,
)


@patch(
    "ansible_collections.sbstp.incus.plugins.module_utils.incuscli.get_bin_path",
    side_effect=ValueError("boom"),
)
def test_valid_invalid_bin(_get_bin_path):
    # print(dir(_get_bin_path))
    with pytest.raises(ValueError):
        _get_bin_path.return_value = ""
        IncusClient()
        # _get_bin_path.assert_called_once()


@patch(
    "ansible_collections.sbstp.incus.plugins.module_utils.incuscli.get_bin_path",
    autospec=True,
)
def test_instanciation(_get_bin_path):
    _get_bin_path.return_value = "/usr/bin/incus"
    client = IncusClient()
    _get_bin_path.assert_called_once()
    assert client is not None


def test_ensure_remote():
    assert ensure_remote("local") == "local:"
    assert ensure_remote("local:") == "local:"
    with pytest.raises(ValueError):
        ensure_remote("loc al")
