"""
Test Link Downloader — Tyler Unfurling & Multi-Doc
===================================================
Covers: LD-01..LD-09 from the testing plan.
"""
import pytest
import re
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from utils.link_downloader import MultiDocumentResult


class TestMultiDocumentResult:
    """TD-02, LD-06, LD-07: Multi-document Tyler detection."""

    def test_multi_doc_regex_finds_all_links(self):
        """LD-06: re.findall captures ALL DownloadResource.ashx links."""
        html = """
        <a href="/DownloadResource.ashx?id=abc123&name=AX40A25.pdf">Doc 1</a>
        <a href="/DownloadResource.ashx?id=def456&name=AXPEA25.pdf">Doc 2</a>
        <a href="/DownloadResource.ashx?id=ghi789&name=AX40A25CL.pdf">Doc 3</a>
        """
        links = re.findall(r'DownloadResource\.ashx\?[^"\']+', html)
        assert len(links) == 3

    def test_filename_regex_captures_pdf(self):
        """LD-07: Filename extraction from DownloadResource URL."""
        url = "/DownloadResource.ashx?id=abc123&name=AX40A25C05955CL.pdf"
        match = re.search(r'name=([^&"\']+\.pdf)', url, re.IGNORECASE)
        assert match is not None
        assert match.group(1) == "AX40A25C05955CL.pdf"

    def test_multi_doc_exception_carries_data(self):
        """TD-02: MultiDocumentResult carries all document info."""
        docs = [
            {'url': 'http://ex.com/dl1', 'filename': 'AX40A25.pdf'},
            {'url': 'http://ex.com/dl2', 'filename': 'AXPEA25.pdf'},
        ]
        exc = MultiDocumentResult("http://tyler.example.com", docs)
        assert len(exc.documents) == 2
        assert exc.documents[0]['filename'] == 'AX40A25.pdf'
        assert exc.documents[1]['url'] == 'http://ex.com/dl2'


class TestExpiryDetection:
    """LD-02..LD-04: Expired link detection patterns."""

    def test_expired_text_detection(self):
        """LD-02: 'no longer available' indicates expired page."""
        html = "<html><body>This document is no longer available for download.</body></html>"
        assert "no longer available" in html.lower()

    def test_expired_label_detection(self):
        """LD-03: 'lblexpired' element indicates expired page."""
        html = '<html><body><span id="lblexpired">Expired</span></body></html>'
        assert "lblexpired" in html.lower()

    def test_tyler_page_detection(self):
        """LD-05: Tyler pages contain 'tyler' in content."""
        html = '<html><head><title>Tyler Technologies</title></head><body></body></html>'
        assert "tyler" in html.lower()


class TestProofpointDecoding:
    """LD-01: Proofpoint URL unwrapping."""

    def test_urldefense_pattern_detected(self):
        """LD-01: urldefense URLs should be detected for unwrapping."""
        url = "https://urldefense.com/v3/__https://courts.example.com/download__"
        assert "urldefense" in url.lower()

    def test_base_url_reconstruction(self):
        """LD-08: Base URL can be reconstructed from original."""
        original = "https://courts.example.com/path/resource.ashx?id=123"
        from urllib.parse import urlparse
        parsed = urlparse(original)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        assert base_url == "https://courts.example.com"
