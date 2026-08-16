from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ProjectCapabilityProfile:
    targets: tuple[str, ...]
    capabilities: tuple[str, ...]
    external_gates: tuple[str, ...]
    technology_defaults: Mapping[str, str]


_TERM_MAP: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "mobile",
        (
            "mobile",
            "android",
            "ios",
            "iphone",
            "ipad",
            "موبايل",
            "هاتف",
            "اندرويد",
            "أندرويد",
            "ايفون",
            "آيفون",
        ),
    ),
    (
        "desktop",
        (
            "desktop",
            "windows app",
            "macos app",
            "linux app",
            "سطح المكتب",
            "ويندوز",
            "ماك",
        ),
    ),
    (
        "browser_extension",
        (
            "browser extension",
            "chrome extension",
            "firefox extension",
            "اضافة متصفح",
            "إضافة متصفح",
        ),
    ),
    (
        "bot",
        (
            "telegram bot",
            "discord bot",
            "whatsapp bot",
            "chat bot",
            "بوت",
            "تليجرام",
            "تيليجرام",
            "واتساب",
            "ديسكورد",
        ),
    ),
    (
        "ai",
        (
            "ai app",
            "artificial intelligence",
            "rag",
            "embedding",
            "llm",
            "agent",
            "ذكاء اصطناعي",
            "وكيل",
            "وكلاء",
        ),
    ),
    (
        "data",
        (
            "data pipeline",
            "analytics",
            "etl",
            "dashboard analytics",
            "تحليلات",
            "خط بيانات",
            "بيانات ضخمة",
        ),
    ),
    (
        "commerce",
        (
            "ecommerce",
            "e-commerce",
            "shop",
            "store",
            "checkout",
            "subscription",
            "متجر",
            "تجارة",
            "اشتراك",
            "اشتراكات",
        ),
    ),
    ("game", ("game", "2d game", "multiplayer game", "لعبة", "العاب", "ألعاب")),
    (
        "three_d",
        ("3d", "three.js", "webgl", "gltf", "glb", "ثلاثي الأبعاد", "ثلاثية الأبعاد"),
    ),
    (
        "iot",
        (
            "iot",
            "firmware",
            "embedded",
            "sensor",
            "microcontroller",
            "اردوينو",
            "أردوينو",
            "حساس",
            "متحكم",
        ),
    ),
    (
        "database",
        (
            "database",
            "postgres",
            "postgresql",
            "mysql",
            "mariadb",
            "sqlite",
            "قاعدة بيانات",
            "قواعد بيانات",
            "بوستجريس",
        ),
    ),
    (
        "infrastructure",
        (
            "terraform",
            "kubernetes",
            "docker",
            "cloud infrastructure",
            "aws",
            "azure",
            "gcp",
            "devops",
            "بنية تحتية",
            "سحابة",
            "كوبيرنيتس",
            "دوكر",
        ),
    ),
    (
        "smart_contract",
        (
            "smart contract",
            "solidity",
            "ethereum",
            "blockchain",
            "web3",
            "عقد ذكي",
            "بلوك تشين",
            "بلوكتشين",
            "ويب 3",
        ),
    ),
    (
        "serverless",
        (
            "serverless",
            "lambda function",
            "cloud function",
            "edge function",
            "وظيفة سحابية",
        ),
    ),
    (
        "library",
        (
            "software library",
            "sdk",
            "python package",
            "npm package",
            "مكتبة برمجية",
            "حزمة برمجية",
        ),
    ),
    (
        "xr",
        (
            "webxr",
            "virtual reality",
            "augmented reality",
            "vr app",
            "ar app",
            "واقع افتراضي",
            "واقع معزز",
        ),
    ),
    (
        "robotics",
        ("robotics", "robot", "ros2", "drone", "روبوت", "روبوتات", "طائرة بدون طيار"),
    ),
    (
        "media",
        (
            "video production",
            "audio production",
            "image production",
            "graphic design",
            "storyboard",
            "مونتاج",
            "إنتاج فيديو",
            "انتاج فيديو",
            "إنتاج صوت",
            "تصميم جرافيك",
        ),
    ),
    (
        "cli",
        ("cli", "command line", "automation", "script", "أتمتة", "سطر أوامر", "سكريبت"),
    ),
    (
        "auth",
        (
            "login",
            "sign in",
            "account",
            "accounts",
            "member",
            "members",
            "authentication",
            "تسجيل دخول",
            "حساب",
            "حسابات",
            "عضو",
            "أعضاء",
            "مسجلين",
        ),
    ),
    (
        "api",
        ("api", "backend", "rest", "graphql", "websocket", "خلفية", "واجهة برمجية"),
    ),
    (
        "web",
        (
            "website",
            "web app",
            "saas",
            "portal",
            "dashboard",
            "موقع",
            "ويب",
            "منصة",
            "لوحة",
        ),
    ),
)


