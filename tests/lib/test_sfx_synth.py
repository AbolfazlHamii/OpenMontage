"""Procedural SFX: deterministic, peak-limited, the right shape in time."""

from __future__ import annotations

import wave

import numpy as np
import pytest

from lib.sfx_synth import PEAK_DBFS, RATE, SYNTHS, peak_time, render


@pytest.mark.parametrize("name", sorted(SYNTHS))
def test_each_effect_is_deterministic_and_peak_limited(name):
    a, b = SYNTHS[name](), SYNTHS[name]()
    assert np.array_equal(a, b)
    peak = 20 * np.log10(np.max(np.abs(a)))
    assert peak == pytest.approx(PEAK_DBFS, abs=0.2)


def test_crackle_bed_is_dense_enough_to_hear():
    bed = SYNTHS["crackle"](duration=3.0)
    assert 20 * np.log10(np.sqrt(np.mean(bed ** 2))) > -26


def test_seed_changes_noise_effects():
    assert not np.array_equal(SYNTHS["whoosh"](seed=1), SYNTHS["whoosh"](seed=9))


def test_shapes_in_time():
    # Impacts peak at once; a riser peaks at its end; a whoosh in its body.
    assert peak_time(SYNTHS["hit"]()) < 0.05
    assert peak_time(SYNTHS["pop"]()) < 0.03
    riser = SYNTHS["riser"](duration=2.0)
    assert peak_time(riser) > 1.6
    whoosh = SYNTHS["whoosh"](duration=0.6)
    assert 0.15 < peak_time(whoosh) < 0.55


def test_render_writes_wav_with_provenance(tmp_path):
    info = render("riser", tmp_path / "sfx" / "riser.wav", duration=1.0)
    assert info["licence"] == "own work (procedural)" and info["duration"] == 1.0
    with wave.open(str(tmp_path / "sfx" / "riser.wav")) as w:
        assert w.getframerate() == RATE and w.getnchannels() == 1
        assert w.getnframes() == RATE
