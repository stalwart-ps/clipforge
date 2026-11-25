"""Download InsightFace buffalo_l face detection and recognition ONNX weights."""

from __future__ import annotations

import argparse
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

BUFFALO_L_URL = "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip"
REQUIRED_MODELS = ("det_10g.onnx", "w600k_r50.onnx")


def download_face_models(target_dir: Path, force: bool = False) -> None:
    """Download buffalo_l.zip and extract required ONNX models into target_dir."""
    target_dir.mkdir(parents=True, exist_ok=True)

    existing = [name for name in REQUIRED_MODELS if (target_dir / name).is_file()]
    if len(existing) == len(REQUIRED_MODELS) and not force:
        print(f"All required models already exist in {target_dir}. Use --force to re-download.")
        return

    with tempfile.TemporaryDirectory() as tmp_dir:
        zip_path = Path(tmp_dir) / "buffalo_l.zip"
        print(f"Downloading {BUFFALO_L_URL} ...")
        with urllib.request.urlopen(BUFFALO_L_URL) as response, zip_path.open("wb") as out_file:
            shutil.copyfileobj(response, out_file)

        print(f"Extracting {', '.join(REQUIRED_MODELS)} to {target_dir} ...")
        extracted: set[str] = set()
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.infolist():
                if member.is_dir():
                    continue
                filename = Path(member.filename).name
                if filename in REQUIRED_MODELS:
                    dest_path = target_dir / filename
                    with zf.open(member) as src, dest_path.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    extracted.add(filename)

        missing = set(REQUIRED_MODELS) - extracted
        if missing:
            raise FileNotFoundError(
                f"Expected models missing from archive: {', '.join(sorted(missing))}"
            )

    print("Model download and extraction complete.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download InsightFace buffalo_l ONNX models for ClipForge Local."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download and overwrite existing model files.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    face_models_dir = repo_root / "backend" / "models" / "face"
    download_face_models(face_models_dir, force=args.force)


if __name__ == "__main__":
    main()