def infer_project_profile(objective: str) -> ProjectCapabilityProfile:
    lowered = objective.casefold()
    detected: list[str] = []
    for target, terms in _TERM_MAP:
        if any(term.casefold() in lowered for term in terms):
            detected.append(target)
    if not detected:
        detected = ["web", "api"]
    if "commerce" in detected:
        for target in ("web", "api"):
            if target not in detected:
                detected.append(target)
    if "mobile" in detected and "api" not in detected:
        detected.append("api")
    if "desktop" in detected and "web" not in detected:
        detected.append("web")
    if "ai" in detected and "api" not in detected:
        detected.append("api")
    if "bot" in detected and "api" not in detected:
        detected.append("api")
    if "three_d" in detected and "web" not in detected:
        detected.append("web")
    if "game" in detected and "web" not in detected:
        detected.append("web")
    if "xr" in detected and "web" not in detected:
        detected.append("web")
    if "serverless" in detected and "api" not in detected:
        detected.append("api")
    if "database" in detected and "api" not in detected:
        detected.append("api")
    if "smart_contract" in detected and "web" not in detected:
        detected.append("web")
    if "domain" not in detected:
        detected.append("domain")
    if "cli" not in detected:
        detected.append("cli")

    capabilities = {
        "governed-build",
        "local-functional-preview",
        "secure-defaults",
        "deterministic-source",
        "rollback-archive",
        "structured-domain-blueprint",
    }
    gates: set[str] = set()
    if "mobile" in detected:
        capabilities.update({"android-source", "ios-source", "react-native"})
        gates.update({"mobile-store-signing", "apple-google-store-credentials"})
    if "desktop" in detected:
        capabilities.update({"desktop-shell", "tauri-capabilities"})
        gates.add("platform-code-signing")
    if "browser_extension" in detected:
        capabilities.update({"manifest-v3", "extension-csp"})
        gates.add("browser-store-publishing")
    if "bot" in detected:
        capabilities.update({"bot-webhook", "provider-adapters"})
        gates.add("messaging-provider-credential")
    if "ai" in detected:
        capabilities.update({"ai-provider-boundary", "rag-ready", "local-fallback"})
        gates.add("ai-provider-credential-when-cloud-mode-enabled")
    if "data" in detected:
        capabilities.update({"etl", "schema-validation", "analytics-output"})
    if "commerce" in detected:
        capabilities.update({"catalog", "cart", "order-domain", "payment-boundary"})
        gates.add("payment-provider-credential-for-live-charges")
    if "game" in detected:
        capabilities.update({"canvas-game-loop", "deterministic-state"})
    if "three_d" in detected:
        capabilities.update({"webgl-preview", "gltf-ready"})
        gates.add("3d-provider-or-approved-assets-for-generated-models")
    if "iot" in detected:
        capabilities.update({"firmware-source", "hardware-simulator"})
        gates.add("physical-hardware-validation")
    if "database" in detected:
        capabilities.update({"sql-schema", "migration-source", "relational-data-model"})
    if "infrastructure" in detected:
        capabilities.update(
            {"container-hardening", "iac-source", "least-privilege-runtime"}
        )
        gates.add("cloud-credential-and-apply-approval")
    if "smart_contract" in detected:
        capabilities.update(
            {"solidity-source", "contract-tests", "chain-deployment-boundary"}
        )
        gates.add("blockchain-wallet-rpc-and-deployment-approval")
    if "serverless" in detected:
        capabilities.update({"serverless-handler", "stateless-function-boundary"})
        gates.add("serverless-provider-deployment-credential")
    if "library" in detected:
        capabilities.update({"library-package", "typed-public-api"})
    if "xr" in detected:
        capabilities.update({"webxr-source", "xr-device-boundary"})
        gates.add("xr-device-validation")
    if "robotics" in detected:
        capabilities.update({"robotics-simulator", "ros2-adapter-source"})
        gates.add("robotics-hardware-and-runtime-validation")
    if "media" in detected:
        capabilities.update(
            {"editable-media-source", "storyboard", "production-manifest"}
        )
    if "domain" in detected:
        capabilities.update({"domain-model", "typed-entities", "governed-workflows"})
    if "auth" in detected:
        capabilities.update({"authentication", "password-hashing", "session-boundary"})
        if "api" not in detected:
            detected.append("api")
    if "api" in detected:
        capabilities.update({"rest-api", "health-endpoint", "structured-errors"})
    if "web" in detected:
        capabilities.update({"responsive-web", "pwa-ready", "csp"})
    capabilities.add("cli-operator")

    tech = {
        "web": "Next.js 16.2.11 / React 19.2.3 production target; dependency-free local preview",
        "api": "FastAPI 0.141.1 / Uvicorn 0.52.0 typed service target with OpenAPI-ready boundary",
        "mobile": "Expo SDK 57.0.9 / React Native 0.86.2 / React 19.2.3 source target",
        "desktop": "Tauri 2.11.5 / tauri-build 2.6.3 capability-scoped desktop target",
        "browser_extension": "Chrome/Chromium Manifest V3",
        "data": "Python typed pipeline with explicit schemas",
        "iot": "C firmware source plus Python simulator",
        "database": "PostgreSQL-first SQL schema and migrations",
        "infrastructure": "OCI container + Compose/IaC least-privilege baseline",
        "smart_contract": "Solidity 0.8.36 contract source with deployment disabled by default",
        "serverless": "Portable Python function handler",
        "library": "Typed Python package baseline",
        "xr": "WebXR progressive target with device validation gate",
        "robotics": "Deterministic simulator plus ROS 2 adapter boundary",
        "media": "Editable storyboard/SVG production package",
        "domain": "Typed domain model, SQL schema, roles and workflow evidence",
    }
    return ProjectCapabilityProfile(
        targets=tuple(dict.fromkeys(detected)),
        capabilities=tuple(sorted(capabilities)),
        external_gates=tuple(sorted(gates)),
        technology_defaults=tech,
    )


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return text[:48] or "aionex-project"


def augment_universal_project(
    base_files: Mapping[str, str],
    project: str,
    objective: str,
    spec: Mapping[str, Any],
    planning: Mapping[str, Any],
) -> dict[str, str]:
    profile = infer_project_profile(objective)
    domain = dict(spec["domain_blueprint"])
    files = dict(base_files)
    files["DOMAIN_BLUEPRINT.json"] = _json(domain)
    files["PROJECT_PROFILE.json"] = _json(
        {
            "schema_version": 1,
            "project": project,
            "application_type": "universal_application",
            "targets": profile.targets,
            "capabilities": profile.capabilities,
            "external_gates": profile.external_gates,
            "technology_defaults": dict(profile.technology_defaults),
            "planning_manifest_sha256": planning["manifest_sha256"],
            "production_claim": False,
            "domain_entities": len(domain.get("entities") or []),
            "domain_workflows": len(domain.get("workflows") or []),
        }
    )
    files["SECURITY.md"] = (
        """# Security boundary\n\n- Generated source contains no embedded production credential.\n- Local preview binds to loopback and performs no external provider call.\n- Live provider, store, signing, payment and hardware actions remain external gates.\n- Treat every generated target as untrusted until its own build/test/security pipeline passes.\n- Use least privilege, secret references, CSP, CSRF/session protections where applicable, and immutable release evidence.\n"""
    )
    files["README.md"] += (
        "\n## Universal targets\n\n"
        + "\n".join(f"- `{item}`" for item in profile.targets)
        + "\n\n## External activation gates\n\n"
        + (
            "\n".join(f"- {item}" for item in profile.external_gates)
            if profile.external_gates
            else "- none for the local governed preview"
        )
        + "\n"
    )

    slug = _slug(project)
    if "domain" in profile.targets:
        files.update(_domain_target(spec))
    if "web" in profile.targets:
        files.update(_web_target(slug, spec, domain))
    if "api" in profile.targets:
        files.update(_api_target(domain, auth_enabled="auth" in profile.targets))
    if "auth" in profile.targets:
        files.update(_auth_target())
    if "mobile" in profile.targets:
        files.update(_mobile_target(slug, spec, domain))
    if "desktop" in profile.targets:
        files.update(_desktop_target(slug, spec))
    if "browser_extension" in profile.targets:
        files.update(_extension_target(slug, spec))
    if "bot" in profile.targets:
        files.update(_bot_target())
    if "ai" in profile.targets:
        files.update(_ai_target())
    if "data" in profile.targets:
        files.update(_data_target())
    if "commerce" in profile.targets:
        files.update(_commerce_target())
    if "game" in profile.targets:
        files.update(_game_target())
    if "three_d" in profile.targets:
        files.update(_three_d_target())
    if "iot" in profile.targets:
        files.update(_iot_target())
    if "database" in profile.targets:
        files.update(_database_target(domain))
    if "infrastructure" in profile.targets:
        files.update(_infrastructure_target())
    if "smart_contract" in profile.targets:
        files.update(_smart_contract_target())
    if "serverless" in profile.targets:
        files.update(_serverless_target(domain))
    if "library" in profile.targets:
        files.update(_library_target(slug, domain))
    if "xr" in profile.targets:
        files.update(_xr_target())
    if "robotics" in profile.targets:
        files.update(_robotics_target())
    if "media" in profile.targets:
        files.update(_media_target(project, spec))
    files.update(_cli_target(slug))
    return files


