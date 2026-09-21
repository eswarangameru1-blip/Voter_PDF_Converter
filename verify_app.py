import os
import sys
import subprocess

from logger_config import setup_logging
setup_logging()
import logging
logger = logging.getLogger("verify_app")

# Lazy load reportlab
try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
except ImportError:
    print("Installing reportlab for testing...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "reportlab"])
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter

import fitz  # PyMuPDF
import openpyxl
from parser import parse_voter_pages, extract_total_electors_summary
from extractor import parse_voter_card_record
from excel_export import export_to_excel

def create_searchable_mock_pdf(filename: str) -> int:
    """
    Generates a searchable PDF voter list.
    Page 1: Cover page with electors summary.
    Page 2 & 3: Standard 3x10 grid of voter cards.
    """
    c = canvas.Canvas(filename, pagesize=letter)
    width, height = letter # 612 x 792
    
    # 1. Page 1: Cover page
    c.setFont("Helvetica-Bold", 16)
    c.drawString(100, height - 150, "ELECTION COMMISSION OF INDIA")
    c.setFont("Helvetica", 12)
    c.drawString(100, height - 180, "Assembly Constituency: 120 - Tirupati")
    c.drawString(100, height - 200, "Part No: 45")
    
    # Summary box
    c.rect(100, height - 350, 400, 100, fill=0, stroke=1)
    c.drawString(120, height - 280, "Voter Summary Details")
    c.setFont("Helvetica-Bold", 11)
    # We purposefully set the summary total to 58 electors while we will extract 60 unique cards.
    # This will trigger the mismatch validation check!
    c.drawString(120, height - 310, "Total Electors : 58") 
    c.drawString(120, height - 330, "Male : 30   Female : 28")
    c.showPage()
    
    # Grid config (3 columns x 10 rows)
    margin_left = 30
    margin_right = 30
    margin_top = 60
    margin_bottom = 50
    grid_width = width - margin_left - margin_right
    grid_height = height - margin_top - margin_bottom
    col_width = grid_width / 3
    row_height = grid_height / 10
    
    voter_idx = 1
    
    # 2. Pages 2 & 3: Voter cards (30 cards per page, total 60 cards)
    for page in range(2):
        # Draw header
        c.setFont("Helvetica-Bold", 9)
        c.drawString(30, height - 30, "Assembly Constituency No and Name : 120 - Tirupati")
        c.setFont("Helvetica", 8)
        c.drawString(30, height - 42, "Section: 1 - Temple Road, Tirupati")
        
        # Grid outline
        c.setStrokeColorRGB(0.7, 0.7, 0.7)
        c.rect(margin_left, margin_bottom, grid_width, grid_height, stroke=1, fill=0)
        
        for r in range(10):
            y = height - margin_top - (r + 1) * row_height
            for col in range(3):
                x = margin_left + col * col_width
                
                # Draw card box
                c.setStrokeColorRGB(0.8, 0.8, 0.8)
                c.rect(x + 2, y + 2, col_width - 4, row_height - 4, fill=0, stroke=1)
                
                # Alphanumeric EPIC formats
                # 30 standard, 30 new formats
                if voter_idx <= 20:
                    epic = f"IQV{voter_idx:07d}"
                elif voter_idx <= 40:
                    epic = f"CYZ{voter_idx:07d}"
                else:
                    epic = f"AP01005{voter_idx:07d}"
                
                # Serial & EPIC
                c.setFont("Helvetica-Bold", 8)
                c.drawString(x + 6, y + row_height - 9, f"{voter_idx}")
                c.drawRightString(x + col_width - 6, y + row_height - 9, epic)
                
                # Name (Multi-line layout simulation)
                c.setFont("Helvetica", 7.5)
                c.drawString(x + 6, y + row_height - 17, "Elector's Name :")
                c.drawString(x + 12, y + row_height - 25, f"Elector Name {voter_idx} PartA")
                c.drawString(x + 12, y + row_height - 33, "PartB") # Spans multiple lines
                
                # Guardian Name (Alternating type)
                g_lbl = "Father's Name :" if voter_idx % 2 == 0 else "Husband's Name :"
                c.drawString(x + 6, y + row_height - 42, g_lbl)
                c.drawString(x + 12, y + row_height - 49, f"Guardian Name {voter_idx}")
                
                # House number (Varying formats)
                h_no = f"1-{100+voter_idx}" if voter_idx % 3 == 0 else (f"2-{voter_idx} MAIN ROAD" if voter_idx % 3 == 1 else f"1-{100+voter_idx}A")
                c.drawString(x + 6, y + row_height - 57, f"House Number : {h_no}")
                
                # Age & Sex (English labels for Helvetica font encoding)
                gender = "Male" if voter_idx % 2 == 0 else "Female"
                age = 18 + (voter_idx % 55)
                c.drawString(x + 6, y + row_height - 64, f"Age : {age}   Sex : {gender}")
                
                voter_idx += 1
                
        # Footer
        c.setFont("Helvetica", 8)
        c.drawString(30, 25, "Age as on 01/01/2026 | E-Roll Version 2026")
        c.drawRightString(width - 30, 25, f"Page {page + 2} of 3")
        c.showPage()
        
    c.save()
    return 60

def create_scanned_mock_pdf(searchable_pdf: str, output_scanned_pdf: str):
    """
    Simulates a scanned E-Roll page by rendering a searchable page as an image
    and writing it back as a flat image block in a new PDF.
    This triggers the OCR engine since it contains zero selectable text characters.
    """
    print(f"Creating scanned mock PDF: {output_scanned_pdf}...")
    doc = fitz.open(searchable_pdf)
    
    # Grab page 2 (index 1) which is a voter card grid
    page = doc[1]
    pix = page.get_pixmap(dpi=150)
    
    # Save to a temporary image file
    temp_img = "temp_scanned_page.png"
    pix.save(temp_img)
    
    # Create new PDF containing only this image
    sc_doc = fitz.open()
    sc_page = sc_doc.new_page(width=page.rect.width, height=page.rect.height)
    
    # Place image on page
    sc_page.insert_image(sc_page.rect, filename=temp_img)
    sc_doc.save(output_scanned_pdf)
    
    sc_doc.close()
    doc.close()
    
    # Cleanup temp image
    if os.path.exists(temp_img):
        os.remove(temp_img)

def test_pipeline():
    logger.info("Executing integration test pipeline...")
    searchable_pdf = "test_voters_searchable.pdf"
    scanned_pdf = "test_voters_scanned.pdf"
    excel_output = "outputs/verify_upgrade_output.xlsx"
    
    # Ensure clean workspace directories
    os.makedirs("outputs", exist_ok=True)
    os.makedirs("uploads", exist_ok=True)
    
    try:
        # 1. Create mock searchable PDF
        create_searchable_mock_pdf(searchable_pdf)
        
        # 2. Extract declared electors summary count
        print("\n[TEST 1] Testing Declared Elector Summary extraction...")
        declared_count = extract_total_electors_summary(searchable_pdf, "uploads")
        logger.info(f"Summary extracted elector count: {declared_count}")
        assert declared_count == 58, f"Expected summary count 58, got {declared_count}"
        
        # 3. Parse searchable PDF
        print("\n[TEST 2] Parsing Searchable E-Roll PDF (PyMuPDF Grid Mode)...")
        card_blocks_with_conf = parse_voter_pages(searchable_pdf, "uploads", lambda c, t, s: print(f"  {s} ({int(c/t*100)}%)"))
        
        print(f"Extracted {len(card_blocks_with_conf)} text card blocks.")
        assert len(card_blocks_with_conf) == 60, f"Expected 60 card blocks, got {len(card_blocks_with_conf)}"
        
        # 4. Structure voter records
        print("\n[TEST 3] Extracting and validating structured voter details...")
        voters = []
        for idx, (block, conf) in enumerate(card_blocks_with_conf):
            voter = parse_voter_card_record(block, conf)
            if voter:
                voters.append(voter)
                
        assert len(voters) == 60, f"Expected 60 records, got {len(voters)}"
        
        # Verify first voter
        v1 = voters[0]
        print("\nSample Voter 1 Structure:")
        for k, v in v1.items():
            print(f"  {k}: {v}")
            
        assert v1["S.No"] == 1
        assert v1["VoterID Number"] == "IQV0000001"
        assert v1["Elector's Name"] == "Elector Name 1 PartA PartB"  # Checks multi-line name merge
        assert v1["Guardian Name"] == "Guardian Name 1"
        assert v1["Guardian Type"] == "Husband"  # Serial 1 % 2 != 0 -> Husband
        assert v1["House Number"] == "2-1 MAIN ROAD"  # Serial 1 % 3 == 1 -> MAIN ROAD
        assert v1["Sex"] == "Female"
        assert v1["Age"] == 19
        
        # 5. Create Scanned PDF and test OCR fallback
        create_scanned_mock_pdf(searchable_pdf, scanned_pdf)
        
        print("\n[TEST 4] Parsing Scanned E-Roll PDF (PaddleOCR Mode)...")
        ocr_blocks_with_conf = parse_voter_pages(scanned_pdf, "uploads", lambda c, t, s: print(f"  {s} ({int(c/t*100)}%)"))
        
        print(f"Extracted {len(ocr_blocks_with_conf)} OCR card blocks.")
        # Scanned page has full page of grid, meaning 30 cards.
        assert len(ocr_blocks_with_conf) == 30, f"Expected 30 cards from scanned page, got {len(ocr_blocks_with_conf)}"
        
        ocr_voters = []
        for block, conf in ocr_blocks_with_conf:
            voter = parse_voter_card_record(block, conf)
            if voter:
                ocr_voters.append(voter)
                
        print(f"Extracted {len(ocr_voters)} structured voter records via OCR.")
        assert len(ocr_voters) > 0, "No records extracted via OCR!"
        
        # Check OCR confidence flagging
        review_records = [v for v in ocr_voters if v["review_required"]]
        print(f"Total OCR records requiring manual review: {len(review_records)} of {len(ocr_voters)}")
        
        # 6. Test Deduplication
        # Add duplicate card
        duplicate_list = voters.copy()
        duplicate_list.append(voters[0].copy()) # Add copy of first voter
        
        seen = set()
        dedup_voters = []
        duplicates_removed = 0
        for v in duplicate_list:
            epic = v["VoterID Number"]
            if epic in seen:
                duplicates_removed += 1
            else:
                seen.add(epic)
                dedup_voters.append(v)
                
        assert len(dedup_voters) == 60, "Deduplication failed!"
        assert duplicates_removed == 1, "Duplicate count failed!"
        
        # 7. Test Mismatch Warnings
        if len(dedup_voters) != declared_count:
            logger.warning(
                f"[VALIDATION] Elector mismatch warning triggered! "
                f"Summary count: {declared_count}, Extracted count: {len(dedup_voters)}"
            )
            
        export_res = export_to_excel(dedup_voters, "test_voters.pdf")
        excel_output = os.path.abspath(export_res["file"])
        
        # 9. Verify Excel formatting
        wb = openpyxl.load_workbook(excel_output)
        ws = wb.active
        
        # Verify Table object exists
        tables = list(ws.tables.values())
        print(f"Number of Tables added to Worksheet: {len(tables)}")
        assert len(tables) == 1, "Workbook must contain exactly 1 Excel Table object"
        assert tables[0].displayName == "VoterRecordsTable"
        
        # Verify workbook properties
        assert wb.properties.creator == "Voter PDF Converter OCR Engine"
        
        # Verify freeze panes and filters
        assert ws.freeze_panes == 'A2', "Freeze panes must be set to A2"
        assert ws.auto_filter.ref is not None, "Auto filters must be configured"
        
        # Cleanup files
        for f in [searchable_pdf, scanned_pdf]:
            if os.path.exists(f):
                os.remove(f)
                
        logger.info("\n" + "="*60)
        logger.info("VERIFICATION E2E SUCCESSFUL! ALL TESTS PASSED.")
        logger.info("="*60)
        
    except Exception as ex:
        logger.exception(f"Integration pipeline failure: {ex}")
        sys.exit(1)

if __name__ == "__main__":
    test_pipeline()
