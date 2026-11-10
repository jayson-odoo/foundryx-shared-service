"""FastAPI dependency for the write-back gateway routes (plan 55 S5)."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.database import get_db
from modules.autocount.write_back.operations import OperationService
from modules.autocount.write_back.primitives import PrimitiveService
from modules.autocount.write_back.service import WriteBackService


def get_write_back_service(db: Session = Depends(get_db)) -> WriteBackService:
    return WriteBackService(db)


def get_primitive_service(db: Session = Depends(get_db)) -> PrimitiveService:
    return PrimitiveService(db)


def get_operation_service(db: Session = Depends(get_db)) -> OperationService:
    return OperationService(db)
