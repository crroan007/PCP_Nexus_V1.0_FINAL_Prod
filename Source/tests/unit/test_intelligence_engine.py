"""
Test Intelligence Engine — Comment Extraction & Flagging
=========================================================
Covers: IE-01..IE-08 from the testing plan.
"""
import pytest
import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


@pytest.fixture
def intel_engine(tmp_path):
    """IntelligenceEngine with temp keywords file."""
    keywords = {
        "financial_indicators": ["$", "USD", "bond"],
        "potential_action_verbs": ["serve", "hold", "return"],
        "instructional_phrases": ["do not release", "require immediate action"]
    }
    kw_path = str(tmp_path / "reporting_keywords.json")
    with open(kw_path, 'w') as f:
        json.dump(keywords, f)
    
    from core.intelligence_engine import IntelligenceEngine
    return IntelligenceEngine(keywords_path=kw_path)


class TestAnalyzeText:
    """IE-03..IE-06: Action word flagging."""

    def test_financial_indicator_triggers(self, intel_engine):
        """IE-03: '$' should trigger action flag."""
        triggered, terms = intel_engine.analyze_text("Payment of $500 required")
        assert triggered is True
        assert "$" in terms

    def test_action_verb_triggers(self, intel_engine):
        """IE-04: 'serve' and 'hold' should trigger."""
        triggered, terms = intel_engine.analyze_text("Please serve the defendant and hold the papers")
        assert triggered is True
        assert "serve" in terms
        assert "hold" in terms

    def test_clean_text_no_trigger(self, intel_engine):
        """IE-05: Normal text without keywords should not trigger."""
        triggered, terms = intel_engine.analyze_text("This is a standard filing with no special instructions")
        assert triggered is False
        assert len(terms) == 0

    def test_matched_terms_returned(self, intel_engine):
        """IE-06: All matched terms should be returned."""
        triggered, terms = intel_engine.analyze_text("$500 bond — serve immediately and hold")
        assert triggered is True
        assert len(terms) >= 3  # $, bond, serve, hold

    def test_empty_text(self, intel_engine):
        """IE-05 edge: Empty/None text should not trigger."""
        triggered, terms = intel_engine.analyze_text("")
        assert triggered is False
        triggered2, terms2 = intel_engine.analyze_text(None)
        assert triggered2 is False

    def test_instructional_phrase(self, intel_engine):
        """Instructional phrases should trigger."""
        triggered, terms = intel_engine.analyze_text("Do not release until further notice")
        assert triggered is True
        assert "do not release" in terms


class TestLoadRules:
    """IE-07..IE-08: Keywords loading."""

    def test_default_rules_on_missing_file(self, tmp_path):
        """IE-07: Missing keywords file → uses hardcoded defaults."""
        from core.intelligence_engine import IntelligenceEngine
        engine = IntelligenceEngine(keywords_path=str(tmp_path / "nonexistent.json"))
        
        assert "$" in engine.rules.get("financial_indicators", [])
        assert "serve" in engine.rules.get("potential_action_verbs", [])

    def test_custom_keywords_loaded(self, intel_engine):
        """IE-08: Custom keywords from file are loaded."""
        assert "bond" in intel_engine.rules.get("financial_indicators", [])
        assert "return" in intel_engine.rules.get("potential_action_verbs", [])
