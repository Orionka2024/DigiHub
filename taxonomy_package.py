"""Checksum verification and bounded extraction of deployment-supplied ZIPs."""
from hashlib import sha256
import json
import os
import fcntl
from pathlib import Path, PurePosixPath
import shutil
import stat
from tempfile import mkdtemp
import zipfile


def extract_verified(package: Path, expected: str, destination: Path) -> Path:
    if sha256(package.read_bytes()).hexdigest() != expected:
        raise ValueError("Package checksum mismatch.")
    destination.mkdir(parents=True, exist_ok=True)

    # A cache belongs to exactly one archive, never to a shared release folder.
    destination = destination / expected
    destination.mkdir(parents=True, exist_ok=True)
    lock = (destination / "extract.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX)
    cached = destination / "contents"
    marker = destination / "files.json"
    if cached.exists() and marker.exists():
        checks = json.loads(marker.read_text())
        actual = {str(p.relative_to(cached)): sha256(p.read_bytes()).hexdigest()
                  for p in cached.rglob("*") if p.is_file()}
        if checks == actual:
            roots = list(cached.glob("**/META-INF/taxonomyPackage.xml"))
            if len(roots) == 1:
                lock.close()
                return roots[0].parent.parent
    if cached.exists():
        shutil.rmtree(cached, ignore_errors=True)
    # Clean stale temp directories to avoid exhausting /tmp disk quota
    for p in (destination, destination.parent):
        if p.exists():
            for item in p.glob("taxonomy-*"):
                shutil.rmtree(item, ignore_errors=True)
    if os.environ.get("VERCEL"):
        for item in Path("/tmp").glob("taxonomy-*"):
            shutil.rmtree(item, ignore_errors=True)
        if destination.parent.exists():
            for item in destination.parent.iterdir():
                if item.is_dir() and item.name != expected:
                    shutil.rmtree(item, ignore_errors=True)
    target = Path(mkdtemp(prefix="taxonomy-", dir=destination))
    try:
        with zipfile.ZipFile(package) as archive:
            members = archive.infolist()
            if len(members) > 100000 or sum(m.file_size for m in members) > 1024 ** 3:
                raise ValueError("Taxonomy archive exceeds extraction limits.")
            seen = set()
            for member in members:
                path = PurePosixPath(member.filename)
                if (path.is_absolute() or ".." in path.parts or "\\" in member.filename
                        or ":" in member.filename or stat.S_ISLNK(member.external_attr >> 16)):
                    raise ValueError("Unsafe taxonomy archive path.")
                key = str(path).casefold()
                if key in seen:
                    raise ValueError("Duplicate taxonomy archive path.")
                seen.add(key)
            archive.extractall(target)
        roots = [p.parent.parent for p in target.glob("**/META-INF/taxonomyPackage.xml")]
        if len(roots) != 1:
            raise ValueError("Expected one taxonomy package metadata file.")
        relative_root = roots[0].relative_to(target)
        checks = {str(p.relative_to(target)): sha256(p.read_bytes()).hexdigest()
                  for p in target.rglob("*") if p.is_file()}
        os.replace(target, cached)
        marker.write_text(json.dumps(checks, sort_keys=True))
        return cached / relative_root
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    finally:
        lock.close()
