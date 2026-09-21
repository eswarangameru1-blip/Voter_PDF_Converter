import fitz  # PyMuPDF
import re
import os
import logging
from typing import Callable, Optional, List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# Strong EPIC Regex pattern list
EPIC_PATTERNS = [
    r'\b([A-Z]{3}\d{7})\b',                     # Standard ECI (e.g. IQV0021931, CYZ1618594)
    r'\b([A-Z]{2}\d{12})\b',                    # Newer 14-char ECI (e.g. AP010050096422)
    r'\b([A-Z]{2,4}/\d{2,4}/\d{3,4}/\d{3,7})\b', # Older slash-delimited
    r'\b([A-Z]{3}/\d{7})\b',                     # Standard 3 letter + slash + 7 digit
    r'\b([A-Z]{2,4}\d{6,8})\b'                  # General fallback
]

def contains_epic(text: str) -> bool:
    """
    Checks if the given text contains any EPIC number pattern.
    """
    for pattern in EPIC_PATTERNS:
        if re.search(pattern, text):
            return True
    return False

def count_epics(text: str) -> int:
    """
    Counts how many EPIC patterns are found in the text.
    """
    count = 0
    for pattern in EPIC_PATTERNS:
        count += len(re.findall(pattern, text))
    return count

def sort_words_into_lines(words: List[Dict[str, Any]], line_threshold: float = 3.0) -> str:
    """
    Sorts word blocks into reading order (top-to-bottom, left-to-right).
    """
    if not words:
        return ""
    
    # Sort primarily by top, secondarily by x0
    sorted_words = sorted(words, key=lambda w: (w['top'], w['x0']))
    
    lines = []
    current_line = []
    last_top = None
    
    for w in sorted_words:
        w_top = w['top']
        if last_top is None:
            current_line.append(w)
            last_top = w_top
        elif abs(w_top - last_top) < line_threshold:
            current_line.append(w)
        else:
            current_line = sorted(current_line, key=lambda w: w['x0'])
            lines.append(" ".join([x['text'] for x in current_line]))
            current_line = [w]
            last_top = w_top
            
    if current_line:
        current_line = sorted(current_line, key=lambda w: w['x0'])
        lines.append(" ".join([x['text'] for x in current_line]))
        
    return "\n".join(lines)

def extract_total_electors_summary(pdf_path: str, temp_dir: str) -> Optional[int]:
    """
    Scans cover pages and the last page of the PDF to extract the total voter count
    present in the official summary.
    """
    total_val = None
    try:
        doc = fitz.open(pdf_path)
        pages_to_check = [0, 1, len(doc) - 1]
        
        # Keywords for ECI summary total electors (English and Telugu)
        patterns = [
            r'(?:total\s+electors|total|మొత్తం\s+ఓటర్లు|మొత్తం)\s*[:\-\/\=\s]+(\d+)',
            r'మొత్తం\s*[:\s]+(\d+)'
        ]
        
        for p_idx in pages_to_check:
            if p_idx < 0 or p_idx >= len(doc):
                continue
            page = doc[p_idx]
            text = page.get_text("text")
            
            # Fallback if page is scanned
            if len(text.strip()) < 100:
                try:
                    from extractor import run_ocr_on_page
                    blocks = run_ocr_on_page(page, page_num=p_idx+1, temp_dir=temp_dir)
                    text = "\n".join([b["text"] for b in blocks])
                except Exception as ocr_err:
                    logger.error(f"OCR scan failed on summary page {p_idx+1}: {ocr_err}")
            
            for pat in patterns:
                matches = re.findall(pat, text, re.IGNORECASE)
                for m in matches:
                    val = int(m)
                    # Standard E-Roll part counts are between 100 and 3000, relax for tests/small parts
                    if 5 < val < 10000:
                        if total_val is None or val > total_val:
                            total_val = val
        if total_val:
            logger.info(f"Summary Page: Parsed declared total electors count = {total_val}")
    except Exception as e:
        logger.error(f"Error parsing declared electors summary count: {e}")
        
    return total_val

