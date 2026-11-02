export function btn(kind: "default" | "primary" | "approve" | "deny" = "default"): string {
  const base = "rounded-md border px-3 py-1.5 text-sm font-medium transition disabled:opacity-50 disabled:cursor-not-allowed";
  switch (kind) {
    case "primary":
      return `${base} border-indigo-600 bg-indigo-600 text-white hover:bg-indigo-700`;
    case "approve":
      return `${base} border-green-700 bg-green-700 text-white hover:bg-green-800`;
    case "deny":
      return `${base} border-red-600 bg-red-600 text-white hover:bg-red-700`;
    default:
      return `${base} border-gray-400 bg-white text-gray-900 hover:bg-gray-100`;
  }
}

export function badge(status: string | null | undefined): string {
  const base = "inline-block rounded-full px-2 py-0.5 text-xs font-medium";
  switch (status) {
    case "open":
      return `${base} bg-indigo-100 text-indigo-800`;
    case "done":
      return `${base} bg-green-100 text-green-800`;
    case "cancelled":
      return `${base} bg-gray-200 text-gray-600`;
    case "review":
      return `${base} bg-amber-100 text-amber-800`;
    default:
      return `${base} bg-gray-100 text-gray-700`;
  }
}
