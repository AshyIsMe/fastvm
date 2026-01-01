# fastvm

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
$ fastvm debian
root@693220a919f6:/#
```
