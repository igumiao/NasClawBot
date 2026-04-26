import app.domain.models as domain_models
import app.llm.client as llm_client


def test_phase2a_domain_models_do_not_expose_legacy_search_constraints():
    assert not hasattr(domain_models, "SearchConstraints")


def test_phase2a_llm_client_does_not_expose_legacy_constraint_extractors():
    assert not hasattr(llm_client, "ConstraintExtractor")
    assert not hasattr(llm_client, "LocalConstraintExtractor")
