"""Ablage der Daten: Dropbox (produktiv) oder lokaler Ordner (Entwicklung/Tests).

Alle Daten liegen als JSON-Dateien unter einem Basisordner:
  mitglieder.json, plaetze.json, runden/<id>.json, ranglisten/<gruppe>/<datei>.pdf
"""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Protocol


class Storage(Protocol):
    def read(self, path: str) -> bytes | None: ...
    def write(self, path: str, data: bytes) -> None: ...
    def delete(self, path: str) -> None: ...
    def list(self, folder: str) -> list[str]: ...


def read_many(st: Storage, paths: list[str]) -> list[bytes | None]:
    """Mehrere Dateien lesen; bei Dropbox parallel."""
    if isinstance(st, DropboxStorage):
        return st.read_many(paths)
    return [st.read(p) for p in paths]


class LocalStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _p(self, path: str) -> Path:
        p = (self.root / path.lstrip("/")).resolve()
        if self.root.resolve() not in p.parents and p != self.root.resolve():
            raise ValueError("Ungültiger Pfad")
        return p

    def read(self, path: str) -> bytes | None:
        p = self._p(path)
        return p.read_bytes() if p.exists() else None

    def write(self, path: str, data: bytes) -> None:
        p = self._p(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def delete(self, path: str) -> None:
        p = self._p(path)
        if p.exists():
            p.unlink()

    def list(self, folder: str) -> list[str]:
        p = self._p(folder)
        return sorted(x.name for x in p.iterdir() if x.is_file()) if p.exists() else []


class DropboxStorage:
    """Dropbox mit Zwischenspeicher im Arbeitsspeicher.

    Jede Dropbox-Anfrage dauert 0.1-0.3 s. Ohne Zwischenspeicher lädt die Startseite
    jede Runde einzeln und braucht mehrere Sekunden. Gelesene Dateien werden mit ihrer
    Revision gemerkt: beim Auflisten eines Ordners werden nur geänderte Dateien neu geladen.
    Einzelne Dateien (Mitglieder, Plätze, Einstellungen) gelten READ_TTL Sekunden;
    Änderungen über die App aktualisieren den Speicher sofort.
    """

    READ_TTL = 120

    def __init__(self, app_key: str, app_secret: str, refresh_token: str, base: str = "/Stableford"):
        import dropbox

        self._dropbox = dropbox
        self.dbx = dropbox.Dropbox(oauth2_refresh_token=refresh_token, app_key=app_key, app_secret=app_secret)
        self.base = "/" + base.strip("/")
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[bytes | None, str | None, float]] = {}  # path -> (Inhalt, rev, Zeit)
        self._revs: dict[str, str] = {}  # path -> zuletzt beim Auflisten gesehene rev

    def _p(self, path: str) -> str:
        return f"{self.base}/{path.lstrip('/')}"

    @staticmethod
    def _key(path: str) -> str:
        return path.lstrip("/")

    def _download(self, path: str) -> tuple[bytes | None, str | None]:
        from dropbox.exceptions import ApiError

        try:
            meta, resp = self.dbx.files_download(self._p(path))
            return resp.content, meta.rev
        except ApiError:
            return None, None

    def _fresh(self, key: str) -> bool:
        hit = self._cache.get(key)
        if not hit:
            return False
        _, rev, ts = hit
        known = self._revs.get(key)
        if known is not None:
            return rev == known  # durch Auflisten bestätigt
        return time.monotonic() - ts < self.READ_TTL

    def read(self, path: str) -> bytes | None:
        key = self._key(path)
        with self._lock:
            if self._fresh(key):
                return self._cache[key][0]
        data, rev = self._download(path)
        with self._lock:
            self._cache[key] = (data, rev, time.monotonic())
        return data

    def read_many(self, paths: list[str]) -> list[bytes | None]:
        with self._lock:
            missing = [p for p in paths if not self._fresh(self._key(p))]
        if missing:
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(self._download, missing))
            now = time.monotonic()
            with self._lock:
                for p, (data, rev) in zip(missing, results):
                    self._cache[self._key(p)] = (data, rev, now)
        with self._lock:
            return [self._cache.get(self._key(p), (None, None, 0))[0] for p in paths]

    def write(self, path: str, data: bytes) -> None:
        mode = self._dropbox.files.WriteMode.overwrite
        meta = self.dbx.files_upload(data, self._p(path), mode=mode, mute=True)
        key = self._key(path)
        with self._lock:
            self._cache[key] = (data, meta.rev, time.monotonic())
            if key in self._revs:
                self._revs[key] = meta.rev

    def delete(self, path: str) -> None:
        from dropbox.exceptions import ApiError

        try:
            self.dbx.files_delete_v2(self._p(path))
        except ApiError:
            pass
        key = self._key(path)
        with self._lock:
            self._cache.pop(key, None)
            self._revs.pop(key, None)

    def list(self, folder: str) -> list[str]:
        from dropbox.exceptions import ApiError

        try:
            res = self.dbx.files_list_folder(self._p(folder))
        except ApiError:
            return []
        entries = list(res.entries)
        while res.has_more:
            res = self.dbx.files_list_folder_continue(res.cursor)
            entries += res.entries
        prefix = self._key(folder).rstrip("/") + "/"
        with self._lock:
            for k in [k for k in self._revs if k.startswith(prefix)]:
                del self._revs[k]
            for e in entries:
                rev = getattr(e, "rev", None)
                if rev:
                    self._revs[prefix + e.name] = rev
        return sorted(e.name for e in entries)


def env(name: str, default: str = "") -> str:
    """Wert ohne Leerzeichen und Zeilenumbrüche (Render fügt beim Einfügen manchmal welche ein)."""
    return "".join(os.environ.get(name, default).split())


def dropbox_token_set() -> bool:
    """Ein Platzhalter wie "leer" (Render verlangt evtl. einen Wert) zählt nicht als Token."""
    return len(env("DROPBOX_REFRESH_TOKEN")) > 20


def storage_from_env() -> Storage:
    key = env("DROPBOX_APP_KEY")
    if key and dropbox_token_set():
        return DropboxStorage(
            key,
            env("DROPBOX_APP_SECRET"),
            env("DROPBOX_REFRESH_TOKEN"),
            os.environ.get("DROPBOX_FOLDER", "/Stableford"),
        )
    return LocalStorage(os.environ.get("DATA_DIR", "data"))


def read_json(st: Storage, path: str, default):
    raw = st.read(path)
    return json.loads(raw) if raw else default


def write_json(st: Storage, path: str, obj) -> None:
    st.write(path, json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"))
