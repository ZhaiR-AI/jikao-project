from __future__ import annotations

import asyncio
import json
from pathlib import Path

from agents.paper_generation import workflow


async def main() -> None:
    root = Path(__file__).resolve().parent.parent
    pdf = root / "21-25年真题汇编.pdf"
    result_path = Path(__file__).resolve().parent / "data" / "last_full_run.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        run_result = await workflow.run(
            {
                "pdf_path": str(pdf),
                "original_name": pdf.name,
                "max_pages": None,
                "dpi": 160,
                "ocr_concurrency": 3,
            }
        )
        generation = run_result["state"]["generation_result"]
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
        summary = {
            "status": "failed",
            "error": str(exc),
        }

    result_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
