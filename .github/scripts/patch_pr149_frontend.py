from pathlib import Path

root = Path(__file__).resolve().parents[2]
service_path = root / 'web-dashboard/frontend/src/lib/auth-service.ts'
text = service_path.read_text()

text = text.replace(
    '  consent_version: string;\n  required_registration_data: string[];\n};\n',
    '  consent_version: string;\n'
    '  identity: {\n'
    '    minimum_age: number;\n'
    '    phone_verification_required: boolean;\n'
    '    device_signals_required: boolean;\n'
    '    one_account_per_network: boolean;\n'
    '    one_account_per_device: boolean;\n'
    '  };\n'
    '  required_registration_data: string[];\n'
    '};\n',
)

text = text.replace(
    '  referrer?: string;\n};\n\nexport type FreeRegistrationPayload = {\n'
    '  name: string;\n'
    '  email: string;\n'
    '  password: string;\n'
    '  country_code: string;\n',
    '  referrer?: string;\n'
    '  vendor?: string;\n'
    '  webdriver?: boolean;\n'
    '};\n\n'
    'export type FreeRegistrationPayload = {\n'
    '  username: string;\n'
    '  name: string;\n'
    '  email: string;\n'
    '  password: string;\n'
    '  birth_date: string;\n'
    '  country_code: string;\n'
    '  phone_number: string;\n'
    '  phone_verification_token: string;\n',
)

text = text.replace(
    '    save_data: connection?.saveData,\n'
    '    referrer: document.referrer || undefined,\n',
    '    save_data: connection?.saveData,\n'
    '    referrer: document.referrer || undefined,\n'
    '    vendor: navigator.vendor || undefined,\n'
    '    webdriver: navigator.webdriver,\n',
)

service_path.write_text(text)

path = root / 'web-dashboard/frontend/src/components/auth/AuthGate.tsx'
text = path.read_text()

text = text.replace(
    '  const [name, setName] = useState("");\n'
    '  const [registrationEmail, setRegistrationEmail] = useState("");\n',
    '  const [username, setUsername] = useState("");\n'
    '  const [name, setName] = useState("");\n'
    '  const [birthDate, setBirthDate] = useState("");\n'
    '  const [phoneNumber, setPhoneNumber] = useState("");\n'
    '  const [phoneVerificationToken, setPhoneVerificationToken] = useState("");\n'
    '  const [registrationEmail, setRegistrationEmail] = useState("");\n',
)

old_checks = '''    if (registrationPassword !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    if (registrationPassword.length < 12) {
      setError("Password must contain at least 12 characters.");
      return;
    }
    if (!/^[A-Za-z]{2}$/.test(countryCode.trim())) {
      setError("Enter your two-letter country code, such as AE or EG.");
      return;
    }
    if (!consentAccepted) {
      setError("Consent is required to create a free account.");
      return;
    }

    setSubmitting(true);
    try {
      await registerFree({
        name: name.trim(),
        email: registrationEmail.trim(),
        password: registrationPassword,
        country_code: countryCode.trim().toUpperCase(),
        consent_accepted: true,
        consent_version: policy.consent_version,
        telemetry: collectRegistrationTelemetry(),
      });
'''
new_checks = '''    if (!/^[A-Za-z0-9_.-]{3,32}$/.test(username.trim())) {
      setError("Username must contain 3-32 letters, numbers, dots, dashes, or underscores.");
      return;
    }
    if (!birthDate) {
      setError("Date of birth is required.");
      return;
    }
    const birth = new Date(`${birthDate}T00:00:00Z`);
    const today = new Date();
    let age = today.getUTCFullYear() - birth.getUTCFullYear();
    const beforeBirthday =
      today.getUTCMonth() < birth.getUTCMonth() ||
      (today.getUTCMonth() === birth.getUTCMonth() &&
        today.getUTCDate() < birth.getUTCDate());
    if (beforeBirthday) age -= 1;
    if (!Number.isFinite(age) || age < (policy.identity?.minimum_age ?? 18)) {
      setError(`You must be at least ${policy.identity?.minimum_age ?? 18} years old.`);
      return;
    }
    if (!/^\\+[1-9][0-9]{7,14}$/.test(phoneNumber.trim())) {
      setError("Enter a verified mobile number in international format, such as +971501234567.");
      return;
    }
    if (
      policy.identity?.phone_verification_required &&
      phoneVerificationToken.trim().length < 24
    ) {
      setError("Complete mobile-number verification before creating the account.");
      return;
    }
    if (registrationPassword !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    if (registrationPassword.length < 12) {
      setError("Password must contain at least 12 characters.");
      return;
    }
    if (!/^[A-Za-z]{2}$/.test(countryCode.trim())) {
      setError("Enter your two-letter country code, such as AE or EG.");
      return;
    }
    if (!consentAccepted) {
      setError("Consent is required to create a free account.");
      return;
    }

    const telemetry = collectRegistrationTelemetry();
    if (policy.identity?.device_signals_required && telemetry.cookie_enabled !== true) {
      setError("Required cookies must be enabled before registration.");
      return;
    }

    setSubmitting(true);
    try {
      await registerFree({
        username: username.trim().toLowerCase(),
        name: name.trim(),
        email: registrationEmail.trim(),
        password: registrationPassword,
        birth_date: birthDate,
        country_code: countryCode.trim().toUpperCase(),
        phone_number: phoneNumber.trim(),
        phone_verification_token: phoneVerificationToken.trim(),
        consent_accepted: true,
        consent_version: policy.consent_version,
        telemetry,
      });
'''
if old_checks not in text:
    raise SystemExit('registration checks block not found')
