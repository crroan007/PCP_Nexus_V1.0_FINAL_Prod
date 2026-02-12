import json
import os
import re
from pypdf import PdfReader

# Path to the keywords config
from core import app_paths
KEYWORDS_PATH = str(app_paths.ensure_dir(app_paths.logs_dir().parent / "data") / "reporting_keywords.json")

class IntelligenceEngine:
    def __init__(self, keywords_path=None):
        self.keywords_path = keywords_path or KEYWORDS_PATH
        self.rules = self._load_rules()

    def _load_rules(self):
        try:
            with open(self.keywords_path, 'r') as f:
                return json.load(f)
        except:
            return {"financial_indicators": ["$", "USD"], "potential_action_verbs": ["serve", "hold"], "instructional_phrases": []}

    def extract_comments(self, pdf_path):
        """Attempts to extract the 'Comments' section from a PDF."""
        text = ""
        try:
            reader = PdfReader(pdf_path)
            for page in reader.pages:
                text += page.extract_text() + "\n"
            
            # Look for "Comments:" or similar
            # Pattern: Comments: (.*)
            # This is a heuristic. In legal docs, comments are often in a specific box.
            # For now, we'll scan the whole text but try to isolate the tail.
            
            match = re.search(r"Comments?[:\s]+(.*)", text, re.IGNORECASE | re.DOTALL)
            if match:
                return match.group(1).split("\n\n")[0].strip() # Take until next block
            
            return text[:500] # Fallback to first 500 chars if no header found
        except Exception as e:
            return f"Error extracting: {str(e)}"

    def analyze_text(self, text):
        """Analyzes text against the rules and returns (action_triggered, matched_terms)."""
        if not text:
            return False, []

        found_terms = []
        triggered = False
        
        # Combine all rules into a flat list for scanning
        all_keywords = self.rules.get("financial_indicators", []) + \
                       self.rules.get("potential_action_verbs", []) + \
                       self.rules.get("instructional_phrases", [])
        
        text_lower = text.lower()
        
        for kw in all_keywords:
            if kw.lower() in text_lower:
                triggered = True
                found_terms.append(kw)
        
        return triggered, found_terms
