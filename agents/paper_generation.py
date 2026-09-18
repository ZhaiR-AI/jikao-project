from __future__ import annotations

from pathlib import Path

from agentclaw import Input, Workflow

from paper_generator import (
    DEFAULT_OCR_CONCURRENCY,
    MAX_OCR_CONCURRENCY,
    PaperGenerationError,
    assemble_exam_papers,
    create_exam_build_jobs,
    extract_exam_questions_for_jobs,
    get_vision_model_name,
    ocr_page_images,
    persist_paper_collection,
    persist_exam_papers,
    persist_ocr_document,
    render_pdf_for_ocr,
    split_exam_ranges,
)


workflow = Workflow(
    id="paper_generation",
    name="动态卷子生成工作流",
    description="PDF 渲染/OCR/套卷切分/题目 JSON 生成的显式节点工作流。",
    timeout=3600,
    inputs=[
        Input("pdf_path", str, required=True, description="服务端可访问的 PDF 路径"),
        Input("original_name", str, required=True, description="原始文件名"),
        Input("max_pages", int, required=False, default=None, description="最多处理页数"),
        Input("dpi", int, required=False, default=160, description="PDF 渲染 DPI"),
        Input(
            "ocr_concurrency",
            int,
            required=False,
            default=DEFAULT_OCR_CONCURRENCY,
            description="OCR 最大并发数",
        ),
    ],
)


