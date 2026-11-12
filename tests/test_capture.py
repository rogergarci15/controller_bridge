from zwiftplay.capture import CaptureWriter, labelled_frames, read_capture
from zwiftplay.capture_script import guided_steps, steps_for_side


def test_roundtrip_and_labels(tmp_path):
    path = tmp_path / "sub" / "c.jsonl"
    with CaptureWriter(path) as cap:
        cap.write("meta", tool="test")
        cap.rx("dev", "0002", b"\x15")
        cap.label("left_up", "start")
        cap.rx("dev", "0002", b"\x07\x08\x01")
        cap.tx("dev", "0003", b"RideOn")
        cap.label("left_up", "end")
        cap.rx("dev", "0002", b"\x15")
        assert cap.counts == {"meta": 1, "rx": 3, "label": 2, "tx": 1}

    records = list(read_capture(path))
    assert [r["type"] for r in records] == ["meta", "rx", "label", "rx", "tx", "label", "rx"]
    assert all("t" in r and "mono" in r for r in records)
    assert records[4]["hex"] == b"RideOn".hex()

    groups = labelled_frames(path)
    assert [r["hex"] for r in groups["left_up"]] == ["070801"]
    assert [r["hex"] for r in groups[""]] == ["15", "15"]


def test_script_labels_unique_and_cover_both_sides():
    steps = guided_steps(["left", "right"])
    labels = [s.label for s in steps]
    assert len(labels) == len(set(labels))
    for expected in ("left_up", "left_side_button", "left_power_button", "right_a",
                     "right_paddle_steer", "right_paddle_brake", "left_paddle_steer_slow"):
        assert expected in labels
    assert all(s.label.startswith("right_") for s in steps_for_side("right"))
