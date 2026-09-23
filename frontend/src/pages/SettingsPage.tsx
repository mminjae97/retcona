// World/character preset screen (design doc 2.3)
// World: category + title + free-form description
// Character: three sections — fixed attributes / mutable attributes / personality·speech
// All fields are optional; if left blank, they're auto-filled from the editor (7.4)
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, describeError } from "../api/client";
import {
  FIXED_ATTR_FIELDS,
  MUTABLE_ATTR_FIELDS,
  PERSONALITY_FIELDS,
  WORLD_CATEGORIES,
  createCharacter,
  createWorldSetting,
  deleteCharacter,
  deleteWorldSetting,
  listCharacters,
  listWorldSettings,
  updateCharacter,
  updateWorldSetting,
} from "../api/settings";
import type { CharacterInput, CharacterPublic, WorldCategory, WorldSettingInput, WorldSettingPublic } from "../api/settings";
import "./SettingsPage.css";

type Tab = "world" | "characters";

export default function SettingsPage() {
  const { novelId } = useParams<{ novelId: string }>();
  const [tab, setTab] = useState<Tab>("world");
  if (!novelId) return null;

  return (
    <div className="settings-page">
      <Link className="back-link" to={`/novels/${novelId}/episodes`}>
        ← 화 목록
      </Link>
      <h1>설정 관리</h1>
      <p className="settings-hint">모두 선택 입력입니다. 비워 둔 설정은 원고에서 자동으로 채워집니다.</p>
      <div className="settings-tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "world"} onClick={() => setTab("world")}>
          세계관
        </button>
        <button type="button" role="tab" aria-selected={tab === "characters"} onClick={() => setTab("characters")}>
          캐릭터
        </button>
      </div>
      {/* Both stay mounted, only one shown: switching tabs mustn't throw
          away a half-edited form. Keyed by novel: switching novels remounts
          them, so nothing from the previous novel (its list, a half-edited
          form, a response still in flight) can land in the new one. */}
      <div hidden={tab !== "world"}>
        <WorldSettingsSection key={novelId} novelId={novelId} />
      </div>
      <div hidden={tab !== "characters"}>
        <CharactersSection key={novelId} novelId={novelId} />
      </div>
    </div>
  );
}

// Loads a list once per mount, with a retry. `active` keeps a response that
// arrives after unmount (novel switched, page left) from being applied.
function useList<T>(load: () => Promise<T[]>) {
  const [items, setItems] = useState<T[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setError(null);
    load()
      .then((list) => active && setItems(list))
      .catch((err) => active && setError(describeError(err)));
    return () => {
      active = false;
    };
    // Not `load`: it closes over the novelId, which is fixed for this mount
    // (see the key above), and is a new function every render.
  }, [attempt]);

  return { items, setItems, error, retry: () => setAttempt((n) => n + 1) };
}

function confirmDiscard(dirty: boolean): boolean {
  return !dirty || window.confirm("저장하지 않은 변경 사항이 있습니다. 버리시겠습니까?");
}

// ---------------------------------------------------------------- world settings

const EMPTY_WORLD: WorldSettingInput = { category: "era", title: "", content: "" };

