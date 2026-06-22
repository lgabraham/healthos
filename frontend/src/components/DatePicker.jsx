import { useState } from "react";
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover";
import { Calendar } from "@/components/ui/calendar";
import { Button } from "@/components/ui/button";

// A real calendar date picker for the Daily view — click the date to jump
// anywhere instead of arrowing one day at a time. `value`/`onChange` speak
// YYYY-MM-DD strings (what the rest of the app uses); `max` caps selection.
export default function DatePicker({ value, onChange, max }) {
  const [open, setOpen] = useState(false);
  const selected = value ? new Date(`${value}T00:00:00`) : undefined;
  const disabled = max ? { after: new Date(`${max}T00:00:00`) } : undefined;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="font-mono tabular-nums">
          📅 {value || "pick a date"}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start">
        <Calendar
          mode="single"
          selected={selected}
          defaultMonth={selected}
          disabled={disabled}
          onSelect={(d) => {
            if (d) {
              onChange(d.toLocaleDateString("en-CA"));
              setOpen(false);
            }
          }}
        />
      </PopoverContent>
    </Popover>
  );
}
