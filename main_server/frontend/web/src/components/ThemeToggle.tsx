import { useEffect, useState } from "react";

const STORAGE_KEY = "lms.theme";

type ThemeChoice = "system" | "light" | "dark";

function applyTheme(choice: ThemeChoice) {
  const root = document.documentElement;
  if (choice === "system") {
    root.removeAttribute("data-theme");
    return;
  }
  root.setAttribute("data-theme", choice);
}

export function ThemeToggle() {
  const [choice, setChoice] = useState<ThemeChoice>(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved === "light" || saved === "dark" || saved === "system" ? saved : "system";
  });

  useEffect(() => {
    applyTheme(choice);
    localStorage.setItem(STORAGE_KEY, choice);
  }, [choice]);

  useEffect(() => {
    if (choice !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const sync = () => applyTheme("system");
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, [choice]);

  const cycle = () => {
    setChoice((c) => (c === "system" ? "light" : c === "light" ? "dark" : "system"));
  };

  const label = choice === "system" ? "시스템" : choice === "light" ? "라이트" : "다크";

  return (
    <button type="button" className="theme-toggle" onClick={cycle} title={`테마: ${label}`} aria-label={`테마 전환 (현재 ${label})`}>
      {choice === "dark" ? "🌙" : choice === "light" ? "☀" : "◐"}
    </button>
  );
}