function WorldSettingsSection({ novelId }: { novelId: string }) {
  const { items, setItems, error, retry } = useList(() => listWorldSettings(novelId));
  // "new" while adding, an id while editing that card, null otherwise.
  const [editing, setEditing] = useState<string | null>(null);
  const [form, setForm] = useState<WorldSettingInput>(EMPTY_WORLD);
  const [initial, setInitial] = useState<WorldSettingInput>(EMPTY_WORLD);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const dirty = editing !== null && JSON.stringify(form) !== JSON.stringify(initial);

  // While a save is in flight, nothing else can be opened: its result closes
  // the editor, which would otherwise take a form opened meanwhile with it.
  function startEdit(key: string, values: WorldSettingInput) {
    if (saving || !confirmDiscard(dirty)) return;
    setEditing(key);
    setForm(values);
    setInitial(values);
    setFormError(null);
  }

  function cancel() {
    if (!confirmDiscard(dirty)) return;
    setEditing(null);
    setFormError(null);
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    if (saving || editing === null) return;
    const input = { ...form, title: form.title.trim(), content: form.content.trim() };
    if (!input.title || !input.content) {
      setFormError("제목과 내용을 입력해주세요.");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      if (editing === "new") {
        const created = await createWorldSetting(novelId, input);
        setItems((prev) => [...(prev ?? []), created]);
      } else {
        const updated = await updateWorldSetting(novelId, editing, input);
        setItems((prev) => prev?.map((s) => (s.id === updated.id ? updated : s)) ?? null);
      }
      setEditing(null);
    } catch (err) {
      setFormError(describeError(err));
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(setting: WorldSettingPublic) {
    if (!window.confirm(`"${setting.title}" 설정을 삭제하시겠습니까?`)) return;
    setActionError(null);
    try {
      await deleteWorldSetting(novelId, setting.id);
      setItems((prev) => prev?.filter((s) => s.id !== setting.id) ?? null);
      if (editing === setting.id) setEditing(null);
    } catch (err) {
      setActionError(describeError(err));
    }
  }

  const editor = (
    <form className="setting-card setting-form" onSubmit={handleSave}>
      <label>
        분류
        <select
          value={form.category}
          onChange={(e) => setForm({ ...form, category: e.target.value as WorldCategory })}
        >
          {Object.entries(WORLD_CATEGORIES).map(([code, label]) => (
            <option key={code} value={code}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label>
        제목
        <input
          type="text"
          value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
          maxLength={200}
          autoFocus
        />
      </label>
      <label>
        내용
        <textarea
          value={form.content}
          onChange={(e) => setForm({ ...form, content: e.target.value })}
          maxLength={20000}
          rows={5}
        />
      </label>
      {formError && <p className="settings-error">{formError}</p>}
      <div className="form-actions">
        <button type="submit" disabled={saving}>
          {saving ? "저장 중..." : "저장"}
        </button>
        <button type="button" onClick={cancel} disabled={saving}>
          취소
        </button>
      </div>
    </form>
  );

  return (
    <section className="settings-section">
      <div className="section-header">
        <h2>세계관 설정</h2>
        <button type="button" onClick={() => startEdit("new", EMPTY_WORLD)} disabled={items === null || saving}>
          + 항목 추가
        </button>
      </div>
      {actionError && <p className="settings-error">{actionError}</p>}
      {error ? (
        <p className="settings-error">
          {error} <button type="button" onClick={retry}>다시 시도</button>
        </p>
      ) : items === null ? (
        <p>불러오는 중...</p>
      ) : (
        <>
          {editing === "new" && editor}
          {items.length === 0 && editing !== "new" && (
            <p className="empty-state">아직 입력한 세계관 설정이 없습니다.</p>
          )}
          <ul className="setting-list">
            {items.map((setting) =>
              editing === setting.id ? (
                <li key={setting.id}>{editor}</li>
              ) : (
                <li key={setting.id} className="setting-card">
                  <div className="setting-card-header">
                    <span className="category-chip">{WORLD_CATEGORIES[setting.category] ?? setting.category}</span>
                    <strong>{setting.title}</strong>
                    <div className="card-actions">
                      <button
                        type="button"
                        disabled={saving}
                        onClick={() =>
                          startEdit(setting.id, {
                            category: setting.category,
                            title: setting.title,
                            content: setting.content,
                          })
                        }
                      >
                        수정
                      </button>
                      <button type="button" onClick={() => handleDelete(setting)} disabled={saving}>
                        삭제
                      </button>
                    </div>
                  </div>
                  <p className="setting-content">{setting.content}</p>
                </li>
              ),
            )}
          </ul>
        </>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- characters

type SectionForm<Fields> = { [K in keyof Fields]: string };

interface CharacterForm {
  name: string;
  fixed_attrs: SectionForm<typeof FIXED_ATTR_FIELDS>;
  mutable_attrs: SectionForm<typeof MUTABLE_ATTR_FIELDS>;
  personality: SectionForm<typeof PERSONALITY_FIELDS>;
}

// Form values are plain strings ("" for unset); the backend treats a blank
// value as not set, so the form can send every field as it is.
function sectionForm<Fields extends Record<string, string>>(
  fields: Fields,
  values?: { [K in keyof Fields]: string | null },
): SectionForm<Fields> {
  return Object.fromEntries(Object.keys(fields).map((key) => [key, values?.[key] ?? ""])) as SectionForm<Fields>;
}

function characterForm(character?: CharacterPublic): CharacterForm {
  return {
    name: character?.name ?? "",
    fixed_attrs: sectionForm(FIXED_ATTR_FIELDS, character?.fixed_attrs),
    mutable_attrs: sectionForm(MUTABLE_ATTR_FIELDS, character?.mutable_attrs),
    personality: sectionForm(PERSONALITY_FIELDS, character?.personality),
  };
}

const SECTIONS = [
  { key: "fixed_attrs", title: "고정 속성", fields: FIXED_ATTR_FIELDS },
  { key: "mutable_attrs", title: "가변 속성", fields: MUTABLE_ATTR_FIELDS },
  { key: "personality", title: "성격 · 말투", fields: PERSONALITY_FIELDS },
] as const;

function CharactersSection({ novelId }: { novelId: string }) {
  const { items, setItems, error, retry } = useList(() => listCharacters(novelId));
  const [selected, setSelected] = useState<string | null>(null); // "new", an id, or null
  const [form, setForm] = useState<CharacterForm>(() => characterForm());
  const [initial, setInitial] = useState<CharacterForm>(() => characterForm());
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const dirty = selected !== null && JSON.stringify(form) !== JSON.stringify(initial);

  // While a save is in flight, the selection can't change: its result is
  // loaded into the form, which would otherwise overwrite a card opened
  // meanwhile.
  function select(key: string | null, character?: CharacterPublic) {
    if (saving || key === selected || !confirmDiscard(dirty)) return;
    const values = characterForm(character);
    setSelected(key);
    setForm(values);
    setInitial(values);
    setFormError(null);
  }

  function setField(section: (typeof SECTIONS)[number]["key"], field: string, value: string) {
    setForm((prev) => ({ ...prev, [section]: { ...prev[section], [field]: value } }));
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    if (saving || selected === null) return;
    const input: CharacterInput = { ...form, name: form.name.trim() };
    if (!input.name) {
      setFormError("이름을 입력해주세요.");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      const saved =
        selected === "new"
          ? await createCharacter(novelId, input)
          : await updateCharacter(novelId, selected, input);
      setItems((prev) =>
        selected === "new" ? [...(prev ?? []), saved] : (prev?.map((c) => (c.id === saved.id ? saved : c)) ?? null),
      );
      const values = characterForm(saved);
      setSelected(saved.id);
      setForm(values);
      setInitial(values);
    } catch (err) {
      setFormError(
        err instanceof ApiError && err.status === 409 ? "같은 이름의 캐릭터가 이미 있습니다." : describeError(err),
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    const character = items?.find((c) => c.id === selected);
    if (!character) return;
    if (
      !window.confirm(
        `"${character.name}" 캐릭터를 삭제하시겠습니까? 이 캐릭터의 상태 기록과 관계 정보도 함께 삭제됩니다.`,
      )
    ) {
      return;
    }
    setFormError(null);
    try {
      await deleteCharacter(novelId, character.id);
      setItems((prev) => prev?.filter((c) => c.id !== character.id) ?? null);
      setSelected(null);
    } catch (err) {
      setFormError(describeError(err));
    }
  }

  return (
    <section className="settings-section">
      <div className="section-header">
        <h2>캐릭터 설정</h2>
        <button type="button" onClick={() => select("new")} disabled={items === null || saving}>
          + 캐릭터 추가
        </button>
      </div>
      {error ? (
        <p className="settings-error">
          {error} <button type="button" onClick={retry}>다시 시도</button>
        </p>
      ) : items === null ? (
        <p>불러오는 중...</p>
      ) : (
        <div className="character-layout">
          <ul className="character-list">
            {items.length === 0 && <li className="empty-state">아직 등록한 캐릭터가 없습니다.</li>}
            {items.map((character) => (
              <li key={character.id}>
                <button
                  type="button"
                  className={character.id === selected ? "character-item selected" : "character-item"}
                  onClick={() => select(character.id, character)}
                  disabled={saving}
                >
                  {character.name}
                  {character.source === "auto_detected" && <span className="source-badge">자동 생성</span>}
                </button>
              </li>
            ))}
          </ul>

          {selected !== null && (
            <form className="setting-card setting-form character-form" onSubmit={handleSave}>
              <label>
                이름
                <input
                  type="text"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  maxLength={100}
                  autoFocus={selected === "new"}
                />
              </label>
              {SECTIONS.map((section) => (
                <fieldset key={section.key}>
                  <legend>{section.title}</legend>
                  {Object.entries(section.fields).map(([field, label]) => (
                    <label key={field}>
                      {label}
                      <input
                        type="text"
                        value={(form[section.key] as Record<string, string>)[field]}
                        onChange={(e) => setField(section.key, field, e.target.value)}
                        maxLength={500}
                      />
                    </label>
                  ))}
                </fieldset>
              ))}
              {formError && <p className="settings-error">{formError}</p>}
              <div className="form-actions">
                <button type="submit" disabled={saving}>
                  {saving ? "저장 중..." : "저장"}
                </button>
                <button type="button" onClick={() => select(null)} disabled={saving}>
                  닫기
                </button>
                {selected !== "new" && (
                  <button type="button" className="danger" onClick={handleDelete} disabled={saving}>
                    삭제
                  </button>
                )}
              </div>
            </form>
          )}
        </div>
      )}
    </section>
  );
}
