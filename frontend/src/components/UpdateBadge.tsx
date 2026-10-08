import { ArrowClockwise, DownloadSimple } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

type UpdateCheck = { currentVersion: string; latestVersion: string; updateAvailable: boolean; installerAvailable: boolean };
type UpdateProgress = {
  percent: number | null;
  receivedBytes: number;
  totalBytes: number;
  bytesPerSecond: number;
  source: "mirror" | "github";
};

declare global {
  interface Window {
    careerPilotUpdates?: {
      version: () => Promise<string>;
      check: () => Promise<UpdateCheck>;
      install: () => Promise<void>;
      onProgress: (listener: (progress: UpdateProgress) => void) => () => void;
    };
  }
}

type Phase = "idle" | "checking" | "latest" | "available" | "downloading" | "error";

function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatSpeed(bytesPerSecond: number) {
  if (bytesPerSecond < 1024 * 1024) return `${Math.round(bytesPerSecond / 1024)} KB/s`;
  return `${(bytesPerSecond / (1024 * 1024)).toFixed(1)} MB/s`;
}

export function UpdateBadge() {
  const bridge = window.careerPilotUpdates;
  const [version, setVersion] = useState("");
  const [latest, setLatest] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState<UpdateProgress | null>(null);
  const [hint, setHint] = useState("");

  useEffect(() => {
    if (!bridge) return;
    let active = true;
    // 启动后静默检查一次：查得到版本号就显示，有新版本才高亮，失败不打扰。
    void (async () => {
      try {
        const current = await bridge.version();
        if (active) setVersion(current);
      } catch { /* 取不到版本号就留空 */ }
      try {
        const result = await bridge.check();
        if (!active) return;
        setVersion(result.currentVersion);
        if (result.updateAvailable && result.installerAvailable) {
          setLatest(result.latestVersion);
          setPhase("available");
        }
      } catch { /* 静默：启动检查失败不提示 */ }
    })();
    return () => { active = false; };
  }, [bridge]);

  if (!bridge) return null;

  async function manualCheck() {
    setPhase("checking");
    setHint("");
    try {
      const result = await bridge!.check();
      setVersion(result.currentVersion);
      if (result.updateAvailable && result.installerAvailable) {
        setLatest(result.latestVersion);
        setPhase("available");
      } else if (result.updateAvailable) {
        setPhase("error");
        setHint(`发现新版本 v${result.latestVersion}，但 Release 中没有安装包。`);
      } else {
        setPhase("latest");
        setHint("已是最新版本。");
        setTimeout(() => setPhase("idle"), 4000);
      }
    } catch (reason) {
      setPhase("error");
      setHint(reason instanceof Error ? reason.message : "检查更新失败");
    }
  }

  async function download() {
    if (!window.confirm(`下载并安装 v${latest}？安装器启动后当前程序会关闭。`)) return;
    setPhase("downloading");
    setProgress(null);
    setHint("");
    const stop = bridge!.onProgress((value) => setProgress(value));
    try {
      await bridge!.install();
    } catch (reason) {
      setPhase("available");
      setHint(reason instanceof Error ? reason.message : "下载或启动安装器失败");
    } finally {
      stop();
    }
  }

  if (phase === "available") {
    return (
      <button type="button" className="update-badge attention" onClick={() => void download()} title={hint || `发现新版本 v${latest}`}>
        <DownloadSimple size={13} weight="bold" aria-hidden="true" />更新 v{latest}
      </button>
    );
  }
  if (phase === "downloading") {
    const source = progress?.source === "mirror" ? "镜像" : "GitHub";
    const transferred = progress ? formatBytes(progress.receivedBytes) : "等待连接";
    const total = progress?.totalBytes ? ` / ${formatBytes(progress.totalBytes)}` : "";
    const details = progress
      ? `${source} · ${transferred}${total} · ${formatSpeed(progress.bytesPerSecond)}`
      : "正在连接下载源。";
    const status = !progress || progress.receivedBytes === 0
      ? "连接中…"
      : progress.percent === 0
        ? "<1%"
        : `${progress.percent ?? "…"}%`;
    return (
      <span className="update-badge downloading" role="status" title={details} aria-label={`正在下载，${details}`}>
        下载中 {status}
      </span>
    );
  }

  const label = phase === "checking" ? "检查中…" : phase === "latest" ? "已是最新" : phase === "error" ? "检查失败" : version ? `v${version}` : "检查更新";
  return (
    <button type="button" className="update-badge" onClick={() => void manualCheck()} disabled={phase === "checking"} title={hint || "点击检查更新"}>
      <ArrowClockwise size={12} weight="bold" aria-hidden="true" />{label}
    </button>
  );
}
