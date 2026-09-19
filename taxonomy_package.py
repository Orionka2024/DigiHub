"""Checksum verification and bounded extraction of deployment-supplied ZIPs."""
from hashlib import sha256
import atexit
from pathlib import Path, PurePosixPath
import shutil
import stat
from tempfile import mkdtemp
import zipfile


def extract_verified(package: Path, expected: str, destination: Path) -> Path:
    if sha256(package.read_bytes()).hexdigest() != expected:
        raise ValueError("Package checksum mismatch.")
    destination.mkdir(parents=True, exist_ok=True)
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
        atexit.register(shutil.rmtree, target, ignore_errors=True)
        return roots[0]
    except Exception:
        shutil.rmtree(target)
        raise
