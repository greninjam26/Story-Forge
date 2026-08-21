type PollingOptions<T> = {
  load: () => Promise<T>;
  shouldContinue: (value: T) => boolean;
  onValue: (value: T) => void;
  onError: (error: unknown) => void;
  intervalMs?: number;
};

export function startPolling<T>({
  load,
  shouldContinue,
  onValue,
  onError,
  intervalMs = 2_000,
}: PollingOptions<T>): () => void {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;

  async function poll(): Promise<void> {
    try {
      const value = await load();
      if (stopped) return;
      onValue(value);
      if (shouldContinue(value)) {
        timer = setTimeout(() => void poll(), intervalMs);
      }
    } catch (error) {
      if (!stopped) onError(error);
    }
  }

  void poll();
  return () => {
    stopped = true;
    if (timer !== undefined) clearTimeout(timer);
  };
}
