import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.alpaca_client import alpaca_configured, alpaca_ok

REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_CONFIG = REPO_ROOT / ".cursor" / "mcp.json"
MCP_WRAPPER = REPO_ROOT / "scripts" / "run_alpaca_mcp.sh"


def test_mcp_config_exists():
    assert MCP_CONFIG.exists(), "Missing .cursor/mcp.json"
    data = json.loads(MCP_CONFIG.read_text())
    assert "mcpServers" in data
    assert "alpaca" in data["mcpServers"]


def test_mcp_wrapper_is_executable():
    assert MCP_WRAPPER.exists()
    assert MCP_WRAPPER.stat().st_mode & 0o111, "run_alpaca_mcp.sh must be executable"


@pytest.mark.skipif(not shutil.which("uvx"), reason="uvx not installed")
def test_alpaca_mcp_server_available():
    result = subprocess.run(
        ["uvx", "alpaca-mcp-server", "--version"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.skipif(not alpaca_configured(), reason="Alpaca credentials not configured")
def test_alpaca_api_connectivity():
    ok, error = alpaca_ok()
    assert ok, f"Alpaca API connectivity failed: {error}"
