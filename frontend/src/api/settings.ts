// World and character setting card API calls (design doc 2.3).

import { apiFetch } from "./client";

// Stored as these codes (backend/api/settings.py); the labels are this side's.
export const WORLD_CATEGORIES = {
  era: "시대적 배경",
  power_system: "마법·무공 체계",
  faction: "세력·조직",
  history: "역사",
  other: "기타 규칙",
} as const;

export type WorldCategory = keyof typeof WORLD_CATEGORIES;

export interface WorldSettingInput {
  category: WorldCategory;
  title: string;
  content: string;
}

export interface WorldSettingPublic extends WorldSettingInput {
  id: string;
  created_at: string;
}

// The three sections of a character card (2.3). Every field is optional free
// text; the backend stores only the ones that aren't blank and returns null
// for the rest.
export const FIXED_ATTR_FIELDS = {
  age: "나이",
  eye_color: "눈 색깔",
  hair_color: "머리색",
  height: "신장",
  scars: "흉터",
  origin: "출신",
} as const;

export const MUTABLE_ATTR_FIELDS = {
  hairstyle: "헤어스타일",
  outfit: "복장",
  condition: "부상·건강 상태",
  belongings: "소지품",
} as const;

export const PERSONALITY_FIELDS = {
  keywords: "성격 키워드",
  speech: "말투 특징",
  goals: "목표·가치관",
} as const;

type Section<Fields> = { [K in keyof Fields]: string | null };

export type FixedAttrs = Section<typeof FIXED_ATTR_FIELDS>;
export type MutableAttrs = Section<typeof MUTABLE_ATTR_FIELDS>;
export type Personality = Section<typeof PERSONALITY_FIELDS>;

export interface CharacterInput {
  name: string;
  fixed_attrs: Partial<FixedAttrs>;
  mutable_attrs: Partial<MutableAttrs>;
  personality: Partial<Personality>;
}

export interface CharacterPublic {
  id: string;
  name: string;
  source: "manual" | "auto_detected";
  fixed_attrs: FixedAttrs;
  mutable_attrs: MutableAttrs;
  personality: Personality;
  created_at: string;
}

export function listWorldSettings(novelId: string): Promise<WorldSettingPublic[]> {
  return apiFetch<WorldSettingPublic[]>(`/novels/${novelId}/world-settings`);
}

export function createWorldSetting(novelId: string, input: WorldSettingInput): Promise<WorldSettingPublic> {
  return apiFetch<WorldSettingPublic>(`/novels/${novelId}/world-settings`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateWorldSetting(
  novelId: string,
  settingId: string,
  input: WorldSettingInput,
): Promise<WorldSettingPublic> {
  return apiFetch<WorldSettingPublic>(`/novels/${novelId}/world-settings/${settingId}`, {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export async function deleteWorldSetting(novelId: string, settingId: string): Promise<void> {
  await apiFetch<void>(`/novels/${novelId}/world-settings/${settingId}`, { method: "DELETE" });
}

export function listCharacters(novelId: string): Promise<CharacterPublic[]> {
  return apiFetch<CharacterPublic[]>(`/novels/${novelId}/characters`);
}

export function createCharacter(novelId: string, input: CharacterInput): Promise<CharacterPublic> {
  return apiFetch<CharacterPublic>(`/novels/${novelId}/characters`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateCharacter(novelId: string, characterId: string, input: CharacterInput): Promise<CharacterPublic> {
  return apiFetch<CharacterPublic>(`/novels/${novelId}/characters/${characterId}`, {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export async function deleteCharacter(novelId: string, characterId: string): Promise<void> {
  await apiFetch<void>(`/novels/${novelId}/characters/${characterId}`, { method: "DELETE" });
}
