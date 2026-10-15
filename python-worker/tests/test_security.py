import pytest

from ccm.security.paths import PathGuard, PathPolicyError
from ccm.security.ssrf import UnsafeWebhookError, WebhookUrlValidator


def test_path_allowlist(tmp_path):
    root = tmp_path / "watched"
    root.mkdir()
    allowed = root / "app.json"
    allowed.write_text("{}", encoding="utf-8")
    guard = PathGuard([str(root)])
    assert guard.validate_registration(str(allowed)).name == "app.json"
    with pytest.raises(PathPolicyError):
        guard.validate_registration(str(tmp_path / "escape.json"))
    with pytest.raises(PathPolicyError):
        guard.validate_registration("../etc/passwd")
    with pytest.raises(PathPolicyError):
        guard.validate_registration(str(root / "x.txt"))


def test_symlink_escape(tmp_path):
    root = tmp_path / "watched"
    root.mkdir()
    outside = tmp_path / "secret.json"
    outside.write_text("{}", encoding="utf-8")
    link = root / "link.json"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks not available")
    guard = PathGuard([str(root)])
    with pytest.raises(PathPolicyError):
        guard.validate_access(str(link))


def test_ssrf_blocks_private():
    v = WebhookUrlValidator(allow_private=False)
    with pytest.raises(UnsafeWebhookError):
        v.validate("http://127.0.0.1/hook")
    with pytest.raises(UnsafeWebhookError):
        v.validate("http://localhost/hook")
    with pytest.raises(UnsafeWebhookError):
        v.validate("http://169.254.169.254/latest/meta-data")
    with pytest.raises(UnsafeWebhookError):
        v.validate("ftp://example.com/x")
    ok = WebhookUrlValidator(allow_private=True)
    assert ok.validate("http://127.0.0.1:9/hook")
