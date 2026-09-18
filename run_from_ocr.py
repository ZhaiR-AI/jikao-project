from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from agentclaw.model.manager import LLMManager

from paper_generator import (
    PROJECT_DIR,
    build_exam_papers,
    persist_paper_collection,
    read_ocr,
    split_exam_ranges,
)


async def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python run_from_ocr.py <ocr_id>")

    ocr_id = sys.argv[1]
    result_path = PROJECT_DIR / "data" / "last_from_ocr_run.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        ocr_doc = read_ocr(ocr_id)
        original_name = ocr_doc.get("source", {}).get("file_name") or "document.pdf"
        llm = LLMManager(config_path=str(PROJECT_DIR / "models.json"))
        exams = await split_exam_ranges(llm=llm, original_name=original_name, ocr_doc=ocr_doc)
        papers = await build_exam_papers(
            llm=llm,
            original_name=original_name,
            ocr_doc=ocr_doc,
            exams=exams,
        )
        generation = persist_paper_collection(
            original_name=original_name,
            ocr_doc=ocr_doc,
            papers=papers,
        )
        collection = generation["collection"]
        summary = {
            "status": "completed",
            "collection_id": generation["id"],
            "collection_url": f"http://127.0.0.1:8010/exam/{generation['id']}",
            "ocr_url": f"http://127.0.0.1:8010/api/paper/ocr/{generation['id']}",
            "paper_count": len(collection.get("papers", [])),
            "papers": [
                {
                    "id": paper["id"],
                    "title": paper.get("title", ""),
                    "questions": paper.get("question_count", 0),
                    "score": paper.get("total_score", 0),
                    "pages": f"{paper.get('start_page')}-{paper.get('end_page')}",
                    "url": f"http://127.0.0.1:8010{paper.get('paper_url')}",
                }
                for paper in collection.get("papers", [])
            ],
        }
    except Exception as exc:
        summary = {"status": "failed", "error": str(exc)}

    result_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
