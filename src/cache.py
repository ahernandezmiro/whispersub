import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path


CACHE_SCHEMA_VERSION = 1


def source_identity(path):
    resolved = Path(path).resolve()
    stat = resolved.stat()
    return {
        "path": os.path.normcase(str(resolved)),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def build_manifest(stage, source_path, config, metadata=None):
    return {
        "schema": CACHE_SCHEMA_VERSION,
        "stage": stage,
        "source": source_identity(source_path),
        "config": config,
        "metadata": metadata or {},
    }


def manifest_path(artifact_path):
    return f"{artifact_path}.manifest.json"


def read_manifest(artifact_path):
    try:
        with open(manifest_path(artifact_path), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError, TypeError):
        return None


def cache_is_valid(artifact_path, expected_manifest):
    if not os.path.isfile(artifact_path):
        return False
    current = read_manifest(artifact_path)
    if not current:
        return False
    return all(
        current.get(key) == expected_manifest.get(key)
        for key in ("schema", "stage", "source", "config")
    )


def write_manifest(artifact_path, manifest):
    target = manifest_path(artifact_path)
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{os.path.basename(target)}.",
        suffix=".tmp",
        dir=os.path.dirname(os.path.abspath(target)),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


@contextmanager
def atomic_output_path(target_path):
    target = os.path.abspath(target_path)
    directory = os.path.dirname(target)
    os.makedirs(directory, exist_ok=True)
    base, extension = os.path.splitext(os.path.basename(target))
    fd, temporary = tempfile.mkstemp(
        prefix=f".{base}.", suffix=f".tmp{extension}", dir=directory
    )
    os.close(fd)
    os.unlink(temporary)
    try:
        yield temporary
        if not os.path.isfile(temporary):
            raise RuntimeError(f"Expected output was not created: {temporary}")
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def write_text_atomic(path, content):
    with atomic_output_path(path) as temporary:
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(content)
