"use client";

import { useState } from "react";

/**
 * Wrap an async action with automatic error/loading state.
 * Returns `{ error, loading, run }` where `run` clears the error,
 * sets loading, executes the action, and catches errors.
 */
export function useAsyncAction() {
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function run<T>(action: () => Promise<T>): Promise<T | undefined> {
    setError("");
    setLoading(true);
    try {
      const result = await action();
      return result;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return undefined;
    } finally {
      setLoading(false);
    }
  }

  return { error, setError, loading, run };
}
