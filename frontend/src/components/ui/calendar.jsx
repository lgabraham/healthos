import "react-day-picker/style.css";
import { DayPicker } from "react-day-picker";
import { cn } from "@/lib/utils";

// Thin wrapper over react-day-picker. Dark theming lives in index.css under
// `.rdp-healthos` (react-day-picker exposes CSS variables we override there).
export function Calendar({ className, ...props }) {
  return <DayPicker className={cn("rdp-healthos", className)} {...props} />;
}
