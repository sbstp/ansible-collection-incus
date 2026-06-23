# Ansible Collection - sbstp.incus

This repository contains the `sbstp.incus` collection.
It is a collection of ansible modules that enable the creation of incus instances,
storage pools, networks and more.

It also includes a special `ssh_incus` connection module that allows incus instances
to run ansible tasks on a remote host via SSH. It means that the SSH server acts
essentially as a jump host for the incus instance. No need to expose the incus admin
API publicly, and no need to install a SSH server in the instance.

> [!NOTE]
> This repository is forked from https://github.com/kmpm/ansible-collection-incus

> [!WARNING]
> This fork sometimes uses LLM assistance to develop and debug features.
> The features are tested with integration tests but the collection itself has not been battle tested by many people yet.
> If using software developed with the help of LLMs is against your values, that's ok. This warning is here to not misrepresent the nature of this work and let you decide for yourself.

## Tested with Ansible

This collection is currently only tested with core-2.20 and Python 3.13+.

## External requirements

All modules depend on a locally installed and configured `incus`CLI.
That same incus CLI must have [PR 581](https://github.com/lxc/incus/pull/581) included.
This means `incus > 0.6.0`.

## Using this collection

The collection is not yet published in Ansible Galaxy but can be installed with
`ansible-galaxy` and using the [git repository](https://github.com/sbstp/ansible-collection-incus).

```shell
ansible-galaxy collection install git+https://github.com/sbstp/ansible-collection-incus.git
```

### Modules

```yaml
- hosts: localhost
  connection: local
  - tasks:
    - name: create a network
      incus_network:
        name: make_me_some_network
        type: bridge
        config:
            ipv4.address: "192.168.42.0/24"
            ipv4.dhcp: "false"
            ipv6.address: "none"

    - name: get some info about networks
      incus_network_info:
        name: mynetwork # optional name if you want just one network
        project: default # optional 
        # target: sometarget # defaults to empty
      register: netinfo

    - name: create a instance
      incus_instance:
        name: mycontainer
        source: # No default for source. You will need what you need.
            type: image
            alias: debian/12/cloud
            server: "https://images.linuxcontainers.org"
            protocol: simplestreams
            mode: pull
            allow_inconsistent: false

    - name: delete instance
      incus_instance:
        name: mycontainer
        state: absent

    - name: delete network
      incus_network:
        name: mynetwork
        state: absent
```

### Inventory

WIP: There is an inventory module but it has limited documentation and not 
everything planed is complete or implemented.

Get the existing help with `ansible-doc -t inventory sbstp.incus.incus`

To use create a file that ends with `incus.yml` or `incus.yaml`

```yaml
---
plugin: sbstp.incus.incus

```

Test with `ansible-inventory -i <yourfile> --list`

## License

GPL-3.0-or-later
