import { Link } from "@tanstack/react-router";
import { Moon, Search, Sun } from "lucide-react";
import { useEffect, useState } from "react";

import { CommandPalette } from "@/components/shell/command-palette";
import { Button } from "@/components/ui/button";
import { applyTheme, initialTheme, type Theme } from "@/lib/theme";

/** Top bar: brand, search (⌘K / Ctrl+K opens the palette) and the theme switch. */
export function TopBar() {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    applyTheme(next);
    setTheme(next);
  };

  return (
    <header className="bg-background flex h-12 items-center gap-3 border-b px-3">
      <Link to="/" className="font-semibold tracking-tight">
        homelab-harness
      </Link>
      <Button
        variant="outline"
        className="text-muted-foreground mx-auto w-full max-w-md justify-start"
        onClick={() => {
          setPaletteOpen(true);
        }}
      >
        <Search aria-hidden="true" />
        <span>Search the lab…</span>
        <kbd className="bg-muted ml-auto rounded px-1.5 font-mono text-xs">⌘K</kbd>
      </Button>
      <Button
        variant="ghost"
        size="icon"
        aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
        onClick={toggleTheme}
      >
        {theme === "dark" ? <Sun /> : <Moon />}
      </Button>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </header>
  );
}
