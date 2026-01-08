#!/usr/bin/env -S uv run -q
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "requests",
#     "PyYAML",
# ]
# ///

import argparse
import os
import random
import re
import shutil
import socket
import subprocess
import time
import yaml
from pathlib import Path
from urllib.parse import urlparse
from glob import glob

import requests

# TODO:
# TODO: More images: ubuntu, freebsd, openbsd, helios, etc
#   - alpine: https://wiki.alpinelinux.org/wiki/Install_Alpine_in_QEMU
#   - openbsd: https://github.com/hcartiaux/openbsd-cloud-image
#   - helios: https://github.com/oxidecomputer/helios-engvm
# TODO: hash verification

IMAGES = {
    "arch": {
        "amd64": [
            # basic image with ssh running and user:pw arch:arch
            # "https://gitlab.archlinux.org/archlinux/arch-boxes/-/package_files/10674/download"

            # cloud-init image:
            "https://gitlab.archlinux.org/archlinux/arch-boxes/-/package_files/10678/download"
        ]
    },
    "fedora": {
        "amd64": [
            "https://download.fedoraproject.org/pub/fedora/linux/releases/43/Cloud/x86_64/images/Fedora-Cloud-Base-Generic-43-1.6.x86_64.qcow2"
        ],
        "arm64": [
            "https://download.fedoraproject.org/pub/fedora/linux/releases/43/Cloud/aarch64/images/Fedora-Cloud-Base-Generic-43-1.6.aarch64.qcow2"
        ],
    },
    "debian": {
        "amd64": [
            # "https://cloud.debian.org/images/cloud/sid/daily/latest/debian-sid-nocloud-amd64-daily.qcow2"
            "https://cloud.debian.org/images/cloud/sid/daily/latest/debian-sid-generic-amd64-daily.qcow2"
        ],
        "arm64": [
            # "https://cloud.debian.org/images/cloud/sid/daily/latest/debian-sid-nocloud-arm64-daily.qcow2"
            "https://cloud.debian.org/images/cloud/sid/daily/latest/debian-sid-generic-arm64-daily.qcow2"
        ],
    },
}


def get_cache_dir():
    """Get XDG user cache directory for fastvm."""
    xdg_cache_home = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache_home:
        cache_dir = Path(xdg_cache_home) / "fastvm"
    else:
        cache_dir = Path.home() / ".cache" / "fastvm"

    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_data_dir():
    """Get XDG user data directory for fastvm VMs."""
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        data_dir = Path(xdg_data_home) / "fastvm"
    else:
        data_dir = Path.home() / ".local" / "share" / "fastvm"

    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_ssh_public_keys():
    """Get the user's SSH public keys."""
    ssh_dir = Path.home() / ".ssh"
    return [open(f,'r').read().strip() for f in glob(str(ssh_dir / "*.pub"))]


def create_cloud_init_server(vm_name, data_dir, hostname):
    """Create cloud-init HTTP server with user-data and meta-data."""
    server_dir = data_dir / f"{vm_name}-cloud-init-server"

    # Check if server directory already exists
    if server_dir.exists():
        print(f"Cloud-init server directory already exists: {server_dir}")
    else:
        server_dir.mkdir(parents=True, exist_ok=True)

    # Get SSH public key
    ssh_keys = get_ssh_public_keys()
    if len(ssh_keys) == 0:
        print("Warning: No SSH public key found. Creating VM without SSH key setup.")
        print("To generate an SSH key, run: ssh-keygen -t ed25519")
    print(f"Using SSH keys: {ssh_keys}...")

    # Create user-data configuration
    user_data = {
        "users": [
            {
                "name": "user",
                "gecos": "Default user",
                "sudo": "ALL=(ALL) NOPASSWD:ALL",
                "shell": "/bin/bash",
                "ssh-authorized-keys": ssh_keys
            }
        ],
        "ssh_pwauth": False,  # Disable password authentication
        "disable_root": True,
        "package_update": True,
        "packages": ["openssh-server"],
        "runcmd": [
            "systemctl enable ssh",
            "systemctl start ssh"
        ]
    }

    # Create meta-data
    meta_data = {
        "instance-id": f"fastvm-{vm_name}",
        "local-hostname": hostname
    }

    try:
        # Write user-data
        user_data_file = server_dir / "user-data"
        with open(user_data_file, 'w') as f:
            f.write("#cloud-config\n")
            yaml.dump(user_data, f, default_flow_style=False)

        # Write meta-data
        meta_data_file = server_dir / "meta-data"
        with open(meta_data_file, 'w') as f:
            yaml.dump(meta_data, f, default_flow_style=False)

        # Find available port for HTTP server (starting from 8080)
        port = 8080
        while port < 8200:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(('127.0.0.1', port))
                    break
                except OSError:
                    port += 1
        else:
            print("Error: Could not find available port for cloud-init server")
            return None, None

        # Start HTTP server in background
        server_cmd = [
            "python3", "-m", "http.server",
            str(port),
            "--bind", "127.0.0.1",
            "--directory", str(server_dir)
        ]

        server_process = subprocess.Popen(
            server_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL
        )

        print(f"Started cloud-init HTTP server on port {port} (PID: {server_process.pid})")
        print(f"Server directory: {server_dir}")

        # Return server info
        return {
            'port': port,
            'process': server_process,
            'directory': server_dir
        }, port

    except Exception as e:
        print(f"Error creating cloud-init server: {e}")
        return None, None


