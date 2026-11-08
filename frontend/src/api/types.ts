// Форма відповідей API — див. docs/ai/contracts.md.

export type PollStatus = 'draft' | 'active' | 'closed';

export interface PollOption {
  id: number;
  text: string;
  position: number;
}

export interface PollSummary {
  id: number;
  title: string;
  status: PollStatus;
  isPublic: boolean;
  creatorId: number;
  creatorUsername: string;
  optionsCount: number;
  startsAt: string | null;
  endsAt: string;
  createdAt: string;
}

export interface PollDetails extends Omit<PollSummary, 'optionsCount'> {
  description: string | null;
  allowVoteChange: boolean;
  options: PollOption[];
}

export interface Paged<T> {
  items: T[];
  page: number;
  pageSize: number;
  totalCount: number;
}

export interface OptionResult extends PollOption {
  votes: number;
  percentage: number;
}

export interface PollResults {
  pollId: number;
  title: string;
  status: PollStatus;
  totalVotes: number;
  generatedAt: string;
  options: OptionResult[];
}

export interface Vote {
  pollId: number;
  optionId: number;
  votedAt: string;
}

export interface User {
  id: number;
  username: string;
  email: string;
  createdAt: string;
}

export interface Token {
  accessToken: string;
  tokenType: string;
  expiresAt: string;
}

export interface CreatePollRequest {
  title: string;
  description?: string;
  options: string[];
  endsAt: string;
  startsAt?: string;
  isPublic: boolean;
  allowVoteChange: boolean;
}

/** Звідки прийшла відповідь: вузол за балансувальником і стан кешу результатів (X-Instance-ID, X-Cache). */
export interface ServedBy {
  instance: string | null;
  cache: string | null;
}
