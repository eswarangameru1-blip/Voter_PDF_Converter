import re
import os
import uuid
import logging
from typing import Dict, Any, Optional, List, Tuple
import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# Strong EPIC Regex pattern list
EPIC_PATTERNS = [
    r'\b([A-Z]{3}\d{7})\b',                     # Standard ECI (e.g. IQV0021931, CYZ1618594)
    r'\b([A-Z]{2}\d{12})\b',                    # Newer 14-char ECI (e.g. AP010050096422)
    r'\b([A-Z]{2,4}/\d{2,4}/\d{3,4}/\d{3,7})\b', # Older slash-delimited
    r'\b([A-Z]{3}/\d{7})\b',                     # Standard 3 letter + slash + 7 digit
    r'\b([A-Z]{2,4}\d{6,8})\b'                  # General fallback
]

# Lazy-loaded PaddleOCR engine instance
_ocr_instance = None

def get_ocr_instance():
    """
    Lazy loads and returns the PaddleOCR instance using the paddle_dynamic engine to avoid PIR compiler bugs.
    """
    global _ocr_instance
    if _ocr_instance is None:
        try:
            from paddleocr import PaddleOCR
            # Initialize with English engine and paddle_dynamic eager execution engine
            _ocr_instance = PaddleOCR(use_angle_cls=True, lang='en', engine='paddle_dynamic')
            logger.info("PaddleOCR engine (paddle_dynamic) initialized successfully.")
        except ImportError:
            logger.warning("PaddleOCR module not installed. Running in lightweight serverless mode.")
            return None
        except Exception as e:
            logger.error(f"Failed to initialize PaddleOCR engine: {e}")
            return None
    return _ocr_instance

def run_ocr_on_page(page, page_num: int, temp_dir: str) -> List[Dict[str, Any]]:
    """
    Renders a PyMuPDF page as a high-resolution image and performs OCR using PaddleOCR.
    Returns a list of extracted word/text dictionaries with normalized fitz coordinates.
    """
    os.makedirs(temp_dir, exist_ok=True)
    
    # 1. Render page to high-res image (dpi=150 is optimal for PaddleOCR accuracy)
    pix = page.get_pixmap(dpi=150)
    img_name = f"ocr_page_{page_num}_{uuid.uuid4().hex[:8]}.png"
    img_path = os.path.join(temp_dir, img_name)
    pix.save(img_path)
    
    words_result: List[Dict[str, Any]] = []
    try:
        # 2. Retrieve the OCR engine
        ocr = get_ocr_instance()
        if ocr is None:
            logger.warning(f"Page {page_num}: OCR requested but PaddleOCR engine is unavailable.")
            return words_result
        
        # 3. Perform text detection
        ocr_result = ocr.ocr(img_path, use_doc_orientation_classify=False, use_doc_unwarping=False)
        
        if ocr_result and ocr_result[0]:
            res_dict = ocr_result[0]
            texts = res_dict.get("rec_texts", [])
            scores = res_dict.get("rec_scores", [])
            boxes = res_dict.get("rec_boxes", [])
            
            fitz_w = page.rect.width
            fitz_h = page.rect.height
            img_w = pix.width
            img_h = pix.height
            
            # Scale factors to map image pixels to fitz points
            scale_x = fitz_w / img_w
            scale_y = fitz_h / img_h
            
            for idx in range(len(texts)):
                txt = texts[idx]
                confidence = scores[idx]
                box = boxes[idx]  # Coordinates in [x0, y0, x1, y1] format
                
                x0 = float(box[0]) * scale_x
                y0 = float(box[1]) * scale_y
                x1 = float(box[2]) * scale_x
                y1 = float(box[3]) * scale_y
                
                # Split line blocks into individual words to match the parser's adaptive word layout.
                words = txt.split()
                if not words:
                    continue
                    
                total_chars = sum(len(w) for w in words)
                if total_chars == 0:
                    continue
                    
                current_x0 = x0
                full_w = x1 - x0
                
                for word in words:
                    # Estimate width based on character length ratio
                    word_ratio = len(word) / total_chars
                    word_w = full_w * word_ratio
                    word_x1 = current_x0 + word_w
                    
                    words_result.append({
                        "x0": current_x0,
                        "top": y0,
                        "x1": word_x1,
                        "bottom": y1,
                        "text": word,
                        "confidence": float(confidence)
                    })
                    current_x0 = word_x1
                    
        logger.info(f"Page {page_num}: PaddleOCR extracted {len(words_result)} words.")
        
    except Exception as e:
        logger.error(f"Page {page_num} PaddleOCR failure: {e}")
        raise e
    finally:
        # Cleanup temporary image file
        if os.path.exists(img_path):
            try:
                os.remove(img_path)
            except Exception as re_err:
                logger.error(f"Failed to delete temp OCR image {img_path}: {re_err}")
                
    return words_result

