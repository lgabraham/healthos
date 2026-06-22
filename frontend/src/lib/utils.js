import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

// shadcn's class-name helper: merge conditional clsx output, de-duping
// conflicting Tailwind classes (so a later `px-3` beats an earlier `px-4`).
export function cn(...inputs) {
  return twMerge(clsx(inputs));
}
