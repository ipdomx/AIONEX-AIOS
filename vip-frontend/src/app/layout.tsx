// The localized and root redirect route groups each provide their own complete
// document. This pass-through layout lets Next.js compose the global 404 path
// without forcing a fixed language onto every localized <html> element.
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return children;
}
