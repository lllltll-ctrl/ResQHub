"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// Нижня навігація для телефона (на десктопі прихована — там є верхнє меню).
const TABS = [
  { href: "/operations", icon: "dashboard", label: "Операційна" },
  { href: "/analytics", icon: "monitoring", label: "Аналітика" },
  { href: "/resident", icon: "volunteer_activism", label: "Жителю" },
];

export function MobileNav() {
  const path = usePathname();
  return (
    <nav className="md:hidden fixed bottom-0 left-0 w-full z-[70] h-14 bg-surface-container/95 backdrop-blur-xl border-t border-outline-variant/20 flex justify-around items-stretch">
      {TABS.map((t) => {
        const active = path === t.href || (path?.startsWith(t.href) ?? false);
        return (
          <Link
            key={t.href}
            href={t.href}
            className={`flex-1 flex flex-col items-center justify-center gap-0.5 text-[10px] font-medium transition-colors active:scale-95 ${
              active ? "text-primary" : "text-on-surface-variant"
            }`}
          >
            <i
              className="material-symbols-outlined text-[22px]"
              style={active ? { fontVariationSettings: "'FILL' 1" } : undefined}
            >
              {t.icon}
            </i>
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
