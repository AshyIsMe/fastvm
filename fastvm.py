#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "requests",
# ]
# ///

import argparse
import os
import re
import requests
from pathlib import Path
from urllib.parse import urlparse

# TODO: hash verification
IMAGES = {
    "arch": {
        "amd64": [
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
            "https://cloud.debian.org/images/cloud/sid/daily/latest/debian-sid-generic-amd64-daily.qcow2"
        ],
        "arm64": [
            "https://cloud.debian.org/images/cloud/sid/daily/latest/debian-sid-generic-arm64-daily.qcow2"
        ],
    },
    # "ubuntu": "TODO",
    # "freebsd": "TODO",
    # "openbsd": "TODO",
    # "helios": "TODO", # https://github.com/oxidecomputer/helios-engvm
}

def get_cache_dir():
    """Get XDG user cache directory for fastvm."""
    xdg_cache_home = os.environ.get('XDG_CACHE_HOME')
    if xdg_cache_home:
        cache_dir = Path(xdg_cache_home) / 'fastvm'
    else:
        cache_dir = Path.home() / '.cache' / 'fastvm'
    
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir

def get_filename_from_response(response, url):
    """Extract filename from response headers or URL as fallback."""
    # Try to get filename from Content-Disposition header
    content_disposition = response.headers.get('content-disposition')
    if content_disposition:
        # Look for filename= in the header
        filename_match = re.search(r'filename[*]?="?([^"]+)"?', content_disposition)
        if filename_match:
            filename = filename_match.group(1)
            return filename
    
    # Fallback to URL parsing
    parsed = urlparse(url)
    filename = Path(parsed.path).name
    if not filename or '.' not in filename:
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
        
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        print(f"\rProgress: {percent:.1f}% ({downloaded}/{total_size} bytes)", end='', flush=True)
        
        print("\nDownload completed successfully!")
        return filepath
        
    except requests.RequestException as e:
        print(f"\nError downloading image: {e}")
        if 'filepath' in locals() and filepath.exists():
            filepath.unlink()  # Remove partial download
        return None

def parse_args():
    parser = argparse.ArgumentParser(
        prog='fastvm',
        description='Fast VM provisioning with cloud images',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  fastvm debian                    # Use debian with default arch
  fastvm fedora arm64              # Use fedora with arm64 architecture  
  fastvm debian amd64 localvm01    # Use debian, amd64 arch, hostname localvm01
        """)
    
    parser.add_argument('distro', 
                        choices=list(IMAGES.keys()),
                        help='Distribution to use')
    parser.add_argument('arch', 
                        nargs='?', 
                        default='amd64',
                        help='Architecture (default: amd64)')
    parser.add_argument('hostname', 
                        nargs='?',
                        help='Hostname for the VM')
    
    return parser.parse_args()

def main():
    print("fastvm version v0.1")
    args = parse_args()
    
    print(f"Selected distro: {args.distro}")
    print(f"Architecture: {args.arch}")
    if args.hostname:
        print(f"Hostname: {args.hostname}")
    else:
        print("Hostname: (not specified)")
    
    # Check if the selected architecture is available for the distro
    if args.arch not in IMAGES[args.distro]:
        available_archs = list(IMAGES[args.distro].keys())
        print(f"Error: Architecture '{args.arch}' not available for {args.distro}")
        print(f"Available architectures: {', '.join(available_archs)}")
        return 1
    
    # Get the image URL (using first URL in the list for now)
    image_url = IMAGES[args.distro][args.arch][0]
    print(f"Image URL: {image_url}")
    
    # Get cache directory
    cache_dir = get_cache_dir()
    print(f"Cache directory: {cache_dir}")
    
    # Download the image
    image_path = download_image(image_url, cache_dir)
    if image_path:
        print(f"\nImage ready at: {image_path}")
        return 0
    else:
        print("\nFailed to download image")
        return 1


if __name__ == "__main__":
    main()
