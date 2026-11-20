export type Theme = "light" | "dark";

const KEY = "hh.theme";

/** The saved theme, or the system preference. */
export function initialTheme(): Theme {
  const saved = localStorage.getItem(KEY);
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Apply a theme to the document (shadcn's `.dark` class) and remember it. */
export function applyTheme(theme: Theme, { save = true }: { save?: boolean } = {}): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
  document.documentElement.style.colorScheme = theme;
  if (save) localStorage.setItem(KEY, theme);
}
