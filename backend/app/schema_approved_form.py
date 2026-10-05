from uuid import UUID

from app.schema_approval import ExpectedPayload


class FormDispatchCreate(ExpectedPayload):
    idempotency_key: UUID
