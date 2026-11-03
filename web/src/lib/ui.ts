export type ButtonKind = "default" | "primary" | "approve" | "deny" | "ghost" | "danger-ghost";

const KIND_CLASSES: Record<ButtonKind, string> = {
  default: "border-gray-300 bg-white text-gray-800 hover:bg-gray-50 hover:border-gray-400",
  primary:
    "border-indigo-600 bg-indigo-600 text-white shadow-sm shadow-indigo-600/20 hover:bg-indigo-700 hover:border-indigo-700",
  approve: "border-emerald-600 bg-emerald-600 text-white shadow-sm shadow-emerald-600/20 hover:bg-emerald-700",
  deny: "border-red-600 bg-red-600 text-white shadow-sm shadow-red-600/20 hover:bg-red-700",
  ghost: "border-transparent bg-transparent text-gray-600 hover:bg-gray-100 hover:text-gray-900",
  "danger-ghost": "border-transparent bg-transparent text-red-600 hover:bg-red-50",
};

export function btn(kind: ButtonKind = "default"): string {
  return `inline-flex items-center justify-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500 disabled:cursor-not-allowed disabled:opacity-45 ${KIND_CLASSES[kind]}`;
}

export function badge(status: string | null | undefined): string {
  const base = "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium";
  switch (status) {
    case "open":
      return `${base} bg-blue-50 text-blue-700`;
    case "done":
      return `${base} bg-emerald-50 text-emerald-700`;
    case "cancelled":
      return `${base} bg-gray-100 text-gray-500`;
    case "review":
      return `${base} bg-amber-100 text-amber-800`;
    case "offline":
      return `${base} bg-red-100 text-red-700`;
    default:
      return `${base} bg-gray-100 text-gray-700`;
  }
}

export function statusDot(status: string | null | undefined): string {
  switch (status) {
    case "open":
      return "bg-blue-500";
    case "done":
      return "bg-emerald-500";
    case "cancelled":
      return "bg-gray-400";
    default:
      return "bg-gray-300";
  }
}

export function input(): string {
  return "rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-900 placeholder:text-gray-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20";
}

export function card(): string {
  return "rounded-2xl border border-gray-200 bg-white shadow-sm";
}

export function avatarClasses(): string {
  return "flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-xs font-semibold text-indigo-700";
}

export function initialsOf(value: string | null | undefined): string {
  if (!value) return "·";
  const seed = value.split("@")[0];
  const parts = seed.split(/[.\-_+]/).filter(Boolean);
  return (parts.length >= 2 ? parts[0][0] + parts[1][0] : seed.slice(0, 2)).toUpperCase();
}
