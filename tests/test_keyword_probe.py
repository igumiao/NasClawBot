from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _load_keyword_probe_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "keyword_probe.py"
    spec = spec_from_file_location("keyword_probe", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_summarize_results_keeps_count_and_top_candidates():
    module = _load_keyword_probe_module()

    rows = [
        {
            "id": "100",
            "title": "Dune: Part Two",
            "seeders": 42,
            "size": "10.00 GB",
            "size_bytes": 10737418240,
        },
        {
            "id": "101",
            "title": "Dune (2021)",
            "seeders": 15,
            "size": "8.50 GB",
            "size_bytes": 9126805504,
        },
    ]

    summary = module.summarize_results("dune 2", rows, top_n=1)

    assert summary == {
        "keyword": "dune 2",
        "result_count": 2,
        "top_candidates": [
            {
                "id": "100",
                "title": "Dune: Part Two",
                "seeders": 42,
                "size": "10.00 GB",
                "size_bytes": 10737418240,
            }
        ],
    }
