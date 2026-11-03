export interface GridDay {
  iso: string;
  day: number | null;
  inMonth: boolean;
}

export interface MonthGrid {
  label: string;
  weeks: GridDay[][];
  first: string;
  last: string;
  prev: string;
  next: string;
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

function isoOf(date: Date): string {
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
}

/** Monday-first month grid on ISO date strings (~40 lines, no FullCalendar). */
export function monthGrid(month: string): MonthGrid {
  const [year, monthNumber] = month.split("-").map(Number);
  const first = new Date(Date.UTC(year, monthNumber - 1, 1));
  const daysInMonth = new Date(Date.UTC(year, monthNumber, 0)).getUTCDate();
  const startOffset = (first.getUTCDay() + 6) % 7; // Monday=0

  const weeks: GridDay[][] = [];
  const cursor = new Date(first);
  cursor.setUTCDate(1 - startOffset);
  const totalCells = startOffset + daysInMonth;
  const weekCount = Math.ceil(totalCells / 7);

  for (let w = 0; w < weekCount; w++) {
    const week: GridDay[] = [];
    for (let d = 0; d < 7; d++) {
      week.push({
        iso: isoOf(cursor),
        day: cursor.getUTCDate(),
        inMonth: cursor.getUTCMonth() === monthNumber - 1,
      });
      cursor.setUTCDate(cursor.getUTCDate() + 1);
    }
    weeks.push(week);
  }

  const prev = new Date(Date.UTC(year, monthNumber - 2, 1));
  const next = new Date(Date.UTC(year, monthNumber, 1));
  return {
    label: first.toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" }),
    weeks,
    first: isoOf(first),
    last: isoOf(new Date(Date.UTC(year, monthNumber - 1, daysInMonth))),
    prev: `${prev.getUTCFullYear()}-${pad(prev.getUTCMonth() + 1)}`,
    next: `${next.getUTCFullYear()}-${pad(next.getUTCMonth() + 1)}`,
  };
}

/** Today's date in a named IANA zone as YYYY-MM-DD. */
export function todayIso(timeZone: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

export function currentMonth(timeZone: string): string {
  return todayIso(timeZone).slice(0, 7);
}

/** "Nov 5, 14:30" for a thread's last-message ISO timestamp. */
export function formatWhen(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}
