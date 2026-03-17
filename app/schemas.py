from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, ConfigDict, Field

from app.models import ItemStatus, ListingStatus, UserRole


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
    error_message: Optional[str]
    created_at: datetime


class CompatibilityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    motorcycle_brand: str
    motorcycle_model: str
    year_start: int
    year_end: int
    notes: Optional[str] = None


class AttributeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    value: str


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    oem: str
    part_name: Optional[str]
    brand: Optional[str]
    category: Optional[str]
    technical_description: Optional[str]
    confidence_level: Optional[int]
    source_data: Optional[str]
    compatibilities: List[CompatibilityOut] = []
    attributes: List[AttributeOut] = []


class ProductUpdateIn(BaseModel):
    part_name: Optional[str] = Field(default=None, max_length=255)
    brand: Optional[str] = Field(default=None, max_length=120)
    category: Optional[str] = Field(default=None, max_length=120)
    technical_description: Optional[str] = None
    confidence_level: Optional[int] = Field(default=None, ge=0, le=100)


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
    final_price: Optional[float]


class ListingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: Optional[str]
    description: Optional[str]
    ml_category: Optional[str]
    condition: str
    price: Optional[float]
    quantity: int
    status: ListingStatus
    ml_item_id: Optional[str]


class ValidationResponse(BaseModel):
    valid: bool
    errors: list[str]