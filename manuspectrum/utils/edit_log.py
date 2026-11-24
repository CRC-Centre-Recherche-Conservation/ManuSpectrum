"""Author attribution for tiles saved or deleted without a user.

``Tile.save()`` and ``Tile.delete()`` called without a request or user write
their ``EditLog`` rows with an empty ``userid`` (Arches 8.2). ``attribute``
names the author on those rows afterwards, so the transaction queries that
match on ``userid`` find them.
"""


def user_fields(user):
    """``EditLog`` user columns for *user*: a null id and empty names when
    *user* is ``None``."""
    return {
        "userid": (
            str(user.id) if user is not None and getattr(user, "id", None) else None
        ),
        "user_username": getattr(user, "username", "") or "",
        "user_firstname": getattr(user, "first_name", "") or "",
        "user_lastname": getattr(user, "last_name", "") or "",
        "user_email": getattr(user, "email", "") or "",
    }


def attribute(transaction_id, tile_id, user, edittype=None):
    """Name *user* on the unattributed ``EditLog`` rows of one tile.

    Rows of *tile_id* under *transaction_id* whose ``userid`` is empty or null
    are updated, restricted to *edittype* (``"tile create"``, ``"tile delete"``…)
    when given. Returns the number of rows updated. Call it inside the
    transaction of the save or delete.
    """
    from arches.app.models.models import EditLog
    from django.db.models import Q

    rows = EditLog.objects.filter(
        Q(userid="") | Q(userid__isnull=True),
        transactionid=transaction_id,
        tileinstanceid=str(tile_id),
    )
    if edittype is not None:
        rows = rows.filter(edittype=edittype)
    return rows.update(**user_fields(user))
