from config.settings import load_config, normalize


def test_normalize_applies_defaults() -> None:
    cfg = normalize({})
    assert cfg["app_name"] == "app"
    assert cfg["debug"] is False


def test_old_style_config_without_enable_async() -> None:
    cfg = normalize({"app_name": "legacy", "debug": True})
    assert cfg["app_name"] == "legacy"
    assert cfg["debug"] is True
    assert cfg["enable_async"] is False


def test_enable_async_unlocks_async_pipeline_flag() -> None:
    cfg = normalize({"enable_async": True})
    assert cfg["feature_flags"]["async_pipeline"] is True


def test_load_yaml_fixture(tmp_path) -> None:
    path = tmp_path / "cfg.yaml"
    path.write_text("app_name: demo\ndebug: false\n", encoding="utf-8")
    cfg = load_config(path)
    assert cfg["app_name"] == "demo"
    assert cfg["enable_async"] is False
