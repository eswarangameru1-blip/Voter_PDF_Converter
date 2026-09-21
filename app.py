import os
import uuid
import time
import json
import logging
import shutil
import base64
from datetime import datetime
from typing import Dict, Any, List
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException, Request, Form
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Setup unified logging before importing local modules
from logger_config import setup_logging
setup_logging()

logger = logging.getLogger(__name__)

# Import local modules
from parser import parse_voter_pages, extract_total_electors_summary
from extractor import parse_voter_card_record
from excel_export import export_to_excel

app = FastAPI(title="Voter PDF Converter", version="1.0")

import tempfile

# Setup directories automatically (using system temp dir on serverless read-only environments)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IS_VERCEL = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
TEMP_BASE = tempfile.gettempdir() if IS_VERCEL else BASE_DIR

UPLOAD_DIR = os.path.join(TEMP_BASE, "uploads")
OUTPUT_DIR = os.path.join(TEMP_BASE, "output")
LOG_DIR = os.path.join(TEMP_BASE, "logs")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

for dir_path in [UPLOAD_DIR, OUTPUT_DIR, LOG_DIR]:
    try:
        os.makedirs(dir_path, exist_ok=True)
    except Exception as dir_err:
        logger.warning(f"Could not create directory {dir_path}: {dir_err}")

# Templates & Static Files setup
templates = Jinja2Templates(directory=TEMPLATES_DIR)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# In-memory database for background task status tracking and byte caching
tasks_db: Dict[str, Dict[str, Any]] = {}
EXCEL_BYTES_CACHE: Dict[str, bytes] = {}
HISTORY_FILE = os.path.join(OUTPUT_DIR, "history.json")

def load_history() -> List[Dict[str, Any]]:
    """Loads recent conversion logs from history.json."""
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read history file: {e}")
        return []

def add_history_entry(task_id: str, filename: str, voter_count: int, duplicates_removed: int, invalid_records: int, status: str):
    """Appends a new conversion entry to history.json."""
    history = load_history()
    history.insert(0, {
        "task_id": task_id,
        "filename": filename,
        "date": datetime.now().isoformat(),
        "voter_count": voter_count,
        "duplicates_removed": duplicates_removed,
        "invalid_records": invalid_records,
        "status": status
    })
    # Keep only the last 50 entries
    history = history[:50]
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to write history file: {e}")

