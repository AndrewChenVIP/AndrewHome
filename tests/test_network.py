from __future__ import annotations

from wandao_launchpad.config import Mirrors
from wandao_launchpad.constants import PIP_MIRRORS
from wandao_launchpad.network import mirror_env_vars, pip_index_url


def test_default_hf_mirror_injected():
    env = mirror_env_vars(Mirrors())
    assert env["HF_ENDPOINT"] == "https://hf-mirror.com"


def test_custom_hf_wins():
    env = mirror_env_vars(Mirrors(hf="https://x.example"))
    assert env["HF_ENDPOINT"] == "https://x.example"


def test_gh_proxy_only_when_set():
    assert "WANDAO_GH_PROXY" not in mirror_env_vars(Mirrors())
    env = mirror_env_vars(Mirrors(github_proxy="https://gh.example/"))
    assert env["WANDAO_GH_PROXY"] == "https://gh.example/"


def test_pip_index_alias_and_url_and_empty():
    assert pip_index_url("tuna") == PIP_MIRRORS["tuna"]
    assert pip_index_url("https://mirror.example/simple") == "https://mirror.example/simple"
    assert pip_index_url("") is None
    assert pip_index_url("   ") is None
