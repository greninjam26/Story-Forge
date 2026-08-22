import { api, getToken, setToken } from "./api";
import type { TokenResponse } from "./types";

type SetLocale = (locale: TokenResponse["locale"]) => void;

export function startAuthSession(
  session: TokenResponse,
  setLocale: SetLocale,
): void {
  setToken(session.access_token);
  setLocale(session.locale);
}

export async function changeAccountLocale(
  locale: TokenResponse["locale"],
  setLocale: SetLocale,
): Promise<boolean> {
  try {
    if (getToken()) {
      await api.updateLocale(locale);
    }
  } catch {
    return false;
  }
  setLocale(locale);
  return true;
}
