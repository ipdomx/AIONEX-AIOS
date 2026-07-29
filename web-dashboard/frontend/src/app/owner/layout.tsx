import SuperOwnerGuard from "@/components/auth/SuperOwnerGuard";

export default function OwnerLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <SuperOwnerGuard>{children}</SuperOwnerGuard>;
}