def clean_value(val: str) -> str:
    """
    Trims whitespaces and strips ECI-specific layout symbols.
    """
    if not val:
        return ""
    val = val.strip()
    # If the value is purely dashes/hyphens (e.g. '--', '-', '—', '- -'), preserve '--'
    if re.match(r'^[:\s]*[-—–\s]{1,6}$', val) and re.search(r'[-—–]', val):
        return "--"
        
    # Strip garbage symbols like colons, vertical bars, hyphens, slashes at start/end
    val = re.sub(r'^[:\-\|/\\,\s\u200b]+|[:\-\|/\\,\s\u200b]+$', '', val)
    val = re.sub(r'\s+', ' ', val)
    return val.strip()

def find_keyword_pos(text: str, keywords: List[str], start_pos: int = 0) -> Tuple[int, int]:
    """
    Finds the earliest match among the given keywords in text[start_pos:],
    ensuring word boundaries so keywords like 'age' or 'name' won't match inside
    names (e.g. 'NAGESH', 'RAJESH', 'BHAGYA').
    Returns (match_start_idx, match_end_idx).
    If not found, returns (-1, -1).
    """
    sub_text = text[start_pos:]
    best_start = -1
    best_end = -1
    
    for kw in keywords:
        pattern = r'(?<![a-zA-Z0-9])' + re.escape(kw) + r'(?![a-zA-Z0-9])'
        match = re.search(pattern, sub_text, re.IGNORECASE)
        if match:
            m_start = start_pos + match.start()
            m_end = start_pos + match.end()
            if best_start == -1 or m_start < best_start:
                best_start = m_start
                best_end = m_end
                
    return best_start, best_end

def extract_field_between_labels(text: str, start_keywords: List[str], end_keywords: List[str]) -> str:
    """
    Extracts the substring located between start_keywords and end_keywords.
    Uses word-boundary regex matching to avoid substring collisions.
    Splits multi-line fields and joins wrapped text cleanly.
    """
    _, start_idx = find_keyword_pos(text, start_keywords, 0)
    if start_idx == -1:
        return ""
        
    end_idx, _ = find_keyword_pos(text, end_keywords, start_idx)
    if end_idx == -1:
        val = text[start_idx:]
    else:
        val = text[start_idx:end_idx]
        
    # Replace line breaks in fields (like names) with spaces
    val = val.replace("\n", " ")
    return clean_value(val)

def extract_voter_id(text: str) -> str:
    """
    Applies strong regexes to find the voter's EPIC card number.
    """
    for pattern in EPIC_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return match.group(1).replace(" ", "").upper()
    return ""

def extract_serial_number(text: str) -> Optional[int]:
    """
    Extracts the serial number (S.No).
    """
    patterns = [
        r'(?:S\.?No\.?|Sl\.?\s*No\.?|Serial\s+No\.?|Sl\s+No|क्रम\s+संख्या|क्र\.\s*సం\.?|క్ర\.\s*సంఖ్య)\s*[:.-]?\s*(\d+)',
        r'^\s*(\d+)\s+'
    ]
    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
            
    # Check first line token
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    if lines:
        tokens = lines[0].split()
        for tok in tokens:
            clean_tok = re.sub(r'\D', '', tok)
            if clean_tok.isdigit() and 1 <= len(clean_tok) <= 4:
                return int(clean_tok)
    return None

def detect_guardian_type(text: str) -> str:
    """
    Detects guardian type based on ECI relationship keywords.
    """
    father_keywords = ["father's name", "fathers name", "father name", "తండ్రి పేరు", "తండ్రి"]
    husband_keywords = ["husband's name", "husbands name", "husband name", "భర్త పేరు", "భర్త"]
    mother_keywords = ["mother's name", "mothers name", "mother name", "తల్లి పేరు", "తల్లి"]
    other_keywords = [
        "other's name", "others name", "other name", "guardian's name", "guardians name",
        "guardian name", "సంరక్షకుడి పేరు", "సంరక్షకుడు", "ఇతరుల పేరు", "ఇతరులు"
    ]
    
    categories = [
        ("Father", father_keywords),
        ("Husband", husband_keywords),
        ("Mother", mother_keywords),
        ("Other", other_keywords)
    ]
    
    best_pos = -1
    best_cat = "Father"
    
    for cat_name, kw_list in categories:
        pos, _ = find_keyword_pos(text, kw_list, 0)
        if pos != -1:
            if best_pos == -1 or pos < best_pos:
                best_pos = pos
                best_cat = cat_name
                
    return best_cat

