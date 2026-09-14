import {
  CalendarDots,
  ListChecks,
  MagicWand,
  Brain,
  ClipboardText,
  ClockCounterClockwise,
  ShieldCheck,
  Gauge,
  SlidersHorizontal,
} from "@phosphor-icons/react";
import { NavLink, Outlet } from "react-router-dom";

const links = [
  { to: "/dashboard", label: "作战总览", icon: Gauge, group: "总览" },
  { to: "/applications", label: "投递台账", icon: ListChecks, group: "记录" },
  { to: "/smart-entry", label: "通知录入", icon: MagicWand, group: "记录" },
  { to: "/timeline", label: "时间线", icon: CalendarDots, group: "记录" },
  { to: "/intel", label: "面经情报", icon: Brain, group: "分析" },
  { to: "/planner", label: "备战计划", icon: ClipboardText, group: "分析" },
  { to: "/daily-briefings", label: "每日简报", icon: ClockCounterClockwise, group: "分析" },
  { to: "/settings", label: "模型配置", icon: SlidersHorizontal, group: "工作区" },
];

export function Layout() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true"><img src="/brand-mark.png" alt="" /></span>
          <div>
            <strong>求职作战台</strong>
            <span>校园招聘工作区</span>
          </div>
        </div>
        <nav className="main-nav" aria-label="主导航">
          {links.map(({ icon: Icon, group, ...link }, index) => (
            <div className="nav-group" key={link.to}>
              {(index === 0 || links[index - 1].group !== group) && <span className="nav-group-label">{group}</span>}
              <NavLink to={link.to}>
                <Icon size={20} weight="duotone" aria-hidden="true" />
                {link.label}
              </NavLink>
            </div>
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
            <span className="brand-mark" aria-hidden="true"><img src="/brand-mark.png" alt="" /></span>
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
