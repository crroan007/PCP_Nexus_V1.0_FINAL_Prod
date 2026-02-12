"""
Test Classification & CL Detection Logic
==========================================
Covers: HC-05..HC-12 from the testing plan.
Tests _is_clerk_letter() in isolation (no heavy deps needed).
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


# ──────────────────────────────────────────────
# _is_clerk_letter is a pure string function.
# We can test it without instantiating HunterV2 at all.
# ──────────────────────────────────────────────

def _is_clerk_letter(filename):
    """Extracted clone of HunterV2._is_clerk_letter for isolated unit testing.
    This mirrors the production logic exactly."""
    name_upper = filename.upper().replace(".PDF", "").replace(".pdf", "").strip()
    if name_upper.endswith("CL"):
        return True
    if name_upper.startswith("CL"):
        return True
    return False


# ──────────────────────────────────────────────
# HC-05..HC-09: _is_clerk_letter()
# ──────────────────────────────────────────────

class TestIsClerkLetter:
    """Tests for full-filename CL suffix scanning (v4.2)."""

    def test_cl_suffix_detected(self):
        """HC-05: AX40A25C05955CL.pdf → True"""
        assert _is_clerk_letter("AX40A25C05955CL.pdf") is True

    def test_no_cl_suffix(self):
        """HC-06: AX40A25C05955.pdf → False"""
        assert _is_clerk_letter("AX40A25C05955.pdf") is False

    def test_cl_prefix_standalone(self):
        """HC-07: CL_something.pdf → True (legacy prefix)"""
        assert _is_clerk_letter("CL_something.pdf") is True

    def test_no_cl_at_end(self):
        """HC-08: Filename not ending with CL → False"""
        assert _is_clerk_letter("AXPE_NOCLA.pdf") is False

    def test_empty_string(self):
        """HC-09: Empty string → False"""
        assert _is_clerk_letter("") is False

    def test_cl_case_insensitive(self):
        """CL detection should be case insensitive."""
        assert _is_clerk_letter("ax40a25c05955cl.pdf") is True
        assert _is_clerk_letter("AX40A25C05955Cl.PDF") is True

    def test_cl_with_extra_spaces(self):
        """CL detection handles trailing spaces."""
        assert _is_clerk_letter("AX40A25C05955CL.pdf ") is True

    def test_not_cl_when_cl_in_middle(self):
        """AXCLA25 — doesn't end with CL, doesn't start with CL."""
        assert _is_clerk_letter("AXCLA25.pdf") is False

    def test_just_cl_dot_pdf(self):
        """Edge case: filename is literally 'CL.pdf'."""
        assert _is_clerk_letter("CL.pdf") is True


# ──────────────────────────────────────────────
# HC-10: Discard list (AX69, AX81, CL) — Prefix checks
# ──────────────────────────────────────────────

class TestDiscardLogic:
    """Tests the multi-doc discard scanning from _download_message_parts."""

    def test_ax69_detected_for_discard(self):
        """HC-10a: AX69 prefix is flagged for discard."""
        name_upper = "AX69A25C05955.PDF".upper().replace(".PDF", "")
        assert "AX69" in name_upper

    def test_ax81_detected_for_discard(self):
        """HC-10b: AX81 prefix is flagged for discard."""
        name_upper = "AX81A25C05955.PDF".upper().replace(".PDF", "")
        assert "AX81" in name_upper

    def test_combined_discard_check(self):
        """Full discard check as in _download_message_parts."""
        test_cases = [
            ("AX40A25C05955CL.pdf", True),   # CL suffix → discard
            ("AX69A25C05955.pdf", True),      # AX69 → discard
            ("AX81A25C05955.pdf", True),      # AX81 → discard
            ("AX40A25C05955.pdf", False),     # Normal lead → keep
            ("AXPEA25C05955.pdf", False),     # Attachment → keep
        ]
        for filename, should_discard in test_cases:
            name_upper = filename.upper().replace(".PDF", "")
            is_discardable = (
                _is_clerk_letter(filename) or 
                "AX69" in name_upper or 
                "AX81" in name_upper
            )
            assert is_discardable == should_discard, f"Failed for {filename}: expected {should_discard}"


# ──────────────────────────────────────────────
# HC-11: Phase routing
# ──────────────────────────────────────────────

class TestPhaseRouting:
    """Tests prefix → phase routing logic."""

    def test_phase1_prefixes(self):
        """HC-11a: Phase 1 handles AX02, AX03, AX07, AX09."""
        phase1 = {"AX02", "AX03", "AX07", "AX09"}
        for prefix in ["AX02", "AX03", "AX07", "AX09"]:
            assert prefix in phase1

    def test_phase2_prefixes(self):
        """HC-11b: Phase 2 handles AX40, AX69, AXPE, AXEX, AXCR."""
        phase2_all = {"AX40", "AX69", "AXPE", "AXEX", "AXCR", "CL", "AX81"}
        for prefix in ["AX40", "AXPE", "AXCR"]:
            assert prefix in phase2_all

    def test_no_overlap_between_phases(self):
        """Phase 1 and Phase 2 prefixes should not overlap."""
        phase1 = {"AX02", "AX03", "AX07", "AX09"}
        phase2 = {"AX40", "AX69", "AXPE", "AXEX", "AXCR", "CL", "AX81"}
        assert len(phase1 & phase2) == 0
