import numpy as np

from eventrank.weak_labels.dense import cache_path, mean_pool


def test_mean_pool_bo_qua_token_dem_va_chuan_hoa_do_dai_1():
    h = np.array([[[1.0, 0.0], [3.0, 0.0], [100.0, 100.0]]])     # token thứ 3 là đệm (mask = 0)
    mask = np.array([[1, 1, 0]])
    v = mean_pool(h, mask)
    assert np.allclose(v, [[1.0, 0.0]])                          # trung bình (1,0),(3,0) = (2,0) → chuẩn hoá


def test_ten_file_cache_khong_chua_dau_gach_cheo():
    assert cache_path("data/c", "Xenova/paraphrase-multilingual-MiniLM-L12-v2").name == \
        "Xenova__paraphrase-multilingual-MiniLM-L12-v2.npz"


def test_tai_mo_hinh_noi_tiep_khi_dut_mang_va_kiem_ma_bam(tmp_path, monkeypatch):
    import hashlib
    import io
    import urllib.request

    from eventrank.weak_labels import dense

    data = bytes(range(256)) * 40
    sha = hashlib.sha256(data).hexdigest()
    calls = []

    class Resp(io.BytesIO):
        def __init__(self, body, status):
            super().__init__(body)
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=-1):
            chunk = super().read(1000)                               # mạng thật trả từng khúc nhỏ
            if calls[-1] == 0 and self.tell() > 3000:                # lần đầu: đứt mạng giữa chừng
                raise OSError("connection reset")
            return chunk

    def fake_urlopen(req, timeout=60):
        rng = req.headers.get("Range")
        start = int(rng.split("=")[1].rstrip("-")) if rng else 0
        calls.append(start)
        return Resp(data[start:], 206 if start else 200)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", lambda s: None)
    d = dense.download_model("org/m", root=tmp_path, files={"model.onnx": sha})
    assert (d / "model.onnx").read_bytes() == data
    assert calls[0] == 0 and calls[1] > 0                            # lần hai nối tiếp, không tải lại từ đầu