def _domain_target(spec: Mapping[str, Any]) -> dict[str, str]:
    domain = dict(spec.get("domain_blueprint") or {})
    roles = list(domain.get("roles") or [])
    entities = list(domain.get("entities") or [])
    workflows = list(domain.get("workflows") or [])
    sql_types = {
        "string": "VARCHAR(255)",
        "text": "TEXT",
        "integer": "BIGINT",
        "number": "NUMERIC",
        "boolean": "BOOLEAN",
        "datetime": "TIMESTAMPTZ",
        "email": "VARCHAR(320)",
        "url": "TEXT",
    }
    python_types = {
        "string": "str",
        "text": "str",
        "integer": "int",
        "number": "float",
        "boolean": "bool",
        "datetime": "datetime",
        "email": "str",
        "url": "str",
    }
    sql_lines = ["BEGIN;"]
    py_lines = [
        "from __future__ import annotations",
        "",
        "from dataclasses import dataclass",
        "from datetime import datetime",
        "",
    ]
    for entity in entities:
        name = str(entity["name"])
        table = f"domain_{name}"
        columns = [
            '    "id" BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY',
        ]
        class_name = "".join(part.capitalize() for part in name.split("_"))
        py_lines.extend(["@dataclass(frozen=True, slots=True)", f"class {class_name}:"])
        fields = list(entity.get("fields") or [])
        for field in fields:
            field_name = str(field["name"])
            field_type = str(field["type"])
            required = bool(field["required"])
            sql_type = sql_types[field_type]
            columns.append(
                f'    "{field_name}" {sql_type}' + (" NOT NULL" if required else "")
            )
            annotation = python_types[field_type]
            if not required:
                annotation = f"{annotation} | None"
            py_lines.append(f"    {field_name}: {annotation}")
        columns.append(
            '    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP'
        )
        sql_lines.extend(
            [
                f'CREATE TABLE IF NOT EXISTS "{table}" (',
                ",\n".join(columns),
                ");",
                f'CREATE INDEX IF NOT EXISTS "ix_{table}_created_at" ON "{table}" ("created_at" DESC);',
            ]
        )
        if not fields:
            py_lines.append("    pass")
        py_lines.append("")
    sql_lines.append("COMMIT;")
    if not entities:
        py_lines.extend(
            [
                "@dataclass(frozen=True, slots=True)",
                "class ProjectState:",
                '    status: str = "planned"',
                "",
            ]
        )
    return {
        "targets/domain/schema.sql": "\n".join(sql_lines) + "\n",
        "targets/domain/models.py": "\n".join(py_lines),
        "targets/domain/roles.json": _json({"roles": roles}),
        "targets/domain/workflows.json": _json({"workflows": workflows}),
        "targets/domain/README.md": "# Domain target\n\nTyped entities, roles and workflows are generated only from the validated schema-v3 blueprint approved by the governed planning cycle.\n",
    }


def _web_target(
    slug: str, spec: Mapping[str, Any], domain: Mapping[str, Any]
) -> dict[str, str]:
    title_literal = json.dumps(str(spec["title"]), ensure_ascii=False)
    tagline_literal = json.dumps(str(spec["tagline"]), ensure_ascii=False)
    domain_literal = json.dumps(domain, ensure_ascii=False, separators=(",", ":"))
    page = (
        f"const title = {title_literal};\n"
        f"const tagline = {tagline_literal};\n"
        f"const domain = {domain_literal} as const;\n"
        "export default function Page() {\n"
        "  return <main><h1>{title}</h1><p>{tagline}</p>"
        "<section><h2>Domain</h2><ul>{domain.entities.map((entity)=><li key={entity.name}><strong>{entity.label}</strong> · {entity.fields.map((field)=>field.name).join(', ')}</li>)}</ul></section>"
        "<section><h2>Workflows</h2><ul>{domain.workflows.map((workflow)=><li key={workflow.name}><strong>{workflow.name}</strong> · {workflow.steps.join(' → ')}</li>)}</ul></section>"
        "</main>;\n"
        "}\n"
    )
    return {
        "targets/web-next/package.json": _json(
            {
                "name": f"{slug}-web",
                "private": True,
                "engines": {"node": ">=20.9.0"},
                "scripts": {
                    "dev": "next dev",
                    "build": "next build",
                    "start": "next start",
                    "lint": "eslint .",
                },
                "dependencies": {
                    "next": "16.2.11",
                    "react": "19.2.3",
                    "react-dom": "19.2.3",
                },
                "devDependencies": {
                    "typescript": "^5.9.0",
                    "@types/react": "^19.0.0",
                    "@types/node": "^24.0.0",
                    "eslint": "^9.0.0",
                    "eslint-config-next": "16.2.11",
                },
            }
        ),
        "targets/web-next/app/page.tsx": page,
        "targets/web-next/app/layout.tsx": 'import type { ReactNode } from "react";\nexport default function RootLayout({children}:{children:ReactNode}){return <html lang="en"><body>{children}</body></html>}\n',
        "targets/web-next/eslint.config.mjs": 'import { defineConfig } from "eslint/config";\nimport nextVitals from "eslint-config-next/core-web-vitals";\nexport default defineConfig([...nextVitals]);\n',
        "targets/web-next/tsconfig.json": _json(
            {
                "compilerOptions": {
                    "target": "ES2022",
                    "lib": ["dom", "dom.iterable", "esnext"],
                    "strict": True,
                    "noEmit": True,
                    "module": "esnext",
                    "moduleResolution": "bundler",
                    "jsx": "preserve",
                }
            }
        ),
    }


