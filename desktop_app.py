"""Native-window launcher for MkWorld2Snap."""
from __future__ import annotations

import atexit
import os
import plistlib
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


APP_NAME = "MkWorld2Snap"
WINDOW_SIZE = (1220, 820)
WINDOW_MIN_SIZE = (760, 560)


@dataclass(frozen=True)
class RuntimePaths:
    app_root: Path
    data_root: Path
    profiles: Path
    user_profiles: Path
    target_profiles: Path
    recipes: Path
    tmp: Path
    failed_tmp: Path
    frontend: Path
    config: Path


def _project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def _switch_to_local_venv() -> None:
    if getattr(sys, "frozen", False):
        return
    if os.environ.get("MKWORLD2SNAP_NO_VENV_REEXEC") == "1":
        return

    root = _project_root()
    local_python = root / ".venv" / "bin" / "python"
    if not local_python.exists():
        return

    try:
        active_prefix = Path(sys.prefix).resolve()
        local_prefix = (root / ".venv").resolve()
        running_python = Path(sys.executable).resolve()
    except OSError:
        return

    if active_prefix == local_prefix or running_python == local_python.resolve():
        return

    argv = getattr(sys, "orig_argv", [sys.executable, *sys.argv])[1:]
    os.environ["MKWORLD2SNAP_REEXECED"] = "1"
    os.execv(str(local_python), [str(local_python), *argv])


