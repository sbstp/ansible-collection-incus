class ModuleDocFragment(object):
    # Taken from https://github.com/ansible/ansible/blob/stable-2.20/lib/ansible/plugins/connection/ssh.py
    # Haven't found a nice way of extending otherwise.
    DOCUMENTATION = """
        options:
          host:
              description: Hostname/IP to connect to.
              default: inventory_hostname
              type: string
              vars:
                   - name: inventory_hostname
                   - name: ansible_host
                   - name: ansible_ssh_host
          host_key_checking:
              description: Determines if SSH should reject or not a connection after checking host keys.
              default: True
              type: boolean
              ini:
                  - section: defaults
                    key: 'host_key_checking'
                  - section: ssh_connection
                    key: 'host_key_checking'
              env:
                  - name: ANSIBLE_HOST_KEY_CHECKING
                  - name: ANSIBLE_SSH_HOST_KEY_CHECKING
              vars:
                  - name: ansible_host_key_checking
                  - name: ansible_ssh_host_key_checking
          password:
              description: Authentication password for the O(remote_user). Can be supplied as CLI option.
              type: string
              vars:
                  - name: ansible_password
                  - name: ansible_ssh_pass
                  - name: ansible_ssh_password
          password_mechanism:
              description: Mechanism to use for handling ssh password prompt
              type: string
              default: ssh_askpass
              choices:
                  - ssh_askpass
                  - sshpass
                  - disable
              env:
                  - name: ANSIBLE_SSH_PASSWORD_MECHANISM
              ini:
                  - {key: password_mechanism, section: ssh_connection}
              vars:
                  - name: ansible_ssh_password_mechanism
          sshpass_prompt:
              description:
                  - Password prompt that C(sshpass)/C(SSH_ASKPASS) should search for.
                  - Supported by sshpass 1.06 and up when O(password_mechanism) set to V(sshpass).
                  - Defaults to C(Enter PIN for) when pkcs11_provider is set.
                  - Defaults to C(assword) when O(password_mechanism) set to V(ssh_askpass).
              default: ''
              type: string
              ini:
                  - section: 'ssh_connection'
                    key: 'sshpass_prompt'
              env:
                  - name: ANSIBLE_SSHPASS_PROMPT
              vars:
                  - name: ansible_sshpass_prompt
          ssh_args:
              description: Arguments to pass to all SSH CLI tools.
              default: '-C -o ControlMaster=auto -o ControlPersist=60s'
              type: string
              ini:
                  - section: 'ssh_connection'
                    key: 'ssh_args'
              env:
                  - name: ANSIBLE_SSH_ARGS
              vars:
                  - name: ansible_ssh_args
          ssh_common_args:
              description: Common extra args for all SSH CLI tools.
              default: ''
              type: string
              ini:
                  - section: 'ssh_connection'
                    key: 'ssh_common_args'
              env:
                  - name: ANSIBLE_SSH_COMMON_ARGS
              vars:
                  - name: ansible_ssh_common_args
              cli:
                  - name: ssh_common_args
          ssh_executable:
              default: ssh
              description:
                - This defines the location of the SSH binary. It defaults to V(ssh) which will use the first SSH binary available in $PATH.
                - This option is usually not required, it might be useful when access to system SSH is restricted,
                  or when using SSH wrappers to connect to remote hosts.
              type: string
              env: [{name: ANSIBLE_SSH_EXECUTABLE}]
              ini:
              - {key: ssh_executable, section: ssh_connection}
              vars:
                  - name: ansible_ssh_executable
          sftp_executable:
              default: sftp
              description:
                - This defines the location of the sftp binary. It defaults to V(sftp) which will use the first binary available in $PATH.
              type: string
              env: [{name: ANSIBLE_SFTP_EXECUTABLE}]
              ini:
              - {key: sftp_executable, section: ssh_connection}
              vars:
                  - name: ansible_sftp_executable
          scp_executable:
              default: scp
              description:
                - This defines the location of the scp binary. It defaults to V(scp) which will use the first binary available in $PATH.
              type: string
              env: [{name: ANSIBLE_SCP_EXECUTABLE}]
              ini:
              - {key: scp_executable, section: ssh_connection}
              vars:
                  - name: ansible_scp_executable
          scp_extra_args:
              description: Extra exclusive to the C(scp) CLI
              default: ''
              type: string
              vars:
                  - name: ansible_scp_extra_args
              env:
                - name: ANSIBLE_SCP_EXTRA_ARGS
              ini:
                - key: scp_extra_args
                  section: ssh_connection
              cli:
                - name: scp_extra_args
          sftp_extra_args:
              description: Extra exclusive to the C(sftp) CLI
              default: ''
              type: string
              vars:
                  - name: ansible_sftp_extra_args
              env:
                - name: ANSIBLE_SFTP_EXTRA_ARGS
              ini:
                - key: sftp_extra_args
                  section: ssh_connection
              cli:
                - name: sftp_extra_args
          ssh_extra_args:
              description: Extra exclusive to the SSH CLI.
              default: ''
              type: string
              vars:
                  - name: ansible_ssh_extra_args
              env:
                - name: ANSIBLE_SSH_EXTRA_ARGS
              ini:
                - key: ssh_extra_args
                  section: ssh_connection
              cli:
                - name: ssh_extra_args
          reconnection_retries:
              description:
                - Number of attempts to connect.
                - Ansible retries connections only if it gets an SSH error with a return code of 255.
                - Any errors with return codes other than 255 indicate an issue with program execution.
              default: 0
              type: integer
              env:
                - name: ANSIBLE_SSH_RETRIES
              ini:
                - section: connection
                  key: retries
                - section: ssh_connection
                  key: retries
              vars:
                - name: ansible_ssh_retries
          port:
              description: Remote port to connect to.
              type: int
              ini:
                - section: defaults
                  key: remote_port
              env:
                - name: ANSIBLE_REMOTE_PORT
              vars:
                - name: ansible_port
                - name: ansible_ssh_port
              keyword:
                - name: port
          remote_user:
              description:
                  - User name with which to login to the remote server, normally set by the remote_user keyword.
                  - If no user is supplied, Ansible will let the SSH client binary choose the user as it normally.
              type: string
              ini:
                - section: defaults
                  key: remote_user
              env:
                - name: ANSIBLE_REMOTE_USER
              vars:
                - name: ansible_user
                - name: ansible_ssh_user
              cli:
                - name: user
              keyword:
                - name: remote_user
          pipelining:
              description: SSH pipelining
              env:
                - name: ANSIBLE_PIPELINING
                - name: ANSIBLE_SSH_PIPELINING
              ini:
                - section: defaults
                  key: pipelining
                - section: connection
                  key: pipelining
                - section: ssh_connection
                  key: pipelining
              vars:
                - name: ansible_pipelining
                - name: ansible_ssh_pipelining
          private_key_file:
              description:
                  - Path to private key file to use for authentication.
              type: string
              ini:
                - section: defaults
                  key: private_key_file
              env:
                - name: ANSIBLE_PRIVATE_KEY_FILE
              vars:
                - name: ansible_private_key_file
                - name: ansible_ssh_private_key_file
              cli:
                - name: private_key_file
                  option: '--private-key'
          private_key:
              description:
                - Private key contents in PEM format. Requires the C(SSH_AGENT) configuration to be enabled.
              type: string
              env:
                - name: ANSIBLE_PRIVATE_KEY
              vars:
                - name: ansible_private_key
                - name: ansible_ssh_private_key
          private_key_passphrase:
              description:
                - Private key passphrase, dependent on O(private_key).
                - This does NOT have any effect when used with O(private_key_file).
              type: string
              env:
                - name: ANSIBLE_PRIVATE_KEY_PASSPHRASE
              vars:
                - name: ansible_private_key_passphrase
                - name: ansible_ssh_private_key_passphrase
          control_path:
            description:
              - This is the location to save SSH's ControlPath sockets, it uses SSH's variable substitution.
              - |
                Since 2.3.0, if null (default), ansible will generate a unique hash.
                Use ``%(directory)s`` to indicate where to use the control dir path setting.
              - Before 2.3.0 it defaulted to ``control_path=%(directory)s/ansible-ssh-%%h-%%p-%%r``.
              - Be aware that this setting is ignored if C(-o ControlPath) is set in ssh args.
            type: string
            env:
              - name: ANSIBLE_SSH_CONTROL_PATH
            ini:
              - key: control_path
                section: ssh_connection
            vars:
              - name: ansible_control_path
          control_path_dir:
            default: ~/.ansible/cp
            description:
              - This sets the directory to use for ssh control path if the control path setting is null.
              - Also, provides the ``%(directory)s`` variable for the control path setting.
            type: string
            env:
              - name: ANSIBLE_SSH_CONTROL_PATH_DIR
            ini:
              - section: ssh_connection
                key: control_path_dir
            vars:
              - name: ansible_control_path_dir
          sftp_batch_mode:
            default: true
            description:
              - When set to C(True), sftp will be run in batch mode, allowing detection of transfer errors.
              - When set to C(False), sftp will not be run in batch mode, preventing detection of transfer errors.
            env: [{name: ANSIBLE_SFTP_BATCH_MODE}]
            ini:
            - {key: sftp_batch_mode, section: ssh_connection}
            type: bool
            vars:
              - name: ansible_sftp_batch_mode
          ssh_transfer_method:
            description: Preferred method to use when transferring files over ssh
            choices:
                  sftp: This is the most reliable way to copy things with SSH.
                  scp: Deprecated in OpenSSH. For OpenSSH >=9.0 you must add an additional option to enable scp C(scp_extra_args="-O").
                  piped: Creates an SSH pipe with C(dd) on either side to copy the data.
                  smart: Tries each method in order (sftp > scp > piped), until one succeeds or they all fail.
            default: smart
            type: string
            env: [{name: ANSIBLE_SSH_TRANSFER_METHOD}]
            ini:
                - {key: transfer_method, section: ssh_connection}
            vars:
                - name: ansible_ssh_transfer_method
          use_tty:
            default: true
            description: add -tt to ssh commands to force tty allocation.
            env: [{name: ANSIBLE_SSH_USETTY}]
            ini:
            - {key: usetty, section: ssh_connection}
            type: bool
            vars:
              - name: ansible_ssh_use_tty
          timeout:
            default: 10
            description:
                - This is the default amount of time we will wait while establishing an SSH connection.
                - It also controls how long we can wait to access reading the connection once established (select on the socket).
            env:
                - name: ANSIBLE_TIMEOUT
                - name: ANSIBLE_SSH_TIMEOUT
            ini:
                - key: timeout
                  section: defaults
                - key: timeout
                  section: ssh_connection
            vars:
              - name: ansible_ssh_timeout
            cli:
              - name: timeout
            type: integer
          pkcs11_provider:
            default: ""
            type: string
            description:
              - "PKCS11 SmartCard provider such as opensc, example: /usr/local/lib/opensc-pkcs11.so"
            env: [{name: ANSIBLE_PKCS11_PROVIDER}]
            ini:
              - {key: pkcs11_provider, section: ssh_connection}
            vars:
              - name: ansible_ssh_pkcs11_provider
          verbosity:
            default: 0
            type: int
            description:
              - Requested verbosity level for the SSH CLI.
            env: [{name: ANSIBLE_SSH_VERBOSITY}]
            ini:
              - {key: verbosity, section: ssh_connection}
            vars:
              - name: ansible_ssh_verbosity
    """
