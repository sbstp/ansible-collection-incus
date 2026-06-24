# Copyright (c) 2026 Simon Bernier St-Pierre
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

DOCUMENTATION = r"""
author: Simon Bernier St-Pierre (@sbstp)
name: ssh_incus2
short_description: Run tasks in Incus instances via SSH (extends the ssh plugin)
description:
  - Extends the built-in C(ssh) connection plugin to run commands inside
    an Incus container on the remote host via C(incus exec) and transfer
    files using C(incus file).
  - The container needs no SSH server running.
  - The Incus daemon's TCP port does not need to be exposed.
  - All standard Ansible modules (copy, template, package, service, etc.)
    work transparently inside the container.
  - All SSH options (host, port, user, key, ControlMaster, etc.) are
    inherited from the C(ssh) plugin and work as usual.
  - See the SSH options at https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/ssh_connection.html
version_added: "1.0.0"
extends_documentation_fragment:
  - ansible.builtin.ssh
options:
  incus_instance:
    description:
      - The Incus instance (container/VM) identifier.
    type: string
    vars:
      - name: ansible_incus_host
      - name: ansible_incus_instance
  incus_user:
    description:
      - The user to use inside the Incus container.
      - This is separate from the SSH user (O(remote_user)) used to
        authenticate to the remote host.
    type: string
    default: root
    vars:
      - name: ansible_incus_user
  incus_executable:
    description:
      - The shell to use inside the Incus container.
    type: string
    default: /bin/sh
    vars:
      - name: ansible_incus_executable
  incus_project:
    description:
      - The Incus project to use (see C(incus project list)).
    type: string
    default: default
    vars:
      - name: ansible_incus_project
  incus_remote:
    description:
      - The Incus remote to use (see C(incus remote list)).
    type: string
    default: local
    vars:
      - name: ansible_incus_remote
  incus_file_transfer_method:
    description:
      - How to transfer files to/from the container.
      - V(piped) pipes the file content through the SSH connection using
        shell redirections.
      - V(temp) copies the file to a temporary location on the remote host
        via SCP, then uses C(incus file push/pull) from there.
    type: string
    default: piped
    choices:
      - piped
      - temp
    vars:
      - name: ansible_incus_file_transfer_method
"""

import os
import shlex

from ansible.errors import AnsibleConnectionFailure, AnsibleError, AnsibleFileNotFound
from ansible.module_utils.common.text.converters import to_bytes
from ansible.plugins.connection.ssh import Connection as SSHConnection


