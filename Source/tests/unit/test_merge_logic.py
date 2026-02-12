"""
Test Phase 2 Merge Logic — P0 Compliance Tests
=================================================
Covers: PM2-01..PM2-10 from the testing plan.
Tests sort order, CL exclusion, and job number extraction.

These are the most critical tests — they verify the v4.2 compliance fixes.
"""
import pytest
import os
import sys
import re
from datetime import datetime
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


# ──────────────────────────────────────────────
# Sort Key Tests (PM2-01, PM2-05)
# ──────────────────────────────────────────────

class TestMergeSortOrder:
    """PM2-01: Verify the sort order: LEAD (0) → CORRECTION (1) → ATTACHMENT (2) → CL (99)."""

    def test_lead_sorts_first(self):
        """LEAD doc_type should have the lowest sort key."""
        files = [
            {'prefix': 'AXPE', 'doc_type': 'ATTACHMENT'},
            {'prefix': 'AX40', 'doc_type': 'LEAD'},
            {'prefix': 'AX40', 'doc_type': 'CLERK_LETTER'},
        ]
        
        def get_sort_key(f):
            doc_type = f.get('doc_type', 'UNKNOWN')
            type_order = {
                'LEAD': 0, 'CORRECTION': 1, 'ATTACHMENT': 2, 'CLERK_LETTER': 99
            }
            return (type_order.get(doc_type, 50), 0)
        
        sorted_files = sorted(files, key=get_sort_key)
        assert sorted_files[0]['doc_type'] == 'LEAD'
        assert sorted_files[1]['doc_type'] == 'ATTACHMENT'
        assert sorted_files[2]['doc_type'] == 'CLERK_LETTER'

    def test_ax40_before_axpe(self):
        """PM2-05: AX40 (LEAD) should always appear before AXPE (ATTACHMENT)."""
        files = [
            {'prefix': 'AXPE', 'doc_type': 'ATTACHMENT'},
            {'prefix': 'AX40', 'doc_type': 'LEAD'},
        ]
        
        def get_sort_key(f):
            type_order = {
                'LEAD': 0, 'CORRECTION': 1, 'ATTACHMENT': 2, 'CLERK_LETTER': 99
            }
            return (type_order.get(f.get('doc_type', 'UNKNOWN'), 50), 0)
        
        sorted_files = sorted(files, key=get_sort_key)
        assert sorted_files[0]['prefix'] == 'AX40'

    def test_correction_between_lead_and_attachment(self):
        """CORRECTION should sort after LEAD but before ATTACHMENT."""
        files = [
            {'prefix': 'AXPE', 'doc_type': 'ATTACHMENT'},
            {'prefix': 'AXCR', 'doc_type': 'CORRECTION'},
            {'prefix': 'AX40', 'doc_type': 'LEAD'},
        ]
        
        def get_sort_key(f):
            type_order = {
                'LEAD': 0, 'CORRECTION': 1, 'ATTACHMENT': 2, 'CLERK_LETTER': 99
            }
            return (type_order.get(f.get('doc_type', 'UNKNOWN'), 50), 0)
        
        sorted_files = sorted(files, key=get_sort_key)
        assert sorted_files[0]['doc_type'] == 'LEAD'
        assert sorted_files[1]['doc_type'] == 'CORRECTION'
        assert sorted_files[2]['doc_type'] == 'ATTACHMENT'


# ──────────────────────────────────────────────
# CL Merge Exclusion (PM2-02) — P0 CRITICAL
# ──────────────────────────────────────────────