def _auth_service_source() -> str:
    return '''from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from pathlib import Path

DATABASE = Path(__file__).resolve().parent / "app.db"
SESSION_SECONDS = 12 * 60 * 60
USERNAME = re.compile(r"^[A-Za-z0-9_.-]{3,40}$")


def initialize_auth() -> None:
    with sqlite3.connect(DATABASE) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS ix_sessions_user_expiry ON sessions(user_id, expires_at);
            """
        )
        connection.commit()


def _derive(password: str, salt: bytes) -> bytes:
    if not 12 <= len(password) <= 128:
        raise ValueError("password must contain 12 to 128 characters")
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**15,
        r=8,
        p=1,
        maxmem=64 * 1024 * 1024,
        dklen=32,
    )


def register_user(username: str, password: str) -> dict[str, object]:
    normalized = username.strip()
    if not USERNAME.fullmatch(normalized):
        raise ValueError("username must contain 3 to 40 safe characters")
    salt = secrets.token_bytes(16)
    digest = _derive(password, salt).hex()
    try:
        with sqlite3.connect(DATABASE) as connection:
            cursor = connection.execute(
                "INSERT INTO users(username, password_hash, salt, created_at) VALUES(?,?,?,?)",
                (normalized, digest, salt.hex(), int(time.time())),
            )
            connection.commit()
            user_id = int(cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise ValueError("username already exists") from exc
    return {"id": user_id, "username": normalized}


def login_user(username: str, password: str) -> tuple[dict[str, object], str]:
    normalized = username.strip()
    with sqlite3.connect(DATABASE) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT id, username, password_hash, salt FROM users WHERE username=?",
            (normalized,),
        ).fetchone()
    salt = bytes.fromhex(str(row["salt"])) if row is not None else bytes(16)
    candidate = _derive(password, salt).hex()
    valid = row is not None and hmac.compare_digest(candidate, str(row["password_hash"]))
    if not valid:
        raise ValueError("invalid credentials")
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = int(time.time()) + SESSION_SECONDS
    with sqlite3.connect(DATABASE) as connection:
        connection.execute("DELETE FROM sessions WHERE expires_at<=?", (int(time.time()),))
        connection.execute(
            "INSERT INTO sessions(token_hash, user_id, expires_at) VALUES(?,?,?)",
            (token_hash, int(row["id"]), expires_at),
        )
        connection.commit()
    return {"id": int(row["id"]), "username": str(row["username"])}, token


def authenticate_token(token: str) -> dict[str, object]:
    if not 20 <= len(token) <= 256:
        raise ValueError("invalid session")
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with sqlite3.connect(DATABASE) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT users.id, users.username FROM sessions JOIN users ON users.id=sessions.user_id "
            "WHERE sessions.token_hash=? AND sessions.expires_at>?",
            (token_hash, int(time.time())),
        ).fetchone()
    if row is None:
        raise ValueError("invalid session")
    return {"id": int(row["id"]), "username": str(row["username"])}


def logout_token(token: str) -> None:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with sqlite3.connect(DATABASE) as connection:
        connection.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
        connection.commit()
'''


