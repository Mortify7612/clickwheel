import sys

from clickwheel import desktop


def entries(data):
    return sorted(p.name for p in (data / "applications").iterdir())


def test_source_checkout_installs_as_clickwheel_dev(tmp_path, monkeypatch):
    data = tmp_path / "share"
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    launcher = desktop._launcher()
    (data / "applications").mkdir(parents=True)
    (data / "applications" / "clickwheel.desktop").write_text(f"[Desktop Entry]\nName=Clickwheel\nExec={launcher}\n")

    desktop.install_desktop_entry()
    assert entries(data) == ["clickwheel-dev.desktop"]  # the old entry for this checkout is replaced
    text = (data / "applications" / "clickwheel-dev.desktop").read_text()
    assert "Name=Clickwheel Dev\n" in text and "Icon=clickwheel-dev\n" in text and f"Exec={launcher}\n" in text
    icons = sorted(p.parent.parent.name for p in data.glob("icons/hicolor/*/apps/clickwheel-dev.png"))
    assert "256x256" in icons and "1024x1024" not in icons
    assert not list(data.glob("icons/hicolor/*/apps/clickwheel.png"))


def test_a_release_entry_is_left_alone(tmp_path, monkeypatch):
    data = tmp_path / "share"
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    (data / "applications").mkdir(parents=True)
    release = "[Desktop Entry]\nName=Clickwheel\nExec=/home/me/Applications/Clickwheel.AppImage\n"
    (data / "applications" / "clickwheel.desktop").write_text(release)
    desktop.install_desktop_entry()
    assert entries(data) == ["clickwheel-dev.desktop", "clickwheel.desktop"]
    assert (data / "applications" / "clickwheel.desktop").read_text() == release


def test_an_appimage_launches_itself(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/tmp/.mount_Clickw123/Clickwheel/Clickwheel")
    monkeypatch.setenv("APPIMAGE", "/home/me/Applications/Clickwheel.AppImage")
    assert desktop._launcher() == "/home/me/Applications/Clickwheel.AppImage"
    monkeypatch.delenv("APPIMAGE")
    assert desktop._launcher() == "/tmp/.mount_Clickw123/Clickwheel/Clickwheel"
