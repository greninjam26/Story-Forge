import { setToken } from "./api";
import type { TokenResponse } from "./types";

type SetLocale = (locale: TokenResponse["locale"]) => void;

export function startAuthSession(
  session: TokenResponse,
  setLocale: SetLocale,
): void {
  setToken(session.access_token);
  setLocale(session.locale);
}