def _api_target(
    domain: Mapping[str, Any], *, auth_enabled: bool = False
) -> dict[str, str]:
    imports = "from fastapi import FastAPI, HTTPException"
    auth_models = ""
    auth_init = ""
    auth_routes = ""
    guard_parameter = ""
    guard_body = ""
    if auth_enabled:
        imports = "from fastapi import Depends, FastAPI, Header, HTTPException"
        auth_models = """\n\nclass Credentials(BaseModel):\n    username: str\n    password: str\n"""
        auth_init = "\ninitialize_auth()\n"
        auth_routes = """


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    return authorization[7:].strip()


def current_user(authorization: str | None = Header(default=None)) -> dict[str, object]:
    try:
        return authenticate_token(_bearer_token(authorization))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Authentication required") from exc


@app.post("/auth/register", status_code=201)
def register(credentials: Credentials) -> dict[str, object]:
    try:
        return register_user(credentials.username, credentials.password)
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=409 if "exists" in detail else 422, detail=detail) from exc


@app.post("/auth/login")
def login(credentials: Credentials) -> dict[str, object]:
    try:
        user, token = login_user(credentials.username, credentials.password)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid credentials") from exc
    return {"user": user, "access_token": token, "token_type": "bearer", "expires_in": SESSION_SECONDS}


@app.get("/me")
def me(user: dict[str, object] = Depends(current_user)) -> dict[str, object]:
    return user


@app.post("/auth/logout", status_code=204)
def logout(authorization: str | None = Header(default=None)) -> None:
    token = _bearer_token(authorization)
    try:
        authenticate_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Authentication required") from exc
    logout_token(token)
"""
        guard_parameter = ", user: dict[str, object] = Depends(current_user)"
        guard_body = "    del user\n"

    app = f"""from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

{imports}
from pydantic import BaseModel
"""
    if auth_enabled:
        app += """from security import (\n    SESSION_SECONDS,\n    authenticate_token,\n    initialize_auth,\n    login_user,\n    logout_token,\n    register_user,\n)\n"""
    app += """
ROOT = Path(__file__).resolve().parent
DOMAIN = json.loads((ROOT / "domain.json").read_text(encoding="utf-8"))
ENTITIES = {item["name"]: item for item in DOMAIN.get("entities", [])}
DATABASE = ROOT / "app.db"

app = FastAPI(title="AIONEX generated domain API", docs_url="/docs")


class ResourcePayload(BaseModel):
    data: dict[str, Any]
"""
    app += auth_models
    app += """

def _initialize() -> None:
    with sqlite3.connect(DATABASE) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS records ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, entity TEXT NOT NULL, "
            "payload TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        connection.execute("CREATE INDEX IF NOT EXISTS ix_records_entity ON records(entity, id)")
        connection.commit()


def _entity(name: str) -> dict[str, Any]:
    schema = ENTITIES.get(name)
    if schema is None:
        raise HTTPException(status_code=404, detail="Unknown domain resource")
    return schema


def _validate(name: str, values: dict[str, Any]) -> dict[str, Any]:
    schema = _entity(name)
    fields = {item["name"]: item for item in schema["fields"]}
    unknown = sorted(set(values) - set(fields))
    if unknown:
        raise HTTPException(status_code=422, detail={"unknown_fields": unknown})
    missing = sorted(
        item["name"]
        for item in schema["fields"]
        if item["required"] and item["name"] not in values
    )
    if missing:
        raise HTTPException(status_code=422, detail={"missing_fields": missing})
    for field_name, value in values.items():
        kind = fields[field_name]["type"]
        if kind in {"string", "text", "datetime", "email", "url"}:
            valid = isinstance(value, str)
        elif kind == "boolean":
            valid = isinstance(value, bool)
        elif kind == "integer":
            valid = isinstance(value, int) and not isinstance(value, bool)
        elif kind == "number":
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
        else:
            valid = False
        if not valid:
            raise HTTPException(
                status_code=422,
                detail={"invalid_field": field_name, "expected_type": kind},
            )
    return values


_initialize()
"""
    app += auth_init
    app += """

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/domain")
def domain() -> dict[str, Any]:
    return DOMAIN
"""
    app += auth_routes
    app += f"""

@app.post("/resources/{{entity_name}}", status_code=201)
def create_resource(entity_name: str, payload: ResourcePayload{guard_parameter}) -> dict[str, Any]:
{guard_body}    values = _validate(entity_name, payload.data)
    with sqlite3.connect(DATABASE) as connection:
        cursor = connection.execute(
            "INSERT INTO records(entity, payload) VALUES(?, ?)",
            (entity_name, json.dumps(values, ensure_ascii=False, separators=(",", ":"))),
        )
        connection.commit()
        record_id = int(cursor.lastrowid)
    return {{"id": record_id, "entity": entity_name, "data": values}}


@app.get("/resources/{{entity_name}}")
def list_resources(entity_name: str{guard_parameter}) -> dict[str, Any]:
{guard_body}    _entity(entity_name)
    with sqlite3.connect(DATABASE) as connection:
        rows = connection.execute(
            "SELECT id, payload, created_at FROM records WHERE entity=? ORDER BY id DESC LIMIT 200",
            (entity_name,),
        ).fetchall()
    return {{
        "items": [
            {{"id": row[0], "data": json.loads(row[1]), "created_at": row[2]}}
            for row in rows
        ]
    }}


@app.delete("/resources/{{entity_name}}/{{record_id}}")
def delete_resource(entity_name: str, record_id: int{guard_parameter}) -> dict[str, bool]:
{guard_body}    _entity(entity_name)
    with sqlite3.connect(DATABASE) as connection:
        cursor = connection.execute(
            "DELETE FROM records WHERE entity=? AND id=?", (entity_name, record_id)
        )
        connection.commit()
    if not cursor.rowcount:
        raise HTTPException(status_code=404, detail="Record not found")
    return {{"deleted": True}}
"""
    files = {
        "targets/api/app.py": app,
        "targets/api/domain.json": _json(domain),
        "targets/api/requirements.txt": "fastapi==0.141.1\nuvicorn[standard]==0.52.0\npydantic==2.13.4\n",
        "targets/api/README.md": "# API target\n\nDomain-driven FastAPI resource API with local SQLite persistence for the generated target. Run behind TLS; production database and secrets are supplied only by the deployment environment.\n",
    }
    if auth_enabled:
        files["targets/api/security.py"] = _auth_service_source()
    return files


def _auth_target() -> dict[str, str]:
    return {
        "targets/auth/service.py": _auth_service_source(),
        "targets/auth/README.md": "# Authentication target\n\nMemory-hard scrypt password hashing with salted hashes and hashed expiring session tokens. Identity federation, MFA, recovery and email verification are activated only through reviewed provider/configuration gates.\n",
    }


def _mobile_target(
    slug: str, spec: Mapping[str, Any], domain: Mapping[str, Any]
) -> dict[str, str]:
    title_literal = json.dumps(str(spec["title"]), ensure_ascii=False)
    tagline_literal = json.dumps(str(spec["tagline"]), ensure_ascii=False)
    entities_literal = json.dumps(
        [str(item["label"]) for item in domain.get("entities", [])], ensure_ascii=False
    )
    workflows_literal = json.dumps(
        [str(item["name"]) for item in domain.get("workflows", [])], ensure_ascii=False
    )
    screen = (
        'import { ScrollView, Text, StyleSheet } from "react-native";\n'
        f"const title = {title_literal};\n"
        f"const tagline = {tagline_literal};\n"
        f"const entities = {entities_literal};\n"
        f"const workflows = {workflows_literal};\n"
        "export default function Home(){return <ScrollView contentContainerStyle={styles.container}><Text style={styles.title}>{title}</Text><Text>{tagline}</Text><Text style={styles.heading}>Domain</Text>{entities.map((item)=><Text key={item}>• {item}</Text>)}<Text style={styles.heading}>Workflows</Text>{workflows.map((item)=><Text key={item}>• {item}</Text>)}</ScrollView>}\n"
        'const styles=StyleSheet.create({container:{flexGrow:1,justifyContent:"center",padding:24,gap:8},title:{fontSize:32,fontWeight:"700"},heading:{fontSize:20,fontWeight:"700",marginTop:16}});\n'
    )
    return {
        "targets/mobile-expo/package.json": _json(
            {
                "name": f"{slug}-mobile",
                "private": True,
                "main": "expo-router/entry",
                "engines": {"node": "^22.13.0 || ^24.3.0 || ^26.0.0 || >=27.0.0"},
                "scripts": {
                    "start": "expo start",
                    "android": "expo run:android",
                    "ios": "expo run:ios",
                    "check": "expo config --type public",
                },
                "dependencies": {
                    "expo": "~57.0.9",
                    "expo-constants": "~57.0.8",
                    "expo-linking": "~57.0.4",
                    "expo-router": "~57.0.9",
                    "expo-splash-screen": "~57.0.5",
                    "expo-status-bar": "~57.0.1",
                    "react": "19.2.3",
                    "react-native": "0.86.2",
                    "react-native-gesture-handler": "~2.32.0",
                    "react-native-reanimated": "4.5.1",
                    "react-native-safe-area-context": "~5.7.0",
                    "react-native-screens": "4.26.0",
                    "react-native-worklets": "0.10.1",
                },
                "devDependencies": {"@types/react": "~19.2.2", "typescript": "~6.0.3"},
            }
        ),
        "targets/mobile-expo/app.json": _json(
            {
                "expo": {
                    "name": str(spec["title"]),
                    "slug": slug,
                    "scheme": slug,
                    "plugins": ["expo-router"],
                    "ios": {"supportsTablet": True},
                    "android": {"adaptiveIcon": {"backgroundColor": "#050816"}},
                }
            }
        ),
        "targets/mobile-expo/app/_layout.tsx": 'import { Stack } from "expo-router";\nexport default function Layout(){return <Stack screenOptions={{headerShown:false}}/>}\n',
        "targets/mobile-expo/app/index.tsx": screen,
        "targets/mobile-expo/domain.json": _json(domain),
        "targets/mobile-expo/README.md": "# Mobile target\n\nExpo/React Native source for Android and iOS derived from the governed domain blueprint. Store signing and Apple/Google credentials are external release gates, not embedded in source.\n",
    }


