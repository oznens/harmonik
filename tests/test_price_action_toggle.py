"""Price Action ANA anahtarı: --price-action / env / salt harmonik çözümü."""
from __future__ import annotations

from terminal.cli.run_live_multi import PA_DEFAULT_MIN_SMC, _env_truthy, _resolve_pa


def test_env_truthy():
    for v in ("on", "ON", "On", "1", "true", "evet", "aç"):
        assert _env_truthy(v) is True
    for v in ("off", "0", "", None, "hayir", "false"):
        assert _env_truthy(v) is False


def test_pa_off_is_pure_harmonic():
    # Anahtar kapalı + granül kapalı → salt harmonik
    ltf, smc, on = _resolve_pa(price_action=None, env_on=False, ltf_choch=False, min_smc=0)
    assert (ltf, smc, on) == (False, 0, False)


def test_pa_flag_on_enables_both():
    ltf, smc, on = _resolve_pa(price_action=True, env_on=False, ltf_choch=False, min_smc=0)
    assert ltf is True and smc == PA_DEFAULT_MIN_SMC and on is True


def test_pa_env_on_enables_when_flag_none():
    ltf, smc, on = _resolve_pa(price_action=None, env_on=True, ltf_choch=False, min_smc=0)
    assert ltf is True and smc == PA_DEFAULT_MIN_SMC and on is True


def test_flag_overrides_env_off():
    # --no-price-action (False) env'i ezer → kapalı
    ltf, smc, on = _resolve_pa(price_action=False, env_on=True, ltf_choch=False, min_smc=0)
    assert on is False


def test_pa_on_respects_explicit_min_smc():
    # Anahtar açık ama elle --min-smc 60 verilmiş → 60 korunur
    ltf, smc, on = _resolve_pa(price_action=True, env_on=False, ltf_choch=False, min_smc=60)
    assert smc == 60 and ltf is True and on is True


def test_granular_works_when_master_off():
    # Anahtar kapalı ama elle --ltf-choch / --min-smc verilmiş → bağımsız çalışır
    ltf, smc, on = _resolve_pa(price_action=None, env_on=False, ltf_choch=True, min_smc=40)
    assert ltf is True and smc == 40 and on is False
