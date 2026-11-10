from pathlib import Path

from forexbot.config import load_settings


def test_load_settings_reads_risk_limits(tmp_path: Path) -> None:
    path = tmp_path / "bot.toml"
    path.write_text("[bot]\nmode = 'demo'\n[risk]\nrisk_per_trade = 0.02\n")

    settings = load_settings(path)

    assert settings.mode == "demo"
    assert settings.risk_limits.risk_per_trade == 0.02
