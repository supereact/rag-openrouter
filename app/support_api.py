"""Authenticated support endpoints; existing cookie CSRF/auth checks apply."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
import psycopg

from app import support_chat
from app.security import Principal, require_principal

router = APIRouter(prefix='/support/chats', tags=['support'])


class MessageBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    body: str = Field(min_length=1, max_length=4000)
    request_key: UUID

    @field_validator('body')
    @classmethod
    def trim_body(cls, value):
        if not value.strip():
            raise ValueError('Message cannot be blank')
        return value.strip()


class NewChatBody(MessageBody):
    subject: str = Field(min_length=1, max_length=120)

    @field_validator('subject')
    @classmethod
    def trim_subject(cls, value):
        if not value.strip():
            raise ValueError('Subject cannot be blank')
        return value.strip()


class StatusBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['open', 'closed']


class Chat(BaseModel):
    id: int
    subject: str
    tenant_id: int
    user_id: int
    username: str
    status: Literal['open', 'closed']
    created_at: datetime
    updated_at: datetime


class Message(BaseModel):
    id: int
    sender_user_id: int
    username: str
    author_kind: Literal['user', 'staff']
    body: str
    created_at: datetime


class ChatList(BaseModel):
    items: list[Chat]
    total: int
    page: int
    page_size: int
    is_staff: bool
    enabled: bool


class Messages(BaseModel):
    chat: Chat
    messages: list[Message]
    has_more: bool


def storage_call(response, function, *args):
    response.headers['Cache-Control'] = 'no-store'
    try:
        return function(*args)
    except (psycopg.Error, OSError) as exc:
        raise HTTPException(503, 'Support is temporarily unavailable. Please try again later.') from exc


@router.get('', response_model=ChatList)
def list_chats(response: Response, page: int = Query(1, ge=1),
               page_size: int = Query(20),
               status: Literal['all', 'open', 'closed'] = 'all',
               principal: Principal = Depends(require_principal)):
    if page_size not in (20, 50, 100):
        raise HTTPException(422, 'page_size must be 20, 50 or 100')
    return storage_call(response, support_chat.list_chats, principal, page, page_size, status)


@router.post('', response_model=Chat, status_code=201)
def create_chat(body: NewChatBody, response: Response, principal: Principal = Depends(require_principal)):
    return storage_call(response, support_chat.create_chat, principal, body.subject, body.body, body.request_key)


@router.get('/{chat_id}/messages', response_model=Messages)
def read_messages(chat_id: int, response: Response, after_id: int = Query(0, ge=0),
                  principal: Principal = Depends(require_principal)):
    return storage_call(response, support_chat.read_messages, principal, chat_id, after_id)


@router.post('/{chat_id}/messages', response_model=Message, status_code=201)
def send_message(chat_id: int, body: MessageBody, response: Response,
                 principal: Principal = Depends(require_principal)):
    return storage_call(response, support_chat.send_message, principal, chat_id, body.body, body.request_key)


@router.patch('/{chat_id}', response_model=Chat)
def set_status(chat_id: int, body: StatusBody, response: Response,
               principal: Principal = Depends(require_principal)):
    return storage_call(response, support_chat.set_status, principal, chat_id, body.status)
