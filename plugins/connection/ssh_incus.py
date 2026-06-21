# Copyright (c) 2024 Ansible Project
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

"""
ssh_incus connection plugin

Combines SSH and Incus to manage containers on a remote host without
requiring SSH inside the container or exposing the Incus TCP port.

How it works::

    ┌──────────────┐   SSH    ┌──────────────┬──────────────┐
    │  Controller  │─────── ─>│  Remote Host │  Incus       │
    │  (your       │  tunnel  │  (bastion)   │  Container   │
    │  machine)    │          │              │  web-01      │
    │              │          │  ssh user@   │              │
    │  ssh_incus   │          │  ─────────── │  incus exec  │
    │  plugin      │          │  incus file  │  / incus     │
    │              │          │  push/pull   │  file        │
    └──────────────┘          └──────────────└──────────────┘
                                 No open port    No SSHd

The connection chain is:

1. SSH from local machine to remote host (the bastion)
2. ``incus exec`` / ``incus file`` on the remote host to interact with the
   container

This means:

* The container needs **no SSH server** running inside it.
* The Incus daemon's TCP port (8443) does **not** need to be exposed.
* All standard Ansible modules (``copy``, ``template``, ``package``,
  ``service``, etc.) work transparently inside the container.
* Module pipelining is supported for performance.
"""

from __future__ import annotations

import hashlib
import os
import shlex
import subprocess

from ansible.errors import AnsibleConnectionFailure, AnsibleError, AnsibleFileNotFound
from ansible.module_utils.common.text.converters import to_bytes, to_native, to_text
from ansible.plugins.connection import ConnectionBase
from ansible.utils.path import makedirs_safe, unfrackpath

DOCUMENTATION = r"""
author: Simon (inspired by community.general.incus)
name: ssh_incus
short_description: Run tasks in Incus instances via an SSH bastion host
description:
  - Connects to a remote host via SSH, then executes commands inside an
    Incus container on that host using C(incus exec) and transfers files
    using C(incus file).
  - The container needs no SSH server running.
  - The Incus daemon's TCP port does not need to be exposed.
  - All standard Ansible modules (copy, template, package, service, etc.)
    work transparently inside the container.
version_added: "1.0.0"
options:
  remote_addr:
    description:
      - The Incus instance (container/VM) identifier.
    type: string
    default: inventory_hostname
    vars:
      - name: inventory_hostname
      - name: ansible_host
      - name: ansible_incus_host
  remote_host:
    description:
      - The SSH target for the remote host running Incus.
      - Can be specified as C(user@hostname) or just C(hostname).
      - This is required; there is no default.
    type: string
    required: True
    vars:
      - name: ansible_ssh_incus_host
  remote_user:
    description:
      - The user to use inside the Incus container (not the SSH user).
    type: string
    default: root
    vars:
      - name: ansible_user
    env:
      - name: ANSIBLE_REMOTE_USER
    ini:
      - section: defaults
        key: remote_user
    keyword:
      - name: remote_user
  ssh_user:
    description:
      - The SSH user for the remote host. Defaults to the same value as
        O(remote_user), which is typically C(root). Override this if you
        SSH as a different user than the one you operate as inside the
        container.
    type: string
    vars:
      - name: ansible_ssh_user
      - name: ansible_ssh_incus_ssh_user
  ssh_port:
    description:
      - SSH port for the remote host.
    type: int
    vars:
      - name: ansible_ssh_port
      - name: ansible_ssh_incus_port
  ssh_common_args:
    description:
      - Extra arguments to pass to all SSH CLI invocations.
      - Use this to set ProxyJump, custom ciphers, etc.
    type: string
    default: ''
    vars:
      - name: ansible_ssh_incus_ssh_common_args
  ssh_executable:
    description:
      - The SSH binary to use.
    type: string
    default: ssh
    vars:
      - name: ansible_ssh_incus_ssh_executable
      - name: ansible_ssh_executable
  scp_executable:
    description:
      - The SCP binary to use for file transfers.
    type: string
    default: scp
    vars:
      - name: ansible_ssh_incus_scp_executable
      - name: ansible_scp_executable
  private_key_file:
    description:
      - Path to the SSH private key to authenticate to the remote host.
    type: string
    vars:
      - name: ansible_private_key_file
      - name: ansible_ssh_private_key_file
      - name: ansible_ssh_incus_private_key_file
  executable:
    description:
      - The shell to use inside the Incus container.
    type: string
    default: /bin/sh
    vars:
      - name: ansible_executable
      - name: ansible_incus_executable
  project:
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
  file_transfer_method:
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
      - name: ansible_ssh_incus_file_transfer_method
  control_path_dir:
    description:
      - Directory to use for SSH ControlPath sockets.
    type: string
    default: ~/.ansible/cp
    vars:
      - name: ansible_control_path_dir
      - name: ansible_ssh_incus_control_path_dir
  timeout:
    description:
      - Connection timeout for SSH in seconds.
    type: int
    default: 10
    vars:
      - name: ansible_timeout
      - name: ansible_ssh_incus_timeout
  host_key_checking:
    description:
      - Whether to verify SSH host keys for the remote host.
    type: bool
    default: true
    vars:
      - name: ansible_host_key_checking
      - name: ansible_ssh_incus_host_key_checking
"""