text = text.replace(old_checks, new_checks)

old_form_start = '''            <div className="grid gap-4 sm:grid-cols-2">
              <label className="space-y-2">
                <span className="text-sm text-white/70">Full name</span>
'''
new_form_start = '''            <div className="grid gap-4 sm:grid-cols-2">
              <label className="space-y-2">
                <span className="text-sm text-white/70">Username</span>
                <input
                  value={username}
                  onChange={(event) =>
                    setUsername(
                      event.target.value
                        .replace(/[^A-Za-z0-9_.-]/g, "")
                        .slice(0, 32),
                    )
                  }
                  autoComplete="username"
                  minLength={3}
                  maxLength={32}
                  required
                  className="w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-white outline-none focus:border-electric-400/60"
                />
              </label>
              <label className="space-y-2">
                <span className="text-sm text-white/70">Full name</span>
'''
if old_form_start not in text:
    raise SystemExit('form start not found')
text = text.replace(old_form_start, new_form_start)

marker = '''              <label className="space-y-2">
                <span className="text-sm text-white/70">Password</span>
'''
insert = '''              <label className="space-y-2">
                <span className="text-sm text-white/70">Date of birth</span>
                <input
                  type="date"
                  value={birthDate}
                  onChange={(event) => setBirthDate(event.target.value)}
                  autoComplete="bday"
                  required
                  className="w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-white outline-none focus:border-electric-400/60"
                />
              </label>
              <label className="space-y-2">
                <span className="text-sm text-white/70">Mobile number</span>
                <input
                  type="tel"
                  value={phoneNumber}
                  onChange={(event) =>
                    setPhoneNumber(
                      event.target.value.replace(/[^+0-9]/g, "").slice(0, 16),
                    )
                  }
                  placeholder="+971501234567"
                  autoComplete="tel"
                  required
                  className="w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-white outline-none focus:border-electric-400/60"
                />
              </label>
              <label className="space-y-2 sm:col-span-2">
                <span className="text-sm text-white/70">
                  Phone verification assertion
                </span>
                <input
                  value={phoneVerificationToken}
                  onChange={(event) => setPhoneVerificationToken(event.target.value)}
                  autoComplete="one-time-code"
                  minLength={24}
                  required={policy?.identity?.phone_verification_required ?? true}
                  placeholder="Issued after OTP and mobile-line verification"
                  className="w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3 font-mono text-xs text-white outline-none focus:border-electric-400/60"
                />
                <span className="block text-[11px] leading-5 text-white/35">
                  Registration fails closed until the configured phone-verification
                  provider confirms a real mobile line; virtual and VoIP numbers are
                  rejected.
                </span>
              </label>
              <label className="space-y-2">
                <span className="text-sm text-white/70">Password</span>
'''
if marker not in text:
    raise SystemExit('password marker not found')
text = text.replace(marker, insert, 1)

text = text.replace(
    '<Cookie className="h-4 w-4 text-electric-300" /> Required consent',
    '<Cookie className="h-4 w-4 text-electric-300" /> Required privacy and security consent',
)

text = text.replace(
    '                consent, AIONEX records my declared/detected country, IP address,\n'
    '                browser/user agent, language, timezone, screen and coarse device\n'
    '                capabilities, plus network-quality information when the browser\n'
    '                provides it. This supports security, abuse prevention, quotas, and\n'
    '                owner audit. No MAC address, Wi-Fi name, contacts, files, or precise\n'
    '                GPS location are collected by this form.\n',
    '                consent, AIONEX records my verified username, date of birth,\n'
    '                country, protected phone identity, IP address, browser/user agent,\n'
    '                language, timezone, screen and coarse device capabilities, plus\n'
    '                network-quality information when the browser provides it. This\n'
    '                supports identity verification, one-account controls, security,\n'
    '                quotas, and owner audit. No MAC address, Wi-Fi name, contacts,\n'
    '                files, or precise GPS location are collected by this web form.\n',
)

path.write_text(text)
print('patched frontend files')
