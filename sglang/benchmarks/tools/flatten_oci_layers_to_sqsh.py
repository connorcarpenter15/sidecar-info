#!/usr/bin/env python3
"""Flatten cached OCI image layers into a squashfs image.

This is a fallback for Enroot imports that can download and extract layers but
fail when mounting too many lowerdirs during squashfs creation.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def docker_json(url: str, token: str, accept: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": accept},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def layer_digests(repo: str, tag: str) -> tuple[str, list[str]]:
    token_url = (
        "https://auth.docker.io/token?"
        f"service=registry.docker.io&scope=repository:{repo}:pull"
    )
    with urllib.request.urlopen(token_url, timeout=120) as resp:
        token = json.load(resp)["token"]

    index = docker_json(
        f"https://registry-1.docker.io/v2/{repo}/manifests/{tag}",
        token,
        "application/vnd.docker.distribution.manifest.list.v2+json, "
        "application/vnd.oci.image.index.v1+json",
    )
    digest = None
    for manifest in index.get("manifests", []):
        platform = manifest.get("platform", {})
        if platform.get("architecture") in {"arm64", "aarch64"}:
            digest = manifest["digest"]
            break
    if digest is None:
        raise RuntimeError(f"no arm64 manifest found for {repo}:{tag}")

    manifest = docker_json(
        f"https://registry-1.docker.io/v2/{repo}/manifests/{digest}",
        token,
        "application/vnd.docker.distribution.manifest.v2+json, "
        "application/vnd.oci.image.manifest.v1+json",
    )
    return digest, [layer["digest"].split(":", 1)[1] for layer in manifest["layers"]]


def safe_clear(path: Path, required_parent: Path) -> None:
    path = path.resolve()
    required_parent = required_parent.resolve()
    if required_parent not in path.parents and path != required_parent:
        raise RuntimeError(f"refusing to remove {path}; outside {required_parent}")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def remove_path(path: Path) -> None:
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    except FileNotFoundError:
        return


def apply_whiteouts(layer_dir: Path, rootfs: Path) -> None:
    for dirpath, _, filenames in os.walk(layer_dir):
        current = Path(dirpath)
        rel_dir = Path(os.path.relpath(current, layer_dir))
        if rel_dir == Path("."):
            rel_dir = Path()

        if ".wh..wh..opq" in filenames:
            target_dir = rootfs / rel_dir
            if target_dir.exists():
                for child in target_dir.iterdir():
                    remove_path(child)
            (current / ".wh..wh..opq").unlink()

        for filename in filenames:
            if not filename.startswith(".wh.") or filename == ".wh..wh..opq":
                continue
            target_name = filename[len(".wh.") :]
            remove_path(rootfs / rel_dir / target_name)
            (current / filename).unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="lmsysorg/sglang")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--processors", default="16")
    args = parser.parse_args()

    args.work_dir.mkdir(parents=True, exist_ok=True)
    layer_dir = args.work_dir / "layer"
    rootfs = args.work_dir / "rootfs"
    metadata = args.output.with_suffix(args.output.suffix + ".json")

    manifest_digest, layers = layer_digests(args.repo, args.tag)
    print(f"manifest: {manifest_digest}", flush=True)
    print(f"layers: {len(layers)}", flush=True)

    safe_clear(rootfs, args.work_dir)
    for index, digest in enumerate(layers, 1):
        cache_file = args.cache_dir / digest
        if not cache_file.exists():
            raise FileNotFoundError(f"missing cached layer {cache_file}")

        safe_clear(layer_dir, args.work_dir)
        print(f"[{index}/{len(layers)}] {digest}", flush=True)
        run(
            [
                "tar",
                "-C",
                str(layer_dir),
                "--warning=no-timestamp",
                "--anchored",
                "--exclude=dev/*",
                "--exclude=./dev/*",
                "--use-compress-program=zstd",
                "--delay-directory-restore",
                "-pxf",
                str(cache_file),
            ]
        )
        apply_whiteouts(layer_dir, rootfs)
        run(["rsync", "-aHAX", "--numeric-ids", f"{layer_dir}/", f"{rootfs}/"])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        args.output.unlink()
    run(
        [
            "mksquashfs",
            str(rootfs),
            str(args.output),
            "-noappend",
            "-comp",
            "zstd",
            "-processors",
            args.processors,
            "-no-progress",
        ]
    )
    metadata.write_text(
        json.dumps(
            {"repo": args.repo, "tag": args.tag, "manifest": manifest_digest, "layers": layers},
            indent=2,
        )
        + "\n"
    )
    print(f"wrote {args.output}", flush=True)
    print(f"wrote {metadata}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
