import Image from "next/image";
import Link from "next/link";

type BrandProps = {
  locale: string;
  compact?: boolean;
};

export function Brand({ locale, compact = false }: BrandProps) {
  return (
    <Link
      href={`/${locale}`}
      className="brand-lockup"
      aria-label="AIONEX AIOS"
    >
      <Image
        src="/brand/aionex-mark.svg"
        alt=""
        width={compact ? 36 : 42}
        height={compact ? 36 : 42}
        priority
      />
      <span className="brand-words">
        <strong>AIONEX</strong>
        <span>AIOS</span>
      </span>
    </Link>
  );
}
