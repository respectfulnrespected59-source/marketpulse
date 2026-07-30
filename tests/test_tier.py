"""Tier resolution, including the hosted-deployment override.

These exist because the public Render demo served TIER="pro" to everyone who
had the link — the whole paid product, free — since a hosted instance runs one
build for all visitors and the tier was a hardcoded constant. The override has
to work, and just as importantly it has to fail closed.
"""

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent


def load_config(monkeypatch, env_value):
    """Load the ROOT config.py fresh, with MP_TIER set (or absent).

    Loaded by path rather than `import config`: conftest puts agent/ first on
    sys.path so a bare import resolves to agent/config.py, which is a different
    module entirely. Executing the file fresh each call is also what lets us see
    boot-time behaviour, since the env is read at import.
    """
    if env_value is None:
        monkeypatch.delenv("MP_TIER", raising=False)
    else:
        monkeypatch.setenv("MP_TIER", env_value)

    spec = importlib.util.spec_from_file_location("mp_root_config", ROOT / "config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestTierOverride:
    def test_defaults_to_the_shipped_tier_when_unset(self, monkeypatch):
        # A downloaded zip sets no env var and must keep its built tier.
        cfg = load_config(monkeypatch, None)
        assert cfg.TIER == "pro"
        assert cfg.is_pro() is True

    def test_env_can_pin_a_hosted_instance_to_free(self, monkeypatch):
        cfg = load_config(monkeypatch, "free")
        assert cfg.TIER == "free"
        assert cfg.is_pro() is False

    def test_free_locks_every_paid_feature(self, monkeypatch):
        cfg = load_config(monkeypatch, "free")
        feats = cfg.features()
        for paid in ("proof", "alerts", "unlimited_symbols", "dca", "options"):
            assert feats[paid] is False, paid

    def test_env_is_case_and_whitespace_tolerant(self, monkeypatch):
        assert load_config(monkeypatch, "  FREE  ").TIER == "free"

    @pytest.mark.parametrize("bogus", ["premium", "PRO_PLUS", "1", "yes", "", "   "])
    def test_an_unrecognised_value_fails_closed_to_free(self, monkeypatch, bogus):
        # A typo in the Render dashboard must never unlock the paid product.
        cfg = load_config(monkeypatch, bogus)
        assert cfg.TIER == "free"
        assert cfg.is_pro() is False

    def test_env_can_also_pin_pro(self, monkeypatch):
        cfg = load_config(monkeypatch, "pro")
        assert cfg.TIER == "pro"
        assert cfg.features()["options"] is True


class TestBuilderStillRewritesTier:
    """The override must not break the build-time rewrite it sits next to."""

    def test_builder_can_still_produce_both_editions(self):
        import re
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(root / "tools"))
        import build_buyer_pack as bp

        for tier in ("free", "pro"):
            src = bp._config_source(tier)
            literal = re.search(r'^TIER = "(\w+)"', src, re.M)
            assert literal and literal.group(1) == tier

    def test_a_free_zip_stays_free_with_no_env_var(self, monkeypatch):
        """The rewritten literal is what the env default falls back to."""
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(root / "tools"))
        import build_buyer_pack as bp

        monkeypatch.delenv("MP_TIER", raising=False)
        namespace: dict = {}
        exec(compile(bp._config_source("free"), "config.py", "exec"), namespace)
        assert namespace["TIER"] == "free"
        assert namespace["features"]()["options"] is False
