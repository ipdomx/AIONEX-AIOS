export function isOwnerRole(role?: string | null): boolean {
  const normalized = role
    ?.trim()
    .toLowerCase()
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ");

  return normalized === "super owner";
}
