from pathlib import Path

root = Path(__file__).resolve().parents[2]
path = root / 'web-dashboard/backend/app/services/free_tier.py'
text = path.read_text()

text = text.replace(
    'import base64\nimport ipaddress\nimport secrets\nfrom datetime import UTC, datetime, timedelta\n',
    'import base64\nimport hashlib\nimport hmac\nimport ipaddress\nimport json\nimport os\nimport re\nimport secrets\nfrom datetime import UTC, date, datetime, timedelta\n',
)

text = text.replace(
    'REGISTRATION_TELEMETRY_DOMAIN = "registration-telemetry"\n',
    'REGISTRATION_TELEMETRY_DOMAIN = "registration-telemetry"\n'
    'FREE_USERNAME_IDENTITY_DOMAIN = "free-identity-username"\n'
    'FREE_PHONE_IDENTITY_DOMAIN = "free-identity-phone"\n'
    'FREE_NETWORK_IDENTITY_DOMAIN = "free-identity-network"\n'
    'FREE_DEVICE_IDENTITY_DOMAIN = "free-identity-device"\n',
)

text = text.replace(
    '    "registrations_per_ip_per_day": 3,\n'
    '    "telemetry_retention_days": 90,\n',
    '    "registrations_per_ip_per_day": 1,\n'
    '    "minimum_age": 18,\n'
    '    "require_phone_verification": True,\n'
    '    "require_device_signals": True,\n'
    '    "one_account_per_network": True,\n'
    '    "one_account_per_device": True,\n'
    '    "telemetry_retention_days": 90,\n',
)

text = text.replace(
    '    "referrer": 500,\n',
    '    "referrer": 500,\n'
    '    "vendor": 160,\n',
)

text = text.replace(
    '        "registrations_per_ip_per_day": int(\n'
    '            merged["registrations_per_ip_per_day"]\n'
    '        ),\n'
    '        "telemetry_retention_days": int(merged["telemetry_retention_days"]),\n',
    '        "registrations_per_ip_per_day": int(\n'
    '            merged["registrations_per_ip_per_day"]\n'
    '        ),\n'
    '        "minimum_age": int(merged["minimum_age"]),\n'
    '        "require_phone_verification": bool(\n'
    '            merged["require_phone_verification"]\n'
    '        ),\n'
    '        "require_device_signals": bool(merged["require_device_signals"]),\n'
    '        "one_account_per_network": bool(merged["one_account_per_network"]),\n'
    '        "one_account_per_device": bool(merged["one_account_per_device"]),\n'
    '        "telemetry_retention_days": int(merged["telemetry_retention_days"]),\n',
)

text = text.replace(
    '        "consent_version": policy["consent_version"],\n'
    '        "required_registration_data": [\n',
    '        "consent_version": policy["consent_version"],\n'
    '        "identity": {\n'
    '            "minimum_age": policy["minimum_age"],\n'
    '            "phone_verification_required": policy[\n'
    '                "require_phone_verification"\n'
    '            ],\n'
    '            "device_signals_required": policy["require_device_signals"],\n'
    '            "one_account_per_network": policy["one_account_per_network"],\n'
    '            "one_account_per_device": policy["one_account_per_device"],\n'
    '        },\n'
    '        "required_registration_data": [\n',
)

text = text.replace(
    '            "available network quality metadata",\n'
    '            "essential-cookie consent",\n',
    '            "available network quality metadata",\n'
    '            "verified mobile phone",\n'
    '            "date of birth and minimum-age validation",\n'
    '            "unique username",\n'
    '            "essential-cookie consent",\n',
)

text = text.replace(
    '    for key in ("cookie_enabled", "do_not_track", "save_data"):\n',
    '    for key in ("cookie_enabled", "do_not_track", "save_data", "webdriver"):\n',
)