def process_pdf_task(task_id: str, file_path: str, pdf_filename: str):
    """
    Background worker pipeline executing:
    1. Parsing of total electors from cover/summary page.
    2. Extraction of voter cards page by page (adapting between PyMuPDF & PaddleOCR fallback).
    3. Parsing, validating, and structuring voter fields.
    4. Removing duplicates based on EPIC code.
    5. Formatting and exporting to a styled Excel table worksheet.
    6. Appending statistics to history.json.
    """
    try:
        logger.info(f"Task {task_id}: Starting voter roll conversion pipeline for PDF: {pdf_filename}")
        tasks_db[task_id]["status"] = "processing"
        tasks_db[task_id]["stage"] = "Extracting elector summary count..."
        tasks_db[task_id]["progress"] = 3
        
        # 1. Parse declared elector count from first/last pages of PDF
        declared_count = extract_total_electors_summary(file_path, UPLOAD_DIR)
        tasks_db[task_id]["declared_count"] = declared_count
        
        # 2. Extract card text blocks page-by-page
        def progress_cb(current: int, total: int, status_text: str):
            percent = 5 + int((current / total) * 75)
            tasks_db[task_id]["progress"] = percent
            tasks_db[task_id]["current_page"] = current
            tasks_db[task_id]["total_pages"] = total
            tasks_db[task_id]["stage"] = f"{status_text}"
            
        card_blocks_with_conf = parse_voter_pages(file_path, UPLOAD_DIR, progress_callback=progress_cb)
        
        # 3. Extract and validate voter records
        tasks_db[task_id]["stage"] = "Structuring voter records..."
        tasks_db[task_id]["progress"] = 82
        
        extracted_voters: List[Dict[str, Any]] = []
        review_count = 0
        sum_confidence = 0.0
        
        for idx, (block_text, conf) in enumerate(card_blocks_with_conf):
            try:
                voter = parse_voter_card_record(block_text, conf)
                if voter:
                    extracted_voters.append(voter)
                    sum_confidence += voter["confidence"]
                    if voter["review_required"]:
                        review_count += 1
            except Exception as parse_err:
                logger.error(f"Task {task_id}: Parser error on raw block {idx}: {parse_err}")
                
        total_extracted = len(extracted_voters)
        avg_confidence = sum_confidence / total_extracted if total_extracted > 0 else 1.0
        
        # 4. EPIC-based Deduplication
        tasks_db[task_id]["stage"] = "Validating and removing duplicate EPICs..."
        tasks_db[task_id]["progress"] = 90
        
        unique_voters: List[Dict[str, Any]] = []
        seen_epics = set()
        duplicates_removed = 0
        
        for voter in extracted_voters:
            epic = voter["VoterID Number"]
            if epic in seen_epics:
                duplicates_removed += 1
                logger.info(f"Task {task_id}: Removing duplicate record for EPIC {epic}")
            else:
                seen_epics.add(epic)
                unique_voters.append(voter)
                
        final_count = len(unique_voters)
        tasks_db[task_id]["voter_count"] = final_count
        tasks_db[task_id]["duplicates_removed"] = duplicates_removed
        
        # 5. Mismatch verification (Extracted vs. Declared count)
        mismatch_warning = None
        if declared_count is not None:
            if final_count != declared_count:
                mismatch_warning = (
                    f"Warning: Elector count mismatch! PDF summary lists "
                    f"{declared_count} electors, but we extracted {final_count} unique records."
                )
                logger.warning(f"Task {task_id}: {mismatch_warning}")
            else:
                logger.info(f"Task {task_id}: Validation SUCCESS: Extracted count matches summary page count ({final_count}).")
                
        tasks_db[task_id]["warning"] = mismatch_warning
        
        # 6. Generate styled Excel sheet
        tasks_db[task_id]["stage"] = "Exporting structured Excel workbook..."
        tasks_db[task_id]["progress"] = 95
        
        export_res = export_to_excel(unique_voters, pdf_filename)
        actual_output_path = os.path.abspath(export_res["file"])
        
        # Read excel file into memory & base64 string
        excel_b64 = None
        try:
            with open(actual_output_path, "rb") as ef:
                file_bytes = ef.read()
            EXCEL_BYTES_CACHE[task_id] = file_bytes
            excel_b64 = base64.b64encode(file_bytes).decode("utf-8")
            tasks_db[task_id]["excel_bytes"] = file_bytes
            tasks_db[task_id]["excel_b64"] = excel_b64
        except Exception as cache_err:
            logger.error(f"Task {task_id}: Failed to cache file in memory: {cache_err}")
        
        # Capture invalid record stats
        invalid_records = export_res.get("invalid_records", 0)
        tasks_db[task_id]["invalid_records"] = invalid_records
        
        # 7. Finalize Task Status
        tasks_db[task_id]["status"] = "completed"
        tasks_db[task_id]["progress"] = 100
        tasks_db[task_id]["excel_file"] = actual_output_path
        tasks_db[task_id]["stage"] = "Conversion Completed"
        
        # Add entry to history JSON
        add_history_entry(
            task_id=task_id,
            filename=pdf_filename,
            voter_count=final_count,
            duplicates_removed=duplicates_removed,
            invalid_records=invalid_records,
            status="completed"
        )
        
        # Log Summary
        logger.info(
            f"Task {task_id} Extraction Summary:\n"
            f"  PDF Name: {pdf_filename}\n"
            f"  Declared Electors Count: {declared_count}\n"
            f"  Total Cards Parsed: {total_extracted}\n"
            f"  Unique Records Extracted: {final_count}\n"
            f"  Duplicates Removed: {duplicates_removed}\n"
            f"  Average OCR Confidence: {avg_confidence:.2%}\n"
            f"  Records Flagged for Review: {review_count}\n"
            f"  Mismatch Warning: {mismatch_warning}"
        )
        
    except Exception as e:
        logger.exception(f"Task {task_id}: Failed with exception: {e}")
        tasks_db[task_id]["status"] = "failed"
        tasks_db[task_id]["stage"] = "Failed"
        tasks_db[task_id]["progress"] = 100
        tasks_db[task_id]["error"] = f"Extraction Pipeline Error: {str(e)}"
        
        add_history_entry(
            task_id=task_id,
            filename=pdf_filename,
            voter_count=0,
            duplicates_removed=0,
            invalid_records=0,
            status="failed"
        )
        
    finally:
        # Cleanup raw uploaded file to release resources
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"Task {task_id}: Temporary PDF cleared.")
            except Exception as cleanup_err:
                logger.error(f"Task {task_id}: Failed to delete temporary PDF: {cleanup_err}")

