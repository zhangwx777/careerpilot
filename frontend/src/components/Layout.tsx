import {
  CalendarDots,
  Compass,
  ListChecks,
  MagicWand,
  Brain,
  ClipboardText,
  ClockCounterClockwise,
  ShieldCheck,
  Gauge,
} from "@phosphor-icons/react";
import { NavLink, Outlet } from "react-router-dom";

const links = [
  { to: "/dashboard", label: "作战总览", icon: Gauge },
  { to: "/applications", label: "投递台账", icon: ListChecks },
  { to: "/smart-entry", label: "通知录入", icon: MagicWand },
  { to: "/timeline", label: "时间线", icon: CalendarDots },
  { to: "/intel", label: "面经情报", icon: Brain },
  { to: "/planner", label: "备战计划", icon: ClipboardText },
  { to: "/daily-briefings", label: "每日简报", icon: ClockCounterClockwise },
];

export function Layout() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true"><Compass weight="duotone" /></span>
          <div>
            <strong>求职作战台</strong>
            <span>校园招聘工作区</span>
          </div>
        </div>
        <nav className="main-nav" aria-label="主导航">
          {links.map(({ icon: Icon, ...link }) => (
            <NavLink key={link.to} to={link.to}>
              <Icon size={20} weight="duotone" aria-hidden="true" />
              {link.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-note">
          <ShieldCheck size={20} weight="duotone" aria-hidden="true" />
          <div>
            <strong>数据留在本地</strong>
            <small>记录进展，决定权始终在你</small>
          </div>
        </div>
      </aside>
      <div className="workspace">
        <header className="mobile-header">
          <div className="brand compact">
            <span className="brand-mark" aria-hidden="true"><Compass weight="duotone" /></span>
            <strong>求职作战台</strong>
          </div>
          <nav aria-label="移动端导航">
            {links.map(({ icon: Icon, ...link }) => (
              <NavLink key={link.to} to={link.to}>
                <Icon size={18} weight="duotone" aria-hidden="true" />
                {link.label}
              </NavLink>
            ))}
          </nav>
        </header>
        <main className="page-container">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
