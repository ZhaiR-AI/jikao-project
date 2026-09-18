"""Create a separate corrected paper from saved OCR; keep original submissions."""
import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from cet4_parser import build_cet4_paper
from study_store import _write_json


def repair(collection_id):
    if not re.fullmatch(r"[a-f0-9]{32}", collection_id):
        raise ValueError("Invalid collection ID")
    root = Path(__file__).resolve().parent
    collection_path = root / "data/papers" / f"{collection_id}.json"
    collection = json.loads(collection_path.read_text(encoding="utf-8"))
    doc = json.loads((root / "data/ocr" / f"{collection_id}.json").read_text(encoding="utf-8"))
    if len(collection["papers"]) != 1:
        raise ValueError("This repair requires a single-paper collection")
    original_id = f"{collection_id}-1"
    original = json.loads((root / "data/papers" / f"{original_id}.json").read_text(encoding="utf-8"))
    new_id = f"{original_id}-corrected"
    target = root / "data/papers" / f"{new_id}.json"
    if target.exists():
        raise ValueError("Corrected paper already exists; refusing to overwrite it")
    paper = build_cet4_paper(new_id, doc["source"]["file_name"], {"title": original["title"] + "（修正版）"}, doc["pages"])
    if not paper:
        raise ValueError("OCR does not pass completeness checks")
    paper["source"] = original["source"]
    paper["ocr_pages"] = doc["pages"]
    paper["repaired_from"] = original_id
    backup = root / "data/backups" / datetime.now().strftime("cet4-repair-%Y%m%d-%H%M%S")
    backup.mkdir(parents=True, exist_ok=False)
    (backup / collection_path.name).write_bytes(collection_path.read_bytes())
    _write_json(target, paper)
    entry = dict(collection["papers"][0])
    entry.update(id=new_id, title=paper["title"], description=paper["description"], question_count=57,
                 paper_url=f"/exam/{new_id}", json_url=f"/api/paper/{new_id}")
    collection["papers"] = [entry]
    _write_json(collection_path, collection)
    print(f"Corrected paper: http://127.0.0.1:8020/exam/{new_id}")
    print("Original paper and all submissions retained. Collection index backed up.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("collection_id")
    repair(parser.parse_args().collection_id)
