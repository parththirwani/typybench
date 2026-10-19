"""Copy only stripped source from the official archive for a fresh cohort."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from .select import DATA_ROOT


PREFIX = "typybenchdata/"
MAX_FILE_BYTES = 5_000_000


def extract_sources(archive: Path, repos: tuple[str, ...], *, dry_run: bool = False) -> dict:
    if not repos or len(set(repos)) != len(repos):
        raise ValueError("Provide distinct repositories")
    for repo in repos:
        if not repo or PurePosixPath(repo).name != repo or repo in (".", ".."):
            raise ValueError(f"Unsafe repository name: {repo}")
        if (DATA_ROOT / repo / "repo_without_types").exists():
            raise FileExistsError(f"Source already exists: {repo}")

    chosen = []
    with ZipFile(archive) as source:
        for info in source.infolist():
            if info.is_dir():
                continue
            path = PurePosixPath(info.filename)
            parts = path.parts
            if (len(parts) < 4 or parts[0] != "typybenchdata"
                    or parts[1] not in repos or parts[2] != "repo_without_types"):
                continue
            rel = PurePosixPath(*parts[3:])
            if rel.is_absolute() or ".." in rel.parts or info.file_size > MAX_FILE_BYTES:
                raise ValueError(f"Unsafe source member: {info.filename}")
            chosen.append((info, rel))
        counts = {repo: sum(info.filename.startswith(
            f"{PREFIX}{repo}/repo_without_types/") for info, _ in chosen)
            for repo in repos}
        if any(count == 0 for count in counts.values()):
            raise ValueError(f"Missing source repository: {counts}")
        if not dry_run:
            for info, rel in chosen:
                repo = PurePosixPath(info.filename).parts[1]
                root = (DATA_ROOT / repo / "repo_without_types").resolve()
                target = (root / str(rel)).resolve()
                if not target.is_relative_to(root) or target.exists():
                    raise ValueError(f"Unsafe or existing source target: {target}")
                target.parent.mkdir(parents=True, exist_ok=True)
                data = source.read(info)
                if len(data) != info.file_size:
                    raise ValueError(f"Incomplete source member: {info.filename}")
                with target.open("xb") as handle:
                    handle.write(data)

    digest = hashlib.sha256()
    with archive.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return {"archive_sha256": digest.hexdigest(), "archive_bytes": archive.stat().st_size,
            "repositories": repos, "files_by_repo": counts,
            "source_bytes": sum(info.file_size for info, _ in chosen),
            "dry_run": dry_run}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--repos", nargs="+", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(extract_sources(args.archive, tuple(args.repos), dry_run=args.dry_run),
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
