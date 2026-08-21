import { storyCreateMessage } from "../lib/story-create-errors";

storyCreateMessage("quota", {
  surface: "dashboard",
  childName: "Camille",
});
storyCreateMessage("quota", { surface: "regeneration" });

// @ts-expect-error Dashboard translations require a child name.
storyCreateMessage("quota", { surface: "dashboard" });