def parse_voter_pages(
    pdf_path: str,
    temp_dir: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> List[Tuple[str, float]]:
    """
    Reads the PDF and extracts raw card blocks (text, confidence) from all voter roll pages.
    Automatically detects scanned pages and delegates to PaddleOCR.
    Skips non-voter layouts (cover sheet, section details, summaries).
    """
    card_blocks: List[Tuple[str, float]] = []
    
    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        logger.info(f"PDF {pdf_path} opened. Total pages: {total_pages}")
        
        # Pre-scan pages to calibrate a global layout template from a fully populated page
        calibrated_grid = None
        best_words_count = 0
        best_words_list = []
        best_page_w = 595.0
        best_page_h = 842.0
        
        for p_idx in range(total_pages):
            p = doc[p_idx]
            plain_text = p.get_text("text")
            epic_count = count_epics(plain_text)
            is_cov = (p_idx <= 1 or p_idx == total_pages - 1) and (epic_count < 3)
            # Skip cover pages and empty text pages to avoid false calibration
            if is_cov and len(plain_text.strip()) >= 40:
                continue
            
            w_list = p.get_text("words")
            if len(w_list) > best_words_count:
                best_words_count = len(w_list)
                best_words_list = w_list
                best_page_w = p.rect.width
                best_page_h = p.rect.height
                
        if best_words_count >= 150:
            h_min_y = best_page_h * 0.06
            h_max_y = best_page_h * 0.94
            body_w = [w for w in best_words_list if h_min_y <= w[1] <= h_max_y]
            if body_w:
                p_min_x = min(w[0] for w in body_w)
                p_max_x = max(w[2] for w in body_w)
                p_min_y = min(w[1] for w in body_w)
                p_max_y = max(w[3] for w in body_w)
                
                expected_full_height = best_page_h * 0.88
                if (p_max_y - p_min_y) > 0.65 * expected_full_height:
                    col_width = (p_max_x - p_min_x) / 3
                    row_height = (p_max_y - p_min_y) / 10
                    calibrated_grid = (p_min_x, p_max_x, p_min_y, p_max_y, col_width, row_height)
                    logger.info(f"Global grid calibrated from page: x={p_min_x:.1f}..{p_max_x:.1f}, y={p_min_y:.1f}..{p_max_y:.1f}, col_w={col_width:.1f}, row_h={row_height:.1f}")

        for page_idx in range(total_pages):
            page_num = page_idx + 1
            if progress_callback:
                progress_callback(page_num, total_pages, f"Reading page {page_num} of {total_pages}...")
            
            page = doc[page_idx]
            
            # Extract plain text to analyze selectable characters and check if page contains voter lists
            plain_text = page.get_text("text")
            
            # Check if this page is a voter list page (must contain at least some EPIC numbers)
            epic_count = count_epics(plain_text)
            
            # Page layout filtering: Cover sheets and summary sections typically have very few/no EPIC numbers.
            # However, if it's a scanned PDF, plain_text will be empty, meaning epic_count is 0.
            # We must distinguish between a scanned voter list page and a cover page.
            # A scanned voter page will have NO text, but it is a middle page.
            # Cover sheets are usually pages 1, 2 and the last page.
            is_cover_or_summary = (page_num <= 2 or page_num == total_pages) and (epic_count < 3)
            
            # Check if page is scanned (very little or no selectable text)
            # Standard voter page has 30 voter boxes containing name, relative name, age, etc., approx > 500 chars
            is_scanned = len(plain_text.strip()) < 40
            
            if is_cover_or_summary and not is_scanned:
                # Selectable text, but recognized as cover/summary -> Skip
                logger.info(f"Page {page_num}: Skipped cover/summary page (selectable).")
                continue
            
            grid_words: List[Dict[str, Any]] = []
            ocr_run = False
            
            if is_scanned:
                # Scanned Page -> Run PaddleOCR
                logger.info(f"Page {page_num}: Text quality poor or scanned. Running PaddleOCR...")
                if progress_callback:
                    progress_callback(page_num, total_pages, f"Running OCR on page {page_num}...")
                
                try:
                    from extractor import run_ocr_on_page
                    grid_words = run_ocr_on_page(page, page_num, temp_dir)
                    ocr_run = True
                except Exception as ocr_err:
                    logger.error(f"Page {page_num}: OCR failed: {ocr_err}")
                    # If OCR fails, try to fall back to whatever fitz extracted (empty/partial)
                    grid_words = []
            else:
                # Selectable Page -> Extract words with layout info
                fitz_words = page.get_text("words")
                for w in fitz_words:
                    grid_words.append({
                        "x0": w[0],
                        "top": w[1],
                        "x1": w[2],
                        "bottom": w[3],
                        "text": w[4],
                        "confidence": 1.0 # 100% confidence for selectable text
                    })
            
            # Filter words to only include grid layout area
            # A4 dimensions are typically 595 x 842. We ignore header (top 8%) and footer (bottom 7%)
            page_h = page.rect.height
            page_w = page.rect.width
            
            h_min_y = page_h * 0.06
            h_max_y = page_h * 0.94
            
            body_words = [w for w in grid_words if h_min_y <= w['top'] <= h_max_y]
            
            # Double-check if the OCR output actually contains voter data
            # If OCR extracted text has zero EPIC matches and it is a cover sheet, skip
            if ocr_run:
                ocr_full_text = " ".join([w["text"] for w in body_words])
                ocr_epic_count = count_epics(ocr_full_text)
                if (page_num <= 2 or page_num == total_pages) and ocr_epic_count < 3:
                    logger.info(f"Page {page_num}: Skipped cover/summary page (OCR scan verified).")
                    continue
                if len(body_words) < 20:
                    logger.warning(f"Page {page_num}: No words extracted via OCR. Skipping page.")
                    continue
            
            if not body_words:
                logger.warning(f"Page {page_num}: No body words found. Skipping page.")
                continue
                
            # On-the-fly calibration from first parsed scanned/OCR page if needed
            if ocr_run and calibrated_grid is None:
                body_w = [w for w in grid_words if h_min_y <= w['top'] <= h_max_y]
                if len(body_w) >= 150:
                    p_min_x = min(w['x0'] for w in body_w)
                    p_max_x = max(w['x1'] for w in body_w)
                    p_min_y = min(w['top'] for w in body_w)
                    p_max_y = max(w['bottom'] for w in body_w)
                    expected_full_height = page_h * 0.88
                    if (p_max_y - p_min_y) > 0.65 * expected_full_height:
                        col_width = (p_max_x - p_min_x) / 3
                        row_height = (p_max_y - p_min_y) / 10
                        calibrated_grid = (p_min_x, p_max_x, p_min_y, p_max_y, col_width, row_height)
                        logger.info(f"Global grid calibrated from OCR page {page_num}: x={p_min_x:.1f}..{p_max_x:.1f}, y={p_min_y:.1f}..{p_max_y:.1f}, col_w={col_width:.1f}, row_h={row_height:.1f}")

            # Calculate grid boundaries for this page (prioritize calibrated template)
            if calibrated_grid is not None:
                min_x, max_x, min_y, max_y, col_width, row_height = calibrated_grid
            else:
                p_min_x = min(w['x0'] for w in body_words)
                p_max_x = max(w['x1'] for w in body_words)
                p_min_y = min(w['top'] for w in body_words)
                p_max_y = max(w['bottom'] for w in body_words)
                
                # Check horizontal span (must span at least 60% of page width to be multi-column)
                if (p_max_x - p_min_x) < 0.6 * page_w:
                    min_x = 0.045 * page_w
                    max_x = 0.955 * page_w
                else:
                    min_x = p_min_x
                    max_x = p_max_x
                    
                col_width = (max_x - min_x) / 3
                min_y = p_min_y
                
                # Estimate vertical row height using a geometric ratio to prevent grid compression/shifting
                # The average ratio of card row height to total page height in ECI voter lists is ~0.0865
                span_y = p_max_y - p_min_y
                estimated_row_h = 0.0865 * page_h
                num_rows = max(1, min(10, round(span_y / estimated_row_h)))
                row_height = span_y / num_rows
                max_y = min_y + 10 * row_height
            
            page_cards = 0
            
            # Partition words into standard 3 columns x 10 rows grid cells
            for r in range(10):
                y_start = min_y + r * row_height
                y_end = min_y + (r + 1) * row_height
                
                for c in range(3):
                    x_start = min_x + c * col_width
                    x_end = min_x + (c + 1) * col_width
                    
                    cell_words = []
                    for w in body_words:
                        cx = (w['x0'] + w['x1']) / 2
                        cy = (w['top'] + w['bottom']) / 2
                        
                        # Check centroid with 0.5px padding to prevent row-bleeding
                        if (x_start - 0.5 <= cx <= x_end + 0.5) and (y_start - 0.5 <= cy <= y_end + 0.5):
                            cell_words.append(w)
                            
                    if cell_words:
                        cell_text = sort_words_into_lines(cell_words)
                        # Compute average confidence for this cell
                        confidences = [w.get("confidence", 1.0) for w in cell_words]
                        avg_conf = sum(confidences) / len(confidences) if confidences else 1.0
                        
                        # Only add if it contains actual data
                        if cell_text.strip():
                            card_blocks.append((cell_text, avg_conf))
                            page_cards += 1
                            
            logger.info(f"Page {page_num}: Extracted {page_cards} voter cards. Mode: {'OCR' if ocr_run else 'Searchable'}")
            
    except Exception as e:
        logger.error(f"Failed to parse PDF pages: {e}")
        raise e
        
    return card_blocks
