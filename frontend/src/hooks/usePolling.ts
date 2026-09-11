import { useEffect, useRef } from "react";

interface UsePollingOptions {
  enabled: boolean;
  interval: number;
  maxAttempts: number;
  poll: () => Promise<void>;
  onError?: (reason: unknown) => void;
}

export function usePolling({ enabled, interval, maxAttempts, poll, onError }: UsePollingOptions) {
  const pollRef = useRef(poll);
  const onErrorRef = useRef(onError);

  useEffect(() => {
    pollRef.current = poll;
    onErrorRef.current = onError;
  }, [onError, poll]);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let timer: number | undefined;
    let attempts = 0;
    const run = async () => {
      if (cancelled || attempts >= maxAttempts) return;
      attempts += 1;
      try {
        await pollRef.current();
      } catch (reason) {
        if (!cancelled) onErrorRef.current?.(reason);
        return;
      }
      if (!cancelled) timer = window.setTimeout(run, interval);
    };

    void run();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [enabled, interval, maxAttempts]);
}