# --- API ENDPOINTS ---

@app.get("/")
async def serve_index(request: Request):
    """Serves the main web interface page."""
    return templates.TemplateResponse(request, "index.html")

@app.post("/api/upload")
async def upload_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    ocr_enabled: bool = Form(True),
    ocr_engine: str = Form("paddle_dynamic"),
    auto_detect: bool = Form(True),
    export_format: str = Form("xlsx")
):
    """
    Saves PDF file securely, performs validations, and queues extraction task.
    Max File Size: 100MB
    """
    # 1. Validate File Extension
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Uploaded file must be a PDF document.")
        
    # 2. Validate MIME Type
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Invalid file type. Only PDF documents are allowed.")

    # 3. Read first few bytes to check magic headers (Security: Reject executables, MZ, ELF)
    try:
        header = await file.read(4)
        await file.seek(0)  # Reset file cursor for saving
        
        if header.startswith(b"MZ") or header.startswith(b"\x7fELF"):
            raise HTTPException(status_code=400, detail="Security violation: Executable files are strictly prohibited.")
            
        if header != b"%PDF":
            raise HTTPException(status_code=400, detail="Invalid file header. File does not appear to be a valid PDF.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File safety inspection failed: {e}")
        raise HTTPException(status_code=400, detail="Failed to analyze uploaded file safety header.")

    # 4. Generate random filename using UUID to prevent overwriting
    task_id = str(uuid.uuid4())
    temp_pdf_name = f"{task_id}.pdf"
    temp_pdf_path = os.path.join(UPLOAD_DIR, temp_pdf_name)

    # 5. Save file with max size check (100MB)
    max_size = 100 * 1024 * 1024
    total_bytes = 0
    try:
        with open(temp_pdf_path, "wb") as buffer:
            while chunk := await file.read(8192):
                total_bytes += len(chunk)
                if total_bytes > max_size:
                    # Clean up partial file
                    buffer.close()
                    os.remove(temp_pdf_path)
                    raise HTTPException(status_code=413, detail="File too large. Maximum size allowed is 100MB.")
                buffer.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cache uploaded file on disk: {e}")
        raise HTTPException(status_code=500, detail="Internal server error writing uploaded file.")

    # 6. Initialize task state in db
    tasks_db[task_id] = {
        "status": "queued",
        "stage": "Queued for processing...",
        "progress": 0,
        "current_page": 0,
        "total_pages": 0,
        "voter_count": 0,
        "duplicates_removed": 0,
        "invalid_records": 0,
        "declared_count": None,
        "excel_file": None,
        "warning": None,
        "error": None,
        "start_time": time.time(),
        "filename": file.filename
    }

    # 7. Add pipeline convert to background executor (or synchronous execution on Vercel)
    if IS_VERCEL:
        process_pdf_task(task_id, temp_pdf_path, file.filename)
        task = tasks_db.get(task_id, {})
        return {
            "task_id": task_id,
            "status": task.get("status"),
            "stage": task.get("stage"),
            "progress": task.get("progress"),
            "current_page": task.get("current_page"),
            "total_pages": task.get("total_pages"),
            "records_found": task.get("voter_count", 0),
            "voter_count": task.get("voter_count", 0),
            "duplicates_removed": task.get("duplicates_removed", 0),
            "invalid_records": task.get("invalid_records", 0),
            "warning": task.get("warning"),
            "error": task.get("error"),
            "excel_b64": task.get("excel_b64"),
            "filename": file.filename
        }
    else:
        background_tasks.add_task(
            process_pdf_task,
            task_id,
            temp_pdf_path,
            file.filename
        )
        return {"task_id": task_id}

