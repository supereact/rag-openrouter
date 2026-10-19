"""Authenticated credits endpoints; public provider callbacks use HMAC authentication."""
from datetime import datetime
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app import credit_payments
from app.security import Principal, require_principal

router = APIRouter()


class PurchaseBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    credits: str = Field(strict=True, min_length=1, max_length=10)
    network: Literal['usdttrc20', 'usdtbsc', 'usdterc20']
    request_key: UUID


class PaymentOrder(BaseModel):
    id: UUID
    mode: Literal['sandbox', 'live']
    credits: str
    service_fee: str
    total_usd: str
    network: str
    status: str
    pay_address: str | None
    pay_amount: str | None
    expires_at: datetime | None
    created_at: datetime


class Network(BaseModel):
    id: str
    label: str


class CreditSummary(BaseModel):
    mode: Literal['disabled', 'sandbox', 'live']
    payments_enabled: bool
    usage_enforced: bool
    balance: str
    reserved: str
    available: str
    service_fee_percent: str
    minimum_credits: str
    maximum_credits: str
    networks: list[Network]


class PaymentHistory(BaseModel):
    items: list[PaymentOrder]
    total: int
    page: int
    page_size: int
    pages: int


class CreditTransaction(BaseModel):
    id: int
    kind: Literal['topup', 'usage', 'refund']
    amount: str
    created_at: datetime


class TransactionHistory(BaseModel):
    items: list[CreditTransaction]
    total: int
    page: int
    page_size: int
    pages: int


def storage_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (psycopg.Error, OSError) as exc:
        raise HTTPException(503, 'Credits storage unavailable. Check the credits migration and database.') from exc


def page_size(size: int):
    if size not in (20, 50, 100):
        raise HTTPException(422, 'page_size must be 20, 50 or 100')
    return size


@router.get('/credits', response_model=CreditSummary)
def credits(response: Response, principal: Principal = Depends(require_principal)):
    response.headers['Cache-Control'] = 'no-store'
    return storage_call(credit_payments.summary, principal)


@router.get('/credits/orders', response_model=PaymentHistory)
def orders(response: Response, page: int = Query(1, ge=1), size: int = Query(20, alias='page_size'),
           principal: Principal = Depends(require_principal)):
    response.headers['Cache-Control'] = 'no-store'
    return storage_call(credit_payments.history, principal, page, page_size(size))


@router.get('/credits/transactions', response_model=TransactionHistory)
def transactions(response: Response, page: int = Query(1, ge=1), size: int = Query(20, alias='page_size'),
                 principal: Principal = Depends(require_principal)):
    response.headers['Cache-Control'] = 'no-store'
    return storage_call(credit_payments.history, principal, page, page_size(size), transactions=True)


@router.post('/credits/orders', response_model=PaymentOrder, status_code=201)
def purchase(body: PurchaseBody, response: Response, principal: Principal = Depends(require_principal)):
    response.headers['Cache-Control'] = 'no-store'
    return storage_call(credit_payments.create_order, principal, body.credits, body.network, body.request_key)


@router.post('/credits/orders/{order_id}/check', response_model=PaymentOrder)
def check_payment(order_id: UUID, response: Response, principal: Principal = Depends(require_principal)):
    response.headers['Cache-Control'] = 'no-store'
    return storage_call(credit_payments.check_order, principal, order_id)


@router.post('/payments/nowpayments/{mode}/ipn')
async def nowpayments_notification(mode: Literal['sandbox', 'live'], request: Request,
                                  signature: str = Header('', alias='x-nowpayments-sig')):
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > 64_000:
            raise HTTPException(413, 'Payment notification too large')
        chunks.append(chunk)
    await run_in_threadpool(storage_call, credit_payments.notification, mode, b''.join(chunks), signature)
    return Response(status_code=204, headers={'Cache-Control': 'no-store'})
