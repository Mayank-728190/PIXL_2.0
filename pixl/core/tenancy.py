from pixl.core.exceptions import ForbiddenError


async def require_owned_reference(db, model, reference_id, organization_id):
    if reference_id is None:
        return
    obj = await db.get(model, reference_id)
    if obj is None or obj.organization_id != organization_id:
        raise ForbiddenError(f"{model.__name__} does not belong to the target agency")
