import os
import re
import fitz  # PyMuPDF
from core.secure_config import conf
from core.agent_base import BaseAgent

class OCRSplitter(BaseAgent):
    """
    Phase 2 Component: OCR Splitter Service
    Responsibility: Detect anchors in large PDFs and split them.
    Queue: Consumes 'READY_TO_SPLIT' jobs.
    """
    def __init__(self):
        super().__init__("OCRSplitter")
        self.shadow_mode = conf.get_kvi("phase2.shadow_mode_enabled", True)
        self.anchors = conf.get_kvi("phase2.split_config.anchors", ["CAUSE NO"])
        self.min_pages = conf.get_kvi("phase2.split_config.min_pages", 20)
        
    def detect_anchors(self, page_text):
        """Returns True if any anchor keyword is found in text."""
        for anchor in self.anchors:
            if anchor.upper() in page_text.upper():
                return True
        return False

    def validate_page_zero(self, page_text):
        """
        Risk Mitigation: Data Cross-Contamination.
        Every 'First Page' of a split MUST have a Case Caption.
        """
        return self.detect_anchors(page_text)

    def run_cycle(self):
        from core.job_manager import job_manager
        
        self.log("Checking Queue for 'READY_TO_SPLIT'...", "INFO")
        
        # 1. Reserve Job
        job = job_manager.reserve_job('READY_TO_SPLIT')
        if not job:
            self.log("No jobs ready to split.", "DATA") # Low noise log
            return

        # Fix: reserve_job returns a DICT (sqlite3.Row)
        job_id = job['id']
        file_path = job['file_path']
        source = job['original_source']
        status = job['status']
        
        self.log(f"Processing Job #{job_id}: {os.path.basename(file_path)}", "INFO")
        
        if not os.path.exists(file_path):
             self.log(f"File Not Found: {file_path}", "ERROR")
             job_manager.update_job_status(job_id, 'QA_FAILED')
             return

        # 2. Open PDF & Scan
        try:
            doc = fitz.open(file_path)
            split_points = [0] # First document always starts at 0
            
            # Scan pages (Optimized: Get text)
            for i in range(len(doc)):
                # Skip Page 0 (Already implicit start)
                if i == 0: continue
                
                page_text = doc[i].get_text()
                if self.detect_anchors(page_text):
                    self.log(f"Split Anchor Found at Page {i}", "INFO")
                    split_points.append(i)
            
            # 3. Execute Splits
            if len(split_points) > 0:
                self._execute_splits(doc, split_points, job_id, file_path, source)
                job_manager.update_job_status(job_id, 'SPLIT_COMPLETE')
            else:
                self.log(f"No anchors found. Marking as VERIFIED (Single Doc).", "INFO")
                # If it was marked READY_TO_SPLIT due to size but had no anchors, treat as one big doc
                job_manager.update_job_status(job_id, 'VERIFIED')

            doc.close()
            
        except Exception as e:
            self.log(f"Split Critical Error Job #{job_id}: {e}", "ERROR")
            job_manager.update_job_status(job_id, 'QA_FAILED')

    def _execute_splits(self, doc, split_points, parent_job_id, parent_path, source):
        from core.job_manager import job_manager
        
        total_pages = len(doc)
        split_points.append(total_pages) # End marker
        
        base_name = os.path.basename(parent_path).replace(".pdf", "")
        output_dir = os.path.dirname(parent_path)
        
        if self.shadow_mode:
            output_dir = conf.get_kvi("phase2.shadow_folder")
            if not os.path.exists(output_dir): os.makedirs(output_dir)
            self.log(f"Shadow Mode Active. Output to: {output_dir}", "INFO")

        child_count = 0
        
        for i in range(len(split_points) - 1):
            start = split_points[i]
            end = split_points[i+1]
            
            # Create Child PDF
            new_doc = fitz.open()
            new_doc.insert_pdf(doc, from_page=start, to_page=end-1)
            
            # Page Zero Check (Risk Mitigation)
            # Verify the FIRST page of this new sub-doc has an anchor
            first_page_text = new_doc[0].get_text()
            if not self.validate_page_zero(first_page_text):
                self.log(f"Part {i+1} Failed Page-Zero Check. Marking QA_FAILED.", "WARN")
                child_status = "QA_FAILED"
            else:
                child_status = "VERIFIED"
            
            # Save
            new_filename = f"{base_name}_Part{i+1}.pdf"
            new_path = os.path.join(output_dir, new_filename)
            new_doc.save(new_path)
            new_doc.close()
            
            # Register Child Job
            # Note: Source includes Parent Info
            child_source = f"{source} [Split-Child-{i+1}]"
            job_manager.create_job(
                filename=new_filename,
                file_path=new_path,
                source=child_source,
                initial_status=child_status
            )
            child_count += 1
            self.log(f"Created Child Job: {new_filename} [{child_status}]", "SUCCESS")

        self.log(f"Split Complete. Generated {child_count} sub-documents.", "INFO")