@app.get("/api/status/{task_id}")
async def get_status(task_id: str):
    """
    Returns live task status, progress and metrics.
    """
    task = tasks_db.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Requested conversion task not found.")

    # Calculate active elapsed time
    elapsed = time.time() - task["start_time"]
    elapsed_time_str = f"{elapsed:.1f}s"

    return JSONResponse(content={
        "status": task["status"],
        "progress": task["progress"],
        "current_page": task["current_page"],
        "total_pages": task["total_pages"],
        "records_found": task["voter_count"],
        "duplicates_removed": task["duplicates_removed"],
        "invalid_records": task["invalid_records"],
        "elapsed_time": elapsed_time_str,
        "stage": task["stage"],
        "warning": task["warning"],
        "error": task["error"],
        "excel_b64": task.get("excel_b64"),
        "filename": task.get("filename")
    })

@app.get("/api/download/{task_id}")
async def download_excel(task_id: str):
    """
    Serves the output Excel spreadsheet file from memory, base64, or disk fallback.
    """
    task = tasks_db.get(task_id)
    original_filename = "voter_details.xlsx"
    if task and task.get("filename"):
        clean_name = os.path.splitext(task['filename'])[0]
        original_filename = f"{clean_name}_voter_details.xlsx"

    # 1. Check in-memory EXCEL_BYTES_CACHE
    if task_id in EXCEL_BYTES_CACHE:
        return Response(
            content=EXCEL_BYTES_CACHE[task_id],
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{original_filename}"'}
        )

    # 2. Check task Base64 data
    if task and task.get("excel_b64"):
        b_data = base64.b64decode(task["excel_b64"])
        return Response(
            content=b_data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{original_filename}"'}
        )

    # 3. Fallback: check physical file on disk
    excel_path = None
    if task and task.get("excel_file"):
        excel_path = task["excel_file"]

    if not excel_path or not os.path.exists(excel_path):
        history = load_history()
        match = next((item for item in history if item["task_id"] == task_id), None)
        if match and match.get("status") == "completed":
            base_name = os.path.splitext(os.path.basename(match["filename"]))[0]
            original_filename = f"{base_name}_voter_details.xlsx"
            candidate_path = os.path.join(OUTPUT_DIR, f"{base_name}_voter_details.xlsx")
            if os.path.exists(candidate_path):
                excel_path = candidate_path
            elif os.path.exists(OUTPUT_DIR):
                files = os.listdir(OUTPUT_DIR)
                matched_files = [f for f in files if f.startswith(f"{base_name}_voter_details")]
                if matched_files:
                    excel_path = os.path.join(OUTPUT_DIR, matched_files[0])

    if excel_path and os.path.exists(excel_path):
        return FileResponse(
            path=excel_path,
            filename=original_filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    raise HTTPException(status_code=404, detail="Excel spreadsheet file not found on disk.")

@app.get("/api/history")
async def get_history():
    """
    Returns conversion logs from history.json.
    """
    return JSONResponse(content=load_history())

@app.get("/api/health")
async def get_health():
    """
    Health check endpoint.
    """
    return {
        "status": "healthy",
        "version": "1.0",
        "timestamp": datetime.now().isoformat()
    }

# Mock downloadable PDF endpoint as required by index page tests
@app.get("/test_voters.pdf")
async def serve_test_pdf():
    pdf_path = os.path.join(BASE_DIR, "test_voters.pdf")
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="Test PDF not found.")
    return FileResponse(pdf_path, media_type="application/pdf")
