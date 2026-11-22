import '../../l10n/generated/app_localizations.dart';
import '../core/api/api_exception.dart';
import '../core/auth/auth_repository.dart';

/// A user-facing sentence for any failure, in the current language.
String describeError(AppLocalizations l, Object error) {
  if (error is OwnerConsoleOnlyException) return l.app_ownerConsoleOnly;
  if (error is ApiException) {
    return switch (error.failure) {
      ApiFailure.network => l.app_networkError,
      ApiFailure.rateLimited => l.auth_tooManyAttempts,
      ApiFailure.unauthorized => l.app_sessionExpired,
      _ => error.message,
    };
  }
  return l.app_networkError;
}

/// Sign-in failures name what actually went wrong (same mapping as the website, PR #1103).
String describeLoginError(AppLocalizations l, Object error) {
  if (error is ApiException) {
    return switch (error.failure) {
      ApiFailure.unauthorized => l.auth_invalidCredentials,
      ApiFailure.forbidden => l.auth_accountUnavailable,
      ApiFailure.rateLimited => l.auth_tooManyAttempts,
      ApiFailure.network => l.app_networkError,
      _ => l.auth_connectionError,
    };
  }
  if (error is OwnerConsoleOnlyException) return l.app_ownerConsoleOnly;
  return l.auth_connectionError;
}