insert_marker = '\n\nasync def _registration_rate_check(\n'
helpers = r'''

def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=422,
            detail="Invalid phone verification token",
        ) from exc


def verify_phone_verification_token(
    token: str,
    phone_number: str,
) -> dict[str, Any]:
    """Validate a signed assertion from the configured phone-verification service.

    The provider must sign ``base64url(JSON).base64url(HMAC-SHA256(payload))`` and
    attest that the number is a currently verified mobile line.  The application
    fails closed when no production secret is configured.
    """

    secret = os.getenv("AIOS_PHONE_VERIFICATION_SECRET", "").encode("utf-8")
    if len(secret) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Phone verification provider is not configured",
        )

    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        payload_bytes = _b64url_decode(encoded_payload)
        signature = _b64url_decode(encoded_signature)
        expected = hmac.new(
            secret,
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        payload = json.loads(payload_bytes)
        if not isinstance(payload, dict):
            raise TypeError("phone assertion payload must be an object")
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=422,
            detail="Invalid phone verification token",
        ) from exc

    expires_at = _as_utc(payload.get("expires_at"))
    line_type = str(payload.get("line_type") or "").strip().lower()
    blocked_types = {
        "voip",
        "virtual",
        "fixed_voip",
        "landline",
        "toll_free",
        "premium",
        "unknown",
    }
    if (
        payload.get("phone_number") != phone_number
        or payload.get("verified") is not True
        or line_type != "mobile"
        or line_type in blocked_types
        or expires_at is None
        or expires_at <= _now()
        or not str(payload.get("provider") or "").strip()
    ):
        raise HTTPException(
            status_code=422,
            detail="A currently verified real mobile number is required",
        )

    payload["line_type"] = line_type
    return payload


def _age_on(birth_date: date, today: date) -> int:
    return today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )


def _assert_real_device_signals(telemetry: dict[str, Any]) -> None:
    user_agent = str(telemetry.get("user_agent") or "").strip()
    platform = str(telemetry.get("platform") or "").strip()
    browser_automation = re.compile(
        r"headless|phantomjs|selenium|playwright|puppeteer|webdriver",
        re.IGNORECASE,
    )
    if (
        telemetry.get("cookie_enabled") is not True
        or telemetry.get("webdriver") is True
        or int(telemetry.get("hardware_concurrency") or 0) < 1
        or not user_agent
        or not platform
        or browser_automation.search(user_agent)
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Registration requires enabled cookies and supported real-device "
                "browser signals"
            ),
        )


def _identity_hmac(value: str) -> str:
    configured = os.getenv("AIOS_IDENTITY_HASH_SECRET") or os.getenv(
        "AIOS_PHONE_VERIFICATION_SECRET"
    )
    secret = (configured or settings.SECRET_KEY).encode("utf-8")
    if len(secret) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Identity protection secret is not configured",
        )
    return hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()


def _device_fingerprint(telemetry: dict[str, Any]) -> str:
    stable = {
        key: telemetry.get(key)
        for key in (
            "platform",
            "user_agent",
            "screen_width",
            "screen_height",
            "color_depth",
            "device_memory_gb",
            "hardware_concurrency",
            "max_touch_points",
            "timezone",
            "language",
        )
    }
    return _identity_hmac(json.dumps(stable, sort_keys=True, separators=(",", ":")))


async def _reserve_identity(
    session: AsyncSession,
    *,
    domain: str,
    resource_id: str,
    user_id: str,
    duplicate_detail: str,
) -> None:
    now = _now()
    reserved_id = await session.scalar(
        pg_insert(OwnerControlRecord)
        .values(
            id=uuid_str(),
            domain=domain,
            resource_id=resource_id,
            status="reserved",
            enabled=True,
            payload={"user_id": user_id},
            version=1,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_owner_control_domain_resource")
        .returning(OwnerControlRecord.id)
    )
    if reserved_id is None:
        raise HTTPException(status_code=409, detail=duplicate_detail)
'''
if insert_marker not in text:
    raise SystemExit('registration rate marker not found')
text = text.replace(insert_marker, helpers + insert_marker, 1)

