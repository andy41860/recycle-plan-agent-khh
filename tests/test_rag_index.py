from types import SimpleNamespace

from recycle_agent.rag_index import COLLECTION_METADATA, collection_name, collection_space


def test_collection_name_slug():
    assert collection_name("text-embedding-3-large") == "recycle_rules__text-embedding-3-large"
    assert collection_name("org/model:v1") == "recycle_rules__org-model-v1"
    assert collection_name("-weird-") == "recycle_rules__weird"


def test_collection_name_valid_for_chroma():
    import re

    name = collection_name("text-embedding-3-large")
    assert 3 <= len(name) <= 512
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]", name)


def test_space_from_dict_configuration():
    col = SimpleNamespace(configuration={"hnsw": {"space": "cosine"}}, metadata=None)
    assert collection_space(col) == "cosine"


def test_space_from_object_configuration():
    cfg = SimpleNamespace(hnsw_configuration=SimpleNamespace(space="ip"))
    col = SimpleNamespace(configuration=cfg, metadata=None)
    assert collection_space(col) == "ip"


def test_space_from_metadata_fallback():
    col = SimpleNamespace(configuration={}, metadata=COLLECTION_METADATA)
    assert collection_space(col) == "cosine"


def test_space_default_l2():
    assert collection_space(SimpleNamespace(configuration=None, metadata=None)) == "l2"
