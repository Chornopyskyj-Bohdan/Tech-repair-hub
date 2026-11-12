class DomainException(Exception):
    """Базовий клас для всіх винятків доменної області."""
    pass

class InvalidStateTransitionException(DomainException):
    """Виникає при спробі виконати недопустимий перехід стану."""
    pass

class InvalidMoneyAmountException(DomainException):
    """Виникає при недопустимій сумі грошей."""
    pass

class DiagnosticRequiredException(DomainException):
    """Виникає при спробі почати ремонт без діагностики."""
    pass