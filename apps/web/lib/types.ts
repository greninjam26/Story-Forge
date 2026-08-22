export type Parent = {
  id: string;
  email: string;
  locale: "en" | "fr";
  is_subscribed: boolean;
  free_stories_used: number;
  free_stories_limit: number;
  created_at: string;
};

export type Child = {
  id: string;
  parent_id: string;
  name: string;
  age: number;
  interests: string;
  language: "en" | "fr";
  created_at: string;
};

export type StoryPage = {
  id: string;
  page_number: number;
  text: string;
  image_url: string | null;
  audio_url: string | null;
};

export type StoryStatus =
  | "generating"
  | "pending_review"
  | "approved"
  | "rejected"
  | "generation_failed";

export type GenerationStage =
  | "story_text"
  | "moderation"
  | "illustrations"
  | "narration"
  | "complete";

export type StoryOut = {
  id: string;
  child_id: string;
  title: string;
  language: "en" | "fr";
  status: StoryStatus;
  failure_reason: string | null;
  cost_usd: number;
  created_at: string;
  approved_at: string | null;
  pages: StoryPage[];
  generation_stage: GenerationStage;
};

export type StoryDetail = StoryOut & {
  event_text: string;
  safety_reason: string | null;
};

export type ReaderStory = {
  id: string;
  child_id: string;
  title: string;
  language: "en" | "fr";
  created_at: string;
  pages: StoryPage[];
};

export type TokenResponse = {
  access_token: string;
  token_type: string;
  locale: "en" | "fr";
};
