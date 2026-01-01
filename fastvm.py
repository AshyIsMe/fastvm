#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "requests",
# ]
# ///

import argparse
import os
import random
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import requests

# TODO:
# TODO: Use cloud-init to configure ssh-keys and ssh https://cloudinit.readthedocs.io/en/latest/tutorial/qemu.html
# TODO: More images: ubuntu, freebsd, openbsd, helios, etc
# TODO: hash verification

IMAGES = {
    "arch": {
        "amd64": [
            # basic image with ssh running and user:pw arch:arch
            "https://gitlab.archlinux.org/archlinux/arch-boxes/-/package_files/10674/download"
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
            "https://cloud.debian.org/images/cloud/sid/daily/latest/debian-sid-nocloud-amd64-daily.qcow2"
        ],
        "arm64": [
            "https://cloud.debian.org/images/cloud/sid/daily/latest/debian-sid-nocloud-arm64-daily.qcow2"
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


def get_qemu_command(arch, vm_image_path, vm_name):
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

    # Add KVM if available (but don't fail if not)
    if arch in ["amd64", "i386"]:
        cmd.extend(["-enable-kvm"])

    # Add architecture-specific options
    if arch == "arm64":
        cmd.extend(["-machine", "virt", "-cpu", "cortex-a72"])

    return cmd, ssh_port


def run_vm(qemu_cmd, vm_name, ssh_port):
    """Run the VM using QEMU command."""
    print(f"Starting VM '{vm_name}' with command: {' '.join(qemu_cmd)}")

    try:
        # Check if QEMU binary exists
        qemu_binary = qemu_cmd[0]
        if shutil.which(qemu_binary) is None:
            print(f"Error: {qemu_binary} not found. Please install QEMU.")
            return False

        # Run QEMU in background using Popen
        process = subprocess.Popen(
            qemu_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
        )

        print(f"VM '{vm_name}' started successfully in the background!")
        print(f"Process ID: {process.pid}")
        print(f"SSH port forwarding: localhost:{ssh_port} -> VM:22")
        print()
        print("Connection methods:")
        print(f"1. SSH (once VM is booted): ssh -p {ssh_port} user@localhost")
        print(f"2. QEMU Monitor: socat - UNIX-CONNECT:/tmp/qemu-monitor-{vm_name}.sock")
        print(f"3. Check VM status: ps aux | grep {process.pid}")
        print(f"4. Stop VM: kill {process.pid}")
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
        epilog="""
examples:
  fastvm debian                    # Use debian with default arch
  fastvm fedora arm64              # Use fedora with arm64 architecture  
  fastvm debian amd64 localvm01    # Use debian, amd64 arch, hostname localvm01
        """,
    )

    parser.add_argument(
        "distro", choices=list(IMAGES.keys()), help="Distribution to use"
    )
    parser.add_argument(
        "arch", nargs="?", default="amd64", help="Architecture (default: amd64)"
    )
    parser.add_argument("hostname", nargs="?", help="Hostname for the VM")

    return parser.parse_args()


def main():
    print("fastvm version v0.1")
    args = parse_args()

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

    # Generate QEMU command
    qemu_cmd, ssh_port = get_qemu_command(args.arch, vm_image_path, vm_name)

    # Run the VM
    if run_vm(qemu_cmd, vm_name, ssh_port):
        return 0
    else:
        return 1


if __name__ == "__main__":
    main()