def create_vm_image(cached_image_path, distro, arch, hostname, data_dir):
    """Create a new VM image by copying the cached image."""
    vm_name = f"{distro}-{arch}-{hostname}"
    vm_image_path = data_dir / f"{vm_name}.qcow2"

    if vm_image_path.exists():
        print(f"VM image already exists: {vm_image_path}")
        return vm_image_path, vm_name

    print(f"Creating VM image: {vm_image_path}")
    try:
        shutil.copy2(cached_image_path, vm_image_path)
        print(f"VM image created successfully")
        return vm_image_path, vm_name
    except Exception as e:
        print(f"Error creating VM image: {e}")
        return None, None


def get_qemu_command(arch, vm_image_path, vm_name, cloud_init_server_port=None):
    """Generate QEMU command based on architecture."""
    # Architecture to QEMU binary mapping
    qemu_binaries = {
        "amd64": "qemu-system-x86_64",
        "arm64": "qemu-system-aarch64",
        "i386": "qemu-system-i386",
    }

    qemu_binary = qemu_binaries.get(arch, "qemu-system-x86_64")

    # Use random port for SSH forwarding (22222-22999)
    ssh_port = random.randint(22222, 22999)

    cmd = [
        qemu_binary,
        "-m",
        "2048",  # 2GB RAM
        "-smp",
        "2",  # 2 CPUs
        "-drive",
        f"file={vm_image_path},format=qcow2",
        "-netdev",
        f"user,id=net0,hostfwd=tcp::{ssh_port}-:22",  # SSH port forwarding
        "-device",
        "virtio-net-pci,netdev=net0",
        "-nographic",  # No GUI, console only
        "-name",
        vm_name,  # Set VM name
        "-monitor",
        f"unix:/tmp/qemu-monitor-{vm_name}.sock,server,nowait",  # Monitor socket
        "-serial",
        "stdio",  # Serial console to stdio
    ]

    # Add cloud-init NoCloud datasource via kernel cmdline if server provided
    if cloud_init_server_port:
        # Use NoCloud datasource pointing to our HTTP server
        # The VM will access the host's HTTP server via the default gateway (10.0.2.2)
        datasource_url = f"http://10.0.2.2:{cloud_init_server_port}/"
        cmd.extend([
            "-smbios",
            f"type=1,serial=ds='nocloud;s={datasource_url}'"
        ])

    # Add KVM if available (but don't fail if not)
    if arch in ["amd64", "i386"]:
        cmd.extend(["-enable-kvm"])

    # Add architecture-specific options
    if arch == "arm64":
        cmd.extend(["-machine", "virt", "-cpu", "cortex-a72"])

    return cmd, ssh_port