def _desktop_target(slug: str, spec: Mapping[str, Any]) -> dict[str, str]:
    cargo = f"""[package]
name = "{slug.replace('-', '_')}"
version = "0.1.0"
edition = "2021"

[build-dependencies]
tauri-build = {{ version = "=2.6.3" }}

[dependencies]
tauri = {{ version = "=2.11.5" }}
"""
    return {
        "targets/desktop-tauri/src-tauri/Cargo.toml": cargo,
        "targets/desktop-tauri/src-tauri/build.rs": "fn main() { tauri_build::build(); }\n",
        "targets/desktop-tauri/src-tauri/src/main.rs": 'fn main() { tauri::Builder::default().run(tauri::generate_context!()).expect("tauri runtime error"); }\n',
        "targets/desktop-tauri/src-tauri/tauri.conf.json": _json(
            {
                "productName": str(spec["title"]),
                "version": "0.1.0",
                "identifier": f"net.vip-e.{slug}",
                "build": {"frontendDist": "../dist"},
                "app": {
                    "windows": [
                        {
                            "label": "main",
                            "title": str(spec["title"]),
                            "width": 1100,
                            "height": 760,
                        }
                    ],
                    "security": {"csp": "default-src 'self'; connect-src 'self'"},
                },
            }
        ),
        "targets/desktop-tauri/src-tauri/capabilities/default.json": _json(
            {
                "identifier": "default",
                "description": "Minimum application capability",
                "windows": ["main"],
                "permissions": ["core:default"],
            }
        ),
        "targets/desktop-tauri/dist/index.html": '<!doctype html><meta charset="utf-8"><title>AIONEX Desktop</title><main><h1>AIONEX Desktop Target</h1></main>\n',
        "targets/desktop-tauri/README.md": "# Desktop target\n\nTauri 2 source with explicit capability scoping and CSP. Platform signing remains a release gate.\n",
    }


def _extension_target(slug: str, spec: Mapping[str, Any]) -> dict[str, str]:
    return {
        "targets/browser-extension/manifest.json": _json(
            {
                "manifest_version": 3,
                "name": str(spec["title"]),
                "version": "0.1.0",
                "action": {"default_popup": "popup.html"},
                "permissions": ["storage"],
                "background": {"service_worker": "service-worker.js"},
                "content_security_policy": {
                    "extension_pages": "script-src 'self'; object-src 'self'"
                },
            }
        ),
        "targets/browser-extension/popup.html": '<!doctype html><meta charset="utf-8"><title>AIONEX extension</title><main><h1>AIONEX Extension</h1><p id="status">Ready</p></main><script src="popup.js"></script>\n',
        "targets/browser-extension/popup.js": '"use strict"; document.getElementById("status").textContent="Ready";\n',
        "targets/browser-extension/service-worker.js": '"use strict"; chrome.runtime.onInstalled.addListener(()=>{});\n',
    }


def _bot_target() -> dict[str, str]:
    return {
        "targets/bot/bot.py": """from __future__ import annotations\n\nimport os\n\ndef configured_provider() -> str:\n    return os.getenv("BOT_PROVIDER", "dry-run")\n\ndef handle_message(text: str) -> str:\n    clean = " ".join(text.split())[:2000]\n    return f"received:{clean}"\n\nif __name__ == "__main__":\n    print(f"provider={configured_provider()}")\n""",
        "targets/bot/README.md": "# Bot target\n\nDry-run by default. Telegram/Discord/WhatsApp credentials must be injected by the operator secret store before live transport is enabled.\n",
    }


def _ai_target() -> dict[str, str]:
    return {
        "targets/ai/service.py": """from __future__ import annotations\n\nfrom dataclasses import dataclass\n\n@dataclass(frozen=True)\nclass Document:\n    text: str\n\ndef retrieve(query: str, documents: list[Document], limit: int = 3) -> list[Document]:\n    terms = {item.casefold() for item in query.split() if item}\n    ranked = sorted(documents, key=lambda doc: -sum(term in doc.text.casefold() for term in terms))\n    return ranked[: max(1, min(limit, 10))]\n\ndef answer_local(query: str, documents: list[Document]) -> str:\n    hits = retrieve(query, documents)\n    return "\\n".join(doc.text for doc in hits) or "No local evidence."\n""",
        "targets/ai/README.md": "# AI target\n\nLocal retrieval works without a cloud key. Cloud generation must be routed through AIOS provider secrets; generated projects never embed provider keys.\n",
    }


