from uuid import UUID

import uuid_utils


def uuid7() -> UUID:
    return UUID(int=uuid_utils.uuid7().int)
