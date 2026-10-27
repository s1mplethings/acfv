from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_product_tabs_are_service_backed_and_registered() -> None:
    tabs = (ROOT / "src/acfv/ui/tabs/__init__.py").read_text(encoding="utf-8")
    window = (ROOT / "src/acfv/main_window.py").read_text(encoding="utf-8")
    library = (ROOT / "src/acfv/ui/tabs/library_tab.py").read_text(encoding="utf-8")
    conversation = (ROOT / "src/acfv/ui/tabs/conversation_tab.py").read_text(encoding="utf-8")

    assert "create_library_tab" in tabs and "create_conversation_tab" in tabs
    assert "create_review_tab" in tabs
    assert window.index("create_library_tab") < window.index("create_twitch_tab(self")
    assert "LibraryService" in library and "Session(" not in library
    assert "GroundedConversationService" in conversation and "Session(" not in conversation
    assert "setPosition(start_ms)" in conversation
    assert "Create Clip" in conversation and "ClipService" in conversation
    review = (ROOT / "src/acfv/ui/tabs/review_tab.py").read_text(encoding="utf-8")
    assert "GuiVariantWorkflowService" in review and "Re-render" in review
    assert "FeedbackService" in review and "保存偏好" in review
    assert "Duration Profile" in review and "Generate All" in review
    assert "Subtitle Mode" in review and "Subtitle Cue Editor" in review
    assert "QTableWidget" in review and "QDesktopServices.openUrl" in review
    assert "Session(" not in review and "subprocess" not in review