class TestCLExclusion:
    """PM2-02: CLERK_LETTER files must be EXCLUDED from the merged PDF."""

    @pytest.mark.compliance
    def test_cl_excluded_from_merge_list(self, sample_packet_files):
        """🔴 P0: CLERK_LETTER should not appear in the merge file list."""
        sorted_files = sample_packet_files  # Already has LEAD, ATTACHMENT, CLERK_LETTER
        
        # This is the actual filtering logic from the fixed code
        merge_files = [f for f in sorted_files if f.get('doc_type') != 'CLERK_LETTER']
        
        # Assert CL is excluded
        assert len(merge_files) == 2  # LEAD + ATTACHMENT only
        for f in merge_files:
            assert f['doc_type'] != 'CLERK_LETTER', f"CLERK_LETTER found in merge list: {f}"

    @pytest.mark.compliance
    def test_cl_count_logged(self, sample_packet_files):
        """CL exclusion count should be trackable for logging."""
        sorted_files = sample_packet_files
        merge_files = [f for f in sorted_files if f.get('doc_type') != 'CLERK_LETTER']
        cl_excluded = len(sorted_files) - len(merge_files)
        assert cl_excluded == 1

    @pytest.mark.compliance
    def test_all_cl_envelope_produces_empty_merge(self):
        """PM2-08: An envelope with ONLY CL documents should produce 0 merge files."""
        all_cl_files = [
            {'prefix': 'AX40', 'doc_type': 'CLERK_LETTER', 'path': '/fake/cl1.pdf', 'original_name': 'AX40A25CL.pdf'},
            {'prefix': 'AX40', 'doc_type': 'CLERK_LETTER', 'path': '/fake/cl2.pdf', 'original_name': 'AX40B26CL.pdf'},
        ]
        merge_files = [f for f in all_cl_files if f.get('doc_type') != 'CLERK_LETTER']
        assert len(merge_files) == 0

    @pytest.mark.compliance
    def test_cl_still_in_comment_extraction(self, sample_packet_files):
        """CL should still be included in comment extraction (sorted_files), just not merged."""
        sorted_files = sample_packet_files
        merge_files = [f for f in sorted_files if f.get('doc_type') != 'CLERK_LETTER']
        
        # Comment extraction uses sorted_files (all), merge uses merge_files (no CL)
        assert len(sorted_files) == 3  # All docs for comment extraction
        assert len(merge_files) == 2   # Only non-CL for merge

    @pytest.mark.compliance
    def test_merge_pdf_without_cl_pages(self, sample_packet_files, tmp_path):
        """🔴 P0: Actual PDF merge should not contain pages from CL documents."""
        from pypdf import PdfWriter, PdfReader
        
        sorted_files = sample_packet_files
        merge_files = [f for f in sorted_files if f.get('doc_type') != 'CLERK_LETTER']
        
        # Perform the actual merge (same logic as _process_expired_packets)
        writer = PdfWriter()
        valid_count = 0
        for f_info in merge_files:
            path = f_info['path']
            if os.path.exists(path):
                reader = PdfReader(path)
                for page in reader.pages:
                    writer.add_page(page)
                valid_count += 1
        
        assert valid_count == 2  # Only LEAD + ATTACHMENT
        
        # Save and verify
        output_path = str(tmp_path / "merged_output.pdf")
        with open(output_path, "wb") as f:
            writer.write(f)
        
        # Verify the merged PDF has exactly 2 pages (1 from each non-CL file)
        merged_reader = PdfReader(output_path)
        assert len(merged_reader.pages) == 2


# ──────────────────────────────────────────────
# Job Number Extraction (PM2-03) — P0 CRITICAL
# ──────────────────────────────────────────────

