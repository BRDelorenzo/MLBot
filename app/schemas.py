from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import ItemStatus, KBDocumentStatus, ListingStatus, UserRole


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: UserRole


class BatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    total_items: int
    total_valid: int
    total_invalid: int
    created_at: datetime


class ImportItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_id: int
    oem_raw: str
    oem_normalized: str
    status: ItemStatus
    error_message: str | None
    created_at: datetime


class CompatibilityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    motorcycle_brand: str
    motorcycle_model: str
    year_start: int
    year_end: int
    notes: str | None = None


class AttributeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    value: str


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    oem: str
    part_name: str | None
    brand: str | None
    category: str | None
    technical_description: str | None
    confidence_level: int | None
    source_data: str | None
    compatibilities: list[CompatibilityOut] = []
    attributes: list[AttributeOut] = []


class ProductUpdateIn(BaseModel):
    part_name: str | None = Field(default=None, min_length=1, max_length=255)
    brand: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, min_length=1, max_length=120)
    technical_description: str | None = Field(default=None, min_length=1)
    confidence_level: int | None = Field(default=None, ge=0, le=100)


class PricingRequest(BaseModel):
    cost: float = Field(gt=0)
    estimated_shipping: float = Field(default=0, ge=0)
    commission_percent: float = Field(default=0.16, ge=0, lt=1)
    fixed_fee: float = Field(default=0, ge=0)
    margin_percent: float = Field(default=0.20, ge=0, lt=1)


class PricingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    cost: float
    estimated_shipping: float
    commission_percent: float
    fixed_fee: float
    margin_percent: float
    suggested_price: float
    final_price: float | None


class ListingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None
    description: str | None
    ml_category: str | None
    condition: str
    price: float | None
    quantity: int
    status: ListingStatus
    ml_item_id: str | None


class ValidationResponse(BaseModel):
    valid: bool
    errors: list[str]


# --- Mercado Livre ---

class MLAuthURL(BaseModel):
    auth_url: str


class MLTokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ml_user_id: str | None
    token_type: str
    expires_at: datetime
    scope: str | None


class MLPublishResult(BaseModel):
    ml_item_id: str
    permalink: str | None = None
    status: str


# --- Knowledge Base ---

class KBCompatibilityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    motorcycle_model: str
    year_info: str | None


class KBEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    oem_code: str
    oem_code_normalized: str
    honda_part_name: str | None
    honda_price: float | None = None
    section_context: str | None = None
    page_number: int | None = None
    compatibilities: list[KBCompatibilityOut] = []


class KBDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    document_type: str
    brand: str
    page_count: int | None
    status: KBDocumentStatus
    error_message: str | None
    created_at: datetime
    entry_count: int = 0


class KBSearchResult(BaseModel):
    oem_code: str
    entries: list[KBEntryOut]
    found_in_kb: bool


class EnrichmentResult(BaseModel):
    product_id: int
    common_name: str
    confidence: int
    source: str
    provider: str = ""
    model: str = ""
    honda_price: float | None = None
    compatibilities_count: int
    attributes_count: int
