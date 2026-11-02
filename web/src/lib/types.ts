// Client-safe type aliases (type-only imports are erased at build time).
import type { components } from "./api-schema";

export type MetaView = components["schemas"]["MetaView"];
export type TaskView = components["schemas"]["TaskView"];
export type TaskBoardView = components["schemas"]["TaskBoardView"];
export type SuggestionView = components["schemas"]["SuggestionView"];
export type ThreadView = components["schemas"]["ThreadView"];
export type ChatSessionView = components["schemas"]["ChatSessionView"];
export type ChatMessageView = components["schemas"]["ChatMessageView"];
export type ChatActionView = components["schemas"]["ChatActionView"];
export type TaskStatus = NonNullable<TaskView["status"]>;