class Connection(ConnectionBase):
    """SSH + Incus based connection — manage containers without SSHd inside."""

    transport = "simon.incus.ssh_incus"
    has_pipelining = True

    def __init__(self, play_context, new_stdin, *args, **kwargs):
        super().__init__(play_context, new_stdin, *args, **kwargs)

        self._ssh_control_path: str | None = None
        self._ssh_control_path_dir: str | None = None
        self._connected = False
        self._remote_host: str | None = None
        self._incus_cmd = "incus"

    # ------------------------------------------------------------------
    # SSH ControlMaster helpers
    # ------------------------------------------------------------------

    def _get_control_path(self) -> str:
        """Generate or return a cached ControlPath for the SSH connection."""
        if self._ssh_control_path:
            return self._ssh_control_path

        self._ssh_control_path_dir = unfrackpath(
            self.get_option("control_path_dir") or "~/.ansible/cp"
        )
        cpdir = unfrackpath(self._ssh_control_path_dir)
        makedirs_safe(cpdir, 0o700)

        # Build a unique hash from the connection parameters
        host = self._get_ssh_host()
        user = self._get_ssh_user()
        port = str(self.get_option("ssh_port") or "")
        raw = f"{host}-{user}-{port}-{os.getpid()}"
        digest = hashlib.sha256(to_bytes(raw)).hexdigest()[:16]

        self._ssh_control_path = os.path.join(cpdir, f"ansible-ssh-incus-{digest}")
        return self._ssh_control_path

    def _get_ssh_user(self) -> str:
        """Determine SSH user for the remote host.

        Checks (in order):
        1. Explicit ``ssh_user`` option
        2. User parsed from ``remote_host`` (user@host syntax)
        3. Falls back to ``remote_user`` (the container user), defaults to ``root``
        """
        # 1. Explicit option
        user = self.get_option("ssh_user")
        if user:
            return user

        # 2. User@ in remote_host
        host_raw = self.get_option("remote_host") or ""
        if "@" in host_raw:
            return host_raw.split("@", 1)[0]

        # 3. Fall back to container user
        return self.get_option("remote_user") or "root"

    def _get_ssh_host(self) -> str:
        """Return the SSH host string, stripping any user@ prefix."""
        host_raw = self.get_option("remote_host") or ""
        if "@" in host_raw:
            return host_raw.split("@", 1)[1]
        return host_raw

    def _build_ssh_base_command(self) -> list[str]:
        """Build the base SSH command with ControlMaster for connection reuse."""
        host = self._get_ssh_host()
        user = self._get_ssh_user()

        cmd = [self.get_option("ssh_executable") or "ssh"]

        # Quiet, no escalation
        cmd.extend(["-q", "-T"])

        # ControlMaster for connection reuse across tasks
        cmd.extend(["-o", "ControlMaster=auto"])
        cmd.extend(["-o", f"ControlPath={self._get_control_path()}"])
        cmd.extend(["-o", "ControlPersist=60s"])

        # Connection timeout
        timeout = self.get_option("timeout") or 10
        cmd.extend(["-o", f"ConnectTimeout={timeout}"])

        # Port
        port = self.get_option("ssh_port")
        if port:
            cmd.extend(["-o", f"Port={port}"])

        # Private key
        key_file = self.get_option("private_key_file")
        if key_file:
            key_path = os.path.expanduser(key_file)
            cmd.extend(["-o", f'IdentityFile="{key_path}"'])

        # User
        if user:
            cmd.extend(["-o", f"User={user}"])

        # StrictHostKeyChecking
        host_key_checking = self.get_option("host_key_checking")
        if host_key_checking is False:
            cmd.extend(["-o", "StrictHostKeyChecking=no"])
            cmd.extend(["-o", "UserKnownHostsFile=/dev/null"])

        # Custom SSH args from the user
        extra = self.get_option("ssh_common_args") or ""
        if extra:
            cmd.extend(shlex.split(extra))

        # Destination host
        cmd.append(host)

        return cmd

    def _run_ssh_incus(
        self, incus_args: list[str], in_data: bytes | None = None
    ) -> tuple[int, bytes, bytes]:
        """Run an ``incus`` command on the remote host via SSH.

        The entire ``incus <args>`` is shell-quoted into a single string
        so that SSH passes it to the remote shell atomically. This prevents
        the remote shell from interpreting shell metacharacters (backticks,
        parentheses, ``&&``, etc.) in the inner command.

        Builds::

            ssh [options] remote-host 'incus <incus_args>'
        """
        ssh_cmd = self._build_ssh_base_command()

        # Shell-quote the entire remote incus command into a single argument.
        # The remote shell will unquote it once, then incus receives each
        # argument correctly.
        remote_cmd = shlex.join([self._incus_cmd] + incus_args)
        full_cmd = ssh_cmd + [remote_cmd]

        if self._display.verbosity > 3:
            self._display.vvvv(
                f"ssh_incus exec: {shlex.join(full_cmd)}",
                host=self._container_name(),
            )

        try:
            proc = subprocess.Popen(
                full_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = proc.communicate(input=in_data)
            return proc.returncode, stdout, stderr
        except OSError as exc:
            raise AnsibleConnectionFailure(f"SSH subprocess failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Container name
    # ------------------------------------------------------------------

    def _container_name(self) -> str:
        """Return the short container/instance name."""
        # Strip FQDN to first component, like the incus plugin does
        return self.get_option("remote_addr").split(".")[0]

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def _connect(self):
        """Open the persistent SSH connection to the remote host.

        Verifies that both SSH and ``incus`` are reachable.
        """
        super()._connect()

        if self._connected:
            return self

        host = self._get_ssh_host()
        if not host:
            raise AnsibleError(
                "remote_host is not set. Define ansible_ssh_incus_host "
                "or set remote_host in the inventory."
            )

        self._display.vvv(
            f"ESTABLISH SSH_INCUS CONNECTION FOR CONTAINER: "
            f"{self._container_name()} "
            f"(SSH host={host}, "
            f"SSH user={self._get_ssh_user()}, "
            f"container user={self.get_option('remote_user')})",
            host=self._container_name(),
        )

        # Test SSH connectivity + incus availability
        rc, stdout, stderr = self._run_ssh_incus(["info"])
        if rc != 0:
            raise AnsibleConnectionFailure(
                f"Cannot reach Incus on remote host {host}: "
                f"{stderr.decode(errors='replace')}"
            )

        self._connected = True
        return self

    def close(self):
        """Shut down the SSH ControlMaster connection and clean up."""
        if not self._connected:
            return

        host = self._get_ssh_host()
        cp = self._get_control_path()

        # Gracefully stop the control master
        if os.path.exists(cp):
            try:
                # Try -O check first to see if it's alive
                cmd = [self.get_option("ssh_executable") or "ssh"]
                cmd.extend(["-o", f"ControlPath={cp}"])
                cmd.extend(["-O", "check", host])
                subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                # Stop it
                cmd[cmd.index("-O") + 1] = "stop"
                subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
            finally:
                try:
                    os.unlink(cp)
                except OSError:
                    pass

        self._connected = False
        super().close()

    # ------------------------------------------------------------------
    # Command execution
    # ------------------------------------------------------------------

    def _build_incus_exec_cmd(self, cmd: str) -> list[str]:
        """Build the ``incus exec`` argument list for a command.

        The actual invocation happens via SSH in ``_run_ssh_incus``, so
        this just returns the *incus* portion of the command.
        """
        project = self.get_option("project")
        remote = self.get_option("incus_remote")
        executable = self.get_option("executable") or "/bin/sh"
        container_user = self.get_option("remote_user") or "root"

        incus_args: list[str] = [
            "--project",
            project,
            "exec",
            f"{remote}:{self._container_name()}",
            "--",
        ]

        # If the container user is not root, use su to switch
        if container_user != "root":
            incus_args.extend(
                [
                    "su",
                    "-",
                    container_user,
                    "-c",
                ]
            )

        incus_args.extend(
            [
                executable,
                "-c",
                cmd,
            ]
        )

        return incus_args

    def exec_command(
        self,
        cmd: str,
        in_data: bytes | None = None,
        sudoable: bool = True,
    ) -> tuple[int, bytes, bytes]:
        """Execute a command inside the Incus container.

        The command is wrapped in ``shell -c`` and forwarded over SSH to the remote
        host, which runs it via ``incus exec``.

        If *sudoable* is ``True`` andbecome is enabled, the command runs
        in the become context.
        """
        super().exec_command(cmd, in_data=in_data, sudoable=sudoable)

        # Incorporate become if needed
        if sudoable and self.become:
            cmd = self.become.build_become_command(cmd, self._shell)

        self._display.vvv(
            f"EXEC {cmd[:120]}{'...' if len(cmd) > 120 else ''}",
            host=self._container_name(),
        )

        incus_args = self._build_incus_exec_cmd(cmd)

        if self._display.verbosity > 3:
            self._display.vvvv(
                f"EXEC incus args: {shlex.join(incus_args)}",
                host=self._container_name(),
            )

        rc, stdout, stderr = self._run_ssh_incus(incus_args, in_data=in_data)

        # Translate common errors
        err_text = stderr.decode(errors="replace").strip()
        if err_text.startswith("Error: ") and "Instance is not running" in err_text:
            raise AnsibleConnectionFailure(
                f"instance not running: {self._container_name()}"
            )
        if err_text.startswith("Error: ") and "Instance not found" in err_text:
            raise AnsibleConnectionFailure(
                f"instance not found: {self._container_name()}"
            )
        if err_text.startswith("Error: ") and (
            "User does not have permission" in err_text
            or "User does not have entitlement" in err_text
        ):
            raise AnsibleConnectionFailure(
                f"instance access denied: {self._container_name()}"
            )

        return rc, stdout, stderr

    # ------------------------------------------------------------------
    # File transfer
    # ------------------------------------------------------------------

    def _get_remote_uid_gid(self) -> tuple[int, int]:
        """Determine UID and GID of ``remote_user`` inside the container.

        Used to set file ownership with ``incus file push --uid/--gid``.
        """
        rc, uid_out, err = self.exec_command("/bin/id -u")
        if rc != 0:
            raise AnsibleError(
                f"Failed to get remote uid for user "
                f"{self.get_option('remote_user')}: {err.decode(errors='replace')}"
            )

        rc, gid_out, err = self.exec_command("/bin/id -g")
        if rc != 0:
            raise AnsibleError(
                f"Failed to get remote gid for user "
                f"{self.get_option('remote_user')}: {err.decode(errors='replace')}"
            )

        return int(uid_out.strip()), int(gid_out.strip())

    def put_file(self, in_path: str, out_path: str) -> None:
        """Transfer a file from local to the container.

        Two methods are available, controlled by the ``file_transfer_method``
        option:

        * ``piped`` (default): pipe file content through the SSH connection
          and write it inside the container via shell redirection.
        * ``temp``: SCP the file to a temp location on the remote host,
          then use ``incus file push`` to copy it into the container with
          correct ownership and permissions.
        """
        super().put_file(in_path, out_path)

        if not os.path.isfile(to_bytes(in_path, errors="surrogate_or_strict")):
            raise AnsibleFileNotFound(f"input path is not a file: {in_path}")

        self._display.vvv(
            f"PUT {in_path} TO {out_path}",
            host=self._container_name(),
        )

        method = self.get_option("file_transfer_method") or "piped"

        if method == "piped":
            self._put_file_piped(in_path, out_path)
        else:
            self._put_file_temp(in_path, out_path)

    def _put_file_piped(self, in_path: str, out_path: str) -> None:
        """Transfer a file by piping its content through the SSH connection.

        Uses::

            cat <local> | ssh ... incus exec container -- sh -c 'cat > dest'
        """
        container_user = self.get_option("remote_user") or "root"

        # Read the file locally
        with open(in_path, "rb") as f:
            data = f.read()

        # Build the incus exec command that writes to the destination
        project = self.get_option("project")
        remote = self.get_option("incus_remote")
        container = self._container_name()

        incus_args = [
            "--project",
            project,
            "exec",
            f"{remote}:{container}",
            "--",
        ]

        if container_user != "root":
            incus_args.extend(["su", "-", container_user, "-c"])

        # Write via the shell: mkdir -p and cat > dest
        # Each argument is separate so incus receives them atomically
        write_cmd = (
            f"mkdir -p {shlex.quote(os.path.dirname(out_path))} && "
            f"cat > {shlex.quote(out_path)}"
        )
        incus_args.extend(["/bin/sh", "-c", write_cmd])

        rc, stdout, stderr = self._run_ssh_incus(incus_args, in_data=data)
        if rc != 0:
            raise AnsibleError(
                f"Failed to put file via piped method: "
                f"{stderr.decode(errors='replace')}"
            )

    def _put_file_temp(self, in_path: str, out_path: str) -> None:
        """Transfer a file via a temporary location on the remote host.

        1. Create a temp dir on the remote host.
        2. SCP the file there.
        3. Use ``incus file push`` to copy into the container
           (with correct ownership).
        4. Clean up the temp file.
        """
        container = self._container_name()
        remote_host = self._get_ssh_host()
        container_user = self.get_option("remote_user") or "root"
        project = self.get_option("project")
        incus_remote = self.get_option("incus_remote")

        # 1. Create temp dir on remote host
        temp_dir = "/tmp/.ansible_ssh_incus"
        rc, _, stderr = self._run_ssh_incus(
            ["exec", container, "--", "mkdir", "-p", temp_dir]
        )
        if rc != 0:
            raise AnsibleError(
                f"Failed to create temp dir on remote host: "
                f"{stderr.decode(errors='replace')}"
            )

        # Unique temp file name
        temp_file = f"{temp_dir}/{os.path.basename(in_path)}.{os.getpid()}"

        try:
            # 2. SCP to remote host
            scp_cmd = [self.get_option("scp_executable") or "scp"]
            scp_cmd.extend(["-q"])
            scp_cmd.extend(["-o", f"ControlPath={self._get_control_path()}"])
            scp_cmd.extend(["-o", "ControlMaster=auto"])
            scp_cmd.append(in_path)
            scp_cmd.append(f"{remote_host}:{temp_file}")

            if self._display.verbosity > 3:
                self._display.vvvv(
                    f"SCP {in_path} -> {remote_host}:{temp_file}",
                    host=container,
                )

            rc = subprocess.run(scp_cmd, capture_output=True, check=False)
            if rc.returncode != 0:
                raise AnsibleError(
                    f"SCP to remote host failed: {rc.stderr.decode(errors='replace')}"
                )

            # 3. incus file push from temp path into container
            incus_args = [
                "--project",
                project,
                "file",
                "push",
            ]

            if container_user != "root":
                uid, gid = self._get_remote_uid_gid()
                incus_args.extend(["--uid", str(uid), "--gid", str(gid)])

            incus_args.extend([temp_file, f"{incus_remote}:{container}/{out_path}"])

            rc, _, stderr = self._run_ssh_incus(incus_args)
            if rc != 0:
                raise AnsibleError(
                    f"incus file push failed: {stderr.decode(errors='replace')}"
                )

        finally:
            # 4. Clean up temp file
            self._run_ssh_incus(["exec", container, "--", "rm", "-f", temp_file])

    def fetch_file(self, in_path: str, out_path: str) -> None:
        """Transfer a file from the container to the local machine.

        Two methods are available, controlled by the ``file_transfer_method``
        option:

        * ``piped`` (default): read the file inside the container via shell
          redirection and pipe the content back over the SSH connection.
        * ``temp``: Use ``incus file pull`` to a temp location on the remote
          host, then SCP it back locally.
        """
        super().fetch_file(in_path, out_path)

        self._display.vvv(
            f"FETCH {in_path} TO {out_path}",
            host=self._container_name(),
        )

        method = self.get_option("file_transfer_method") or "piped"

        if method == "piped":
            self._fetch_file_piped(in_path, out_path)
        else:
            self._fetch_file_temp(in_path, out_path)

    def _fetch_file_piped(self, in_path: str, out_path: str) -> None:
        """Fetch a file by piping its content back over the SSH connection.

        Uses::

            ssh ... incus exec container -- sh -c 'cat src' > <local>
        """
        container_user = self.get_option("remote_user") or "root"

        project = self.get_option("project")
        remote = self.get_option("incus_remote")
        container = self._container_name()

        incus_args = [
            "--project",
            project,
            "exec",
            f"{remote}:{container}",
            "--",
        ]

        if container_user != "root":
            incus_args.extend(["su", "-", container_user, "-c"])

        # cat the file — each argument is separate
        incus_args.extend(["/bin/sh", "-c", f"cat {shlex.quote(in_path)}"])

        rc, stdout, stderr = self._run_ssh_incus(incus_args)

        if rc != 0:
            # If the file doesn't exist, raise a proper error
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
        2. SCP that temp file back locally.
        3. Clean up the temp file on the remote host.
        """
        container = self._container_name()
        remote_host = self._get_ssh_host()
        project = self.get_option("project")
        incus_remote = self.get_option("incus_remote")

        # 1. Create temp dir on remote host
        temp_dir = "/tmp/.ansible_ssh_incus"
        self._run_ssh_incus(["exec", container, "--", "mkdir", "-p", temp_dir])

        temp_file = f"{temp_dir}/{os.path.basename(in_path)}.{os.getpid()}"

        try:
            # 2. incus file pull to temp path
            incus_args = [
                "--project",
                project,
                "file",
                "pull",
                f"{incus_remote}:{container}/{in_path}",
                temp_file,
            ]

            self._display.vvvv(
                f"incus file pull {incus_remote}:{container}/{in_path} -> {temp_file}",
                host=container,
            )

            rc, _, stderr = self._run_ssh_incus(incus_args)
            if rc != 0:
                err_text = stderr.decode(errors="replace").strip()
                if "not found" in err_text.lower() or "No such file" in err_text:
                    raise AnsibleFileNotFound(f"file not found in container: {in_path}")
                raise AnsibleError(f"incus file pull failed: {err_text}")

            # 3. SCP from remote host to local
            parent = os.path.dirname(out_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

            scp_cmd = [self.get_option("scp_executable") or "scp"]
            scp_cmd.extend(["-q"])
            scp_cmd.extend(["-o", f"ControlPath={self._get_control_path()}"])
            scp_cmd.extend(["-o", "ControlMaster=auto"])
            scp_cmd.append(f"{remote_host}:{temp_file}")
            scp_cmd.append(out_path)

            if self._display.verbosity > 3:
                self._display.vvvv(
                    f"SCP {remote_host}:{temp_file} -> {out_path}",
                    host=container,
                )

            rc = subprocess.run(scp_cmd, capture_output=True, check=False)
            if rc.returncode != 0:
                raise AnsibleError(
                    f"SCP from remote host failed: {rc.stderr.decode(errors='replace')}"
                )

        finally:
            # 4. Clean up temp file on remote host
            self._run_ssh_incus(["exec", container, "--", "rm", "-f", temp_file])

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Force-close the persistent connection."""
        self.close()

    def is_pipelining_enabled(self, wrap_async: bool = False) -> bool:
        """Override to check if a TTY was requested (pipelining needs no TTY)."""
        # Windows check
        if getattr(self._shell, "_IS_WINDOWS", False):
            return True

        # Check if user requested a TTY via ssh_common_args
        extra = self.get_option("ssh_common_args") or ""
        if "-tt" in extra or "-t" in shlex.split(extra):
            return False

        return super().is_pipelining_enabled(wrap_async)
