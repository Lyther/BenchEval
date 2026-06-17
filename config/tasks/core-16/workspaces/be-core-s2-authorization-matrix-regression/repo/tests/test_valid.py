from authz import can


def test_viewer_reads_document() -> None:
    assert can("viewer", "read", "document") is True


def test_editor_writes_document() -> None:
    assert can("editor", "write", "document") is True


def test_admin_deletes_settings() -> None:
    assert can("admin", "delete", "settings") is True
