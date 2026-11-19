"""Data models shared by the extraction, verification, and policy layers."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class FieldType(str, Enum):
    TEXT = "text"
    DATE = "date"
    MONTHS = "months"
    DAYS = "days"
    MONEY = "money"
    BOOL = "bool"


class FieldSpec(BaseModel):
    name: str
    type: FieldType
    description: str
    # Regex that marks a sentence as talking about this field; used by the conflict scan.
    anchor: str | None = None
    # Every valid agreement states this field, so "not found" means something went wrong.
    required: bool = False


FIELDS: list[FieldSpec] = [
    FieldSpec(
        name="vendor_name",
        type=FieldType.TEXT,
        description="Legal name of the vendor entity that is a party to the agreement (not its parent company, not the customer).",
        required=True,
    ),
    FieldSpec(
        name="effective_date",
        type=FieldType.DATE,
        description="Effective date of the agreement, as YYYY-MM-DD. If an amendment changes it, use the amended date.",
        anchor=r"effective date",
        required=True,
    ),
    FieldSpec(
        name="term_months",
        type=FieldType.MONTHS,
        description="Length of the initial term in months, as an integer. Convert years to months. If amended, use the amended term.",
        anchor=r"initial term|term of this agreement",
        required=True,
    ),
    FieldSpec(
        name="total_contract_value",
        type=FieldType.MONEY,
        description='Total contract value, formatted as "<CURRENCY> <amount>", e.g. "USD 240000.00". If amended, use the amended value.',
        anchor=r"contract value",
        required=True,
    ),
    FieldSpec(
        name="termination_notice_days",
        type=FieldType.DAYS,
        description="Days of prior written notice required to terminate for convenience, as an integer.",
        anchor=r"terminat",
    ),
    FieldSpec(
        name="auto_renewal",
        type=FieldType.BOOL,
        description="Whether the agreement renews automatically (true or false).",
        anchor=r"renew",
    ),
]

FIELDS_BY_NAME = {f.name: f for f in FIELDS}


class Page(BaseModel):
    number: int  # 1-based
    text: str


class Document(BaseModel):
    doc_id: str
    pages: list[Page]

    def page(self, number: int) -> Page | None:
        if 1 <= number <= len(self.pages):
            return self.pages[number - 1]
        return None


class FieldExtraction(BaseModel):
    """What the model claims about one field. Values are raw strings; normalization happens in code."""

    status: Literal["found", "not_found"] = "found"
    value: str | None = None
    evidence_quote: str | None = None
    page: int | None = None
    confidence: float | None = Field(default=None, description="Self-reported; logged but never used for decisions.")


class Decision(str, Enum):
    ACCEPT = "accept"
    REVIEW = "review"
    NOT_FOUND = "not_found"


class FieldOutcome(BaseModel):
    """Final, auditable result for one field after verification and policy."""

    field: str
    decision: Decision
    value: str | None  # normalized value, e.g. "2025-03-04", "24", "USD 240000.00", "true"
    raw_value: str | None
    evidence_quote: str | None
    page: int | None
    confidence: float | None
    reasons: list[str] = Field(default_factory=list)
    checks: dict[str, object] = Field(default_factory=dict)
