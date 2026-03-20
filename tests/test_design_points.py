from opens_suite.design_points import DesignPoints
import tempfile
import os
import json

def test_design_points_serialization_with_units():
    dps = DesignPoints()
    dps["R5.R [Ohm]"] = 100
    
    assert dps._length == 1
    assert dps._units["R5.R"] == "Ohm"
    assert dps["R5.R"] == [100]
    
    # Test to_dict
    d = dps.to_dict(0)
    assert "R5.R [Ohm]" in d
    assert d["R5.R [Ohm]"] == 100
    
    # Test save/load natively
    with tempfile.TemporaryDirectory() as td:
        json_path = os.path.join(td, "test_dps.json")
        dps.save(json_path)
        
        with open(json_path, 'r') as f:
            data = json.load(f)
            
        assert "R5.R [Ohm]" in data
        assert data["R5.R [Ohm]"] == 100
        
        # Test constructor load_many dynamically
        dps2 = DesignPoints([json_path])
        assert dps2._length == 1
        assert "R5.R" in dps2._units
        assert dps2._units["R5.R"] == "Ohm"
