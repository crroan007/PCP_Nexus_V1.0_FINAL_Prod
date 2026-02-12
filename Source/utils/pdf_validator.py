import re
try:
    from pypdf import PdfReader
except ImportError:
    # Fallback or error if not installed, but verified it exists
    import PyPDF2 as PdfReader

class PDFValidator:
    """
    Validates PDF content by checking for critical metadata in the text layer.
    """
    
    def __init__(self):
        pass

    def validate_content(self, pdf_path, metadata):
        """
        Checks if the PDF text contains the Case Number.
        Returns (bool_valid, reason_string).
        """
        case_num = metadata.get('case_num')
        if not case_num:
            return False, "Metadata missing Case Number"
            
        try:
            reader = PdfReader(pdf_path)
            full_text = ""
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    full_text += extracted + "\n"
            
            # Normalize text for comparison (remove excessive whitespace)
            # Case numbers might have dashes or spaces. 
            # Strategy: Normalize both to alphanumeric-only for flexible matching?
            # Or just search simple substring.
            
            # Simple check first
            if case_num in full_text:
                return True, "Case Number found in text"
            
            # Normalize check: Remove dashes/spaces
            def normalize(s):
                return re.sub(r'[\s\-]', '', s).lower()
                
            norm_case = normalize(case_num)
            norm_text = normalize(full_text)
            
            if norm_case in norm_text:
                return True, "Case Number found (normalized)"
                
            # PRIMARY CHECK FAILED - TRY ENVELOPE ID FALLBACK (For Scanned Docs)
            env_num = metadata.get('envelope_num')
            if env_num:
                norm_env = normalize(env_num)
                if norm_env in norm_text:
                    return True, f"Envelope ID {env_num} found (Scanned Doc Backup)"
            
            # Failure
            return False, f"Case {case_num} missing. Text snippet: {full_text[:50]}..."
            
        except Exception as e:
            return False, f"PDF Read Error: {e}"
