"use client";

import { useFormStatus } from "react-dom";
import { btn, type ButtonKind } from "@/lib/ui";

export default function SubmitButton({
  children,
  kind = "default",
  testid,
}: {
  children: React.ReactNode;
  kind?: ButtonKind;
  testid?: string;
}) {
  const { pending } = useFormStatus();
  return (
    <button type="submit" disabled={pending} data-testid={testid} className={btn(kind)}>
      {children}
    </button>
  );
}