def _platform_data_root() -> Path:
    override = os.environ.get("MKWORLD2SNAP_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / APP_NAME
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME


def _copy_missing_files(source_dir: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    if not source_dir.is_dir():
        return
    for source in source_dir.iterdir():
        if source.name.startswith(".") or not source.is_file():
            continue
        target = target_dir / source.name
        if not target.exists():
            shutil.copy2(source, target)


def _runtime_paths() -> RuntimePaths:
    app_root = _project_root()
    data_root = _platform_data_root()
    paths = RuntimePaths(
        app_root=app_root,
        data_root=data_root,
        profiles=app_root / "profiles",
        user_profiles=data_root / "user_profiles",
        target_profiles=data_root / "target_profiles",
        recipes=data_root / "rules",
        tmp=data_root / "tmp",
        failed_tmp=data_root / "tmp_failed",
        frontend=app_root / "frontend" / "dist",
        config=data_root / "settings.json",
    )
    for folder in (
        paths.data_root,
        paths.user_profiles,
        paths.target_profiles,
        paths.recipes,
        paths.tmp,
        paths.failed_tmp,
    ):
        folder.mkdir(parents=True, exist_ok=True)
    _copy_missing_files(app_root / "rules", paths.recipes)
    return paths


def _publish_env(paths: RuntimePaths) -> None:
    os.environ.update(
        {
            "MKWORLD2SNAP_APP_ROOT": str(paths.app_root),
            "MKWORLD2SNAP_TARGET_PROFILES": str(paths.target_profiles),
            "MKWORLD2SNAP_CONFIG": str(paths.config),
            "MKWORLD2SNAP_FAILED_TMP": str(paths.failed_tmp),
            "MKWORLD2SNAP_FRONTEND_DIST": str(paths.frontend),
            "MKWORLD2SNAP_PROFILES": str(paths.profiles),
            "MKWORLD2SNAP_RULES": str(paths.recipes),
            "MKWORLD2SNAP_TMP": str(paths.tmp),
            "MKWORLD2SNAP_USER_PROFILES": str(paths.user_profiles),
            "DOMAINHOST": "localhost",
            "MAX_UPLOAD_MB": os.environ.get("MAX_UPLOAD_MB", "500"),
        }
    )


def _initial_window_size() -> tuple[int, int]:
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        width = int(root.winfo_screenwidth() * 0.92)
        height = int(root.winfo_screenheight() * 0.92)
        root.destroy()
        return max(WINDOW_MIN_SIZE[0], width), max(WINDOW_MIN_SIZE[1], height)
    except Exception:
        return WINDOW_SIZE


def _pick_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class LocalApiEngine:
    def __init__(self, port: int) -> None:
        self.port = port
        self.url = f"http://127.0.0.1:{port}"
        self._uvicorn_server: Any | None = None
        self._worker: threading.Thread | None = None

    def launch(self, app_root: Path) -> None:
        import uvicorn

        for candidate in (app_root / "backend", app_root):
            value = str(candidate)
            if value not in sys.path:
                sys.path.insert(0, value)

        from local_gateway import app

        cfg = uvicorn.Config(
            app=app,
            host="127.0.0.1",
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        self._uvicorn_server = uvicorn.Server(cfg)
        self._worker = threading.Thread(
            target=self._uvicorn_server.run,
            name="mkworld2snap-local-api",
            daemon=True,
        )
        self._worker.start()
        self._wait_for_health()

    def shutdown(self) -> None:
        if self._uvicorn_server is not None:
            self._uvicorn_server.should_exit = True
        if self._worker is not None:
            self._worker.join(timeout=3)

    def _wait_for_health(self) -> None:
        deadline = time.monotonic() + 20
        last_failure: Exception | None = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"{self.url}/engine/ping", timeout=1) as response:
                    if response.status == 200:
                        return
            except Exception as exc:  # noqa: BLE001 - startup probe reports final failure
                last_failure = exc
                time.sleep(0.15)
        raise RuntimeError(f"Local API did not become ready: {last_failure}")


class NativeWindowBridge:
    def __init__(self, engine_url: str, data_root: Path) -> None:
        self.engine_url = engine_url.rstrip("/")
        self.data_root = data_root

    @staticmethod
    def _save_start_dir() -> Path:
        downloads = Path.home() / "Downloads"
        return downloads if downloads.is_dir() else Path.home()

    @staticmethod
    def _with_3mf_extension(path: Path) -> Path:
        if path.name.lower().endswith(".3mf"):
            return path
        return path.with_name(f"{path.name}.3mf")

    @staticmethod
    def _show_in_file_manager(path: Path) -> bool:
        if os.environ.get("MKWORLD2SNAP_REVEAL_SAVED", "1") == "0":
            return False
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(path)])
            elif os.name == "nt":
                subprocess.Popen(["explorer", f"/select,{path}"])
            else:
                subprocess.Popen(["xdg-open", str(path.parent)])
            return True
        except Exception:
            return False

    def save_converted_file(self, job_id: str, suggested_name: str) -> dict[str, Any]:
        try:
            import webview

            window = webview.windows[0] if webview.windows else None
            if window is None:
                return {"ok": False, "error": "No desktop window is available."}

            filename = Path(suggested_name or "converted.3mf").name
            selection = window.create_file_dialog(
                webview.SAVE_DIALOG,
                directory=str(self._save_start_dir()),
                save_filename=filename,
                file_types=("3MF project (*.3mf)", "All files (*.*)"),
            )
            if not selection:
                return {"ok": False, "cancelled": True}

            raw_path = selection[0] if isinstance(selection, (list, tuple)) else selection
            target_path = self._with_3mf_extension(Path(raw_path))
            safe_job_id = urllib.parse.quote(job_id, safe="")
            download_url = f"{self.engine_url}/engine/jobs/{safe_job_id}/artifact"

            with urllib.request.urlopen(download_url, timeout=30) as response:
                with target_path.open("wb") as output:
                    shutil.copyfileobj(response, output)

            return {
                "ok": True,
                "path": str(target_path),
                "revealed": self._show_in_file_manager(target_path),
            }
        except urllib.error.HTTPError as exc:
            return {"ok": False, "error": f"Download failed: HTTP {exc.code}"}
        except Exception as exc:  # noqa: BLE001 - UI should receive the real failure text
            return {"ok": False, "error": str(exc)}

    def save_text_file(self, suggested_name: str, content: str) -> dict[str, Any]:
        try:
            import webview

            window = webview.windows[0] if webview.windows else None
            if window is None:
                return {"ok": False, "error": "No desktop window is available."}

            filename = Path(suggested_name or "mkworld2snap-note.txt").name
            if not filename.lower().endswith(".txt"):
                filename = f"{filename}.txt"
            selection = window.create_file_dialog(
                webview.SAVE_DIALOG,
                directory=str(self._save_start_dir()),
                save_filename=filename,
                file_types=("Text file (*.txt)", "All files (*.*)"),
            )
            if not selection:
                return {"ok": False, "cancelled": True}

            raw_path = selection[0] if isinstance(selection, (list, tuple)) else selection
            target_path = Path(raw_path)
            if not target_path.name.lower().endswith(".txt"):
                target_path = target_path.with_name(f"{target_path.name}.txt")
            target_path.write_text(content, encoding="utf-8")
            return {
                "ok": True,
                "path": str(target_path),
                "revealed": self._show_in_file_manager(target_path),
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def open_data_folder(self) -> dict[str, Any]:
        try:
            import webview

            window = webview.windows[0] if webview.windows else None
            if window is not None:
                window.create_file_dialog(webview.FOLDER_DIALOG, directory=str(self.data_root))
            return {"ok": True, "path": str(self.data_root)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "path": str(self.data_root)}

    @staticmethod
    def _launch_command() -> list[str]:
        if getattr(sys, "frozen", False):
            executable = Path(sys.executable).resolve()
            app_bundle = executable.parents[2] if len(executable.parents) >= 3 else None
            if sys.platform == "darwin" and app_bundle is not None and app_bundle.suffix == ".app":
                return ["/usr/bin/open", "-n", str(app_bundle)]
            return [str(executable)]
        return [str(Path(sys.executable).resolve()), str((_project_root() / "desktop_app.py").resolve())]

    @staticmethod
    def _mac_launch_agent_path() -> Path:
        return Path.home() / "Library" / "LaunchAgents" / "com.mkworld2snap.desktop.plist"

    @staticmethod
    def _linux_autostart_path() -> Path:
        return Path.home() / ".config" / "autostart" / "mkworld2snap.desktop"

    def autostart_status(self) -> dict[str, Any]:
        try:
            if sys.platform == "darwin":
                path = self._mac_launch_agent_path()
                return {"supported": True, "enabled": path.exists(), "path": str(path)}
            if os.name == "nt":
                import winreg

                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                        winreg.QueryValueEx(key, APP_NAME)
                    enabled = True
                except FileNotFoundError:
                    enabled = False
                return {"supported": True, "enabled": enabled, "path": r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"}
            path = self._linux_autostart_path()
            return {"supported": True, "enabled": path.exists(), "path": str(path)}
        except Exception as exc:  # noqa: BLE001
            return {"supported": False, "enabled": False, "error": str(exc)}

    def set_autostart(self, enabled: bool) -> dict[str, Any]:
        try:
            command = self._launch_command()
            if sys.platform == "darwin":
                path = self._mac_launch_agent_path()
                if enabled:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    payload = {
                        "Label": "com.mkworld2snap.desktop",
                        "ProgramArguments": command,
                        "RunAtLoad": True,
                        "KeepAlive": False,
                    }
                    with path.open("wb") as handle:
                        plistlib.dump(payload, handle)
                else:
                    path.unlink(missing_ok=True)
                return self.autostart_status()
            if os.name == "nt":
                import winreg

                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Run",
                    0,
                    winreg.KEY_SET_VALUE,
                ) as key:
                    if enabled:
                        value = " ".join(f'"{part}"' if " " in part else part for part in command)
                        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, value)
                    else:
                        try:
                            winreg.DeleteValue(key, APP_NAME)
                        except FileNotFoundError:
                            pass
                return self.autostart_status()
            path = self._linux_autostart_path()
            if enabled:
                path.parent.mkdir(parents=True, exist_ok=True)
                command_text = " ".join(f'"{part}"' if " " in part else part for part in command)
                path.write_text(
                    "[Desktop Entry]\n"
                    "Type=Application\n"
                    f"Name={APP_NAME}\n"
                    f"Exec={command_text}\n"
                    "Terminal=false\n"
                    "X-GNOME-Autostart-enabled=true\n",
                    encoding="utf-8",
                )
            else:
                path.unlink(missing_ok=True)
            return self.autostart_status()
        except Exception as exc:  # noqa: BLE001
            return {"supported": False, "enabled": False, "error": str(exc)}


def main() -> None:
    _switch_to_local_venv()
    paths = _runtime_paths()
    _publish_env(paths)

    if not (paths.frontend / "index.html").exists():
        raise SystemExit("Frontend build missing. Run `pnpm run build` inside frontend/ first.")

    engine = LocalApiEngine(_pick_port())
    engine.launch(paths.app_root)
    atexit.register(engine.shutdown)

    try:
        import webview
    except ImportError as exc:
        raise SystemExit("pywebview is missing. Install dependencies from requirements-desktop.txt.") from exc

    bridge = NativeWindowBridge(engine.url, paths.data_root)
    initial_width, initial_height = _initial_window_size()
    window = webview.create_window(
        APP_NAME,
        engine.url,
        js_api=bridge,
        width=initial_width,
        height=initial_height,
        min_size=WINDOW_MIN_SIZE,
        text_select=True,
    )
    window.events.closed += engine.shutdown

    print(f"{APP_NAME} running at {engine.url}")
    print(f"User data: {paths.data_root}")
    webview.start(debug=False)


if __name__ == "__main__":
    main()
