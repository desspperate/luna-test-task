from sqlalchemy.exc import IntegrityError


def get_asyncpg_error(error: IntegrityError) -> BaseException | None:
    return error.orig.__cause__ if error.orig and error.orig.__cause__ else error.orig
