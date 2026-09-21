# Voter PDF Converter

Production-ready Election Commission of India (ECI) voter list extractor and Excel conversion suite. Features automatic dual-mode processing (selectable text vs. PaddleOCR fallback), multi-line name/address reconstruction, EPIC validation, and professional spreadsheet styling.

---

## Folder Structure

```
voter-pdf-converter/
│
├── app.py                  # FastAPI Application Entrypoint & REST APIs
├── parser.py               # PDF Reader, Selector Check & Grid Layout Engine
├── extractor.py            # PaddleOCR Integration & Field Label Segmenter
├── excel_export.py         # Workbook Styling & Formatting Helpers
├── logger_config.py        # Global Logging Configuration (conversion.log)
├── test_excel_export.py    # Excel Export Module Unit Tests
├── verify_app.py           # End-to-End Integration Verification Script
├── requirements.txt        # Python Dependencies
│
├── templates/
│   └── index.html          # Glassmorphic Web UI
├── static/
│   ├── style.css           # Premium Glassmorphic Styles
│   └── script.js           # Drag-and-drop & API Polling Logic
│
├── uploads/                # Cached/Uploaded PDF Cache (cleared automatically)
├── output/                 # Generated Spreadsheet Outputs
└── logs/
    └── conversion.log      # Application Logging File
```

---

## Installation & Setup

1. **Prerequisites**: Ensure you have Python 3.13 installed.
2. **Setup Virtual Environment**:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```
3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

---

## Run Instructions

Launch the FastAPI local server using:
```bash
uvicorn app:app --reload
```
Once started, navigate to `http://127.0.0.1:8000` in your web browser.

---

## API Documentation

### 1. `GET /`
- **Description**: Serves the user interface.
- **Response**: HTML file response.

### 2. `POST /api/upload`
- **Description**: Upload a voter roll PDF to start parsing.
- **Parameters**: `file` (UploadFile, PDF, Max 100MB).
- **Security**: Validates PDF signature, rejects executable magic headers, and generates randomized UUID filenames.
- **Response**:
  ```json
  {
    "task_id": "8f87e5b6-6819-4822-b5e1-512c019be55d"
  }
  ```

### 3. `GET /api/status/{task_id}`
- **Description**: Retrieves live execution progress and analytics.
- **Response**:
  ```json
  {
    "status": "completed",
    "progress": 100,
    "current_page": 3,
    "total_pages": 3,
    "records_found": 60,
    "duplicates_removed": 0,
    "invalid_records": 0,
    "elapsed_time": "12.4s",
    "stage": "Conversion Completed",
    "warning": null,
    "error": null
  }
  ```

### 4. `GET /api/download/{task_id}`
- **Description**: Downloads the completed Excel workbook.
- **Response**: Excel File stream.

### 5. `GET /api/history`
- **Description**: Lists recent conversions from `history.json`.
- **Response**: JSON array of logs.

### 6. `GET /api/health`
- **Description**: Verifies service status.
- **Response**: `{"status": "healthy", "version": "1.0", "timestamp": "..."}`

---

## Troubleshooting & FAQs

- **Slow Scanned PDF Extraction**:
  - Processing scanned pages via CPU OCR executes deep learning models (text detection and recognition) on the CPU.
  - To optimize speed, the application automatically disables document unwarping (`use_doc_unwarping=False`) and document orientation check (`use_doc_orientation_classify=False`).
- **ConvertPirAttribute2RuntimeAttribute Error**:
  - This is a known PaddlePaddle bug on Windows CPU when compiling execution pipelines. The application uses `engine='paddle_dynamic'` to execute models dynamically, avoiding this compiler crash.
- **MKL/OpenMP Deadlocks**:
  - Unsetting thread-pools and utilizing dynamically allocated eager execution threads resolves deadlocks on local environments.