old_sig = '''async def register_free_account(
    session: AsyncSession,
    request: Request,
    *,
    email: str,
    password: str,
    name: str,
    country_code: str,
    consent_accepted: bool,
    consent_version: str,
    telemetry: dict[str, Any] | None,
) -> User:
'''
new_sig = '''async def register_free_account(
    session: AsyncSession,
    request: Request,
    *,
    username: str,
    email: str,
    password: str,
    name: str,
    birth_date: date,
    country_code: str,
    phone_number: str,
    phone_verification_token: str,
    consent_accepted: bool,
    consent_version: str,
    telemetry: dict[str, Any] | None,
) -> User:
'''
if old_sig not in text:
    raise SystemExit('old register signature not found')
text = text.replace(old_sig, new_sig)

old_validation = '''    normalized_email = email.strip().lower()
    normalized_name = name.strip()
    normalized_country = country_code.strip().upper()
    if len(normalized_name) < 2:
        raise HTTPException(status_code=422, detail="Name is too short")
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters",
        )
    if policy["require_country"] and (
        len(normalized_country) != 2 or not normalized_country.isalpha()
    ):
        raise HTTPException(
            status_code=422,
            detail="A two-letter country code is required",
        )
    if await session.scalar(select(User.id).where(User.email == normalized_email)):
        raise HTTPException(status_code=409, detail="Email already registered")

    ip_address = client_ip_from_request(request)
    await _registration_rate_check(
        session,
        ip_address=ip_address,
        policy=policy,
    )
'''
new_validation = '''    normalized_username = username.strip().lower()
    normalized_email = email.strip().lower()
    normalized_name = name.strip()
    normalized_country = country_code.strip().upper()
    normalized_phone = phone_number.strip()

    if not re.fullmatch(r"[a-z0-9_.-]{3,32}", normalized_username):
        raise HTTPException(status_code=422, detail="Username is invalid")
    if len(normalized_name) < 2:
        raise HTTPException(status_code=422, detail="Name is too short")
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters",
        )
    if policy["require_country"] and (
        len(normalized_country) != 2 or not normalized_country.isalpha()
    ):
        raise HTTPException(
            status_code=422,
            detail="A two-letter country code is required",
        )
    if not re.fullmatch(r"\\+[1-9][0-9]{7,14}", normalized_phone):
        raise HTTPException(
            status_code=422,
            detail="A valid international mobile number is required",
        )
    if birth_date > _now().date() or _age_on(birth_date, _now().date()) < int(
        policy["minimum_age"]
    ):
        raise HTTPException(
            status_code=422,
            detail="Minimum registration age is not met",
        )

    phone_assertion = (
        verify_phone_verification_token(
            phone_verification_token,
            normalized_phone,
        )
        if policy["require_phone_verification"]
        else {"provider": "disabled", "line_type": "mobile", "verified": False}
    )
    sanitized = sanitize_registration_telemetry(telemetry)
    if policy["require_device_signals"]:
        _assert_real_device_signals(sanitized)

    if await session.scalar(select(User.id).where(User.email == normalized_email)):
        raise HTTPException(status_code=409, detail="Email already registered")

    ip_address = client_ip_from_request(request)
    if ip_address == "unknown":
        raise HTTPException(
            status_code=422,
            detail="A verifiable client network address is required",
        )
    await _registration_rate_check(
        session,
        ip_address=ip_address,
        policy=policy,
    )

    user_id = uuid_str()
    phone_hash = _identity_hmac(normalized_phone)
    network_hash = _identity_hmac(ip_address)
    device_hash = _device_fingerprint(sanitized)
    await _reserve_identity(
        session,
        domain=FREE_USERNAME_IDENTITY_DOMAIN,
        resource_id=normalized_username,
        user_id=user_id,
        duplicate_detail="Username already registered",
    )
    await _reserve_identity(
        session,
        domain=FREE_PHONE_IDENTITY_DOMAIN,
        resource_id=phone_hash,
        user_id=user_id,
        duplicate_detail="Phone number already registered",
    )
    if policy["one_account_per_network"]:
        await _reserve_identity(
            session,
            domain=FREE_NETWORK_IDENTITY_DOMAIN,
            resource_id=network_hash,
            user_id=user_id,
            duplicate_detail="A free account already exists on this network",
        )
    if policy["one_account_per_device"]:
        await _reserve_identity(
            session,
            domain=FREE_DEVICE_IDENTITY_DOMAIN,
            resource_id=device_hash,
            user_id=user_id,
            duplicate_detail="A free account already exists on this device",
        )
'''
if old_validation not in text:
    raise SystemExit('old validation block not found')
