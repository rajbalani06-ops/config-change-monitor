from __future__ import annotations

import os
from pathlib import Path


ALLOWED_EXTENSIONS = {".env", ".json", ".yaml", ".yml", ".properties"}


class PathPolicyError(ValueError):
    pass


class PathGuard:
    def __init__(self, allowlisted_roots: list[str]):
        if not allowlisted_roots:
            raise PathPolicyError("at least one allowlisted directory is required")
        self.roots = [self._canonicalize(Path(root), follow_symlinks=True) for root in allowlisted_roots]

    def _canonicalize(self, path: Path, follow_symlinks: bool) -> Path:
        try:
            if follow_symlinks:
                return path.resolve(strict=False)
            return Path(os.path.realpath(path) if path.exists() else path.absolute())
        except OSError as exc:
            raise PathPolicyError(f"cannot resolve path: {exc}") from exc

    def validate_registration(self, raw_path: str) -> Path:
        if not raw_path or raw_path.strip() != raw_path:
            raise PathPolicyError("path must be a non-empty trimmed string")
        if "\x00" in raw_path:
            raise PathPolicyError("null bytes are not allowed")
        path = Path(raw_path)
        if not path.is_absolute():
            raise PathPolicyError("path must be absolute")
        resolved = self._canonicalize(path, follow_symlinks=True)
        self._assert_inside_roots(resolved)
        if path.exists() and path.is_symlink():
            self._assert_symlink_safe(path)
        suffix = resolved.suffix.lower()
        name = resolved.name
        if name.startswith(".") and name.count(".") == 1:
            suffix = name  # .env
        if name == ".env":
            suffix = ".env"
        if suffix not in ALLOWED_EXTENSIONS:
            raise PathPolicyError("unsupported file extension")
        return resolved

    def validate_access(self, raw_path: str) -> Path:
        resolved = self.validate_registration(raw_path)
        if resolved.exists() and resolved.is_symlink():
            self._assert_symlink_safe(resolved)
        parent = resolved.parent
        if parent.exists() and parent.is_symlink():
            self._assert_inside_roots(parent.resolve())
        return resolved

    def _assert_symlink_safe(self, path: Path) -> None:
        target = path.resolve()
        self._assert_inside_roots(target)

    def _assert_inside_roots(self, resolved: Path) -> None:
        for root in self.roots:
            try:
                resolved.relative_to(root)
                return
            except ValueError:
                continue
        raise PathPolicyError("path is outside allowlisted directories")