def _data_target() -> dict[str, str]:
    return {
        "targets/data/pipeline.py": """from __future__ import annotations\n\nimport csv\nfrom pathlib import Path\n\ndef transform(source: Path, destination: Path) -> int:\n    with source.open(newline="", encoding="utf-8") as src, destination.open("w", newline="", encoding="utf-8") as dst:\n        reader = csv.DictReader(src)\n        fields = list(reader.fieldnames or [])\n        writer = csv.DictWriter(dst, fieldnames=fields)\n        writer.writeheader()\n        count = 0\n        for row in reader:\n            writer.writerow({key: (value or "").strip() for key, value in row.items()})\n            count += 1\n    return count\n""",
        "targets/data/README.md": "# Data target\n\nDeterministic CSV pipeline baseline; replace schemas only through reviewed migration and data-governance gates.\n",
    }


def _commerce_target() -> dict[str, str]:
    return {
        "targets/commerce/domain.py": """from __future__ import annotations\n\nfrom dataclasses import dataclass\nfrom decimal import Decimal\n\n@dataclass(frozen=True)\nclass Product:\n    sku: str\n    price: Decimal\n\ndef cart_total(items: list[tuple[Product, int]]) -> Decimal:\n    return sum((product.price * quantity for product, quantity in items), Decimal("0"))\n""",
        "targets/commerce/README.md": "# Commerce target\n\nCatalog/cart/order domain is local. Real charges remain disabled until a configured payment provider and owner-approved billing policy are supplied.\n",
    }


def _game_target() -> dict[str, str]:
    return {
        "targets/game/index.html": '<!doctype html><meta charset="utf-8"><canvas id="game" width="960" height="540"></canvas><script src="game.js"></script>\n',
        "targets/game/game.js": """"use strict"; const c=document.getElementById("game"),x=c.getContext("2d"); let t=0; function frame(){t+=1;x.clearRect(0,0,c.width,c.height);x.fillStyle="#22d3ee";x.fillRect((t%900)+10,250,40,40);requestAnimationFrame(frame)} requestAnimationFrame(frame);\n""",
    }


def _three_d_target() -> dict[str, str]:
    return {
        "targets/three-d/index.html": '<!doctype html><meta charset="utf-8"><canvas id="scene" width="960" height="540"></canvas><script src="scene.js"></script>\n',
        "targets/three-d/scene.js": """"use strict"; const gl=document.getElementById("scene").getContext("webgl2"); if(!gl) throw new Error("WebGL2 unavailable"); gl.clearColor(0.02,0.04,0.09,1); gl.clear(gl.COLOR_BUFFER_BIT);\n""",
        "targets/three-d/README.md": "# 3D target\n\nDependency-free WebGL2 preview. Approved GLB/glTF assets or configured 3D generation provider can be attached later through the governed 3D pipeline.\n",
    }


def _iot_target() -> dict[str, str]:
    return {
        "targets/iot/firmware/main.c": """#include <stdint.h>\n\nstatic uint16_t clamp_sensor(uint16_t value) { return value > 4095u ? 4095u : value; }\nint main(void) { volatile uint16_t sample = clamp_sensor(2048u); (void)sample; for (;;) { break; } return 0; }\n""",
        "targets/iot/simulator.py": """from __future__ import annotations\n\ndef clamp_sensor(value: int) -> int:\n    return max(0, min(int(value), 4095))\n\nif __name__ == "__main__":\n    assert clamp_sensor(5000) == 4095\n    print("simulation-ok")\n""",
        "targets/iot/README.md": "# IoT target\n\nFirmware source is paired with a simulator. Physical electrical/timing validation requires the actual target hardware and remains an external gate.\n",
    }


def _database_target(domain: Mapping[str, Any]) -> dict[str, str]:
    type_map = {
        "string": "VARCHAR(255)",
        "text": "TEXT",
        "integer": "BIGINT",
        "number": "NUMERIC",
        "boolean": "BOOLEAN",
        "datetime": "TIMESTAMPTZ",
        "email": "VARCHAR(320)",
        "url": "TEXT",
    }
    entities = list(domain.get("entities") or [])
    if not entities:
        entities = [
            {
                "name": "project_event",
                "label": "Project event",
                "fields": [{"name": "event_type", "type": "string", "required": True}],
            }
        ]
    statements = ["BEGIN;"]
    rollback = ["BEGIN;"]
    for entity in entities:
        columns = ["    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY"]
        for field in entity["fields"]:
            sql_type = type_map[str(field["type"])]
            required = " NOT NULL" if field["required"] else ""
            columns.append(f"    {field['name']} {sql_type}{required}")
        columns.append("    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP")
        statements.append(
            f"CREATE TABLE IF NOT EXISTS {entity['name']} (\n"
            + ",\n".join(columns)
            + "\n);"
        )
        statements.append(
            f"CREATE INDEX IF NOT EXISTS ix_{entity['name']}_created_at ON {entity['name']}(created_at DESC);"
        )
        rollback.insert(1, f"DROP TABLE IF EXISTS {entity['name']};")
    statements.append("COMMIT;")
    rollback.append("COMMIT;")
    return {
        "targets/database/migrations/001_initial.sql": "\n".join(statements) + "\n",
        "targets/database/migrations/001_rollback.sql": "\n".join(rollback) + "\n",
        "targets/database/domain.json": _json(domain),
        "targets/database/README.md": "# Database target\n\nPostgreSQL-first domain schema with explicit rollback migration. Production credentials are never embedded in migrations.\n",
    }


def _infrastructure_target() -> dict[str, str]:
    dockerfile = """FROM python:3.14.6-slim@sha256:7bec7ddcddeff7975d6ba9b4be7dd6f6b2f55e7491539145e2978f7f97ce9144
RUN groupadd --system app && useradd --system --gid app --home /app app
WORKDIR /app
COPY --chown=app:app . /app
USER app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["python", "targets/cli/main.py", "--health"]
"""
    compose = """services:
  app:
    build:
      context: ../..
      dockerfile: targets/infrastructure/Dockerfile
    read_only: true
    cap_drop: ["ALL"]
    security_opt: ["no-new-privileges:true"]
    tmpfs: ["/tmp:rw,noexec,nosuid,size=32m"]
    pids_limit: 128
    mem_limit: 512m
    cpus: "1.0"
"""
    return {
        "targets/infrastructure/Dockerfile": dockerfile,
        "targets/infrastructure/compose.yaml": compose,
        "targets/infrastructure/README.md": "# Infrastructure target\n\nLeast-privilege container baseline. Cloud/IaC apply remains disabled until credentials and an explicit deployment approval exist.\n",
    }