class Connection(SSHConnection):
    """SSH + Incus connection — extends the SSH plugin for Incus containers."""

    transport = "sbstp.incus.ssh_incus2"
    has_pipelining = True

    def __init__(self, play_context, new_stdin, *args, **kwargs):
        super().__init__(play_context, new_stdin, *args, **kwargs)
        self._incus_cmd = "incus"
        self._incus_verified = False

    # ------------------------------------------------------------------
    # Instance helpers
    # ------------------------------------------------------------------

    def _instance_name(self) -> str:
        """Return the Incus instance (container/VM) name."""
        return self.get_option("incus_instance")

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def _connect(self):
        """Open the SSH connection and verify Incus is reachable."""
        super()._connect()

        if self._incus_verified:
            return

        self._display.vvv(
            f"ESTABLISH SSH_INCUS2 CONNECTION FOR INSTANCE: "
            f"{self._instance_name()} "
            f"(incus user={self.get_option('incus_user')})",
            host=self._instance_name(),
        )

        # Test incus availability on the remote host.
        # This also triggers the parent's lazy SSH connection setup
        # (ControlPath, etc.) so self.control_path is available afterwards.
        rc, _stdout, stderr = self._run_incus(["info"])
        if rc != 0:
            raise AnsibleConnectionFailure(
                f"Cannot reach Incus on remote host: {stderr.decode(errors='replace')}"
            )

        self._incus_verified = True

    def close(self):
        """Close the SSH connection."""
        self._incus_verified = False
        super().close()

    # ------------------------------------------------------------------
    # Incus command execution over SSH
    # ------------------------------------------------------------------

    def _run_incus(
        self, incus_args: list[str], in_data: bytes | None = None
    ) -> tuple[int, bytes, bytes]:
        """Run an ``incus`` command on the remote host via the SSH connection.

        Uses the parent's ``exec_command`` with ``sudoable=False`` so the
        command runs directly on the SSH host without become wrapping.
        """
        cmd = shlex.join([self._incus_cmd] + incus_args)

        if self._display.verbosity > 3:
            self._display.vvvv(
                f"ssh_incus2 exec: {cmd}",
                host=self._instance_name(),
            )

        return super().exec_command(cmd, in_data=in_data, sudoable=False)

    # ------------------------------------------------------------------
    # Command execution inside the container
    # ------------------------------------------------------------------

    def _build_incus_exec_cmd(self, cmd: str) -> list[str]:
        """Build the ``incus exec`` argument list for a command."""
        project = self.get_option("incus_project")
        remote = self.get_option("incus_remote")
        executable = self.get_option("incus_executable") or "/bin/sh"
        container_user = self.get_option("incus_user") or "root"

        incus_args: list[str] = [
            "--project",
            project,
            "exec",
            f"{remote}:{self._instance_name()}",
            "--",
        ]

        # If the container user is not root, use su to switch
        if container_user != "root":
            incus_args.extend(["su", "-", container_user, "-c"])

        incus_args.extend([executable, "-c", cmd])

        return incus_args

    def exec_command(
        self,
        cmd: str,
        in_data: bytes | None = None,
        sudoable: bool = True,
    ) -> tuple[int, bytes, bytes]:
        """Execute a command inside the Incus container.

        The command is wrapped in ``shell -c`` and forwarded over SSH to the
        remote host, which runs it via ``incus exec``.

        If *sudoable* is ``True`` and become is enabled, the command runs
        in the become context inside the container.
        """
        # Call ConnectionBase (not SSHConnection) for bookkeeping only.
        # The actual SSH execution happens in _run_incus() below.
        super(SSHConnection, self).exec_command(cmd, in_data=in_data, sudoable=sudoable)

        # Incorporate become if needed (inside the container, not on the SSH host)
        if sudoable and self.become:
            cmd = self.become.build_become_command(cmd, self._shell)

        self._display.vvv(
            f"EXEC {self._instance_name()} {cmd[:120]}{'...' if len(cmd) > 120 else ''}",
            host=self._instance_name(),
        )

        incus_args = self._build_incus_exec_cmd(cmd)

        if self._display.verbosity > 3:
            self._display.vvvv(
                f"EXEC incus args: {shlex.join(incus_args)}",
                host=self._instance_name(),
            )

        rc, stdout, stderr = self._run_incus(incus_args, in_data=in_data)

        # Translate common errors
        err_text = stderr.decode(errors="replace").strip()
        if err_text.startswith("Error: ") and "Instance is not running" in err_text:
            raise AnsibleConnectionFailure(
                f"instance not running: {self._instance_name()}"
            )
        if err_text.startswith("Error: ") and "Instance not found" in err_text:
            raise AnsibleConnectionFailure(
                f"instance not found: {self._instance_name()}"
            )
        if err_text.startswith("Error: ") and (
            "User does not have permission" in err_text
            or "User does not have entitlement" in err_text
        ):
            raise AnsibleConnectionFailure(
                f"instance access denied: {self._instance_name()}"
            )

        return rc, stdout, stderr

    # ------------------------------------------------------------------
    # File transfer helpers
    # ------------------------------------------------------------------

    def _get_remote_uid_gid(self) -> tuple[int, int]:
        """Determine UID and GID of ``incus_user`` inside the container.

        Used to set file ownership with ``incus file push --uid/--gid``.

        Bypasses ``exec_command`` (and thus become) so we always query the
        ``incus_user`` configured for the connection, not the become user.
        """
        uid_args = self._build_incus_exec_cmd("/bin/id -u")
        rc, uid_out, err = self._run_incus(uid_args)
        if rc != 0:
            raise AnsibleError(
                f"Failed to get remote uid for user "
                f"{self.get_option('incus_user')}: {err.decode(errors='replace')}"
            )

        gid_args = self._build_incus_exec_cmd("/bin/id -g")
        rc, gid_out, err = self._run_incus(gid_args)
        if rc != 0:
            raise AnsibleError(
                f"Failed to get remote gid for user "
                f"{self.get_option('incus_user')}: {err.decode(errors='replace')}"
            )

        return int(uid_out.strip().split()[0]), int(gid_out.strip().split()[0])

    # ------------------------------------------------------------------
    # put_file
    # ------------------------------------------------------------------

    def put_file(self, in_path: str, out_path: str) -> None:
        """Transfer a file from local to the container.

        Two methods are available, controlled by the
        ``incus_file_transfer_method`` option:

        * ``piped`` (default): pipe file content through the SSH connection
          and write it inside the container via shell redirection.
        * ``temp``: SCP the file to a temp location on the remote host,
          then use ``incus file push`` to copy it into the container with
          correct ownership and permissions.
        """
        super(SSHConnection, self).put_file(in_path, out_path)

        if not os.path.isfile(to_bytes(in_path, errors="surrogate_or_strict")):
            raise AnsibleFileNotFound(f"input path is not a file: {in_path}")

        self._display.vvv(
            f"PUT {in_path} TO {self._instance_name()}:{out_path}",
            host=self._instance_name(),
        )

        method = self.get_option("incus_file_transfer_method") or "piped"

        if method == "piped":
            self._put_file_piped(in_path, out_path)
        else:
            self._put_file_temp(in_path, out_path)

    def _put_file_piped(self, in_path: str, out_path: str) -> None:
        """Transfer a file by piping its content through the SSH connection."""
        container_user = self.get_option("incus_user") or "root"

        # Read the file locally
        with open(in_path, "rb") as f:
            data = f.read()

        # Build the incus exec command that writes to the destination
        project = self.get_option("incus_project")
        remote = self.get_option("incus_remote")
        instance = self._instance_name()

        incus_args = [
            "--project",
            project,
            "exec",
            f"{remote}:{instance}",
            "--",
        ]

        if container_user != "root":
            incus_args.extend(["su", "-", container_user, "-c"])

        # Write via the shell: mkdir -p and cat > dest
        parent = os.path.dirname(out_path)
        if parent:
            write_cmd = (
                f"mkdir -p {shlex.quote(parent)} && cat > {shlex.quote(out_path)}"
            )
        else:
            write_cmd = f"cat > {shlex.quote(out_path)}"
        incus_args.extend(["/bin/sh", "-c", write_cmd])

        rc, stdout, stderr = self._run_incus(incus_args, in_data=data)
        if rc != 0:
            raise AnsibleError(
                f"Failed to put file via piped method: "
                f"{stderr.decode(errors='replace')}"
            )

    def _put_file_temp(self, in_path: str, out_path: str) -> None:
        """Transfer a file via a temporary location on the remote host.

        1. SCP the file to the remote host via the SSH plugin.
        2. Use ``incus file push`` to copy into the container
           (with correct ownership).
        3. Clean up the temp file.
        """
        instance = self._instance_name()
        container_user = self.get_option("incus_user") or "root"
        project = self.get_option("incus_project")
        incus_remote = self.get_option("incus_remote")

        # Unique temp file on the remote host
        temp_file = (
            f"/tmp/.ansible_ssh_incus2/{os.path.basename(in_path)}.{os.getpid()}"
        )

        try:
            # 1. Transfer local -> bastion via the SSH plugin's put_file.
            #    The parent handles SCP/SFTP/piped, keys, ports, ControlPath
            #    — everything we'd otherwise have to reimplement.
            SSHConnection.put_file(self, in_path, temp_file)

            # 2. incus file push from temp path into container
            incus_args = [
                "--project",
                project,
                "file",
                "push",
            ]

            if container_user != "root":
                uid, gid = self._get_remote_uid_gid()
                incus_args.extend(["--uid", str(uid), "--gid", str(gid)])

            incus_args.extend([temp_file, f"{incus_remote}:{instance}/{out_path}"])

            rc, _stdout, stderr = self._run_incus(incus_args)
            if rc != 0:
                raise AnsibleError(
                    f"incus file push failed: {stderr.decode(errors='replace')}"
                )

        finally:
            # 3. Clean up temp file
            super().exec_command(f"rm -f {shlex.quote(temp_file)}", sudoable=False)

    # ------------------------------------------------------------------
    # fetch_file
    # ------------------------------------------------------------------

    def fetch_file(self, in_path: str, out_path: str) -> None:
        """Transfer a file from the container to the local machine.

        Two methods are available, controlled by the
        ``incus_file_transfer_method`` option:

        * ``piped`` (default): read the file inside the container via shell
          redirection and pipe the content back over the SSH connection.
        * ``temp``: Use ``incus file pull`` to a temp location on the remote
          host, then SCP it back locally.
        """
        super(SSHConnection, self).fetch_file(in_path, out_path)

        self._display.vvv(
            f"FETCH {self._instance_name()}:{in_path} TO {out_path}",
            host=self._instance_name(),
        )

        method = self.get_option("incus_file_transfer_method") or "piped"

        if method == "piped":
            self._fetch_file_piped(in_path, out_path)
        else:
            self._fetch_file_temp(in_path, out_path)

    def _fetch_file_piped(self, in_path: str, out_path: str) -> None:
        """Fetch a file by piping its content back over the SSH connection."""
        container_user = self.get_option("incus_user") or "root"

        project = self.get_option("incus_project")
        remote = self.get_option("incus_remote")
        instance = self._instance_name()

        incus_args = [
            "--project",
            project,
            "exec",
            f"{remote}:{instance}",
            "--",
        ]

        if container_user != "root":
            incus_args.extend(["su", "-", container_user, "-c"])

        # cat the file
        incus_args.extend(["/bin/sh", "-c", f"cat {shlex.quote(in_path)}"])

        rc, stdout, stderr = self._run_incus(incus_args)

        if rc != 0:
            err_text = stderr.decode(errors="replace").strip()
            if "No such file" in err_text or "not found" in err_text.lower():
                raise AnsibleFileNotFound(f"file not found in container: {in_path}")
            raise AnsibleError(f"Failed to fetch file via piped method: {err_text}")

        # Write the output to local path
        parent = os.path.dirname(out_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(to_bytes(out_path, errors="surrogate_or_strict"), "wb") as f:
            f.write(stdout)

    def _fetch_file_temp(self, in_path: str, out_path: str) -> None:
        """Fetch a file via a temporary location on the remote host.

        1. Use ``incus file pull`` to copy from container to a remote temp file.
        2. Fetch that temp file to local via the SSH plugin.
        3. Clean up the temp file on the remote host.
        """
        instance = self._instance_name()
        project = self.get_option("incus_project")
        incus_remote = self.get_option("incus_remote")

        temp_file = (
            f"/tmp/.ansible_ssh_incus2/{os.path.basename(in_path)}.{os.getpid()}"
        )

        try:
            # 1. incus file pull: container -> bastion temp
            incus_args = [
                "--project",
                project,
                "file",
                "pull",
                f"{incus_remote}:{instance}{in_path}",
                temp_file,
            ]

            self._display.vvvv(
                f"incus file pull {incus_remote}:{instance}{in_path} -> {temp_file}",
                host=instance,
            )

            rc, _stdout, stderr = self._run_incus(incus_args)
            if rc != 0:
                err_text = stderr.decode(errors="replace").strip()
                if "not found" in err_text.lower() or "No such file" in err_text:
                    raise AnsibleFileNotFound(f"file not found in container: {in_path}")
                raise AnsibleError(f"incus file pull failed: {err_text}")

            # 2. Transfer bastion -> local via the SSH plugin's fetch_file.
            #    The parent handles SCP/SFTP/piped, keys, ports, ControlPath.
            SSHConnection.fetch_file(self, temp_file, out_path)

        finally:
            # 3. Clean up temp file on remote host
            super().exec_command(f"rm -f {shlex.quote(temp_file)}", sudoable=False)

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Force-close the persistent connection."""
        super().reset()
