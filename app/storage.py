"""Ablage der Daten: Dropbox (produktiv) oder lokaler Ordner (Entwicklung/Tests).

Alle Daten liegen als JSON-Dateien unter einem Basisordner:
  mitglieder.json, plaetze.json, runden/<id>.json, ranglisten/<gruppe>/<datei>.pdf
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol


class Storage(Protocol):
    def read(self, path: str) -> bytes | None: ...
    def write(self, path: str, data: bytes) -> None: ...
    def delete(self, path: str) -> None: ...
    def list(self, folder: str) -> list[str]: ...


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
    def __init__(self, app_key: str, app_secret: str, refresh_token: str, base: str = "/Stableford"):
        import dropbox

        self._dropbox = dropbox
        self.dbx = dropbox.Dropbox(oauth2_refresh_token=refresh_token, app_key=app_key, app_secret=app_secret)
        self.base = "/" + base.strip("/")

    def _p(self, path: str) -> str:
        return f"{self.base}/{path.lstrip('/')}"

    def read(self, path: str) -> bytes | None:
        from dropbox.exceptions import ApiError

        try:
            _, resp = self.dbx.files_download(self._p(path))
            return resp.content
        except ApiError:
            return None

    def write(self, path: str, data: bytes) -> None:
        mode = self._dropbox.files.WriteMode.overwrite
        self.dbx.files_upload(data, self._p(path), mode=mode, mute=True)

    def delete(self, path: str) -> None:
        from dropbox.exceptions import ApiError

        try:
            self.dbx.files_delete_v2(self._p(path))
        except ApiError:
            pass

    def list(self, folder: str) -> list[str]:
        from dropbox.exceptions import ApiError

        try:
            res = self.dbx.files_list_folder(self._p(folder))
        except ApiError:
            return []
        names = [e.name for e in res.entries]
        while res.has_more:
            res = self.dbx.files_list_folder_continue(res.cursor)
            names += [e.name for e in res.entries]
        return sorted(names)


def storage_from_env() -> Storage:
    key = os.environ.get("DROPBOX_APP_KEY")
    if key:
        return DropboxStorage(
            key,
            os.environ["DROPBOX_APP_SECRET"],
            os.environ["DROPBOX_REFRESH_TOKEN"],
            os.environ.get("DROPBOX_FOLDER", "/Stableford"),
        )
    return LocalStorage(os.environ.get("DATA_DIR", "data"))


def read_json(st: Storage, path: str, default):
    raw = st.read(path)
    return json.loads(raw) if raw else default


def write_json(st: Storage, path: str, obj) -> None:
    st.write(path, json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"))
