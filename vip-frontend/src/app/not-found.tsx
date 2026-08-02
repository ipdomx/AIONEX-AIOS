import Link from "next/link";

export default function GlobalNotFound() {
  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-20">
      <div className="max-w-xl text-center">
        <p className="title-gradient text-7xl font-bold">404</p>
        <h1 className="mt-6 text-3xl font-semibold">Page not found</h1>
        <p className="mt-4 text-sm leading-7 text-white/50">
          The requested page does not exist in this AIONEX interface.
        </p>
        <Link
          href="/ar"
          className="mt-8 inline-flex h-12 items-center justify-center rounded-xl bg-white px-6 text-sm font-bold text-ink-950"
        >
          Return home
        </Link>
      </div>
    </main>
  );
}
