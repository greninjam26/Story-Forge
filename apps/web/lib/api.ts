import type {
  Child,
  Parent,
  ReaderStory,
  StoryDetail,
  StoryOut,
  TokenResponse,
} from "./types";

export { ApiError, storyCreateFailure, storyCreateMessage } from "./story-create-errors";
import { ApiError } from "./story-create-errors";

// Default to same-origin "/api" (proxied to the backend by next.config.ts rewrites).
// Override with NEXT_PUBLIC_API_URL only for a direct cross-origin backend.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "/api";
const TOKEN_KEY = "storyforge-token";

let token: string | null = null;

export function getToken(): string | null {
  if (token) return token;
  if (typeof window === "undefined") return null;
  token = localStorage.getItem(TOKEN_KEY);
  return token;
}

export function setToken(value: string | null) {
  token = value;
  if (typeof window === "undefined") return;
  if (value) {
    localStorage.setItem(TOKEN_KEY, value);
  } else {
    localStorage.removeItem(TOKEN_KEY);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const storedToken = getToken();
  if (storedToken && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${storedToken}`);
  }
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = body.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((d) => d.msg ?? JSON.stringify(d)).join("; ")
          : `request failed: ${res.status}`;
    throw new ApiError(message, res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  // auth
  register: (email: string, password: string, locale: "en" | "fr") =>
    request<TokenResponse>("/auth/register/token", {
      method: "POST",
      body: JSON.stringify({ email, password, locale }),
    }),
  login: (email: string, password: string) =>
    request<TokenResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  me: () => request<Parent>("/auth/me"),
  deleteAccount: () => request<void>("/auth/me", { method: "DELETE" }),

  // children (scoped to the logged-in parent)
  createChild: (
    parentId: string,
    name: string,
    age: number,
    interests: string,
    language: "en" | "fr" = "en",
  ) =>
    request<Child>(`/parents/${parentId}/children`, {
      method: "POST",
      body: JSON.stringify({ name, age, interests, language }),
    }),
  listChildren: (parentId: string) =>
    request<Child[]>(`/parents/${parentId}/children`),
  getChild: (parentId: string, childId: string) =>
    request<Child>(`/parents/${parentId}/children/${childId}`),
  updateChild: (
    parentId: string,
    childId: string,
    patch: Partial<Pick<Child, "name" | "age" | "interests" | "language">>,
  ) =>
    request<Child>(`/parents/${parentId}/children/${childId}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  uploadReferencePhoto: (parentId: string, childId: string, photo: File) => {
    const body = new FormData();
    body.append("photo", photo);
    return request<void>(`/parents/${parentId}/children/${childId}/reference-photo`, {
      method: "PUT",
      body,
    });
  },
  deleteReferencePhoto: (parentId: string, childId: string) =>
    request<void>(`/parents/${parentId}/children/${childId}/reference-photo`, {
      method: "DELETE",
    }),
  deleteChild: (parentId: string, childId: string) =>
    request<void>(`/parents/${parentId}/children/${childId}`, {
      method: "DELETE",
    }),

  // stories
  createStory: (childId: string, eventText: string) =>
    request<StoryOut>("/stories", {
      method: "POST",
      body: JSON.stringify({ child_id: childId, event_text: eventText }),
    }),
  listStories: (childId: string) =>
    request<StoryOut[]>(`/stories/by-child/${childId}`),
  getStory: (storyId: string) => request<StoryDetail>(`/stories/${storyId}`),
  approveStory: (storyId: string, approve: boolean) =>
    request<StoryOut>(`/stories/${storyId}/approve`, {
      method: "PATCH",
      body: JSON.stringify({ approve }),
    }),
  regenerateStory: (storyId: string) =>
    request<StoryOut>(`/stories/${storyId}/regenerate`, { method: "POST" }),

  // reader (unauthenticated)
  listReaderStories: (childId: string) =>
    request<ReaderStory[]>(`/reader/children/${childId}/stories`),
  getReaderStory: (storyId: string) =>
    request<ReaderStory>(`/reader/stories/${storyId}`),

  // billing
  checkout: () =>
    request<{ checkout_url: string | null; stub: boolean; message?: string }>(
      "/billing/checkout",
      { method: "POST" },
    ),
  portal: () =>
    request<{ portal_url: string }>("/billing/portal", { method: "POST" }),
};

/** Unauthenticated reader API for child-facing pages. */
export const readerApi = {
  listStories: (childId: string) =>
    request<ReaderStory[]>(`/reader/children/${childId}/stories`),
  getStory: (storyId: string) =>
    request<ReaderStory>(`/reader/stories/${storyId}`),
};
