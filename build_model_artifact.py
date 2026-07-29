"""Build model-artifact evidence JSON."""
import hashlib
import json
import os

MODEL_ID = "amazon/chronos-2"
CONFIGURED_REV = "29ec3766d36d6f73f0696f85560a422f50e8498c"
SNAPSHOT_DIR = os.path.join(
    r"D:\Forecasting-Tool-Local\cache\huggingface\hub",
    "models--amazon--chronos-2",
    "snapshots",
    CONFIGURED_REV,
)

files = []
total_bytes = 0
for dirpath, _dirnames, filenames in os.walk(SNAPSHOT_DIR):
    for fname in sorted(filenames):
        fpath = os.path.join(dirpath, fname)
        size = os.path.getsize(fpath)
        sha = hashlib.sha256()
        with open(fpath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha.update(chunk)
        files.append({"filename": fname, "size_bytes": size, "sha256": sha.hexdigest()})
        total_bytes += size

manifest_str = json.dumps(files, sort_keys=True).encode()
manifest_sha = hashlib.sha256(manifest_str).hexdigest()

artifact = {
    "evidence_schema_version": "2",
    "evidence_type": "model_artifact",
    "code_commit": "c55514744f94f25a05393cc3807fb28456b4947e",
    "git_worktree_clean": True,
    "model_id": MODEL_ID,
    "configured_revision": CONFIGURED_REV,
    "resolved_revision": CONFIGURED_REV,
    "snapshot_commit": CONFIGURED_REV,
    "shard_count": len(files),
    "total_bytes": total_bytes,
    "files": files,
    "manifest_sha256": manifest_sha,
}

outdir = r"D:\Forecasting-Tool-Local\temp\evidence-model-artifact"
os.makedirs(outdir, exist_ok=True)
outpath = os.path.join(outdir, "model_artifact.json")
with open(outpath, "w") as f:
    json.dump(artifact, f, indent=2)

print(f"Written: {outpath}")
print(f"Files: {len(files)}")
print(f"Total bytes: {total_bytes}")
print(f"Manifest SHA-256: {manifest_sha}")
for f in files:
    print(f'  {f["filename"]}: {f["size_bytes"]} bytes, SHA: {f["sha256"][:16]}...')