def extract_age_and_sex(text: str) -> Tuple[Optional[int], str]:
    """
    Extracts Age as integer and Sex (normalized to Male/Female/Third Gender).
    """
    text_lower = text.lower()
    
    # 1. Sex Normalized Identification (handles English & Telugu)
    sex = ""
    # Look for sex label first if available
    sex_match = re.search(r'(?:sex|gender|లింగము|లింగం)\s*[:\-\s]+([^\n\r]+)', text, re.IGNORECASE)
    search_context = sex_match.group(1).lower() if sex_match else text_lower

    if "female" in search_context or "స్త్రీ" in search_context or "మహిళ" in search_context:
        sex = "Female"
    elif "male" in search_context or "పురుషుడు" in search_context or "పురుష" in search_context:
        sex = "Male"
    elif any(kw in search_context for kw in ["trans", "third", "other", "ఇతరులు", "తృతీయ"]):
        sex = "Third Gender"
    else:
        # Match standalone character tokens
        match = re.search(r'\b(M|F|T)\b', text)
        if match:
            mapping = {"M": "Male", "F": "Female", "T": "Third Gender"}
            sex = mapping[match.group(1)]
            
    # 2. Age parsing
    age = None
    match = re.search(r'(?:age|వయస్సు|వయసు)\s*[:\-\s]+(\d+)', text, re.IGNORECASE)
    if match:
        age = int(match.group(1))
    else:
        # Search for any standalone 2 or 3 digit number near gender words
        match = re.search(r'\b(\d{2,3})\b', text)
        if match:
            age = int(match.group(1))
            
    return age, sex

def parse_voter_card_record(card_text: str, confidence: float) -> Optional[Dict[str, Any]]:
    """
    Parses card text blocks, applying segmenters to merge multi-line fields.
    Flags records with low confidence (< 90% in OCR) and returns the structured dictionary.
    """
    voter_id = extract_voter_id(card_text)
    if not voter_id:
        return None
        
    s_no = extract_serial_number(card_text)
    
    # Define keywords lists for label segmenter
    name_starts = ["elector's name", "electors name", "elector name", "name", "పేరు"]
    name_ends = [
        "father's name", "fathers name", "father name",
        "husband's name", "husbands name", "husband name",
        "mother's name", "mothers name", "mother name",
        "other's name", "others name", "other name",
        "guardian's name", "guardians name", "guardian name",
        "తండ్రి పేరు", "భర్త పేరు", "తల్లి పేరు", "సంరక్షకుడి పేరు", "ఇతరుల పేరు", "ఇంటి నంబరు", "house number"
    ]
    
    guardian_starts = [
        "father's name", "fathers name", "father name",
        "husband's name", "husbands name", "husband name",
        "mother's name", "mothers name", "mother name",
        "other's name", "others name", "other name",
        "guardian's name", "guardians name", "guardian name",
        "తండ్రి పేరు", "భర్త పేరు", "తల్లి పేరు", "సంరక్షకుడి పేరు", "ఇతరుల పేరు"
    ]
    guardian_ends = ["house number", "house no", "h.no", "h no", "ఇంటి నంబరు", "ఇంటి నం", "ఇంటి నెంబరు", "వయస్సు", "age", "sex"]
    
    house_starts = ["house number", "house no", "h.no", "h no", "ఇంటి నంబరు", "ఇంటి నం", "ఇంటి నెంబరు"]
    house_ends = ["age", "sex", "gender", "వయస్సు", "లింగము"]
    
    # Extract fields
    name = extract_field_between_labels(card_text, name_starts, name_ends)
    guardian = extract_field_between_labels(card_text, guardian_starts, guardian_ends)
    house_no = extract_field_between_labels(card_text, house_starts, house_ends)
    
    # Guardian type (Father/Husband/Mother/Other)
    g_type = detect_guardian_type(card_text)
    
    # Age and Sex
    age, sex = extract_age_and_sex(card_text)
    
    # Validation flag (OCR review requirement)
    review_required = False
    if confidence < 0.90:
        review_required = True
        logger.warning(
            f"Voter ID {voter_id} (S.No {s_no}) flagged for manual review. "
            f"OCR Confidence is {confidence:.2%}"
        )
        
    return {
        "S.No": s_no,
        "VoterID Number": voter_id,
        "Elector's Name": name,
        "Guardian Name": guardian,
        "Guardian Type": g_type,
        "House Number": house_no,
        "Sex": sex,
        "Age": age,
        "confidence": confidence,
        "review_required": review_required
    }
