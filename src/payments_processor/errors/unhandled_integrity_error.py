from payments_processor.errors.payments_errors import PaymentsUnexpectedError


class UnhandledIntegrityError(PaymentsUnexpectedError):
    pass