text = text.replace(old_validation, new_validation)

text = text.replace(
    '    user = User(\n'
    '        organization_id=organization.id,\n',
    '    user = User(\n'
    '        id=user_id,\n'
    '        organization_id=organization.id,\n',
    1,
)

text = text.replace(
    '    sanitized = sanitize_registration_telemetry(telemetry)\n'
    '    detected_country = _safe_text(\n',
    '    detected_country = _safe_text(\n',
    1,
)

old_payload = '''            payload={
                "declared_country": normalized_country,
                "detected_country": detected_country.upper()
                if detected_country
                else None,
                "ip_address": ip_address,
                "server_user_agent": _safe_text(
                    request.headers.get("user-agent"), 512
                ),
                "accept_language": _safe_text(
                    request.headers.get("accept-language"), 160
                ),
                "telemetry": sanitized,
                "consent": {
                    "accepted": True,
                    "version": consent_version,
                    "accepted_at": _iso(now),
                    "categories": ["essential", "security", "quota", "device"],
                },
            },
'''
new_payload = '''            payload={
                "username": normalized_username,
                "birth_date": birth_date.isoformat(),
                "declared_country": normalized_country,
                "detected_country": detected_country.upper()
                if detected_country
                else None,
                "phone_hash": phone_hash,
                "phone_masked": f"{normalized_phone[:3]}***{normalized_phone[-4:]}",
                "phone_verification": {
                    "verified": bool(phone_assertion.get("verified", True)),
                    "provider": str(phone_assertion.get("provider") or "unknown"),
                    "line_type": str(phone_assertion.get("line_type") or "unknown"),
                    "verified_at": str(
                        phone_assertion.get("verified_at") or _iso(now)
                    ),
                },
                "identity_status": "verified",
                "network_hash": network_hash,
                "device_hash": device_hash,
                "ip_address": ip_address,
                "server_user_agent": _safe_text(
                    request.headers.get("user-agent"), 512
                ),
                "accept_language": _safe_text(
                    request.headers.get("accept-language"), 160
                ),
                "telemetry": sanitized,
                "consent": {
                    "accepted": True,
                    "version": consent_version,
                    "accepted_at": _iso(now),
                    "categories": ["essential", "security", "quota", "device"],
                },
            },
'''
if old_payload not in text:
    raise SystemExit('old telemetry payload block not found')
text = text.replace(old_payload, new_payload)

text = text.replace(
    '            details={\n'
    '                "plan": FREE_PLAN_NAME,\n'
    '                "declared_country": normalized_country,\n'
    '                "consent_version": consent_version,\n'
    '            },\n',
    '            details={\n'
    '                "plan": FREE_PLAN_NAME,\n'
    '                "username": normalized_username,\n'
    '                "declared_country": normalized_country,\n'
    '                "phone_provider": phone_assertion.get("provider"),\n'
    '                "phone_line_type": phone_assertion.get("line_type"),\n'
    '                "identity_status": "verified",\n'
    '                "consent_version": consent_version,\n'
    '            },\n',
    1,
)

path.write_text(text)

owner_path = root / 'web-dashboard/backend/app/api/owner/free_tier.py'
owner = owner_path.read_text()
owner = owner.replace(
    '    registrations_per_ip_per_day: int | None = Field(default=None, ge=1, le=1000)\n'
    '    telemetry_retention_days: int | None = Field(default=None, ge=1, le=3650)\n',
    '    registrations_per_ip_per_day: int | None = Field(default=None, ge=1, le=1000)\n'
    '    minimum_age: int | None = Field(default=None, ge=13, le=100)\n'
    '    require_phone_verification: bool | None = None\n'
    '    require_device_signals: bool | None = None\n'
    '    one_account_per_network: bool | None = None\n'
    '    one_account_per_device: bool | None = None\n'
    '    telemetry_retention_days: int | None = Field(default=None, ge=1, le=3650)\n',
)
owner_path.write_text(owner)

print('patched backend files')
