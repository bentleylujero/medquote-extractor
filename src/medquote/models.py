from pydantic import BaseModel, Field


class QuoteThrowaway(BaseModel):
    """Phase 1 throwaway schema: exactly 5 fields to prove the extraction loop.
    Full field list arrives in Phase 2. Confidence/sidecar data is NOT part
    of this model -- it will live in a separate object in Phase 2.
    """

    vendor: str = Field(description="Name of the vendor or supplier issuing the quote")
    quote_number: str = Field(description="Quote or reference number printed on the document")
    quote_date: str = Field(description="Date the quote was issued, as written on the document")
    total_amount: float = Field(description="Total quoted amount, numeric value only, no currency symbol")
    item_description: str = Field(description="Description of the primary line item or equipment quoted")
