"""Phase 36J complete governed course-package factory.

The factory is provider-neutral and offline-capable. A single validated request
materializes curriculum, lessons, exercises, assessments, answer keys, adaptive
paths, citations, six-locale learning pages, real local image/audio/video assets,
an interactive quiz, review metadata, analytics schema, and a deterministic ZIP.
No provider credential or network client is used.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import re
import struct
import subprocess
import wave
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol
from urllib.parse import urlsplit

SUPPORTED_COURSE_LOCALES = ("ar", "en", "fr", "de", "es", "tr")
COURSE_PACKAGE_SCHEMA = "36J.course-package.v1"


class CourseFactoryError(ValueError):
    """The requested course package violates a governed factory boundary."""


@dataclass(frozen=True, slots=True)
class CourseCitation:
    citation_id: str
    title: str
    uri: str
    author: str | None = None

    def validate(self) -> None:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{1,63}", self.citation_id):
            raise CourseFactoryError("citation id is invalid")
        if not self.title.strip():
            raise CourseFactoryError("citation title is required")
        parsed = urlsplit(self.uri.strip())
        if parsed.scheme not in {"https", "internal"}:
            raise CourseFactoryError("citation URI must use https:// or internal://")
        if parsed.scheme == "https" and not parsed.hostname:
            raise CourseFactoryError("HTTPS citation requires a host")
        if parsed.username or parsed.password or parsed.fragment:
            raise CourseFactoryError(
                "citation URI must not embed credentials or fragments"
            )


@dataclass(frozen=True, slots=True)
class CourseFactoryRequest:
    course_id: str
    title: str
    domain: str
    audience: str
    locales: tuple[str, ...] = SUPPORTED_COURSE_LOCALES
    module_count: int = 2
    lessons_per_module: int = 2
    passing_score: float = 80.0
    citations: tuple[CourseCitation, ...] = ()

    def validate(self) -> None:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{2,79}", self.course_id):
            raise CourseFactoryError("course_id must be a safe identifier")
        if not 3 <= len(self.title.strip()) <= 240:
            raise CourseFactoryError("course title must be 3..240 characters")
        if not 2 <= len(self.domain.strip()) <= 240:
            raise CourseFactoryError("course domain is required")
        if not 2 <= len(self.audience.strip()) <= 240:
            raise CourseFactoryError("course audience is required")
        if not 1 <= self.module_count <= 8 or not 1 <= self.lessons_per_module <= 8:
            raise CourseFactoryError(
                "course module/lesson counts are outside the allowed range"
            )
        if self.module_count * self.lessons_per_module > 32:
            raise CourseFactoryError("course package is limited to 32 lessons")
        if not 0 <= self.passing_score <= 100:
            raise CourseFactoryError("passing score must be between 0 and 100")
        if not self.locales:
            raise CourseFactoryError("at least one locale is required")
        if len(set(self.locales)) != len(self.locales):
            raise CourseFactoryError("course locales must be unique")
        if any(locale not in SUPPORTED_COURSE_LOCALES for locale in self.locales):
            raise CourseFactoryError("unsupported course locale")
        for citation in self.citations:
            citation.validate()


@dataclass(frozen=True, slots=True)
class CourseArtifact:
    path: str
    media_type: str
    bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class CoursePackageResult:
    course_id: str
    archive_path: Path
    archive_sha256: str
    archive_bytes: int
    manifest_sha256: str
    lesson_count: int
    locales: tuple[str, ...]
    artifacts: tuple[CourseArtifact, ...]

    def snapshot(self) -> dict[str, object]:
        return {
            "schema": COURSE_PACKAGE_SCHEMA,
            "course_id": self.course_id,
            "archive_name": self.archive_path.name,
            "archive_sha256": self.archive_sha256,
            "archive_bytes": self.archive_bytes,
            "manifest_sha256": self.manifest_sha256,
            "lesson_count": self.lesson_count,
            "locales": list(self.locales),
            "artifact_count": len(self.artifacts),
            "provider_requests": 0,
            "provider_spend_usd": 0.0,
        }


class CourseVideoRenderer(Protocol):
    def preflight(self) -> dict[str, object]:
        ...

    def render(self, destination: Path, *, lesson_index: int) -> None:
        ...


class LocalFFmpegCourseVideoRenderer:
    """Bounded FFmpeg 9 renderer with no input URL or network use."""

    def __init__(
        self, binary: str = "/opt/ffmpeg/bin/ffmpeg", *, target_version: str = "9.0"
    ) -> None:
        self.binary = binary
        self.target_version = target_version

    @staticmethod
    def _env() -> dict[str, str]:
        return {
            "PATH": "/opt/ffmpeg/bin:/usr/local/bin:/usr/bin:/bin",
            "HOME": "/tmp",
            "NO_COLOR": "1",
        }

    def preflight(self) -> dict[str, object]:
        try:
            result = subprocess.run(
                [self.binary, "-version"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
                env=self._env(),
            )
        except (
            OSError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ) as exc:
            raise CourseFactoryError("course video renderer preflight failed") from exc
        first = (result.stdout or "").splitlines()[0] if result.stdout else ""
        if not first.startswith(f"ffmpeg version {self.target_version}"):
            raise CourseFactoryError("course video renderer version mismatch")
        return {
            "engine": "ffmpeg",
            "version": self.target_version,
            "network_used": False,
        }

    def render(self, destination: Path, *, lesson_index: int) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        hue = (lesson_index * 47) % 255
        color = f"0x{hue:02x}{(120 + lesson_index * 17) % 255:02x}{(210 - lesson_index * 11) % 255:02x}"
        tone = 320 + lesson_index * 55
        command = [
            self.binary,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=640x360:r=24:d=1.5",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={tone}:sample_rate=48000:duration=1.5",
            "-shortest",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "25",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            str(destination),
        ]
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
                env=self._env(),
            )
        except (
            OSError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ) as exc:
            raise CourseFactoryError("course video rendering failed") from exc
        if not destination.is_file() or destination.stat().st_size < 1024:
            raise CourseFactoryError(
                "course video renderer produced no usable artifact"
            )


_I18N = {
    "en": {
        "course": "Course",
        "module": "Module",
        "lesson": "Lesson",
        "outcome": "Learning outcome",
        "theory": "Concept",
        "exercise": "Exercise",
        "quiz": "Knowledge check",
        "submit": "Check answer",
        "correct": "Correct",
        "retry": "Review and try again",
        "adaptive": "Adaptive path",
        "citations": "Citations",
    },
    "ar": {
        "course": "الدورة",
        "module": "الوحدة",
        "lesson": "الدرس",
        "outcome": "ناتج التعلم",
        "theory": "المفهوم",
        "exercise": "تمرين",
        "quiz": "اختبار المعرفة",
        "submit": "تحقق من الإجابة",
        "correct": "إجابة صحيحة",
        "retry": "راجع وحاول مرة أخرى",
        "adaptive": "المسار التكيفي",
        "citations": "المراجع",
    },
    "fr": {
        "course": "Cours",
        "module": "Module",
        "lesson": "Leçon",
        "outcome": "Objectif pédagogique",
        "theory": "Concept",
        "exercise": "Exercice",
        "quiz": "Vérification",
        "submit": "Vérifier",
        "correct": "Correct",
        "retry": "Réviser et réessayer",
        "adaptive": "Parcours adaptatif",
        "citations": "Sources",
    },
    "de": {
        "course": "Kurs",
        "module": "Modul",
        "lesson": "Lektion",
        "outcome": "Lernziel",
        "theory": "Konzept",
        "exercise": "Übung",
        "quiz": "Wissenscheck",
        "submit": "Antwort prüfen",
        "correct": "Richtig",
        "retry": "Überprüfen und erneut versuchen",
        "adaptive": "Adaptiver Pfad",
        "citations": "Quellen",
    },
    "es": {
        "course": "Curso",
        "module": "Módulo",
        "lesson": "Lección",
        "outcome": "Resultado de aprendizaje",
        "theory": "Concepto",
        "exercise": "Ejercicio",
        "quiz": "Comprobación",
        "submit": "Comprobar",
        "correct": "Correcto",
        "retry": "Revisar e intentar de nuevo",
        "adaptive": "Ruta adaptativa",
        "citations": "Fuentes",
    },
    "tr": {
        "course": "Kurs",
        "module": "Modül",
        "lesson": "Ders",
        "outcome": "Öğrenme çıktısı",
        "theory": "Kavram",
        "exercise": "Alıştırma",
        "quiz": "Bilgi kontrolü",
        "submit": "Yanıtı kontrol et",
        "correct": "Doğru",
        "retry": "Gözden geçirip yeniden dene",
        "adaptive": "Uyarlanabilir yol",
        "citations": "Kaynaklar",
    },
}

_LOCALIZED_CONTENT = {
    "en": {
        "outcome": "Apply {domain} principle {index} safely for {audience}.",
        "theory": "Practice {domain} through evidence, validation, iteration, and clear documentation.",
        "exercise": "Create an evidence-backed example for {domain} principle {index}.",
        "question": "Which choice best demonstrates the governed method?",
        "choices": ("Ignore evidence", "Apply the governed method", "Skip validation"),
        "adaptive_text": "0–59: review · 60–84: continue · 85–100: extension.",
    },
    "ar": {
        "outcome": "طبّق المبدأ {index} من {domain} بأمان بما يناسب {audience}.",
        "theory": "تدرّب على {domain} باستخدام الأدلة والتحقق والتكرار والتوثيق الواضح.",
        "exercise": "أنشئ مثالًا مدعومًا بالأدلة على المبدأ {index} من {domain}.",
        "question": "أي اختيار يطبق المنهج المحكوم بشكل أفضل؟",
        "choices": ("تجاهل الأدلة", "طبّق المنهج المحكوم", "تجاوز التحقق"),
        "adaptive_text": "0–59: مراجعة · 60–84: متابعة · 85–100: تحدٍ متقدم.",
    },
    "fr": {
        "outcome": "Appliquer en sécurité le principe {index} de {domain} pour {audience}.",
        "theory": "Pratiquer {domain} avec preuves, validation, itération et documentation claire.",
        "exercise": "Créer un exemple étayé par des preuves pour le principe {index} de {domain}.",
        "question": "Quel choix applique le mieux la méthode gouvernée ?",
        "choices": (
            "Ignorer les preuves",
            "Appliquer la méthode gouvernée",
            "Ignorer la validation",
        ),
        "adaptive_text": "0–59 : révision · 60–84 : continuer · 85–100 : extension.",
    },
    "de": {
        "outcome": "Prinzip {index} von {domain} sicher für {audience} anwenden.",
        "theory": "{domain} mit Evidenz, Validierung, Iteration und klarer Dokumentation üben.",
        "exercise": "Ein evidenzgestütztes Beispiel zu Prinzip {index} von {domain} erstellen.",
        "question": "Welche Wahl setzt die gesteuerte Methode am besten um?",
        "choices": (
            "Evidenz ignorieren",
            "Gesteuerte Methode anwenden",
            "Validierung überspringen",
        ),
        "adaptive_text": "0–59: wiederholen · 60–84: fortfahren · 85–100: Erweiterung.",
    },
    "es": {
        "outcome": "Aplicar de forma segura el principio {index} de {domain} para {audience}.",
        "theory": "Practicar {domain} con evidencia, validación, iteración y documentación clara.",
        "exercise": "Crear un ejemplo respaldado por evidencia para el principio {index} de {domain}.",
        "question": "¿Qué opción aplica mejor el método gobernado?",
        "choices": (
            "Ignorar la evidencia",
            "Aplicar el método gobernado",
            "Omitir la validación",
        ),
        "adaptive_text": "0–59: repasar · 60–84: continuar · 85–100: extensión.",
    },
    "tr": {
        "outcome": "{domain} ilke {index} için {audience} grubuna uygun güvenli uygulama yapın.",
        "theory": "{domain} alanını kanıt, doğrulama, yineleme ve açık belgeleme ile uygulayın.",
        "exercise": "{domain} ilke {index} için kanıta dayalı bir örnek oluşturun.",
        "question": "Hangi seçenek yönetilen yöntemi en iyi uygular?",
        "choices": ("Kanıtı yok say", "Yönetilen yöntemi uygula", "Doğrulamayı atla"),
        "adaptive_text": "0–59: gözden geçir · 60–84: devam et · 85–100: ileri görev.",
    },
}


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def _media_type(path: Path) -> str:
    return {
        ".html": "text/html",
        ".js": "text/javascript",
        ".css": "text/css",
        ".json": "application/json",
        ".svg": "image/svg+xml",
        ".wav": "audio/wav",
        ".mp4": "video/mp4",
        ".webmanifest": "application/manifest+json",
    }.get(path.suffix.lower(), "application/octet-stream")


def _safe_href(path: str) -> str:
    rel = PurePosixPath(path)
    if rel.is_absolute() or ".." in rel.parts:
        raise CourseFactoryError("course artifact path escaped package")
    return rel.as_posix()


def _correct_index(question: dict[str, object]) -> int:
    value = question.get("correct")
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise CourseFactoryError("course question answer key is invalid")
    return value


class CompleteCourseFactory:
    def __init__(self, video_renderer: CourseVideoRenderer) -> None:
        self.video_renderer = video_renderer

    def build(
        self, request: CourseFactoryRequest, destination: Path
    ) -> CoursePackageResult:
        request.validate()
        preflight = self.video_renderer.preflight()
        root = destination.resolve()
        root.mkdir(parents=True, exist_ok=True)
        if any(root.iterdir()):
            raise CourseFactoryError("course destination must be empty")
        lesson_count = request.module_count * request.lessons_per_module
        lesson_rows: list[dict[str, object]] = []
        answer_key: dict[str, dict[str, int]] = {}
        adaptive_paths: dict[str, dict[str, object]] = {}

        citations = request.citations or (
            CourseCitation(
                "internal-governance",
                "AIONEX governed course factory",
                "internal://aionex/phase36j",
            ),
        )
        for item in citations:
            item.validate()
        _write(
            root / "citations.json",
            json.dumps([asdict(c) for c in citations], ensure_ascii=False, indent=2),
        )

        lesson_index = 0
        for module_index in range(1, request.module_count + 1):
            for item_index in range(1, request.lessons_per_module + 1):
                lesson_index += 1
                key = f"m{module_index:02d}l{item_index:02d}"
                citation = citations[(lesson_index - 1) % len(citations)]
                outcome = f"Apply {request.domain} principle {lesson_index} safely in a scenario relevant to {request.audience}."
                questions = [
                    {
                        "prompt": f"Which choice best demonstrates principle {lesson_index}?",
                        "choices": [
                            "Ignore evidence",
                            "Apply the governed method",
                            "Skip validation",
                        ],
                        "correct": 1,
                    },
                    {
                        "prompt": "What should happen before accepting a result?",
                        "choices": [
                            "Verify evidence",
                            "Hide errors",
                            "Remove citations",
                        ],
                        "correct": 0,
                    },
                ]
                answer_key[key] = {
                    f"q{i+1}": _correct_index(q) for i, q in enumerate(questions)
                }
                adaptive_paths[key] = {
                    "remediation": {
                        "score_max": 59,
                        "next": key,
                        "action": "review-concept-and-repeat-exercise",
                    },
                    "standard": {
                        "score_min": 60,
                        "score_max": 84,
                        "next": "next-lesson",
                        "action": "continue",
                    },
                    "advanced": {
                        "score_min": 85,
                        "next": "next-lesson",
                        "action": "extension-challenge",
                    },
                }
                media_dir = root / "assets" / key
                self._render_svg(media_dir / "concept.svg", request, key, lesson_index)
                self._render_audio(media_dir / "narration.wav", lesson_index)
                self.video_renderer.render(
                    media_dir / "preview.mp4", lesson_index=lesson_index
                )
                lesson_rows.append(
                    {
                        "key": key,
                        "module": module_index,
                        "ordinal": lesson_index,
                        "outcome": outcome,
                        "exercise": f"Create a short evidence-backed example for {request.domain} principle {lesson_index}.",
                        "questions": [
                            {k: v for k, v in q.items() if k != "correct"}
                            for q in questions
                        ],
                        "citation_ids": [citation.citation_id],
                        "assets": [
                            f"assets/{key}/concept.svg",
                            f"assets/{key}/narration.wav",
                            f"assets/{key}/preview.mp4",
                        ],
                    }
                )
                for locale in request.locales:
                    self._render_lesson_page(
                        root, request, locale, lesson_rows[-1], questions, citation
                    )

        curriculum = {
            "schema": "36J.curriculum.v1",
            "course_id": request.course_id,
            "title": request.title,
            "domain": request.domain,
            "audience": request.audience,
            "passing_score": request.passing_score,
            "module_count": request.module_count,
            "lesson_count": lesson_count,
            "learning_outcomes": [row["outcome"] for row in lesson_rows],
            "lessons": lesson_rows,
        }
        _write(
            root / "curriculum.json",
            json.dumps(curriculum, ensure_ascii=False, indent=2),
        )
        _write(
            root / "_private" / "teacher" / "answer-key.json",
            json.dumps(answer_key, ensure_ascii=False, indent=2),
        )
        _write(
            root / "adaptive-paths.json",
            json.dumps(adaptive_paths, ensure_ascii=False, indent=2),
        )
        _write(
            root / "_private" / "teacher" / "review.json",
            json.dumps(
                {
                    "status": "review_pending",
                    "version": 1,
                    "required_checks": [
                        "curriculum",
                        "citations",
                        "answer-key",
                        "localization",
                        "media-assets",
                        "accessibility",
                    ],
                    "approved": False,
                    "reviewer": None,
                    "notes": None,
                },
                indent=2,
            ),
        )
        _write(
            root / "analytics" / "schema.json",
            json.dumps(
                {
                    "schema": "36J.course-analytics.v1",
                    "events": [
                        "lesson_started",
                        "lesson_completed",
                        "quiz_attempted",
                        "course_completed",
                    ],
                    "dimensions": ["course_id", "lesson_key", "locale"],
                    "metrics": [
                        "progress_percent",
                        "score",
                        "attempts",
                        "duration_seconds",
                    ],
                },
                indent=2,
            ),
        )
        _write(
            root / "mobile" / "manifest.webmanifest",
            json.dumps(
                {
                    "name": request.title,
                    "short_name": request.title[:48],
                    "start_url": "../en/index.html"
                    if "en" in request.locales
                    else f"../{request.locales[0]}/index.html",
                    "display": "standalone",
                    "background_color": "#0b1020",
                    "theme_color": "#2563eb",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        for locale in request.locales:
            self._render_course_index(root, request, locale, lesson_rows)
        default_locale = "en" if "en" in request.locales else request.locales[0]
        _write(
            root / "index.html",
            f'<!doctype html><meta charset="utf-8"><link rel="icon" href="data:,"><meta http-equiv="refresh" content="0; url={default_locale}/index.html"><a href="{default_locale}/index.html">Open course</a>',
        )
        _write(
            root / "README.txt",
            f"{request.title}\nOffline package generated by AIONEX Phase 36J.\nOpen index.html.\n",
        )

        artifacts = self._manifest_artifacts(root)
        manifest_payload = {
            "schema": COURSE_PACKAGE_SCHEMA,
            "course_id": request.course_id,
            "title": request.title,
            "locales": list(request.locales),
            "lesson_count": lesson_count,
            "review_status": "review_pending",
            "renderer": preflight,
            "artifacts": [asdict(item) for item in artifacts],
            "network_used": False,
            "provider_requests": 0,
            "provider_spend_usd": 0.0,
        }
        manifest_raw = json.dumps(
            manifest_payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
        _write(root / "manifest.json", manifest_raw)
        manifest_sha = hashlib.sha256(manifest_raw.encode("utf-8")).hexdigest()
        archive = root.parent / f"{request.course_id}-v1.zip"
        self._zip(root, archive)
        return CoursePackageResult(
            request.course_id,
            archive,
            _sha(archive),
            archive.stat().st_size,
            manifest_sha,
            lesson_count,
            request.locales,
            self._manifest_artifacts(root),
        )

    @staticmethod
    def _render_svg(
        path: Path, request: CourseFactoryRequest, key: str, index: int
    ) -> None:
        title = html.escape(request.domain)
        content = f"""<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540" role="img" aria-label="{title} concept {index}"><rect width="960" height="540" fill="#0b1020"/><circle cx="480" cy="250" r="130" fill="#2563eb"/><path d="M250 390h460" stroke="#67e8f9" stroke-width="14"/><text x="480" y="245" text-anchor="middle" fill="white" font-family="sans-serif" font-size="34">{title}</text><text x="480" y="295" text-anchor="middle" fill="#dbeafe" font-family="sans-serif" font-size="24">{key}</text></svg>"""
        _write(path, content)

    @staticmethod
    def _render_audio(path: Path, lesson_index: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        rate, duration, frequency = 16_000, 1.0, 360 + lesson_index * 35
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            frames = bytearray()
            for i in range(int(rate * duration)):
                sample = int(6000 * math.sin(2 * math.pi * frequency * i / rate))
                frames.extend(struct.pack("<h", sample))
            handle.writeframes(bytes(frames))

    @staticmethod
    def _render_course_index(
        root: Path,
        request: CourseFactoryRequest,
        locale: str,
        lessons: list[dict[str, object]],
    ) -> None:
        t = _I18N[locale]
        direction = "rtl" if locale == "ar" else "ltr"
        links = "".join(
            f'<li><a href="../lessons/{locale}/{row["key"]}/index.html">{t["lesson"]} {row["ordinal"]}</a></li>'
            for row in lessons
        )
        body = f"""<!doctype html><html lang="{locale}" dir="{direction}"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,"><title>{html.escape(request.title)}</title><style>body{{font:16px system-ui;max-width:920px;margin:auto;padding:24px;background:#0b1020;color:#eef2ff}}a{{color:#67e8f9}}li{{margin:.7rem}}</style><h1>{t["course"]}: {html.escape(request.title)}</h1><p>{html.escape(request.domain)} · {html.escape(request.audience)}</p><ol>{links}</ol><p><a href="../citations.json">{t["citations"]}</a></p></html>"""
        _write(root / locale / "index.html", body)

    @staticmethod
    def _render_lesson_page(
        root: Path,
        request: CourseFactoryRequest,
        locale: str,
        lesson: dict[str, object],
        questions: list[dict[str, object]],
        citation: CourseCitation,
    ) -> None:
        t = _I18N[locale]
        direction = "rtl" if locale == "ar" else "ltr"
        key = str(lesson["key"])
        localized = _LOCALIZED_CONTENT[locale]
        choices = localized["choices"]
        options = "".join(
            f'<label><input type="radio" name="q" value="{i}"> {html.escape(str(choice))}</label><br>'
            for i, choice in enumerate(choices)
        )
        localized_outcome = str(localized["outcome"]).format(
            domain=request.domain, audience=request.audience, index=lesson["ordinal"]
        )
        localized_theory = str(localized["theory"]).format(domain=request.domain)
        localized_exercise = str(localized["exercise"]).format(
            domain=request.domain, index=lesson["ordinal"]
        )
        script = f"""<script>window.__AIOS_COURSE__={{lesson:{json.dumps(key)},ready:true,attempts:0,score:null}};document.getElementById("check").onclick=()=>{{const v=document.querySelector('input[name=q]:checked');window.__AIOS_COURSE__.attempts++;if(!v)return;const ok=Number(v.value)==={_correct_index(questions[0])};window.__AIOS_COURSE__.score=ok?100:0;document.getElementById("result").textContent=ok?{json.dumps(t["correct"])}:{json.dumps(t["retry"])};}};</script>"""
        page = f"""<!doctype html><html lang="{locale}" dir="{direction}"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,"><title>{t["lesson"]} {lesson["ordinal"]}</title><style>body{{font:16px system-ui;max-width:900px;margin:auto;padding:24px}}img,video{{max-width:100%;height:auto}}label{{display:inline-block;margin:.35rem}}button{{padding:.7rem 1rem}}</style><a href="../../../{locale}/index.html">← {t["course"]}</a><h1>{t["lesson"]} {lesson["ordinal"]}: {html.escape(request.domain)}</h1><h2>{t["outcome"]}</h2><p>{html.escape(localized_outcome)}</p><h2>{t["theory"]}</h2><p>{html.escape(localized_theory)}</p><img src="../../../assets/{key}/concept.svg" alt="{html.escape(request.domain)} concept"><audio controls src="../../../assets/{key}/narration.wav"></audio><video controls muted playsinline src="../../../assets/{key}/preview.mp4"></video><h2>{t["exercise"]}</h2><p>{html.escape(localized_exercise)}</p><h2>{t["quiz"]}</h2><p>{html.escape(str(localized["question"]))}</p>{options}<button id="check">{t["submit"]}</button><output id="result" aria-live="polite"></output><h2>{t["adaptive"]}</h2><p>{html.escape(str(localized["adaptive_text"]))}</p><h2>{t["citations"]}</h2><p>[{html.escape(citation.citation_id)}] {html.escape(citation.title)}</p>{script}</html>"""
        _write(root / "lessons" / locale / key / "index.html", page)

    @staticmethod
    def _manifest_artifacts(root: Path) -> tuple[CourseArtifact, ...]:
        rows: list[CourseArtifact] = []
        for path in sorted(
            p
            for p in root.rglob("*")
            if p.is_file()
            and p.name != "manifest.json"
            and "_private" not in p.relative_to(root).parts
        ):
            rel = _safe_href(path.relative_to(root).as_posix())
            rows.append(
                CourseArtifact(rel, _media_type(path), path.stat().st_size, _sha(path))
            )
        return tuple(rows)

    @staticmethod
    def _zip(root: Path, destination: Path) -> None:
        if destination.exists():
            destination.unlink()
        with zipfile.ZipFile(
            destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for path in sorted(p for p in root.rglob("*") if p.is_file()):
                rel_path = path.relative_to(root)
                if "_private" in rel_path.parts:
                    continue
                rel = rel_path.as_posix()
                info = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, path.read_bytes())