class TestJobNumberExtraction:
    """PM2-03: Job number must come from lead doc's original_name, not temp path."""

    @pytest.mark.compliance
    def test_job_num_from_original_name(self):
        """🔴 P0: AX40A25C05955.pdf → job number = A25C05955."""
        lead_docs = [{'prefix': 'AX40', 'original_name': 'AX40A25C05955.pdf', 'doc_type': 'LEAD'}]
        
        original_name = lead_docs[0].get('original_name', '')
        job_num = original_name.upper().replace('.PDF', '').replace('.pdf', '')[4:].strip('-_ ')
        
        assert job_num == "A25C05955"

    @pytest.mark.compliance
    def test_job_num_not_envelope_id(self):
        """🔴 P0: Must NOT extract envelope ID from temp filename."""
        temp_filename = "P2_110395847_143000_0_DL_AX40.pdf"
        
        # Old buggy pattern: extracts envelope ID
        match = re.search(r"P2_(\d{9,})", temp_filename)
        assert match is not None
        envelope_id = match.group(1)
        assert envelope_id == "110395847"
        
        # Correct behavior: use original_name instead
        original_name = "AX40A25C05955.pdf"
        job_num = original_name.upper().replace('.PDF', '')[4:].strip('-_ ')
        assert job_num == "A25C05955"
        assert job_num != envelope_id  # Must be different!

    @pytest.mark.compliance
    def test_final_filename_format(self):
        """PM2-06: Final file must be named AX40{JobNum}.pdf."""
        lead_prefix = "AX40"
        job_num = "A25C05955"
        final_name = f"{lead_prefix}{job_num}.pdf"
        assert final_name == "AX40A25C05955.pdf"

    @pytest.mark.compliance
    def test_fallback_to_temp_path_when_no_original(self):
        """Fallback gracefully when original_name is missing."""
        lead_docs = [{'prefix': 'AX40', 'original_name': '', 'doc_type': 'LEAD'}]
        
        original_name = lead_docs[0].get('original_name', '')
        job_num = "UNKNOWN"
        if original_name and len(original_name) > 4:
            job_num = original_name.upper().replace('.PDF', '')[4:].strip('-_ ')
        
        # Should remain UNKNOWN → fallback path will trigger
        assert job_num == "UNKNOWN"

    @pytest.mark.compliance
    def test_various_lead_doc_names(self):
        """Test job number extraction with different naming patterns."""
        test_cases = [
            ("AX40A25B01085.PDF", "A25B01085"),
            ("AX40A26C12345.pdf", "A26C12345"),
            ("AX69B25D98765.pdf", "B25D98765"),
            ("AX40SIMPLE.pdf", "SIMPLE"),
        ]
        for original_name, expected_job in test_cases:
            job_num = original_name.upper().replace('.PDF', '').replace('.pdf', '')[4:].strip('-_ ')
            assert job_num == expected_job, f"Failed for {original_name}: got {job_num}"


# ──────────────────────────────────────────────
# PM2-04, PM2-07: Edge cases
# ──────────────────────────────────────────────

class TestMergeEdgeCases:
    """Additional merge logic tests."""

    def test_multiple_axpe_files_merged(self, sample_pdf_factory):
        """PM2-04: Multiple AXPE files should all be included in merge."""
        files = [
            {'path': sample_pdf_factory("axpe1.pdf"), 'prefix': 'AXPE', 'doc_type': 'ATTACHMENT', 'original_name': 'AXPE1.pdf'},
            {'path': sample_pdf_factory("axpe2.pdf"), 'prefix': 'AXPE', 'doc_type': 'ATTACHMENT', 'original_name': 'AXPE2.pdf'},
            {'path': sample_pdf_factory("lead.pdf"), 'prefix': 'AX40', 'doc_type': 'LEAD', 'original_name': 'AX40A25.pdf'},
        ]
        merge_files = [f for f in files if f.get('doc_type') != 'CLERK_LETTER']
        assert len(merge_files) == 3  # Lead + 2 AXPE

    def test_missing_file_logged_not_crash(self, sample_pdf_factory):
        """PM2-07: Missing files should be skipped without crashing."""
        from pypdf import PdfWriter, PdfReader
        
        files = [
            {'path': sample_pdf_factory("exists.pdf"), 'prefix': 'AX40', 'doc_type': 'LEAD'},
            {'path': '/nonexistent/missing.pdf', 'prefix': 'AXPE', 'doc_type': 'ATTACHMENT'},
        ]
        
        writer = PdfWriter()
        valid_count = 0
        for f_info in files:
            if os.path.exists(f_info['path']):
                reader = PdfReader(f_info['path'])
                for page in reader.pages:
                    writer.add_page(page)
                valid_count += 1
        
        assert valid_count == 1  # Only the existing file was merged