def run_vm(qemu_cmd, vm_name, ssh_port, cloud_init_server=None):
    """Run the VM using QEMU command."""
    print(f"Starting VM '{vm_name}' with command: {' '.join(qemu_cmd)}")

    try:
        # Check if QEMU binary exists
        qemu_binary = qemu_cmd[0]
        if shutil.which(qemu_binary) is None:
            print(f"Error: {qemu_binary} not found. Please install QEMU.")
            return False

        # Run QEMU in background using Popen with proper detachment
        process = subprocess.Popen(
            qemu_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            start_new_session=True,  # Detach from parent process
        )

        # Give the process a moment to start
        time.sleep(1)

        # Check if process started successfully
        poll_result = process.poll()
        if poll_result is not None:
            # Process already terminated, get error info
            stderr_output = process.stderr.read() if process.stderr else "No error output"
            print(f"Error: QEMU process terminated immediately with exit code {poll_result}")
            print(f"Error output: {stderr_output}")
            return False

        print(f"VM '{vm_name}' started successfully in the background!")
        print(f"VM Process ID: {process.pid}")
        if cloud_init_server:
            print(f"Cloud-init Server PID: {cloud_init_server['process'].pid}")
            print(f"Cloud-init Server Port: {cloud_init_server['port']}")
        print(f"SSH port forwarding: localhost:{ssh_port} -> VM:22")
        print()
        print("Connection methods:")
        print(f"1. SSH (once VM is booted): ssh -p {ssh_port} user@localhost")
        print(f"2. QEMU Monitor: socat - UNIX-CONNECT:/tmp/qemu-monitor-{vm_name}.sock")
        print(f"3. Check VM status: ps aux | grep {process.pid}")
        print(f"4. Stop VM: kill {process.pid}")
        if cloud_init_server:
            print(f"5. Stop cloud-init server: kill {cloud_init_server['process'].pid}")
            print(f"6. Cloud-init files: {cloud_init_server['directory']}")
        print()
        print("Note: VM may take 1-2 minutes to fully boot and configure SSH via cloud-init.")
        print("Note: Remember to stop both VM and cloud-init server processes when done.")
        return True

    except Exception as e:
        print(f"Error starting VM: {e}")
        return False


def get_filename_from_response(response, url):
    """Extract filename from response headers or URL as fallback."""
    # Try to get filename from Content-Disposition header
    content_disposition = response.headers.get("content-disposition")
    if content_disposition:
        # Look for filename= in the header
        filename_match = re.search(r'filename[*]?="?([^"]+)"?', content_disposition)
        if filename_match:
            filename = filename_match.group(1)
            return filename

    # Fallback to URL parsing
    parsed = urlparse(url)
    filename = Path(parsed.path).name
    if not filename or "." not in filename:
        # Final fallback for URLs without clear filename
        filename = f"image_{hash(url) % 10000}.qcow2"
    return filename