@workflow.node(id="prepare_input", output_to_user=False, description="校验 PDF 输入")
def prepare_input(state):
    pdf_path = Path(state.get("pdf_path") or "")
    if not pdf_path.exists():
        raise PaperGenerationError(f"PDF 文件不存在: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise PaperGenerationError("只支持 PDF 文件")

    max_pages = state.get("max_pages")
    if max_pages in ("", 0, "0"):
        max_pages = None
    elif max_pages is not None:
        max_pages = int(max_pages)

    dpi = int(state.get("dpi") or 160)
    ocr_concurrency = int(state.get("ocr_concurrency") or DEFAULT_OCR_CONCURRENCY)
    return {
        "pdf_path": str(pdf_path),
        "original_name": state.get("original_name") or pdf_path.name,
        "max_pages": max_pages,
        "dpi": dpi,
        "ocr_concurrency": max(1, min(ocr_concurrency, MAX_OCR_CONCURRENCY)),
        "workflow_stage": "prepared",
    }


@workflow.node(id="render_pdf_pages", output_to_user=False, description="渲染 PDF 为页级图片")
def render_pdf_pages(state):
    render_result = render_pdf_for_ocr(
        Path(state["pdf_path"]),
        dpi=int(state.get("dpi") or 160),
        max_pages=state.get("max_pages"),
    )
    return {
        "collection_id": render_result["collection_id"],
        "stored_pdf": render_result["stored_pdf"],
        "page_images": render_result["page_images"],
        "page_count": render_result["page_count"],
        "workflow_stage": "pdf_rendered",
    }


@workflow.node(id="ocr_pages", output_to_user=False, description="用视觉模型并发 OCR 页级图片")
async def ocr_pages(state, context):
    llm = context.llm_manager
    if llm is None:
        raise PaperGenerationError("工作流 LLMManager 未初始化")

    ocr_pages = await ocr_page_images(
        llm=llm,
        page_images=state["page_images"],
        ocr_concurrency=int(state.get("ocr_concurrency") or DEFAULT_OCR_CONCURRENCY),
    )
    return {
        "ocr_pages": ocr_pages,
        "ocr_pages_count": len(ocr_pages),
        "workflow_stage": "ocr_done",
    }


@workflow.node(id="persist_ocr", output_to_user=False, description="保存页级 OCR 文稿")
def persist_ocr(state, context):
    llm = context.llm_manager
    if llm is None:
        raise PaperGenerationError("工作流 LLMManager 未初始化")

    ocr_doc = persist_ocr_document(
        collection_id=state["collection_id"],
        original_name=state["original_name"],
        page_count=int(state.get("page_count") or len(state.get("ocr_pages", []))),
        ocr_model=get_vision_model_name(llm),
        ocr_pages=state["ocr_pages"],
    )
    return {
        "ocr_doc": ocr_doc,
        "workflow_stage": "ocr_persisted",
    }


@workflow.node(id="split_exams", output_to_user=False, description="根据完整 OCR 文稿切分多套试卷")
async def split_exams(state, context):
    llm = context.llm_manager
    if llm is None:
        raise PaperGenerationError("工作流 LLMManager 未初始化")
    exams = await split_exam_ranges(
        llm=llm,
        original_name=state["original_name"],
        ocr_doc=state["ocr_doc"],
    )
    return {
        "exams": exams,
        "exam_count": len(exams),
        "workflow_stage": "split_done",
    }


@workflow.node(id="create_exam_jobs", output_to_user=False, description="为每套试卷创建页码范围任务")
def create_exam_jobs(state):
    exam_jobs = create_exam_build_jobs(
        original_name=state["original_name"],
        ocr_doc=state["ocr_doc"],
        exams=state["exams"],
    )
    return {
        "exam_jobs": exam_jobs,
        "workflow_stage": "exam_jobs_created",
    }


@workflow.node(id="extract_question_chunks", output_to_user=False, description="按重叠页窗提取题目片段")
async def extract_question_chunks(state, context):
    llm = context.llm_manager
    if llm is None:
        raise PaperGenerationError("工作流 LLMManager 未初始化")
    extracted_jobs = await extract_exam_questions_for_jobs(
        llm=llm,
        exam_jobs=state["exam_jobs"],
    )
    return {
        "extracted_jobs": extracted_jobs,
        "workflow_stage": "question_chunks_extracted",
    }


@workflow.node(id="assemble_papers", output_to_user=False, description="合并跨页/重叠题目并归一化为 100 分")
def assemble_papers(state):
    papers = assemble_exam_papers(
        ocr_doc=state["ocr_doc"],
        extracted_jobs=state["extracted_jobs"],
    )
    return {
        "assembled_papers": papers,
        "paper_count": len(papers),
        "workflow_stage": "papers_assembled",
    }


@workflow.node(id="persist_papers", output_to_user=False, description="保存每套试卷 JSON")
def persist_papers(state):
    papers = persist_exam_papers(state["assembled_papers"])
    return {
        "built_papers": papers,
        "workflow_stage": "papers_persisted",
    }


@workflow.node(id="persist_collection", output_to_user=False, description="保存集合索引并生成最终结果")
def persist_collection(state):
    result = persist_paper_collection(
        original_name=state["original_name"],
        ocr_doc=state["ocr_doc"],
        papers=state["built_papers"],
    )
    return {
        "generation_result": result,
        "collection": result["collection"],
        "papers": result["collection"]["papers"],
        "paper": result["paper"],
        "workflow_stage": "persisted",
    }


@workflow.node(id="format_response", output_to_user=True, description="生成 API 响应摘要")
def format_response(state):
    result = state["generation_result"]
    collection = result["collection"]
    first_paper = result["paper"]
    return {
        "paper_generation_summary": {
            "type": result["type"],
            "collection_id": result["id"],
            "paper_count": len(collection.get("papers", [])),
            "paper_id": first_paper["id"] if first_paper else result["id"],
            "paper_url": f"/exam/{first_paper['id']}" if first_paper else f"/exam/{result['id']}",
            "json_url": f"/api/paper/{first_paper['id']}" if first_paper else f"/api/paper/{result['id']}",
            "ocr_url": collection.get("ocr_url"),
        }
    }


workflow.add_edge("__start__", "prepare_input")
workflow.add_edge("prepare_input", "render_pdf_pages")
workflow.add_edge("render_pdf_pages", "ocr_pages")
workflow.add_edge("ocr_pages", "persist_ocr")
workflow.add_edge("persist_ocr", "split_exams")
workflow.add_edge("split_exams", "create_exam_jobs")
workflow.add_edge("create_exam_jobs", "extract_question_chunks")
workflow.add_edge("extract_question_chunks", "assemble_papers")
workflow.add_edge("assemble_papers", "persist_papers")
workflow.add_edge("persist_papers", "persist_collection")
workflow.add_edge("persist_collection", "format_response")
workflow.add_edge("format_response", "__end__")

workflow.publish()
