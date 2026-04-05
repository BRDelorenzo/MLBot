from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import relationship

from app.database import Base


def _utcnow():
    """UTC naive datetime — compatível com SQLite que não armazena timezone."""
    return datetime.now(UTC).replace(tzinfo=None)


class UserRole(StrEnum):
    admin = "admin"
    operator = "operator"
    reviewer = "reviewer"


class ItemStatus(StrEnum):
    imported = "imported"
    normalized = "normalized"
    enriching = "enriching"
    enriched = "enriched"
    awaiting_review = "awaiting_review"
    awaiting_photos = "awaiting_photos"
    photos_received = "photos_received"
    processing_images = "processing_images"
    processed = "processed"
    validating = "validating"
    validation_error = "validation_error"
    ready_to_publish = "ready_to_publish"
    publishing = "publishing"
    published = "published"
    publish_error = "publish_error"


class ImageType(StrEnum):
    original = "original"
    processed = "processed"


class ListingStatus(StrEnum):
    draft = "draft"
    validating = "validating"
    valid = "valid"
    validation_error = "validation_error"
    publishing = "publishing"
    published = "published"
    publish_error = "publish_error"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(SAEnum(UserRole), default=UserRole.operator, nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    total_items = Column(Integer, default=0, nullable=False)
    total_valid = Column(Integer, default=0, nullable=False)
    total_invalid = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=_utcnow)

    items = relationship("ImportItem", back_populates="batch", cascade="all, delete-orphan")


class ImportItem(Base):
    __tablename__ = "import_items"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("import_batches.id"), index=True, nullable=False)
    oem_raw = Column(String(120), nullable=False)
    oem_normalized = Column(String(120), index=True, nullable=False)
    status = Column(SAEnum(ItemStatus), default=ItemStatus.imported, nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    batch = relationship("ImportBatch", back_populates="items")
    product = relationship("Product", back_populates="import_item", uselist=False)


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    import_item_id = Column(Integer, ForeignKey("import_items.id"), unique=True, nullable=False)
    oem = Column(String(120), unique=True, index=True, nullable=False)
    part_name = Column(String(255), nullable=True)
    brand = Column(String(120), nullable=True)
    category = Column(String(120), nullable=True)
    technical_description = Column(Text, nullable=True)
    confidence_level = Column(Integer, nullable=True)
    source_data = Column(String(120), nullable=True)
    last_confirmed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    import_item = relationship("ImportItem", back_populates="product")
    compatibilities = relationship("ProductCompatibility", back_populates="product", cascade="all, delete-orphan")
    attributes = relationship("ProductAttribute", back_populates="product", cascade="all, delete-orphan")
    images = relationship("Image", back_populates="product", cascade="all, delete-orphan")
    listing = relationship("Listing", back_populates="product", uselist=False, cascade="all, delete-orphan")
    pricing = relationship("ProductPricing", back_populates="product", uselist=False, cascade="all, delete-orphan")


class ProductCompatibility(Base):
    __tablename__ = "product_compatibilities"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), index=True, nullable=False)
    motorcycle_brand = Column(String(120), nullable=False)
    motorcycle_model = Column(String(120), nullable=False)
    year_start = Column(Integer, nullable=False)
    year_end = Column(Integer, nullable=False)
    notes = Column(Text, nullable=True)

    product = relationship("Product", back_populates="compatibilities")


class ProductAttribute(Base):
    __tablename__ = "product_attributes"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), index=True, nullable=False)
    name = Column(String(120), nullable=False)
    value = Column(String(255), nullable=False)

    product = relationship("Product", back_populates="attributes")


class ProductPricing(Base):
    __tablename__ = "product_pricing"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), unique=True, nullable=False)
    cost = Column(Numeric(10, 2), nullable=False)
    estimated_shipping = Column(Numeric(10, 2), default=0, nullable=False)
    commission_percent = Column(Float, default=0.16, nullable=False)
    fixed_fee = Column(Numeric(10, 2), default=0, nullable=False)
    margin_percent = Column(Float, default=0.20, nullable=False)
    suggested_price = Column(Numeric(10, 2), default=0, nullable=False)
    final_price = Column(Numeric(10, 2), nullable=True)
    calculated_at = Column(DateTime, default=_utcnow)

    product = relationship("Product", back_populates="pricing")


class Image(Base):
    __tablename__ = "images"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), index=True, nullable=False)
    image_type = Column(SAEnum(ImageType), default=ImageType.original, nullable=False)
    sort_order = Column(Integer, default=1, nullable=False)
    filename = Column(String(255), nullable=False)
    storage_path = Column(String(500), nullable=False)
    mime_type = Column(String(80), nullable=True)
    status = Column(String(50), default="uploaded", nullable=False)
    created_at = Column(DateTime, default=_utcnow)

    product = relationship("Product", back_populates="images")


class Listing(Base):
    __tablename__ = "listings"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), unique=True, nullable=False)
    title = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    ml_category = Column(String(120), nullable=True)
    condition = Column(String(40), default="new", nullable=False)
    price = Column(Numeric(10, 2), nullable=True)
    quantity = Column(Integer, default=1, nullable=False)
    status = Column(SAEnum(ListingStatus), default=ListingStatus.draft, nullable=False)
    ml_item_id = Column(String(120), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    product = relationship("Product", back_populates="listing")


class MLCredential(Base):
    __tablename__ = "ml_credentials"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=True)
    ml_user_id = Column(String(80), nullable=True)
    access_token_encrypted = Column(Text, nullable=False)
    refresh_token_encrypted = Column(Text, nullable=False)
    token_type = Column(String(40), default="Bearer", nullable=False)
    expires_at = Column(DateTime, nullable=False)
    scope = Column(String(255), nullable=True)
    pkce_verifier = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
