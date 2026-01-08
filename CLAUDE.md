# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

fastvm is a tool for fast VM provisioning with cloud images using QEMU. The goal is to make spinning up VMs as simple as running Docker containers. It's implemented as a single Python script (`fastvm.py`) that uses `uv` for dependency management.

## Development Commands

### Running the tool
```bash
./fastvm.py run debian                    # Run Debian VM with default arch (amd64)
./fastvm.py run fedora arm64              # Run Fedora VM with arm64 architecture
./fastvm.py run debian amd64 localvm01    # Run Debian VM with custom hostname
./fastvm.py ps                            # List running VMs
./fastvm.py ls                            # List all VMs (running and stopped)
./fastvm.py rm <vm_name>                  # Delete a VM
./fastvm.py rm -f <vm_name>               # Force delete without confirmation
./fastvm.py update                        # Check for newer cloud image versions
./fastvm.py update --download             # Download all available updates
```

### Dependencies
The script uses `uv` for inline script dependencies (Python 3.13+):
- `requests` - for downloading cloud images
- `PyYAML` - for cloud-init configuration

No separate installation needed; `uv run` handles dependencies automatically via the script's PEP 723 metadata block.

### Task Tracking
Use `bd` for tracking tasks and TODOs in this codebase.

## Architecture

### Core Workflow
1. **Image Management**: Downloads cloud images to XDG cache directory (`~/.cache/fastvm/`)
2. **VM Creation**: Copies cached images to data directory (`~/.local/share/fastvm/`) per VM instance
3. **Cloud-init Setup**: Creates HTTP server to serve cloud-init config (user-data, meta-data)
4. **QEMU Execution**: Launches VM with appropriate architecture settings and port forwarding

### Key Components

**Directory Structure:**
- Cache dir: `$XDG_CACHE_HOME/fastvm` or `~/.cache/fastvm/` - stores downloaded cloud images
- Data dir: `$XDG_DATA_HOME/fastvm` or `~/.local/share/fastvm/` - stores VM disk images and cloud-init configs
- Monitor sockets: `/tmp/qemu-monitor-{vm_name}.sock` - QEMU monitor interface

**Image Registry (`IMAGES` dict):**
Maps distribution → architecture → download URLs for cloud images. Currently supports:
- Arch Linux (amd64)
- Fedora (amd64, arm64)
- Debian (amd64, arm64)

**Cloud-init Integration:**
- Creates local HTTP server (port 8080-8199) serving user-data and meta-data
- VM accesses server via default gateway (10.0.2.2) using NoCloud datasource
- Automatically configures SSH keys from `~/.ssh/*.pub`
- Creates 'user' account with passwordless sudo

**QEMU Configuration:**
- Random SSH port forwarding (22222-22999) to localhost
- 2GB RAM, 2 CPUs default
- KVM acceleration when available on amd64/i386
- Serial console via stdio
- Monitor socket for management

### Process Management

VMs run as detached background processes. The tool tracks:
- VM state via QEMU monitor sockets
- PIDs via `pgrep -f qemu.*{vm_name}`
- SSH ports by parsing process command lines
- Cloud-init HTTP server as separate background process (must be stopped separately)

### VM Lifecycle

**Creation:**
1. Download cloud image to cache (if not present)
2. Copy to data directory as `{distro}-{arch}-{hostname}.qcow2`
3. Generate cloud-init config in `{vm_name}-cloud-init-server/`
4. Start cloud-init HTTP server
5. Launch QEMU with cloud-init datasource URL

**Deletion:**
1. Check if VM is running, optionally stop process
2. Delete VM disk image (`.qcow2`)
3. Delete cloud-init server directory
4. Clean up monitor socket

## Important Implementation Details

- The script uses uv's inline script feature (shebang: `#!/usr/bin/env -S uv run -q`)
- SSH keys from user's `~/.ssh/` directory are automatically injected via cloud-init
- Cloud-init uses NoCloud datasource with SMBIOS serial field pointing to HTTP server
- Port selection for both SSH forwarding and cloud-init HTTP server uses random/scanning to avoid conflicts
- VMs are detached from parent process using `start_new_session=True`
