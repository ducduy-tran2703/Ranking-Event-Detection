from eventrank.rag.query_ner import boost_candidates_with_ner


def test_boost_candidates_prefers_in_chunk_and_exact_label_match():
    candidates = [
        {"chunk_id": "c1", "article_id": "a1", "start_char": 0, "end_char": 100, "rrf_score": 0.032},
        {"chunk_id": "c2", "article_id": "a2", "start_char": 200, "end_char": 300, "rrf_score": 0.030},
        {"chunk_id": "c3", "article_id": "a3", "start_char": 0, "end_char": 100, "rrf_score": 0.029},
    ]
    query_entities = [{"text": "đà nẵng", "label": "ORG", "start_char": 0, "end_char": 7}]
    art_entities = {
        # a1: Đà Nẵng là LOC (du lịch) trong chunk -> chỉ được text_only_multiplier
        "a1": [{"text": "Đà Nẵng", "label": "LOC", "start_char": 10, "end_char": 17}],
        # a2: Đà Nẵng là ORG nhưng nằm ở tiêu đề (ngoài chunk [200, 300))
        "a2": [{"text": "Đà Nẵng", "label": "ORG", "start_char": 10, "end_char": 17}],
        # a3: Đà Nẵng là ORG nằm ngay trong chunk [0, 100) -> boost cao nhất
        "a3": [{"text": "Đà Nẵng", "label": "ORG", "start_char": 20, "end_char": 27}],
    }
    reranked = boost_candidates_with_ner(candidates, query_entities, art_entities)
    assert [r["chunk_id"] for r in reranked] == ["c3", "c1", "c2"]
    assert reranked[0]["ner_boost"] == 0.008
    assert reranked[0]["final_score"] == 0.037
    assert reranked[1]["ner_boost"] == 0.0032
    assert reranked[2]["ner_boost"] == 0.003


def test_boost_candidates_noop_when_no_query_entities():
    candidates = [
        {"chunk_id": "c1", "article_id": "a1", "start_char": 0, "end_char": 50, "rrf_score": 0.02},
    ]
    out = boost_candidates_with_ner(candidates, [], {})
    assert out[0]["ner_boost"] == 0.0
    assert out[0]["final_score"] == 0.02
    assert out[0]["matched_entities"] == []


def test_boost_giu_lai_hang_rrf_goc_de_truy_vet():
    candidates = [
        {"chunk_id": "c1", "article_id": "a1", "start_char": 0, "end_char": 50, "rrf_score": 0.03, "rank": 1},
        {"chunk_id": "c2", "article_id": "a2", "start_char": 0, "end_char": 50, "rrf_score": 0.02, "rank": 2},
    ]
    q = [{"text": "Hà Nội", "label": "LOC", "start_char": 0, "end_char": 6}]
    arts = {"a2": [{"text": "Hà Nội", "label": "LOC", "start_char": 5, "end_char": 11}]}
    out = boost_candidates_with_ner(candidates, q, arts, in_chunk_boost=0.02)
    assert [(r["chunk_id"], r["rrf_rank"], r["rank"]) for r in out] == [("c2", 2, 1), ("c1", 1, 2)]
