"use client";

import Link from "next/link";
import { useEffect } from "react";

export function LogoMark({ size = 22 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      aria-hidden="true"
    >
      <circle cx="5" cy="18" r="2.3" fill="currentColor" stroke="none" />
      <circle cx="12" cy="6" r="2.3" fill="currentColor" stroke="none" />
      <circle cx="19" cy="18" r="2.3" fill="currentColor" stroke="none" />
      <path d="M6.6 16.6 L10.6 7.6 M13.4 7.6 L17.4 16.6" />
    </svg>
  );
}

const LINKS = [
  { label: "Problem", href: "#problem" },
  { label: "Solution", href: "#solution" },
  { label: "Customers", href: "#customers" },
  { label: "Overview", href: "#overview" },
  { label: "FAQ", href: "#faq" },
];

export default function SiteNav() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") document.body.classList.remove("menu-open");
    };
    const onResize = () => {
      if (window.matchMedia("(min-width: 769px)").matches)
        document.body.classList.remove("menu-open");
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onResize);
    };
  }, []);

  return (
    <header className="site-nav">
      <div className="site-nav__inner">
        <Link href="/" className="brand" aria-label="CodeXRay home">
          <LogoMark />
          <span>
            code<span className="brand__suffix">xray</span>
          </span>
        </Link>
        <nav className="nav-links" aria-label="Primary">
          {LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              onClick={() => document.body.classList.remove("menu-open")}
            >
              {l.label}
            </Link>
          ))}
          <Link
            href="/dashboard"
            className="nav-cta"
            onClick={() => document.body.classList.remove("menu-open")}
          >
            Dashboard
          </Link>
        </nav>
        <button
          className="menu-toggle"
          type="button"
          aria-label="Open menu"
          aria-expanded={false}
          onClick={(e) => {
            const open = document.body.classList.toggle("menu-open");
            e.currentTarget.setAttribute("aria-expanded", String(open));
            e.currentTarget.setAttribute(
              "aria-label",
              open ? "Close menu" : "Open menu"
            );
          }}
        >
          &#9776;
        </button>
      </div>
    </header>
  );
}
