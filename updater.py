"""Self-update from GitHub.

The repo's version.json is compared with the local one. When newer, the
branch zip is downloaded, unpacked over the app folder (the private Python
environment and user files are left alone), new requirements are installed
and PubDesign restarts.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import zipfile

from PySide6.QtCore import QObject, Signal

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "Ljbutton/PubDesign"
BRANCH = "main"
VERSION_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/version.json"
RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
SETUP_NAME = "PubDesign-Setup.exe"
FROZEN = bool(getattr(sys, "frozen", False))  # running as the installed PubDesign.exe
ZIP_URL = f"https://github.com/{REPO}/archive/refs/heads/{BRANCH}.zip"
PROTECTED = {".venv", ".git", ".previous", "__pycache__", "dist", "build"}
UA = {"User-Agent": "PubDesign-Updater"}


def local_version():
    try:
        with open(os.path.join(HERE, "version.json"), encoding="utf-8") as f:
            return json.load(f).get("version", "0")
    except Exception:
        return "0"


def vtuple(v):
    out = []
    for part in str(v).lstrip("vV").split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out + [0] * (3 - len(out)))


def fetch_remote_info(timeout=6):
    """Installed app: newest GitHub Release (it has the installer). Source copy: version.json on main."""
    if FROZEN:
        req = urllib.request.Request(RELEASE_API, headers={**UA, "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            rel = json.loads(r.read().decode("utf-8"))
        asset = next((a["browser_download_url"] for a in rel.get("assets", []) if a.get("name") == SETUP_NAME), None)
        notes = (rel.get("body") or "").strip().splitlines()
        return {"version": rel.get("tag_name", "0").lstrip("vV"), "notes": notes[0] if notes else "", "setup_url": asset}
    req = urllib.request.Request(VERSION_URL + "?nocache=1", headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def download(url, dest, progress=None):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(262144)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)


def install_exe_update(progress=None):
    """Installed app: download the new installer and run it silently once PubDesign has closed.
    The installer reopens PubDesign when it finishes. Call QApplication.quit() right after this."""
    info = fetch_remote_info()
    url = info.get("setup_url")
    if not url:
        raise RuntimeError("The newest release doesn't have an installer yet. Try again in a few minutes.")
    dest = os.path.join(tempfile.gettempdir(), SETUP_NAME)
    download(url, dest, progress)
    if os.path.getsize(dest) < 1_000_000:
        raise RuntimeError("The download was incomplete. Try again.")
    # Run the installer directly (no Command Prompt). /WAITFORAPP makes it wait until this
    # copy of PubDesign has closed (see APP_MUTEX) before replacing files; it shows only a
    # small progress window and reopens PubDesign when done.
    subprocess.Popen([dest, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/WAITFORAPP"],
                     close_fds=True, creationflags=0x00000008 | 0x00000200)  # DETACHED | NEW_PROCESS_GROUP
    return info.get("version", "?")


APP_MUTEX = "PubDesignRunning"
_mutex = None


def mark_running():
    """Hold a named mutex while PubDesign runs so the installer can wait for it to close."""
    global _mutex
    if os.name != "nt" or _mutex is not None:
        return
    try:
        import ctypes
        _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, APP_MUTEX)
    except Exception:
        _mutex = None


def _read(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def install_update(progress=None):
    """Download and apply the latest version. Returns the new version string."""
    tmp = tempfile.mkdtemp(prefix="pubdesign_update_")
    try:
        zpath = os.path.join(tmp, "update.zip")
        req = urllib.request.Request(ZIP_URL, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r, open(zpath, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(os.path.join(tmp, "x"))
        roots = os.listdir(os.path.join(tmp, "x"))
        src = os.path.join(tmp, "x", roots[0]) if len(roots) == 1 else os.path.join(tmp, "x")
        if not (os.path.exists(os.path.join(src, "app.py")) and os.path.exists(os.path.join(src, "version.json"))):
            raise RuntimeError("The download doesn't look like a PubDesign release.")
        with open(os.path.join(src, "version.json"), encoding="utf-8") as f:
            new_version = json.load(f).get("version", "?")

        old_reqs = _read(os.path.join(HERE, "requirements.txt"))
        # keep a copy of the current version so it can be restored by hand if needed
        backup = os.path.join(HERE, ".previous")
        shutil.rmtree(backup, ignore_errors=True)
        os.makedirs(backup, exist_ok=True)
        for name in os.listdir(HERE):
            if name in PROTECTED:
                continue
            p = os.path.join(HERE, name)
            if os.path.isfile(p):
                shutil.copy2(p, os.path.join(backup, name))
        # copy new files over
        for root, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if d not in PROTECTED]
            rel = os.path.relpath(root, src)
            dest_dir = HERE if rel == "." else os.path.join(HERE, rel)
            os.makedirs(dest_dir, exist_ok=True)
            for fn in files:
                shutil.copy2(os.path.join(root, fn), os.path.join(dest_dir, fn))
        # new dependencies?
        new_reqs = _read(os.path.join(HERE, "requirements.txt"))
        if new_reqs and new_reqs != old_reqs:
            py = sys.executable.replace("pythonw.exe", "python.exe")
            kw = {"creationflags": 0x08000000} if os.name == "nt" else {}
            subprocess.run([py, "-m", "pip", "install", "-r", os.path.join(HERE, "requirements.txt")],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900, **kw)
        return new_version
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def restart():
    py = sys.executable
    if os.name == "nt" and py.lower().endswith("python.exe"):
        cand = py[:-10] + "pythonw.exe"
        if os.path.exists(cand):
            py = cand
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([py, os.path.join(HERE, "app.py")], cwd=HERE, close_fds=True, **kw)


class UpdateChecker(QObject):
    """Checks GitHub in a background thread; emits results on the Qt thread."""
    available = Signal(str, str)   # version, notes
    upToDate = Signal(str)         # local version
    failed = Signal(str)

    def check(self):
        def run():
            try:
                info = fetch_remote_info()
                remote = info.get("version", "0")
                if vtuple(remote) > vtuple(local_version()):
                    self.available.emit(remote, info.get("notes", ""))
                else:
                    self.upToDate.emit(local_version())
            except Exception as e:
                self.failed.emit(str(e))
        threading.Thread(target=run, daemon=True).start()
