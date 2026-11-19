"""Verifier and policy unit tests. No LLM needed."""

from docai.policy import STRICT, decide_grounded
from docai.schema import FIELDS_BY_NAME, Decision, Document, FieldExtraction, Page
from docai.verify import verify_field

DOC = Document(
    doc_id="unit",
    pages=[
        Page(number=1, text='This Agreement is entered into as of March 4, 2025 (the "Effective Date") by and between '
                            'Riverbend Co. ("Customer") and Northwind Analytics LLC, a wholly owned subsidiary of '
                            'Northwind Holdings Inc. ("Vendor").'),
        Page(number=2, text='3.1 The total contract value payable is $240,000.00 (the "Total Contract Value"). '
                            "5.1 Aggregate liability shall not exceed $500,000.00."),
        Page(number=3, text="6.1 Either party may terminate this Agreement upon thirty (30) days' prior written notice."),
    ],
)

TCV = FIELDS_BY_NAME["total_contract_value"]
EFFECTIVE = FIELDS_BY_NAME["effective_date"]
NOTICE = FIELDS_BY_NAME["termination_notice_days"]
VENDOR = FIELDS_BY_NAME["vendor_name"]


def run(spec, **kwargs):
    ex = FieldExtraction(**kwargs)
    return decide_grounded(spec, ex, verify_field(DOC, spec, ex))


def test_exact_quote_with_matching_value_is_accepted():
    out = run(TCV, value="USD 240000.00", evidence_quote="The total contract value payable is $240,000.00", page=2)
    assert out.decision == Decision.ACCEPT
    assert out.checks["quote_match"] == "exact"


def test_fabricated_quote_goes_to_review():
    out = run(TCV, value="USD 240000.00", evidence_quote="The contract value is $240,000 per year", page=2)
    assert out.decision == Decision.REVIEW
    assert "quote_not_in_document" in out.reasons


def test_value_not_supported_by_quote_goes_to_review():
    out = run(TCV, value="USD 250000.00", evidence_quote="The total contract value payable is $240,000.00", page=2)
    assert "value_not_in_quote" in out.reasons
    assert out.decision == Decision.REVIEW


def test_distractor_number_with_real_quote_is_caught_by_conflict_scan():
    # The quote is real and contains the value, but it is the liability cap, not the contract value.
    out = run(TCV, value="USD 500000.00", evidence_quote="Aggregate liability shall not exceed $500,000.00", page=2)
    assert out.checks["value_in_quote"] is True
    assert "conflicting_candidates" in out.reasons


def test_wrong_page_citation_goes_to_review_under_strict_policy():
    ex = FieldExtraction(value="30", evidence_quote="may terminate this Agreement upon thirty (30) days' prior written notice", page=1)
    out = decide_grounded(NOTICE, ex, verify_field(DOC, NOTICE, ex), STRICT)
    assert "quote_on_different_page" in out.reasons


def test_wrong_page_citation_is_repaired_by_default():
    out = run(NOTICE, value="30", evidence_quote="may terminate this Agreement upon thirty (30) days' prior written notice", page=1)
    assert out.decision == Decision.ACCEPT
    assert out.page == 3


def test_small_quote_differences_pass_fuzzy_match():
    out = run(NOTICE, value="30", evidence_quote="may terminate this Agreement upon thirty (30) days prior written notice", page=3)
    assert out.checks["quote_match"] == "fuzzy"
    assert out.decision == Decision.ACCEPT


def test_escaped_inner_quotes_still_match_exactly():
    out = run(EFFECTIVE, value="2025-03-04", page=1,
              evidence_quote='"as of March 4, 2025 (the \\"Effective Date\\")"')
    assert out.checks["quote_match"] == "exact"


def test_quote_that_does_not_mention_the_field_goes_to_review():
    out = run(EFFECTIVE, value="2025-03-04", evidence_quote="as of March 4, 2025", page=1)
    assert out.reasons == ["quote_does_not_mention_field"]


def test_abstaining_on_a_required_field_goes_to_review():
    doc = Document(doc_id="x", pages=[Page(number=1, text="An agreement with no parties named.")])
    ex = FieldExtraction(status="not_found")
    out = decide_grounded(VENDOR, ex, verify_field(doc, VENDOR, ex))
    assert out.reasons == ["required_field_missing"]


def test_abstain_when_nothing_in_document_is_not_found():
    doc = Document(doc_id="x", pages=[Page(number=1, text="Termination rights are set out in the SOW.")])
    ex = FieldExtraction(status="not_found")
    out = decide_grounded(NOTICE, ex, verify_field(doc, NOTICE, ex))
    assert out.decision == Decision.NOT_FOUND


def test_abstain_when_document_has_a_candidate_goes_to_review():
    out = run(NOTICE, status="not_found")
    assert out.decision == Decision.REVIEW
    assert out.reasons == ["abstained_but_candidates_found"]


def test_ambiguous_date_goes_to_review():
    doc = Document(doc_id="x", pages=[Page(number=1, text='entered into as of 03/04/2025 (the "Effective Date").')])
    ex = FieldExtraction(value="2025-03-04", evidence_quote='as of 03/04/2025 (the "Effective Date")', page=1)
    out = decide_grounded(EFFECTIVE, ex, verify_field(doc, EFFECTIVE, ex))
    assert "ambiguous_value" in out.reasons


def test_missing_quote_goes_to_review():
    out = run(EFFECTIVE, value="2025-03-04", page=1)
    assert "missing_quote" in out.reasons
