import Link from "next/link";

export function Navigation({ active }: { active: "pulse" | "repositories" | "settings" | "audits" }) {
  return (
    <aside className="rail">
      <Link className="mark" aria-label="OSS Maintainer home" href="/">
        M<span>/</span>
      </Link>
      <nav aria-label="Primary">
        <Link className={active === "pulse" ? "active" : ""} href="/">
          Pulse
        </Link>
        <Link className={active === "repositories" ? "active" : ""} href="/#repositories">
          Repositories
        </Link>
        <Link className={active === "audits" ? "active" : ""} href="/audits">
          Audits
        </Link>
        <Link className={active === "settings" ? "active" : ""} href="/settings">
          Settings
        </Link>
      </nav>
      <div className="railFoot">
        <i /> evidence · review · repair
      </div>
    </aside>
  );
}
