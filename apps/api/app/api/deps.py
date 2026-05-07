"""FastAPI dependencies compartidas."""

from typing import Annotated
from uuid import UUID

from fastapi import Header, HTTPException, status


def get_current_tenant_id(
    x_tenant_id: Annotated[UUID | None, Header(alias="X-Tenant-Id")] = None,
) -> UUID:
    """Tenant del request.

    MVP: header `X-Tenant-Id` (manual / tests).
    Cuando se integre Clerk, leerá `tenant_id` del JWT validado.
    """
    if x_tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Tenant-Id header",
        )
    return x_tenant_id


CurrentTenantId = Annotated[UUID, "tenant_id resolved from auth context"]
