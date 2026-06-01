from app import main as app_main
from app.api import chat_routes
from app.main import create_app


def _route_for(app, path: str):
    return next(route for route in app.router.routes if getattr(route, "path", None) == path)


def test_index_route_serves_html():
    app = create_app()
    response = _route_for(app, "/").endpoint()

    assert "<html" in response.lower() or "<!doctype html" in response.lower()


def test_static_mount_does_not_break_health():
    app = create_app()
    response = _route_for(app, "/health").endpoint()

    assert response == {"status": "ok"}


def test_index_route_prefers_built_dist_html(tmp_path, monkeypatch):
    source_index = tmp_path / "index.html"
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    dist_index = dist_dir / "index.html"
    source_index.write_text("<!doctype html><html><body>source</body></html>", encoding="utf-8")
    dist_index.write_text("<!doctype html><html><body>built</body></html>", encoding="utf-8")
    monkeypatch.setattr(chat_routes, "_FRONTEND_INDEX", source_index)
    monkeypatch.setattr(chat_routes, "_FRONTEND_DIST_INDEX", dist_index)

    app = create_app()
    response = _route_for(app, "/").endpoint()

    assert "built" in response


def test_index_route_does_not_switch_to_dist_after_app_creation(tmp_path, monkeypatch):
    source_index = tmp_path / "index.html"
    dist_dir = tmp_path / "dist"
    dist_index = dist_dir / "index.html"
    source_index.write_text("<!doctype html><html><body>source</body></html>", encoding="utf-8")
    monkeypatch.setattr(chat_routes, "_FRONTEND_INDEX", source_index)
    monkeypatch.setattr(chat_routes, "_FRONTEND_DIST_INDEX", dist_index)

    app = create_app()
    dist_dir.mkdir()
    dist_index.write_text("<!doctype html><html><body>built later</body></html>", encoding="utf-8")

    response = _route_for(app, "/").endpoint()

    assert "source" in response
    assert "built later" not in response


def test_assets_mount_serves_file_when_present_at_app_creation(tmp_path, monkeypatch):
    frontend_dir = tmp_path / "frontend"
    assets_dir = frontend_dir / "dist" / "assets"
    assets_dir.mkdir(parents=True)
    asset_file = assets_dir / "app.js"
    asset_file.write_text("console.log('asset ok');", encoding="utf-8")
    monkeypatch.setattr(app_main, "_frontend_dir", lambda: frontend_dir)

    app = create_app()
    assets_mount = _route_for(app, "/assets")
    resolved_path, stat_result = assets_mount.app.lookup_path("app.js")

    assert resolved_path == str(asset_file)
    assert stat_result is not None
