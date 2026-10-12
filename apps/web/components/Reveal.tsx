"use client";

import { useEffect, useRef, type ReactNode, type RefCallback } from "react";

export default function Reveal({
  children,
  as = "div",
  className = "",
}: {
  children: ReactNode;
  as?: "div" | "section" | "li";
  className?: string;
}) {
  const node = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const el = node.current;
    if (!el) return;
    if (
      window.matchMedia("(prefers-reduced-motion: reduce)").matches ||
      !("IntersectionObserver" in window)
    ) {
      el.classList.add("is-in");
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-in");
            io.unobserve(entry.target);
          }
        }
      },
      { threshold: 0.12 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  const setNode = (el: HTMLElement | null) => {
    node.current = el;
  };
  const cls = `reveal ${className}`;
  if (as === "li")
    return (
      <li ref={setNode as RefCallback<HTMLLIElement>} className={cls}>
        {children}
      </li>
    );
  if (as === "section")
    return (
      <section ref={setNode as RefCallback<HTMLElement>} className={cls}>
        {children}
      </section>
    );
  return (
    <div ref={setNode as RefCallback<HTMLDivElement>} className={cls}>
      {children}
    </div>
  );
}
