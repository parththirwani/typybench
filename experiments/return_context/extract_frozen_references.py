"""Extract only selected typed references after paired predictions are frozen."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from .score import DATA_ROOT


MAX_SOURCE_BYTES = 5_000_000


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extract(run_dir: Path, archive: Path) -> dict:
    output = run_dir / "extraction_manifest.json"
    if output.exists():
        raise FileExistsError(output)
    selection_bytes = (run_dir / "selection.json").read_bytes()
    rows_bytes = (run_dir / "rows.jsonl").read_bytes()
    manifest = json.loads((run_dir / "manifest.json").read_text())
    frozen = json.loads((run_dir / "predictions_frozen.json").read_text())
    if _hash(selection_bytes) != manifest["selection_sha256"]:
        raise ValueError("Selection changed after prediction")
    if _hash(rows_bytes) != frozen["rows_sha256"]:
        raise ValueError("Predictions changed after freeze")
    cases = json.loads(selection_bytes)
    rows = [json.loads(line) for line in rows_bytes.splitlines() if line.strip()]
    if len(rows) != 2 * len(cases) or len(rows) != frozen["rows"]:
        raise ValueError("Paired rows are incomplete")
    allowed_repos = set(manifest["repositories"])
    targets = set()
    for case in cases:
        repo = case["repo"]
        rel = PurePosixPath(case["callee_file"])
        if repo not in allowed_repos or rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"Unsafe reference path: {case['case_id']}")
        if rel.suffix != ".py":
            raise ValueError(f"Non-Python reference: {case['case_id']}")
        targets.add((repo, str(rel)))
    extracted = []
    missing = []
    with ZipFile(archive) as source:
        for repo, rel in sorted(targets):
            member = f"typybenchdata/{repo}/original_repo/{rel}"
            try:
                info = source.getinfo(member)
            except KeyError:
                missing.append(member)
                continue
            if info.is_dir() or info.file_size > MAX_SOURCE_BYTES:
                raise ValueError(f"Unexpected archive member: {member}")
            target_root = (DATA_ROOT / repo / "original_repo").resolve()
            target = (target_root / rel).resolve()
            if not target.is_relative_to(target_root):
                raise ValueError(f"Reference escaped target root: {member}")
            if target.exists():
                raise FileExistsError(target)
            data = source.read(info)
            if len(data) != info.file_size:
                raise ValueError(f"Incomplete archive member: {member}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as handle:
                handle.write(data)
            extracted.append({"path": str(target), "sha256": _hash(data),
                              "bytes": len(data)})
    archive_hash = hashlib.sha256()
    with archive.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            archive_hash.update(chunk)
    result = {"archive_bytes": archive.stat().st_size,
              "archive_sha256": archive_hash.hexdigest(),
              "selected_cases": len(cases), "unique_files": len(targets),
              "extracted": extracted, "missing": missing}
    output.write_text(json.dumps(result, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--archive", required=True)
    args = parser.parse_args()
    result = extract(Path(args.run_dir).resolve(), Path(args.archive).resolve())
    print(f"Extracted {len(result['extracted'])}/{result['unique_files']} "
          f"selected typed files; missing {len(result['missing'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
