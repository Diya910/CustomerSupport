from datetime import datetime
from typing import Optional, Dict, Any, List
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import (
    Column, Integer, String, Boolean, Numeric, DateTime,
    ForeignKey, Text, CheckConstraint, Index,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class QueryExecutionResult(BaseModel):
    success: bool
    rows: Optional[List[Dict[str, Any]]] = None
    metadata: Dict[str, Any] = {}
    message: str = ""


class DBConnectionOutputModel(BaseModel):
    status: bool
    message: Optional[str] = None
    connection: Optional[object] = None
    uri_connection: Optional[object] = None
    database_schema: Optional[Dict[str, Any]] = None
    table_names: Optional[List[str]] = None
    schema_prompt: Optional[str] = None
    few_shot_prompt: Optional[str] = None
    store: Optional[object] = None
    store_ctx: Optional[object] = None
    checkpointer: Optional[object] = None
    checkpoint_pool: Optional[object] = None

    class Config:
        arbitrary_types_allowed = True


# ── Refund domain SQLAlchemy models ──────────────────────────────────────────

class RefundBase(DeclarativeBase):
    pass


class Customer(RefundBase):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    email = Column(String(254), nullable=False, unique=True)
    phone = Column(String(20))
    account_tier = Column(String(20), nullable=False, default="standard")
    total_orders = Column(Integer, nullable=False, default=0)
    total_refunds_issued = Column(Integer, nullable=False, default=0)
    is_flagged = Column(Boolean, nullable=False, default=False)
    flag_reason = Column(String(255))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    orders = relationship("Order", back_populates="customer")
    refund_requests = relationship("RefundRequest", back_populates="customer")

    __table_args__ = (
        CheckConstraint(
            "account_tier IN ('standard','premium','vip')",
            name="ck_account_tier",
        ),
    )


class Order(RefundBase):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    order_number = Column(String(30), nullable=False, unique=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    product_name = Column(String(200), nullable=False)
    category = Column(String(80), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="USD")
    status = Column(String(30), nullable=False)
    ordered_at = Column(DateTime, nullable=False)
    delivered_at = Column(DateTime)
    is_digital = Column(Boolean, nullable=False, default=False)
    payment_method = Column(String(40))
    shipping_method = Column(String(40))

    customer = relationship("Customer", back_populates="orders")
    refund_requests = relationship("RefundRequest", back_populates="order")

    __table_args__ = (
        CheckConstraint(
            "status IN ('delivered','shipped','cancelled','returned','processing')",
            name="ck_order_status",
        ),
        Index("ix_orders_customer_id", "customer_id"),
    )


class RefundRequest(RefundBase):
    __tablename__ = "refund_requests"

    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    reason = Column(String(500), nullable=False)
    decision = Column(String(20))
    denial_reason = Column(String(500))
    agent_reasoning = Column(Text)
    amount_requested = Column(Numeric(10, 2))
    amount_approved = Column(Numeric(10, 2))
    requested_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    decided_at = Column(DateTime)

    customer = relationship("Customer", back_populates="refund_requests")
    order = relationship("Order", back_populates="refund_requests")

    __table_args__ = (
        CheckConstraint(
            "decision IN ('approved','denied','pending') OR decision IS NULL",
            name="ck_refund_decision",
        ),
        Index("ix_refund_customer_id", "customer_id"),
        Index("ix_refund_order_id", "order_id"),
    )


