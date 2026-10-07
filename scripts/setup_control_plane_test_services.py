#!/usr/bin/env python3
"""Extract checksum-pinned disposable test tools into a user-owned directory.

No apt/dpkg installation, package scripts, system repositories or system settings.
These Linux binaries are development fixtures, never application dependencies.
"""

import argparse
import hashlib
import json
import subprocess
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(
        Path(__file__).with_name("control_plane_test_packages.json").read_text()
    )
    for package in manifest["packages"]:
        url = package["url"]
        if not url.startswith("https://deb.debian.org/debian/pool/"):
            raise ValueError("unexpected test-package origin")
        archive = args.root / url.rsplit("/", 1)[1]
        if not archive.exists():
            with urllib.request.urlopen(url, timeout=30) as response:
                data = response.read(package["size"] + 1)
            if (
                len(data) != package["size"]
                or hashlib.sha256(data).hexdigest() != package["sha256"]
            ):
                raise ValueError("test-package verification failed")
            archive.write_bytes(data)
        data = archive.read_bytes()
        if (
            len(data) != package["size"]
            or hashlib.sha256(data).hexdigest() != package["sha256"]
        ):
            raise ValueError("test-package verification failed")
        subprocess.run(
            ["dpkg-deb", "-x", str(archive), str(args.root / "extracted")], check=True
        )
        print(f"Verified {package['name']} {package['version']}")
    print(f"SHIPAGENT_TEST_SERVICE_ROOT={args.root / 'extracted'}")


if __name__ == "__main__":
    main()