def download_image(url, cache_dir):
    """Download image from URL to cache directory."""
    print(f"Checking image from: {url}")

    try:
        # First, make a HEAD request to get the filename from headers
        head_response = requests.head(url, allow_redirects=True)
        head_response.raise_for_status()

        filename = get_filename_from_response(head_response, url)
        filepath = cache_dir / filename

        # Check if file already exists
        if filepath.exists():
            print(f"Image already cached: {filepath}")
            return filepath

        print(f"Downloading image to: {filepath}")

        # Now make the actual download request
        response = requests.get(url, stream=True)
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0

        with open(filepath, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        print(
                            f"\rProgress: {percent:.1f}% ({downloaded}/{total_size} bytes)",
                            end="",
                            flush=True,
                        )

        print("\nDownload completed successfully!")
        return filepath

    except requests.RequestException as e:
        print(f"\nError downloading image: {e}")
        if "filepath" in locals() and filepath.exists():
            filepath.unlink()  # Remove partial download
        return None


def parse_args():
    parser = argparse.ArgumentParser(
        prog="fastvm",
        description="Fast VM provisioning with cloud images",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(
        dest="command",
        help="Available commands",
        required=True
    )

    # Run subcommand
    run_parser = subparsers.add_parser(
        "run",
        help="Run a new VM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  fastvm run debian                    # Use debian with default arch
  fastvm run fedora arm64              # Use fedora with arm64 architecture
  fastvm run debian amd64 localvm01    # Use debian, amd64 arch, hostname localvm01
        """,
    )
    run_parser.add_argument(
        "distro", choices=list(IMAGES.keys()), help="Distribution to use"
    )
    run_parser.add_argument(
        "arch", nargs="?", default="amd64", help="Architecture (default: amd64)"
    )
    run_parser.add_argument("hostname", nargs="?", help="Hostname for the VM")

    # PS subcommand
    ps_parser = subparsers.add_parser(
        "ps",
        help="List running fastvm VMs"
    )

    # LS subcommand
    ls_parser = subparsers.add_parser(
        "ls",
        help="List all fastvm VMs (running and stopped)"
    )

    # RM subcommand
    rm_parser = subparsers.add_parser(
        "rm",
        help="Delete a fastvm VM"
    )
    rm_parser.add_argument(
        "vm_name",
        help="Name of the VM to delete (use 'fastvm ls' to see available VMs)"
    )
    rm_parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Force deletion without confirmation"
    )

    # UPDATE subcommand
    update_parser = subparsers.add_parser(
        "update",
        help="Check for and download updated cloud images"
    )
    update_parser.add_argument(
        "-d", "--download",
        action="store_true",
        help="Automatically download all available updates"
    )

    return parser.parse_args()


def get_all_vms():
    """Get list of all fastvm VMs by scanning data directory."""
    data_dir = get_data_dir()
    vm_files = list(data_dir.glob("*.qcow2"))
    vms = []

    for vm_file in vm_files:
        vm_name = vm_file.stem  # Remove .qcow2 extension
        # Skip cloud-init server directories
        if not vm_name.endswith("-cloud-init-server"):
            vms.append(vm_name)

    return sorted(vms)


def is_vm_running(vm_name):
    """Check if a VM is currently running by checking for monitor socket and process."""
    monitor_socket = f"/tmp/qemu-monitor-{vm_name}.sock"

    # Check if monitor socket exists
    if not os.path.exists(monitor_socket):
        return False, None

    # Try to find QEMU process by searching for VM name in process list
    try:
        result = subprocess.run(
            ["pgrep", "-f", f"qemu.*{vm_name}"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            return True, pids[0]  # Return first PID found
    except Exception:
        pass

    return False, None


def get_vm_ssh_port(vm_name):
    """Try to extract SSH port from running QEMU process command line."""
    try:
        # Get the full command line for the QEMU process
        result = subprocess.run(
            ["pgrep", "-f", "-a", f"qemu.*{vm_name}"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            # Parse the command line to find hostfwd port
            for line in result.stdout.split('\n'):
                if "hostfwd=tcp" in line:
                    import re
                    match = re.search(r'hostfwd=tcp::(\d+)-:22', line)
                    if match:
                        return int(match.group(1))
    except Exception:
        pass
    return None


def list_vms():
    """List all fastvm VMs with their status."""
    vms = get_all_vms()
    if not vms:
        print("No fastvm VMs found.")
        return

    print(f"{'VM NAME':<30} {'STATUS':<10} {'PID':<8} {'SSH PORT':<10}")
    print("-" * 60)

    for vm_name in vms:
        running, pid = is_vm_running(vm_name)
        if running:
            ssh_port = get_vm_ssh_port(vm_name)
            port_str = str(ssh_port) if ssh_port else "N/A"
            print(f"{vm_name:<30} {'RUNNING':<10} {pid:<8} {port_str:<10}")
        else:
            print(f"{vm_name:<30} {'STOPPED':<10} {'-':<8} {'-':<10}")


def list_running_vms():
    """List only running fastvm VMs."""
    vms = get_all_vms()
    running_vms = []

    for vm_name in vms:
        running, pid = is_vm_running(vm_name)
        if running:
            ssh_port = get_vm_ssh_port(vm_name)
            running_vms.append((vm_name, pid, ssh_port))

    if not running_vms:
        print("No running fastvm VMs found.")
        return

    print(f"{'VM NAME':<30} {'PID':<8} {'SSH PORT':<10}")
    print("-" * 50)

    for vm_name, pid, ssh_port in running_vms:
        port_str = str(ssh_port) if ssh_port else "N/A"
        print(f"{vm_name:<30} {pid:<8} {port_str:<10}")


def delete_vm(vm_name, force=False):
    """Delete a fastvm VM and associated files."""
    data_dir = get_data_dir()
    vm_file = data_dir / f"{vm_name}.qcow2"
    cloud_init_dir = data_dir / f"{vm_name}-cloud-init-server"

    # Check if VM exists
    if not vm_file.exists():
        print(f"Error: VM '{vm_name}' not found.")
        return False

    # Check if VM is running
    running, pid = is_vm_running(vm_name)
    if running:
        if not force:
            response = input(f"VM '{vm_name}' is currently running (PID: {pid}). Stop and delete it? (y/N): ")
            if response.lower() not in ['y', 'yes']:
                print("Deletion cancelled.")
                return False

        # Stop the VM
        try:
            print(f"Stopping VM '{vm_name}' (PID: {pid})...")
            os.kill(int(pid), 15)  # SIGTERM
            time.sleep(2)

            # Check if process is still running, force kill if necessary
            if is_vm_running(vm_name)[0]:
                print("Force killing VM...")
                os.kill(int(pid), 9)  # SIGKILL
                time.sleep(1)
        except Exception as e:
            print(f"Warning: Could not stop VM process: {e}")

    # Ask for confirmation if not forced
    if not force:
        response = input(f"Delete VM '{vm_name}' and all associated files? (y/N): ")
        if response.lower() not in ['y', 'yes']:
            print("Deletion cancelled.")
            return False

    # Delete files
    try:
        print(f"Deleting VM files...")
        if vm_file.exists():
            vm_file.unlink()
            print(f"Deleted: {vm_file}")

        if cloud_init_dir.exists():
            shutil.rmtree(cloud_init_dir)
            print(f"Deleted: {cloud_init_dir}")

        # Clean up monitor socket
        monitor_socket = f"/tmp/qemu-monitor-{vm_name}.sock"
        if os.path.exists(monitor_socket):
            os.unlink(monitor_socket)
            print(f"Cleaned up monitor socket: {monitor_socket}")

        print(f"VM '{vm_name}' deleted successfully.")
        return True

    except Exception as e:
        print(f"Error deleting VM: {e}")
        return False


def check_image_updates():
    """Check cached images for available updates (only for distros already in use)."""
    cache_dir = get_cache_dir()
    updates_available = []

    # Patterns to identify cached images by distro
    pattern_prefixes = {
        'arch': ['Arch', 'arch'],
        'fedora': ['Fedora', 'fedora'],
        'debian': ['debian', 'Debian']
    }

    print(f"Checking cached images for updates...\n")

    # Iterate through all distro/arch combinations in the registry
    for distro, archs in IMAGES.items():
        for arch, urls in archs.items():
            url = urls[0]

            # Find existing cached files for this distro
            old_files = []
            if distro in pattern_prefixes:
                for prefix in pattern_prefixes[distro]:
                    old_files.extend(cache_dir.glob(f"{prefix}*.qcow2"))

            # Skip if user has never cached this distro
            if not old_files:
                continue

            try:
                # Get remote file information
                head_response = requests.head(url, allow_redirects=True, timeout=10)
                head_response.raise_for_status()

                remote_filename = get_filename_from_response(head_response, url)
                remote_size = int(head_response.headers.get("content-length", 0))
                last_modified = head_response.headers.get("last-modified")

                cached_file = cache_dir / remote_filename

                if cached_file.exists():
                    # Current version is cached, check if remote is newer
                    cached_size = cached_file.stat().st_size
                    cached_mtime = cached_file.stat().st_mtime

                    update_available = False
                    update_reason = ""

                    if remote_size > 0 and remote_size != cached_size:
                        update_available = True
                        update_reason = f"Size changed: {cached_size} -> {remote_size} bytes"
                    elif last_modified:
                        try:
                            from email.utils import parsedate_to_datetime
                            remote_mtime = parsedate_to_datetime(last_modified).timestamp()
                            if remote_mtime > cached_mtime:
                                update_available = True
                                update_reason = "Remote file is newer"
                        except Exception:
                            pass

                    if update_available:
                        print(f"  {remote_filename}")
                        print(f"    Distro: {distro} ({arch})")
                        print(f"    Reason: {update_reason}")
                        updates_available.append({
                            'filename': remote_filename,
                            'distro': distro,
                            'arch': arch,
                            'url': url,
                            'cached_path': cached_file,
                            'reason': update_reason,
                            'old_files': []
                        })
                    else:
                        print(f"  {remote_filename}")
                        print(f"    Distro: {distro} ({arch})")
                        print(f"    Status: Up to date")
                else:
                    # New version available (filename changed), old version(s) cached
                    old_file_names = [f.name for f in old_files]
                    print(f"  {remote_filename}")
                    print(f"    Distro: {distro} ({arch})")
                    print(f"    Reason: New version available")
                    print(f"    Old cached: {', '.join(old_file_names)}")
                    updates_available.append({
                        'filename': remote_filename,
                        'distro': distro,
                        'arch': arch,
                        'url': url,
                        'cached_path': None,
                        'reason': 'New version available',
                        'old_files': list(old_files)
                    })

                print()

            except requests.RequestException as e:
                print(f"  {distro} ({arch})")
                print(f"    Error checking: {e}")
                print()

    return updates_available


def update_images_command(args):
    """Handle the 'update' subcommand."""
    updates = check_image_updates()

    if not updates:
        print("All cached images are up to date!")
        return 0

    print(f"\n{'='*60}")
    print(f"Found {len(updates)} image(s) with available updates")
    print(f"{'='*60}\n")

    # If --download flag is set, download all updates
    if args.download:
        print("Downloading updates...\n")
        cache_dir = get_cache_dir()

        for update in updates:
            print(f"Processing {update['distro']} ({update['arch']})...")

            # Remove old cached file if it exists
            if update['cached_path']:
                update['cached_path'].unlink()
                print(f"  Removed old version: {update['cached_path'].name}")

            # Remove any other old version files for this distro/arch
            for old_file in update.get('old_files', []):
                old_file.unlink()
                print(f"  Removed old version: {old_file.name}")

            # Download new version
            new_path = download_image(update['url'], cache_dir)
            if new_path:
                print(f"✓ Successfully downloaded {update['filename']}\n")
            else:
                print(f"✗ Failed to download {update['filename']}\n")

        print("Update complete!")
        return 0
    else:
        print("To download these updates, run:")
        print("  fastvm update --download")
        return 0


def run_vm_command(args):
    """Handle the 'run' subcommand to start a new VM."""
    print(f"Selected distro: {args.distro}")
    print(f"Architecture: {args.arch}")

    # Generate hostname if not provided
    if args.hostname:
        hostname = args.hostname
    else:
        hostname = f"vm{random.randint(1000, 9999)}"

    print(f"Hostname: {hostname}")

    # Check if the selected architecture is available for the distro
    if args.arch not in IMAGES[args.distro]:
        available_archs = list(IMAGES[args.distro].keys())
        print(f"Error: Architecture '{args.arch}' not available for {args.distro}")
        print(f"Available architectures: {', '.join(available_archs)}")
        return 1

    # Get the image URL (using first URL in the list for now)
    image_url = IMAGES[args.distro][args.arch][0]
    print(f"Image URL: {image_url}")

    # Get cache and data directories
    cache_dir = get_cache_dir()
    data_dir = get_data_dir()
    print(f"Cache directory: {cache_dir}")
    print(f"Data directory: {data_dir}")

    # Download the image
    cached_image_path = download_image(image_url, cache_dir)
    if not cached_image_path:
        print("\nFailed to download image")
        return 1

    print(f"\nCached image ready at: {cached_image_path}")

    # Create VM image
    vm_image_path, vm_name = create_vm_image(
        cached_image_path, args.distro, args.arch, hostname, data_dir
    )
    if not vm_image_path:
        print("Failed to create VM image")
        return 1

    # Create cloud-init HTTP server
    cloud_init_server, server_port = create_cloud_init_server(vm_name, data_dir, hostname)
    if cloud_init_server:
        print(f"Cloud-init HTTP server started on port {server_port}")
    else:
        print("Warning: Failed to create cloud-init server. VM will start without SSH key setup.")
        server_port = None

    # Generate QEMU command
    qemu_cmd, ssh_port = get_qemu_command(args.arch, vm_image_path, vm_name, server_port)

    # Run the VM
    if run_vm(qemu_cmd, vm_name, ssh_port, cloud_init_server):
        return 0
    else:
        return 1


def main():
    print("fastvm version v0.1")
    args = parse_args()

    if args.command == "run":
        return run_vm_command(args)
    elif args.command == "ps":
        list_running_vms()
        return 0
    elif args.command == "ls":
        list_vms()
        return 0
    elif args.command == "rm":
        success = delete_vm(args.vm_name, args.force)
        return 0 if success else 1
    elif args.command == "update":
        return update_images_command(args)
    else:
        print(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    main()
