import { Brand } from "@/components/brand";

export function AuthShell({
  title,
  description,
  children,
  footer,
  locale
}: {
  title: string;
  description: string;
  children: React.ReactNode;
  footer: React.ReactNode;
  locale: string;
}) {
  return (
    <section className="relative min-h-[calc(100vh-5rem)] overflow-hidden py-14 sm:py-20">
      <div className="grid-surface pointer-events-none absolute inset-0 opacity-50" />
      <div className="pointer-events-none absolute start-1/2 top-0 -z-10 h-[32rem] w-[32rem] -translate-x-1/2 rounded-full bg-electric-500/10 blur-3xl" />
      <div className="page-shell relative">
        <div className="mx-auto max-w-2xl">
          <div className="text-center">
            <span className="inline-flex"><Brand locale={locale} compact /></span>
            <h1 className="mt-5 text-3xl font-black tracking-tight sm:text-4xl">{title}</h1>
            <p className="mx-auto mt-3 max-w-lg text-sm leading-7 text-white/50">{description}</p>
          </div>
          <div className="glass-panel mt-9 rounded-3xl p-5 shadow-panel sm:p-8">{children}</div>
          <div className="mt-6 text-center text-sm text-white/45">{footer}</div>
        </div>
      </div>
    </section>
  );
}
