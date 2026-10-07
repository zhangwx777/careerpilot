import { useEffect, useRef } from "react";
import { requestScope } from "../requests";

export function useRequestScope(key: unknown) {
  const ref = useRef({ key, scope: requestScope() });
  if (ref.current.key !== key) {
    ref.current.scope.invalidate();
    ref.current.key = key;
  }
  useEffect(() => () => ref.current.scope.invalidate(), []);
  return ref.current.scope.capture;
}
