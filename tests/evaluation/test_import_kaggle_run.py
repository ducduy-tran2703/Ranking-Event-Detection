import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "training"))
import import_kaggle_run as ik


def _model(d: Path, tag: str) -> Path:
    m = d / tag
    (m / "1_Pooling").mkdir(parents=True)
    for f in ("model.safetensors", "config_sentence_transformers.json", "modules.json"):
        (m / f).write_text("x")
    return m


def test_nhap_zip_best_model_kem_ket_qua_canh_ben(tmp_path):
    src = tmp_path / "dl"
    _model(src / "z", "bkai-v4-cosent-s43")
    zp = shutil.make_archive(str(src / "best_model_bkai-v4-cosent-s43"), "zip", root_dir=src / "z",
                             base_dir="bkai-v4-cosent-s43")
    (src / "results_v4_cosent.json").write_text(json.dumps({"runs": []}))
    out = ik.import_run(zp, models_dir=tmp_path / "models", stamp="2026-10-30")
    assert [p.name for p in out] == ["bkai-v4-cosent-s43_2026-10-30"]
    assert (out[0] / "model.safetensors").exists() and (out[0] / "results_v4_cosent.json").exists()


def test_nhap_thu_muc_output_lay_moi_seed(tmp_path):
    out_dir = tmp_path / "output"
    for s in (42, 43, 44):
        _model(out_dir / "models", f"e5-v4-cosent-s{s}")
    out = ik.import_run(out_dir, models_dir=tmp_path / "models", stamp="d")
    assert sorted(p.name for p in out) == [f"e5-v4-cosent-s{s}_d" for s in (42, 43, 44)]


def test_khong_ghi_de_model_da_co(tmp_path):
    _model(tmp_path / "src", "bkai-v4-cosent-s44")
    ik.import_run(tmp_path / "src", models_dir=tmp_path / "models", stamp="d")
    with pytest.raises(FileExistsError):
        ik.import_run(tmp_path / "src", models_dir=tmp_path / "models", stamp="d")


def test_khong_co_model_thi_bao_loi(tmp_path):
    (tmp_path / "rong").mkdir()
    with pytest.raises(FileNotFoundError):
        ik.import_run(tmp_path / "rong", models_dir=tmp_path / "models")


def test_lenh_so_sanh_dung_tien_xu_ly_theo_ho_mo_hinh():
    assert ik.compare_arg(Path("data/models/e5-v4-cosent-s42_d")).endswith(":query")
    assert ik.compare_arg(Path("data/models/bkai-v4-cosent-s42_d")).endswith(":pyvi")
