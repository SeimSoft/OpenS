import json
import os
import numpy as np
import pytest

from opens_suite.stimuli.stimuli import Stimuli


def test_stimuli_basic():
    stim = Stimuli()
    stim["t"] = [0.0, 1.0, 2.0]

    # Node proxy testing
    stim["VOUT"] << 1e-3
    stim["VIN"] >> 1e-3

    # Source generation using helpers
    stim[("IN", "0")] = stim.vdc(5.0)
    stim[("CLK", "0")] = stim.vpulse(
        0, 3.3, td=1e-9, tr=100e-12, tf=100e-12, pw=10e-9, per=20e-9
    )

    assert np.array_equal(stim["t"], [0.0, 1.0, 2.0])
    # Verify current sources are captured (gnd to VOUT <<)
    assert ("0", "VOUT") in stim._currents
    assert stim._currents[("0", "VOUT")] == 1e-3


def test_stimuli_spice_generation():
    stim = Stimuli()
    stim["t"] = [0.0, 1.0, 2.0, 3.0]

    # DC Source
    stim[("N1", "0")] = stim.vdc(3.3)

    # PWL via array
    stim[("N2", "N3")] = [0.0, 1.0, 0.5, 0.0]

    # Current source PWL
    stim["IOUT"] << [0, 1e-3, 2e-3, 0]

    spice = stim.generate_spice()
    print("Generated SPICE:\n", spice)

    # Verify sources
    assert "DC 3.3" in spice
    assert "PWL(0.0 0.0 1.0 1.0 2.0 0.5 3.0 0.0)" in spice
    assert (
        "IOUT" in spice
    )  # The current source node name is embedded in the instance name


def test_stimuli_spectre_generation():
    stim = Stimuli()
    stim["t"] = [0.0, 1.0, 2.0]

    # SINE source
    stim[("VIN", "0")] = stim.vsin(f=1e3, amp=1.0, offset=0.0, phase=0.0)

    spectre = stim.generate_spectre()
    print("Generated Spectre:\n", spectre)

    assert "simulator lang=spectre" in spectre
    assert "vsource type=sine" in spectre
    assert "freq=1000.0" in spectre
    assert "ampl=1.0" in spectre


def test_stimuli_json_save(tmp_path):
    stim = Stimuli()
    stim[("DC_NODE", "0")] = stim.vdc(1.23)

    json_path = tmp_path / "test_stimuli.json"
    stim.save_json(str(json_path), format="spice")

    assert os.path.exists(json_path)

    with open(json_path, "r") as f:
        data = json.load(f)

    assert "runset" in data
    assert "DC 1.23" in data["runset"]
