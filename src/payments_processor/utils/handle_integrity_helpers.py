from loguru import logger
from sqlalchemy.exc import IntegrityError

from payments_processor.errors import UnhandledIntegrityError
from payments_processor.utils.fk_detail_pattern import FK_DETAIL_PATTERN


class HandleIntegrityHelpers:
    @staticmethod
    def get_column(asyncpg_error: BaseException, integrity_error: IntegrityError) -> str:
        column = getattr(asyncpg_error, "column_name", None)
        if not isinstance(column, str):
            raise UnhandledIntegrityError from integrity_error
        return column

    @staticmethod
    def get_details(asyncpg_error: BaseException, integrity_error: IntegrityError) -> tuple[str, str, str]:
        detail = getattr(asyncpg_error, "detail", "")
        column = None
        failed_value = None
        referrer_table = None
        match = FK_DETAIL_PATTERN.search(detail)
        if match:
            try:
                column = match.group(1)
                failed_value = match.group(2)
                referrer_table = match.group(3)
            except (ValueError, TypeError):
                raise UnhandledIntegrityError from integrity_error
        if (
            (not isinstance(column, str))
            or (not isinstance(failed_value, str))
            or (not isinstance(referrer_table, str))
        ):
            logger.trace(f"condition breakdown: {type(column)}, {type(failed_value)}, {type(referrer_table)}")
            raise UnhandledIntegrityError from integrity_error
        return column, failed_value, referrer_table

    @staticmethod
    def get_constraint(asyncpg_error: BaseException, integrity_error: IntegrityError) -> str:
        constraint = getattr(asyncpg_error, "constraint_name", None)
        if not isinstance(constraint, str):
            raise UnhandledIntegrityError from integrity_error
        return constraint
