class ProviderError(RuntimeError):
    pass


class ProviderUnavailable(ProviderError):
    pass


class ProviderPolicyDenied(ProviderError):
    pass


class NoEligibleProvider(ProviderError):
    pass


class BudgetExceeded(ProviderError):
    pass
