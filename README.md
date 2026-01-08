# fastvm

## TODO: what can we learn from vagrant?

A simple and fast way to run local VMs with qemu.

Spinning up and running new VMs should be as easy as running a docker container:

```
# docker is as simple as this:
$ docker run -it debian
Emulate Docker CLI using podman. Create /etc/containers/nodocker to quiet msg.
root@3710524c2a6d:/#
```


```
# VMs should be as simple as this:
$ fastvm run debian
root@693220a919f6:/#
```


## Usage:

```
$ ./fastvm.py -h
fastvm version v0.1
usage: fastvm [-h] {run,ps,ls,rm,update} ...

Fast VM provisioning with cloud images

positional arguments:
  {run,ps,ls,rm,update}  Available commands
    run           Run a new VM
    ps            List running fastvm VMs
    ls            List all fastvm VMs (running and stopped)
    rm            Delete a fastvm VM
    update        Check for and download updated cloud images

options:
  -h, --help      show this help message and exit

$ ./fastvm.py run -h
fastvm version v0.1
usage: fastvm run [-h] {arch,fedora,debian} [arch] [hostname]

positional arguments:
  {arch,fedora,debian}  Distribution to use
  arch                  Architecture (default: amd64)
  hostname              Hostname for the VM

options:
  -h, --help            show this help message and exit

examples:
  fastvm run debian                    # Use debian with default arch
  fastvm run fedora arm64              # Use fedora with arm64 architecture
  fastvm run debian amd64 localvm01    # Use debian, amd64 arch, hostname localvm01

$ ./fastvm.py update
  # Check for newer versions of cloud images

$ ./fastvm.py update --download
  # Download all available updates and remove old versions
```
