"""configs/sources.yaml và bộ nạp crawler."""
import pytest

from eventrank.ingest import sources


def test_sau_bao_hien_co_chua_bat_chua_co_crawler():
    rows = {r["source"]: r for r in sources.load_sources()}
    assert set(rows) == {"tuoitre", "thanhnien", "vietnamnet", "nhandan", "vnexpress",
                         "baochinhphu"}
    assert not any(r["enabled"] for r in rows.values())
    assert all(r["homepage"].startswith("https://") for r in rows.values())
    assert "302" in rows["vnexpress"]["notes"]


@pytest.mark.parametrize("bad", [
    "sources:\n  - source: TuoiTre\n",
    "sources:\n  - source: a\n  - source: a\n",
    "sources:\n  - source: a\n    crawler: khong-co-hai-cham\n",
])
def test_cau_hinh_sai_bi_tu_choi(tmp_path, bad):
    p = tmp_path / "s.yaml"
    p.write_text(bad, encoding="utf-8")
    with pytest.raises(sources.SourceConfigError):
        sources.load_sources(p)


def test_nap_crawler_tu_module_lop():
    c = sources.load_crawler("eventrank.ingest.crawlers.example_rss:ExampleRssCrawler")
    assert c.source == "baovidu"
