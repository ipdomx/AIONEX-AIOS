"use client";

import {
  Award,
  BookOpenCheck,
  GraduationCap,
  Loader2,
  Plus,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  phase29fApi,
  type AcademyCertification,
  type AcademyCourse,
  type AcademyEnrollment,
  type WorkforceMember,
} from "@/lib/phase29f-api";

const inputClass =
  "glass-input rounded-xl px-3 py-2.5 text-sm text-white outline-none disabled:cursor-not-allowed disabled:opacity-50";
const buttonClass =
  "inline-flex items-center justify-center gap-2 rounded-xl border border-electric-500/20 bg-electric-500/10 px-3 py-2 text-xs font-semibold text-electric-200 transition hover:bg-electric-500/15 disabled:cursor-not-allowed disabled:opacity-50";

export default function AcademyPage() {
  const [courses, setCourses] = useState<AcademyCourse[]>([]);
  const [members, setMembers] = useState<WorkforceMember[]>([]);
  const [enrollments, setEnrollments] = useState<AcademyEnrollment[]>([]);
  const [certifications, setCertifications] = useState<AcademyCertification[]>(
    [],
  );
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setMessage("");
    try {
      const [courseRows, memberRows, enrollmentRows, certificationRows] =
        await Promise.all([
          phase29fApi.listCourses(),
          phase29fApi.listWorkforceMembers({ limit: 200 }),
          phase29fApi.listEnrollments({ limit: 200 }),
          phase29fApi.listCertifications({ limit: 200 }),
        ]);
      setCourses(courseRows);
      setMembers(memberRows);
      setEnrollments(enrollmentRows);
      setCertifications(certificationRows);
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Academy records could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function createCourse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    setBusy("course-create");
    try {
      await phase29fApi.createCourse({
        code: String(values.get("code") || "").trim(),
        title: String(values.get("title") || "").trim(),
        description: String(values.get("description") || "").trim() || null,
        competencies: String(values.get("competencies") || "")
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        passing_score: Number(values.get("passing_score") || 80),
      });
      form.reset();
      setMessage("Course created with a versioned assessment contract.");
      await load();
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Course creation failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function enroll(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    setBusy("enroll");
    try {
      await phase29fApi.enroll(
        String(values.get("course_id") || ""),
        String(values.get("worker_id") || ""),
      );
      form.reset();
      setMessage("Workforce member enrolled and retained.");
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Enrollment failed.");
    } finally {
      setBusy(null);
    }
  }

  async function assess(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    const enrollmentId = String(values.get("enrollment_id") || "");
    setBusy(enrollmentId);
    try {
      const result = await phase29fApi.assessEnrollment(
        enrollmentId,
        Number(values.get("score") || 0),
      );
      setMessage(
        result.certification
          ? "Assessment passed and a durable certification was issued."
          : "Assessment retained; passing score was not reached.",
      );
      form.reset();
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Assessment failed.");
    } finally {
      setBusy(null);
    }
  }

  const memberName = (id: string) =>
    members.find((member) => member.id === id)?.name || id.slice(0, 8);
  const courseName = (id: string) =>
    courses.find((course) => course.id === id)?.title || id.slice(0, 8);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-purple-500/20 bg-purple-500/10 px-3 py-1 text-xs text-purple-300">
            <GraduationCap className="h-3.5 w-3.5" /> Governed Academy
          </div>
          <h1 className="mt-3 text-3xl font-bold text-white">
            Training, Tests & Certification
          </h1>
          <p className="mt-2 text-sm text-white/45">
            Create competency courses, enroll workforce members, retain
            attempts, and issue or revoke certifications.
          </p>
        </div>
        <button
          className={buttonClass}
          onClick={() => void load()}
          disabled={loading}
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />{" "}
          Refresh
        </button>
      </div>

      {message && (
        <div className="rounded-xl border border-electric-500/20 bg-electric-500/10 px-4 py-3 text-sm text-electric-200">
          {message}
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-3">
        <form onSubmit={createCourse} className="glass-card grid gap-3 p-5">
          <h2 className="font-semibold text-white">Create course</h2>
          <input
            name="code"
            minLength={2}
            required
            placeholder="Course code"
            className={inputClass}
          />
          <input
            name="title"
            minLength={2}
            required
            placeholder="Course title"
            className={inputClass}
          />
          <textarea
            name="description"
            placeholder="Course purpose"
            className={`${inputClass} min-h-20`}
          />
          <input
            name="competencies"
            placeholder="competencies,comma,separated"
            className={inputClass}
          />
          <input
            name="passing_score"
            type="number"
            min="0"
            max="100"
            defaultValue="80"
            className={inputClass}
          />
          <button className={buttonClass} disabled={busy === "course-create"}>
            <Plus className="h-4 w-4" /> Create course
          </button>
        </form>

        <form
          onSubmit={enroll}
          className="glass-card grid content-start gap-3 p-5"
        >
          <h2 className="font-semibold text-white">Enroll workforce member</h2>
          <select
            name="course_id"
            required
            defaultValue=""
            className={inputClass}
          >
            <option value="" disabled>
              Select course
            </option>
            {courses
              .filter((course) => course.status === "active")
              .map((course) => (
                <option key={course.id} value={course.id}>
                  {course.title}
                </option>
              ))}
          </select>
          <select
            name="worker_id"
            required
            defaultValue=""
            className={inputClass}
          >
            <option value="" disabled>
              Select workforce member
            </option>
            {members
              .filter((member) => member.status !== "retired")
              .map((member) => (
                <option key={member.id} value={member.id}>
                  {member.name} · {member.kind}
                </option>
              ))}
          </select>
          <button className={buttonClass} disabled={busy === "enroll"}>
            <BookOpenCheck className="h-4 w-4" /> Enroll
          </button>
        </form>

        <form
          onSubmit={assess}
          className="glass-card grid content-start gap-3 p-5"
        >
          <h2 className="font-semibold text-white">Record assessment</h2>
          <select
            name="enrollment_id"
            required
            defaultValue=""
            className={inputClass}
          >
            <option value="" disabled>
              Select enrollment
            </option>
            {enrollments
              .filter((item) => item.status !== "cancelled")
              .map((item) => (
                <option key={item.id} value={item.id}>
                  {memberName(item.worker_id)} · {courseName(item.course_id)} ·
                  attempt {item.attempts + 1}
                </option>
              ))}
          </select>
          <input
            name="score"
            type="number"
            min="0"
            max="100"
            required
            placeholder="Score"
            className={inputClass}
          />
          <button className={buttonClass}>
            <Award className="h-4 w-4" /> Assess
          </button>
        </form>
      </div>

      {loading ? (
        <div className="glass-card flex min-h-48 items-center justify-center text-white/45">
          <Loader2 className="me-2 h-5 w-5 animate-spin" />
          Loading academy…
        </div>
      ) : (
        <>
          <section className="glass-card p-5">
            <h2 className="font-semibold text-white">Course catalogue</h2>
            <div className="mt-4 grid gap-4 xl:grid-cols-2">
              {courses.length === 0 ? (
                <p className="text-sm text-white/35">
                  No courses are recorded.
                </p>
              ) : (
                courses.map((course) => (
                  <div
                    key={course.id}
                    className="rounded-xl border border-white/[0.06] bg-black/15 p-4"
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <h3 className="font-semibold text-white">
                          {course.title}
                        </h3>
                        <p className="mt-1 text-xs text-white/35">
                          {course.code} · pass {course.passing_score}% · v
                          {course.version}
                        </p>
                      </div>
                      <ShieldCheck className="h-5 w-5 text-purple-300" />
                    </div>
                    <p className="mt-3 text-sm text-white/50">
                      {course.description || "No description"}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {course.competencies.map((competency) => (
                        <span
                          key={competency}
                          className="rounded-full border border-white/[0.07] px-2 py-1 text-[10px] text-white/40"
                        >
                          {competency}
                        </span>
                      ))}
                    </div>
                  </div>
                ))
              )}
            </div>
          </section>

          <section className="glass-card p-5">
            <h2 className="font-semibold text-white">Enrollments</h2>
            <div className="mt-4 space-y-3">
              {enrollments.length === 0 ? (
                <p className="text-sm text-white/35">
                  No enrollments are recorded.
                </p>
              ) : (
                enrollments.map((item) => (
                  <div
                    key={item.id}
                    className="flex flex-col gap-2 rounded-xl border border-white/[0.06] bg-black/15 p-4 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div>
                      <p className="text-sm font-semibold text-white">
                        {memberName(item.worker_id)}
                      </p>
                      <p className="mt-1 text-xs text-white/35">
                        {courseName(item.course_id)} · {item.status} ·{" "}
                        {item.attempts} attempts
                      </p>
                    </div>
                    <span className="text-xs text-white/35">
                      {item.completed_at || item.created_at}
                    </span>
                  </div>
                ))
              )}
            </div>
          </section>

          <section className="glass-card p-5">
            <h2 className="font-semibold text-white">Certifications</h2>
            <div className="mt-4 grid gap-4 xl:grid-cols-2">
              {certifications.length === 0 ? (
                <p className="text-sm text-white/35">
                  No certifications have been issued.
                </p>
              ) : (
                certifications.map((certificate) => (
                  <div
                    key={certificate.id}
                    className="rounded-xl border border-green-500/15 bg-green-500/[0.04] p-4"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="font-semibold text-white">
                          {certificate.code}
                        </p>
                        <p className="mt-1 text-xs text-white/35">
                          {memberName(certificate.worker_id)} ·{" "}
                          {courseName(certificate.course_id)}
                        </p>
                        <p className="mt-2 text-xs text-white/35">
                          issued {certificate.issued_at}
                        </p>
                      </div>
                      <Award className="h-5 w-5 text-green-300" />
                    </div>
                  </div>
                ))
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