def _smart_contract_target() -> dict[str, str]:
    contract = """// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

contract ValueStore {
    uint256 private value;
    event ValueChanged(uint256 value);

    function setValue(uint256 newValue) external {
        value = newValue;
        emit ValueChanged(newValue);
    }

    function getValue() external view returns (uint256) {
        return value;
    }
}
"""
    return {
        "targets/smart-contract/contracts/ValueStore.sol": contract,
        "targets/smart-contract/README.md": "# Smart-contract target\n\nNon-custodial Solidity source baseline. Wallet, RPC, chain selection, audit and deployment approval remain explicit activation gates.\n",
    }


def _serverless_target(domain: Mapping[str, Any]) -> dict[str, str]:
    workflow_names = tuple(str(item["name"]) for item in domain.get("workflows", []))
    handler = f"""from __future__ import annotations

import json
from typing import Any

ALLOWED_WORKFLOWS = {workflow_names!r}

def handler(event: dict[str, Any], context: object | None = None) -> dict[str, Any]:
    del context
    event_type = str(event.get("type") or "unknown")[:80]
    known = event_type in ALLOWED_WORKFLOWS
    body = {{"ok": True, "event_type": event_type, "known_workflow": known}}
    return {{"statusCode": 200, "headers": {{"content-type": "application/json"}}, "body": json.dumps(body)}}
"""
    return {
        "targets/serverless/handler.py": handler,
        "targets/serverless/domain.json": _json(domain),
        "targets/serverless/README.md": "# Serverless target\n\nPortable stateless Python handler constrained to the governed workflow names. Cloud deployment credentials and provider-specific infrastructure remain activation gates.\n",
    }


def _library_target(slug: str, domain: Mapping[str, Any]) -> dict[str, str]:
    package = slug.replace("-", "_")
    entity_names = tuple(str(item["name"]) for item in domain.get("entities", []))
    workflow_names = tuple(str(item["name"]) for item in domain.get("workflows", []))
    pyproject = f"""[build-system]
requires = ["setuptools>=80"]
build-backend = "setuptools.build_meta"

[project]
name = "{slug}"
version = "0.1.0"
requires-python = ">=3.11"
"""
    module = f"""from __future__ import annotations

DOMAIN_ENTITIES = {entity_names!r}
DOMAIN_WORKFLOWS = {workflow_names!r}

def normalize(value: str) -> str:
    return " ".join(value.split())
"""
    return {
        "targets/library/pyproject.toml": pyproject,
        f"targets/library/src/{package}/__init__.py": module,
        "targets/library/domain.json": _json(domain),
        "targets/library/README.md": "# Library target\n\nTyped, dependency-light package baseline exposing the governed entity/workflow contract with no install lifecycle scripts.\n",
    }


def _xr_target() -> dict[str, str]:
    page = '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><button id="enter" type="button">Check XR</button><p id="status">Idle</p><script src="xr.js"></script>\n'
    script = '"use strict"; document.getElementById("enter").addEventListener("click",async()=>{const out=document.getElementById("status");if(!navigator.xr){out.textContent="WebXR unavailable on this device";return}out.textContent=await navigator.xr.isSessionSupported("immersive-vr")?"XR supported":"XR session unsupported"});\n'
    return {
        "targets/xr/index.html": page,
        "targets/xr/xr.js": script,
        "targets/xr/README.md": "# XR target\n\nProgressive WebXR source. Headset/device interaction is validated only on approved physical XR hardware.\n",
    }


def _robotics_target() -> dict[str, str]:
    simulator = """from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Pose:
    x: float = 0.0
    y: float = 0.0
    heading: float = 0.0


def step(pose: Pose, linear: float, angular: float, dt: float) -> Pose:
    if not 0.0 < dt <= 1.0:
        raise ValueError("dt must be within (0, 1]")
    return Pose(pose.x + linear * dt, pose.y, pose.heading + angular * dt)


if __name__ == "__main__":
    assert step(Pose(), 1.0, 0.1, 0.5).x == 0.5
    print("robotics-simulation-ok")
"""
    adapter = """from __future__ import annotations

# ROS 2 adapter boundary intentionally contains no autonomous actuator command.
def command_preview(linear: float, angular: float) -> dict[str, float]:
    return {"linear": max(-1.0, min(1.0, linear)), "angular": max(-1.0, min(1.0, angular))}
"""
    return {
        "targets/robotics/simulator.py": simulator,
        "targets/robotics/ros2_adapter.py": adapter,
        "targets/robotics/README.md": "# Robotics target\n\nDeterministic simulator and bounded ROS 2 adapter boundary. Physical actuator/hardware validation remains an explicit gate.\n",
    }


def _media_target(project: str, spec: Mapping[str, Any]) -> dict[str, str]:
    storyboard = {
        "schema_version": 1,
        "project": project,
        "title": str(spec["title"]),
        "format": "editable-storyboard",
        "scenes": [
            {"id": "opening", "purpose": "introduce", "duration_seconds": 4},
            {"id": "core", "purpose": "explain-value", "duration_seconds": 8},
            {"id": "close", "purpose": "call-to-action", "duration_seconds": 4},
        ],
    }
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900"><rect width="1600" height="900" fill="#050816"/><circle cx="800" cy="450" r="180" fill="#0ea5e9"/><circle cx="800" cy="450" r="105" fill="#050816"/></svg>\n'
    return {
        "targets/media/storyboard.json": _json(storyboard),
        "targets/media/keyframe.svg": svg,
        "targets/media/README.md": "# Media target\n\nEditable storyboard and vector keyframe package suitable for the governed Production Studio rendering/export stage.\n",
    }


def _cli_target(slug: str) -> dict[str, str]:
    return {
        "targets/cli/main.py": f"""from __future__ import annotations\n\nimport argparse\n\ndef main() -> int:\n    parser=argparse.ArgumentParser(prog="{slug}")\n    parser.add_argument("--health", action="store_true")\n    args=parser.parse_args()\n    if args.health: print("healthy")\n    return 0\n\nif __name__ == "__main__": raise SystemExit(main())\n"""
    }
