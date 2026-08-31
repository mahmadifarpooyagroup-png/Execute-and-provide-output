import os
import sys

import pytest

from atrin_core.models import ConnectionKind, Provider


def test_provider_config_supports_dynamic_registration_and_capability_profile_fallback():
    primary = Provider.from_config({
        "id": "primary-provider",
        "name": "Primary Provider",
        "roles": ["coding"],
        "connection_kind": "WEB",
        "adapter_id": "custom-web-adapter",
        "capability_profile_id": "shared-coding-profile",
    })
    fallback = Provider.from_config({
        "id": "fallback-provider",
        "name": "Fallback Provider",
        "roles": ["coding"],
        "connection_kind": "WEB",
        "adapter_id": "fallback-web-adapter",
        "provider_capability_profile_id": "shared-coding-profile",
    })

    assert primary.connection_kind == ConnectionKind.WEB
    assert primary.adapter_id == "custom-web-adapter"
    assert primary.capability_profile_id == "shared-coding-profile"
    assert fallback.capability_profile_id == "shared-coding-profile"
    assert primary.is_valid_fallback_for(fallback, role="coding")
    assert primary.shares_capability_profile(fallback)


def test_core_modules_do_not_embed_vendor_specific_provider_names():
    vendor_tokens = {
        "qwen",
        "claude",
        "gemini",
        "openai",
        "anthropic",
        "google",
        "azure",
    }
    repo_root = os.path.dirname(os.path.dirname(__file__))
    for base, _, files in os.walk(repo_root):
        if ".git" in base:
            continue
        for filename in files:
            if not filename.endswith(".py"):
                continue
            path = os.path.join(base, filename)
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read().lower()
            hits = {token for token in vendor_tokens if token in text}
            if hits and "atrin_core" in path:
                pytest.fail(f"Vendor-specific token leakage in core module: {path} hits={sorted(hits)}")


def test_provider_registry_remains_vendor_neutral_by_default():
    provider = Provider.from_config({"id": "unknown-provider"})
    assert provider.adapter_id == "generic"
    assert provider.capability_profile_id == "default"
    assert provider.enabled is True
